
"""WE-SELL rental inventory sync extension for rental_portal.py (SQLite MVP)."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, abort, session, render_template_string
from rental_portal import db

inventory_sync = Blueprint(
    "inventory_sync",
    __name__,
    url_prefix="/rental-sync"
)

MAX_BODY = 1024 * 1024
CATEGORIES = {"economy", "sedan", "suv", "luxury", "van"}


def init_inventory_sync():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS rental_sync_connections (
          company_id INTEGER PRIMARY KEY REFERENCES rental_companies(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL,
          feed_url TEXT,
          last_success TEXT,
          last_error TEXT,
          last_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS rental_sync_items (
          company_id INTEGER NOT NULL REFERENCES rental_companies(id) ON DELETE CASCADE,
          external_id TEXT NOT NULL,
          vehicle_id INTEGER NOT NULL REFERENCES rental_vehicles(id) ON DELETE CASCADE,
          PRIMARY KEY(company_id, external_id),
          UNIQUE(vehicle_id)
        );

        CREATE INDEX IF NOT EXISTS idx_rental_sync_vehicle_company
          ON rental_vehicles(company_id, status);
        """)


def _company_id_from_token():
    header = request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        abort(401)

    token = header[7:].strip()

    if len(token) != 64 or any(
        c not in "0123456789abcdef" for c in token
    ):
        abort(401)

    digest = hashlib.sha256(token.encode()).hexdigest()

    with db() as conn:
        rows = conn.execute("""
            SELECT c.company_id
            FROM rental_sync_connections c
            JOIN rental_companies p ON p.id=c.company_id
            WHERE p.approved=1
        """).fetchall()

        connection_rows = conn.execute("""
            SELECT company_id, token_hash
            FROM rental_sync_connections
        """).fetchall()

    approved = {r["company_id"] for r in rows}

    for row in connection_rows:
        if (
            hmac.compare_digest(row["token_hash"], digest)
            and row["company_id"] in approved
        ):
            return row["company_id"]

    abort(401)


def _validate(payload):
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("vehicles"), list)
    ):
        raise ValueError(
            "Expected JSON object with vehicles array"
        )

    items = payload["vehicles"]

    if len(items) > 500:
        raise ValueError(
            "Maximum 500 vehicles per snapshot"
        )

    seen = set()
    clean = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError(
                "Every vehicle must be an object"
            )

        external_id = str(
            item.get("external_id", "")
        ).strip()

        if (
            not external_id
            or len(external_id) > 120
            or external_id in seen
        ):
            raise ValueError(
                "Each external_id must be unique, "
                "nonempty and <=120 characters"
            )

        seen.add(external_id)

        try:
            year = int(item["year"])
            rate = Decimal(str(item["daily_rate"]))
            cents = rate * 100
        except (
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation
        ):
            raise ValueError(
                "Invalid year or daily_rate"
            )

        if (
            not 1980 <= year <= 2100
            or not cents.is_finite()
            or cents != cents.to_integral_value()
            or not 0 < cents <= 100000000
        ):
            raise ValueError(
                "Year or daily_rate out of range"
            )

        category = str(
            item.get("category", "")
        ).lower().strip()

        if category not in CATEGORIES:
            raise ValueError("Invalid category")

        status = str(
            item.get("status", "available")
        ).lower().strip()

        if status not in (
            "available",
            "unavailable"
        ):
            raise ValueError("Invalid status")

        fields = [
            str(item.get(key, "")).strip()
            for key in (
                "make",
                "model",
                "pickup_city"
            )
        ]

        if any(
            not x or len(x) > 160
            for x in fields
        ):
            raise ValueError(
                "make, model, pickup_city required"
            )

        description = str(
            item.get("description", "")
        ).strip()

        if len(description) > 2000:
            raise ValueError(
                "Description too long"
            )

        clean.append((
            external_id,
            year,
            *fields[:2],
            category,
            int(cents),
            fields[2],
            description,
            status
        ))

    return clean


def apply_snapshot(company_id, payload):
    """
    Import a full company inventory snapshot.
    Previously synced vehicles missing from the
    snapshot become unavailable.

    Other companies and manually entered
    vehicles are not modified.
    """

    vehicles = _validate(payload)

    now = datetime.now(
        timezone.utc
    ).isoformat()

    with db() as conn:
        for (
            external_id,
            year,
            make,
            model,
            category,
            cents,
            city,
            description,
            status
        ) in vehicles:

            row = conn.execute("""
                SELECT vehicle_id
                FROM rental_sync_items
                WHERE company_id=?
                  AND external_id=?
            """, (
                company_id,
                external_id
            )).fetchone()

            if row:
                conn.execute("""
                    UPDATE rental_vehicles
                    SET year=?,
                        make=?,
                        model=?,
                        category=?,
                        daily_rate_cents=?,
                        pickup_city=?,
                        description=?,
                        status=?
                    WHERE id=? AND company_id=?
                """, (
                    year,
                    make,
                    model,
                    category,
                    cents,
                    city,
                    description,
                    status,
                    row["vehicle_id"],
                    company_id
                ))

            else:
                cur = conn.execute("""
                    INSERT INTO rental_vehicles
                    (
                        company_id,
                        year,
                        make,
                        model,
                        category,
                        daily_rate_cents,
                        pickup_city,
                        description,
                        status
                    )
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    company_id,
                    year,
                    make,
                    model,
                    category,
                    cents,
                    city,
                    description,
                    status
                ))

                conn.execute("""
                    INSERT INTO rental_sync_items
                    (
                        company_id,
                        external_id,
                        vehicle_id
                    )
                    VALUES (?,?,?)
                """, (
                    company_id,
                    external_id,
                    cur.lastrowid
                ))

        ids = [v[0] for v in vehicles]

        if ids:
            placeholders = ",".join(
                "?" for _ in ids
            )

            conn.execute(f"""
                UPDATE rental_vehicles
                SET status='unavailable'
                WHERE id IN (
                    SELECT vehicle_id
                    FROM rental_sync_items
                    WHERE company_id=?
                    AND external_id NOT IN (
                        {placeholders}
                    )
                )
            """, [
                company_id,
                *ids
            ])

        else:
            conn.execute("""
                UPDATE rental_vehicles
                SET status='unavailable'
                WHERE id IN (
                    SELECT vehicle_id
                    FROM rental_sync_items
                    WHERE company_id=?
                )
            """, (company_id,))

        conn.execute("""
            UPDATE rental_sync_connections
            SET last_success=?,
                last_error=NULL,
                last_count=?
            WHERE company_id=?
        """, (
            now,
            len(vehicles),
            company_id
        ))

    return len(vehicles)


@inventory_sync.post("/api/v1/inventory")
def push_inventory():
    company_id = _company_id_from_token()

    if (
        request.content_length is not None
        and request.content_length > MAX_BODY
    ):
        abort(413)

    if request.mimetype != "application/json":
        return jsonify(
            error="Content-Type must be application/json"
        ), 415

    raw = request.get_data(cache=False)

    if len(raw) > MAX_BODY:
        abort(413)

    try:
        payload = json.loads(raw)

        count = apply_snapshot(
            company_id,
            payload
        )

    except (
        ValueError,
        UnicodeDecodeError
    ) as exc:
        return jsonify(
            error=str(exc)
        ), 400

    return jsonify(
        ok=True,
        imported=count
    )


@inventory_sync.get("/api/v1/public-vehicles")
def public_vehicles():
    category = request.args.get(
        "category", ""
    ).strip().lower()

    city = request.args.get(
        "city", ""
    ).strip()

    if category and category not in CATEGORIES:
        return jsonify(
            error="Invalid category"
        ), 400

    sql = """
        SELECT
            v.id,
            v.year,
            v.make,
            v.model,
            v.category,
            v.daily_rate_cents,
            v.pickup_city,
            v.description,
            p.company_name
        FROM rental_vehicles v
        JOIN rental_companies p
          ON p.id=v.company_id
        WHERE p.approved=1
          AND v.status='available'
    """

    params = []

    if category:
        sql += " AND v.category=?"
        params.append(category)

    if city:
        sql += """
            AND lower(v.pickup_city)=lower(?)
        """
        params.append(city[:160])

    sql += " ORDER BY v.id DESC LIMIT 100"

    with db() as conn:
        rows = conn.execute(
            sql,
            params
        ).fetchall()

    return jsonify(
        vehicles=[
            {
                **dict(row),
                "daily_rate": (
                    f"{row['daily_rate_cents']/100:.2f}"
                )
            }
            for row in rows
        ]
    )


@inventory_sync.get("/dashboard")
def sync_dashboard():
    company_id = session.get(
        "rental_company_id"
    )

    if not company_id:
        abort(401)

    with db() as conn:
        company = conn.execute("""
            SELECT company_name
            FROM rental_companies
            WHERE id=?
        """, (company_id,)).fetchone()

        connection = conn.execute("""
            SELECT
                last_success,
                last_error,
                last_count
            FROM rental_sync_connections
            WHERE company_id=?
        """, (company_id,)).fetchone()

    if not company:
        abort(404)

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta name="viewport"
            content="width=device-width,initial-scale=1">
      <title>WE-SELL Inventory Sync</title>
      <style>
        body {
          font-family: Arial, sans-serif;
          background: #f4f7fb;
          color: #071d36;
          margin: 0;
        }
        main {
          max-width: 780px;
          margin: 60px auto;
          padding: 32px;
          background: white;
          border-radius: 16px;
          box-shadow: 0 8px 24px #0012;
        }
        a { color: #0b5ba7; }
        .note {
          padding: 16px;
          background: #fff6d5;
          border-radius: 8px;
        }
      </style>
    </head>
    <body>
      <main>
        <h1>WE-SELL Inventory Connection</h1>
        <p>{{ name }}</p>

        <p>
          <b>Last successful sync:</b>
          {{ connection.last_success
             if connection and connection.last_success
             else 'Never' }}
        </p>

        <p>
          <b>Vehicles in last snapshot:</b>
          {{ connection.last_count if connection else 0 }}
        </p>

        <p>
          <b>Last error:</b>
          {{ connection.last_error
             if connection and connection.last_error
             else 'None' }}
        </p>

        <div class="note">
          To connect your rental software,
          ask WE-SELL support for an integration
          token and feed instructions.
          Never share your token publicly.
        </div>

        <p>
          <a href="/rental-company/dashboard">
            Back to rental dashboard
          </a>
        </p>
      </main>
    </body>
    </html>
    """,
    name=company["company_name"],
    connection=connection)


def issue_token(company_id):
    """
    Administrator-only function.
    Run from a trusted CLI, not a public route.
    """

    token = secrets.token_hex(32)

    digest = hashlib.sha256(
        token.encode()
    ).hexdigest()

    with db() as conn:
        exists = conn.execute("""
            SELECT id
            FROM rental_companies
            WHERE id=?
        """, (company_id,)).fetchone()

        if not exists:
            raise ValueError(
                "Unknown company ID"
            )

        conn.execute("""
            INSERT INTO rental_sync_connections
            (
                company_id,
                token_hash
            )
            VALUES (?,?)
            ON CONFLICT(company_id)
            DO UPDATE SET
              token_hash=excluded.token_hash
        """, (
            company_id,
            digest
        ))

    return token
