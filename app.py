
import os
import sqlite3
import secrets
import re
import json
import math
import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from datetime import timedelta, timezone

from functools import lru_cache, wraps
from urllib.request import urlopen
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, g, abort
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from rental_portal import rental_portal, init_rental_portal
from inventory_sync import inventory_sync, init_inventory_sync
from social_auth import social_auth, init_social_auth


# ==========================================
# CONFIGURATION
# ==========================================

ROOT = os.path.dirname(os.path.abspath(__file__))

DB = os.environ.get(
    "WESELL_DB",
    os.path.join(ROOT, "wesell.db")
)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    secrets.token_hex(32)
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=1024 * 1024
)

STATUSES = [
    "new",
    "dealer_review",
    "appointment_proposed",
    "confirmed",
    "visited",
    "sold_pending",
    "sold_verified",
    "no_sale",
    "cancelled"
]

GAS = [
    "Shell",
    "Chevron",
    "76",
    "ARCO",
    "ExxonMobil",
    "Other"
]


# ==========================================
# DATABASE CONNECTION
# ==========================================

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def init_db():
    conn = sqlite3.connect(DB)

    conn.executescript("""
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reset_user ON password_reset_tokens(user_id);

        CREATE TABLE IF NOT EXISTS dealer_google_identities (
            google_sub TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            role TEXT NOT NULL
                CHECK(role IN ('buyer','dealer','admin')),
            dealer_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dealers(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            approved INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vehicles(
            id INTEGER PRIMARY KEY,
            dealer_id INTEGER NOT NULL REFERENCES dealers(id),
            year INTEGER NOT NULL,
            make TEXT NOT NULL,
            model TEXT NOT NULL,
            trim TEXT DEFAULT '',
            price INTEGER NOT NULL,
            mileage INTEGER NOT NULL,
            vin TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            description TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
            buyer_id INTEGER NOT NULL REFERENCES users(id),
            dealer_id INTEGER NOT NULL REFERENCES dealers(id),
            status TEXT NOT NULL DEFAULT 'new',
            buyer_note TEXT DEFAULT '',
            dealer_note TEXT DEFAULT '',
            appointment_time TEXT DEFAULT '',
            gas_station TEXT DEFAULT 'Shell',
            purchase_verified_at TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lead_events(
            id INTEGER PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id),
            actor_role TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rewards(
            id INTEGER PRIMARY KEY,
            lead_id INTEGER UNIQUE NOT NULL REFERENCES leads(id),
            station TEXT NOT NULL,
            amount INTEGER DEFAULT 25,
            status TEXT DEFAULT 'pending'
                CHECK(status IN ('pending','issued')),
            issued_at TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_vehicle_dealer
            ON vehicles(dealer_id);

        CREATE INDEX IF NOT EXISTS idx_leads_dealer
            ON leads(dealer_id);

        CREATE INDEX IF NOT EXISTS idx_leads_buyer
            ON leads(buyer_id);
    """)

    migrations = [
        ("dealers", "zip_code", "TEXT NOT NULL DEFAULT ''"),
        ("dealers", "address", "TEXT NOT NULL DEFAULT ''"),
        ("dealers", "email", "TEXT NOT NULL DEFAULT ''"),
        ("dealers", "sales_phone", "TEXT NOT NULL DEFAULT ''"),
        ("dealers", "service_phone", "TEXT NOT NULL DEFAULT ''"),
        ("vehicles", "zip_code", "TEXT NOT NULL DEFAULT ''"),
        ("vehicles", "condition", "TEXT NOT NULL DEFAULT 'used'")
    ]

    for table, column, definition in migrations:
        existing = {
            row[1]
            for row in conn.execute(
                f"PRAGMA table_info({table})"
            )
        }

        if column not in existing:
            conn.execute(
                f"ALTER TABLE {table} "
                f"ADD COLUMN {column} {definition}"
            )

    if conn.execute(
        "SELECT COUNT(*) FROM dealers"
    ).fetchone()[0] == 0:

        conn.execute("""
            INSERT INTO dealers(name, city)
            VALUES
            ('Pacific Coast Auto Group', 'San Diego, CA'),
            ('Mission Valley Motors', 'San Diego, CA')
        """)

        vehicles = [
            (
                1, 2019, "Nissan", "Pathfinder", "SV",
                15995, 111349, "5N1DR2MM3KC637462",
                "https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?w=900&q=85",
                "Family-friendly SUV", "", "used"
            ),
            (
                1, 2020, "Mercedes-Benz", "C-Class", "C 300",
                21995, 117155, "",
                "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?w=900&q=85",
                "Luxury sedan", "", "used"
            ),
            (
                2, 2018, "Ford", "Explorer", "Sport",
                17995, 113624, "",
                "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?w=900&q=85",
                "Spacious SUV", "", "used"
            ),
            (
                2, 2017, "Jeep", "Compass", "High Altitude",
                11995, 93168, "",
                "https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=900&q=85",
                "Versatile crossover", "", "used"
            ),
            (
                1, 2019, "Jeep", "Renegade", "Altitude",
                14995, 81381, "",
                "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=900&q=85",
                "Compact SUV", "", "used"
            ),
            (
                2, 2018, "Volkswagen", "Tiguan", "2.0T",
                13995, 115385, "",
                "https://images.unsplash.com/photo-1541899481282-d53bffe3c35d?w=900&q=85",
                "Comfortable daily driver", "", "used"
            )
        ]

        conn.executemany("""
            INSERT INTO vehicles(
                dealer_id, year, make, model, trim,
                price, mileage, vin, image_url,
                description, zip_code, condition
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, vehicles)

    if os.environ.get("WESELL_SEED_DEMO") == "1":
        demo_users = [
            (
                "admin@wesell.local",
                "AdminDemo123!",
                "WE-SELL Admin",
                "admin",
                None
            ),
            (
                "dealer@wesell.local",
                "DealerDemo123!",
                "Dealer Manager",
                "dealer",
                1
            ),
            (
                "buyer@wesell.local",
                "BuyerDemo123!",
                "Demo Buyer",
                "buyer",
                None
            )
        ]

        for email, pw, name, role, dealer_id in demo_users:
            conn.execute("""
                INSERT OR IGNORE INTO users(
                    email, password_hash, name, role, dealer_id
                )
                VALUES(?,?,?,?,?)
            """, (
                email,
                generate_password_hash(pw),
                name,
                role,
                dealer_id
            ))

    conn.commit()
    conn.close()


# ==========================================
# USER SESSION AND CSRF
# ==========================================

@app.before_request
def load_user():
    g.user = None

    if session.get("uid"):
        g.user = db().execute(
            "SELECT * FROM users WHERE id=?",
            (session["uid"],)
        ).fetchone()

        if not g.user:
            session.clear()

    if (
        request.method == "POST"
        and request.endpoint != "inventory_sync.push_inventory"
    ):
        token = request.form.get("csrf", "")
        saved_token = session.get("csrf", "")

        if (
            not saved_token
            or not secrets.compare_digest(token, saved_token)
        ):
            abort(
                400,
                "Invalid form token. Reload and try again."
            )


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)

    return {
        "me": g.get("user"),
        "csrf": session["csrf"],
        "statuses": STATUSES
    }


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not g.user:
                return redirect(
                    url_for("login", next=request.path)
                )

            if role and g.user["role"] != role:
                abort(403)

            return fn(*args, **kwargs)

        return wrapper

    return deco


# ==========================================
# LEAD HELPERS
# ==========================================

def event(lead_id, role, message):
    db().execute("""
        INSERT INTO lead_events(
            lead_id, actor_role, message
        )
        VALUES(?,?,?)
    """, (lead_id, role, message))


def lead_for_role(lead_id):
    lead = db().execute("""
        SELECT
            l.*,
            v.year,
            v.make,
            v.model,
            v.trim,
            v.vin,
            v.price,
            v.image_url,
            d.name AS dealer_name,
            u.name AS buyer_name,
            u.email AS buyer_email,
            u.phone AS buyer_phone
        FROM leads l
        JOIN vehicles v ON l.vehicle_id=v.id
        JOIN dealers d ON l.dealer_id=d.id
        JOIN users u ON l.buyer_id=u.id
        WHERE l.id=?
    """, (lead_id,)).fetchone()

    if not lead:
        abort(404)

    role = g.user["role"]

    if (
        role == "buyer"
        and lead["buyer_id"] != g.user["id"]
    ):
        abort(403)

    if (
        role == "dealer"
        and lead["dealer_id"] != g.user["dealer_id"]
    ):
        abort(403)

    return lead


# ==========================================
# ZIP CODE AND DISTANCE
# ==========================================

@lru_cache(maxsize=4096)
def zip_coordinates(zip_code):
    if not re.fullmatch(r"\d{5}", zip_code or ""):
        return None

    try:
        with urlopen(
            f"https://api.zippopotam.us/us/{zip_code}",
            timeout=4
        ) as response:
            data = json.load(response)

        place = data["places"][0]

        return (
            float(place["latitude"]),
            float(place["longitude"])
        )

    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError
    ):
        return None


def distance_miles(point_a, point_b):
    lat1, lon1 = map(math.radians, point_a)
    lat2, lon2 = map(math.radians, point_b)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return 3958.7613 * 2 * math.asin(
        min(1.0, math.sqrt(a))
    )


# ==========================================
# HOME PAGE AND VEHICLE SEARCH
# ==========================================

@app.get("/")
def home():
    q = request.args.get("q", "").strip()[:100]
    make = request.args.get("make", "").strip()[:50]

    selected_condition = request.args.get(
        "condition", "used"
    ).strip().lower()

    if selected_condition not in ("new", "used"):
        selected_condition = "used"

    selected_zip = request.args.get(
        "zip", ""
    ).strip()[:5]

    selected_distance = request.args.get(
        "distance", "50"
    ).strip().lower()

    allowed_distances = (
        "10", "25", "50", "100", "250", "300",
        "400", "500", "750", "1000", "nationwide"
    )

    if selected_distance not in allowed_distances:
        selected_distance = "50"

    if (
        selected_zip
        and not re.fullmatch(r"\d{5}", selected_zip)
    ):
        flash(
            "Enter a valid 5-digit ZIP code.",
            "error"
        )
        selected_zip = ""

    sql = """
        SELECT
            v.*,
            d.name AS dealer_name,
            d.city,
            d.zip_code AS dealer_zip_code
        FROM vehicles v
        JOIN dealers d ON v.dealer_id=d.id
        WHERE v.active=1
          AND d.approved=1
          AND v.condition=?
    """

    args = [selected_condition]

    if q:
        sql += """
            AND (
                v.make LIKE ?
                OR v.model LIKE ?
                OR v.trim LIKE ?
                OR CAST(v.year AS TEXT) LIKE ?
            )
        """
        args += ["%" + q + "%"] * 4

    if make:
        sql += " AND v.make=?"
        args.append(make)

    sql += " ORDER BY v.created_at DESC, v.id DESC"

    all_vehicles = db().execute(
        sql,
        args
    ).fetchall()

    vehicles = all_vehicles

    if selected_zip and selected_distance != "nationwide":
        origin = zip_coordinates(selected_zip)

        if origin is None:
            flash(
                "ZIP code could not be located. "
                "Please try another ZIP code.",
                "error"
            )
            vehicles = []

        else:
            nearby = []

            for vehicle in all_vehicles:
                vehicle_zip = (
                    vehicle["zip_code"]
                    or vehicle["dealer_zip_code"]
                )

                coords = (
                    zip_coordinates(vehicle_zip)
                    if vehicle_zip
                    else None
                )

                if coords is not None:
                    miles = distance_miles(
                        origin,
                        coords
                    )

                    if miles <= int(selected_distance):
                        nearby.append(vehicle)

            vehicles = nearby

    makes = db().execute("""
        SELECT DISTINCT make
        FROM vehicles
        WHERE active=1
        ORDER BY make
    """).fetchall()

    return render_template(
        "home.html",
        vehicles=vehicles,
        makes=makes,
        q=q,
        selected_make=make,
        selected_condition=selected_condition,
        selected_zip=selected_zip,
        selected_distance=selected_distance
    )


# ==========================================
# SELL YOUR CAR
# ==========================================

@app.get("/sell-your-car")
def sell_car():
    return render_template("sell_car.html")


# ==========================================
# SAVED CARS
# ==========================================

@app.get("/saved-cars")
def saved_cars():
    return render_template("saved_cars.html")


# ==========================================
# RENTAL CARS
# ==========================================

@app.get("/rentals")
def rentals():
    return render_template("rental_cars.html")


# ==========================================
# VEHICLE DETAILS
# ==========================================

@app.get("/vehicle/<int:vid>")
def vehicle(vid):
    v = db().execute("""
        SELECT
            v.*,
            d.name AS dealer_name,
            d.city
        FROM vehicles v
        JOIN dealers d ON v.dealer_id=d.id
        WHERE v.id=?
          AND v.active=1
          AND d.approved=1
    """, (vid,)).fetchone()

    if not v:
        abort(404)

    return render_template(
        "vehicle.html",
        v=v
    )


# ==========================================
# REGISTER
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()[:100]

        email = request.form.get(
            "email", ""
        ).strip().lower()[:254]

        password = request.form.get(
            "password", ""
        )

        phone = request.form.get(
            "phone", ""
        ).strip()[:30]

        if (
            not name
            or not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email
            )
            or len(password) < 10
        ):
            flash(
                "Enter your name, valid email, "
                "and a password of at least 10 characters.",
                "error"
            )

        else:
            try:
                cur = db().execute("""
                    INSERT INTO users(
                        email,
                        password_hash,
                        name,
                        phone,
                        role
                    )
                    VALUES(?,?,?,?,?)
                """, (
                    email,
                    generate_password_hash(password),
                    name,
                    phone,
                    "buyer"
                ))

                db().commit()

                session.clear()
                session["uid"] = cur.lastrowid

                flash(
                    "Account created. Welcome to WE-SELL!",
                    "success"
                )

                return redirect(url_for("home"))

            except sqlite3.IntegrityError:
                flash(
                    "This email is already registered.",
                    "error"
                )

    return render_template(
        "auth.html",
        mode="register"
    )


# ==========================================
# LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute(
            "SELECT * FROM users WHERE email=?",
            (
                request.form.get(
                    "email", ""
                ).strip().lower(),
            )
        ).fetchone()

        if u and check_password_hash(
            u["password_hash"],
            request.form.get("password", "")
        ):
            session.clear()
            session["uid"] = u["id"]

            flash(
                "Welcome back!",
                "success"
            )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Incorrect email or password.",
            "error"
        )

    return render_template(
        "auth.html",
        mode="login"
    )


# ==========================================
# PASSWORD RECOVERY
# ==========================================

def send_password_reset_email(recipient, reset_url):
    """Send through configured SMTP provider; never log reset URLs."""
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "").strip()
    if not all((host, username, password, sender)):
        app.logger.error("Password reset email is not configured")
        return False

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["Subject"] = "Reset your WE-SELL password"
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(
            "We received a request to reset your WE-SELL password.\n\n"
            f"Open this link within 30 minutes:\n{reset_url}\n\n"
            "If you did not request this, ignore this email."
        )
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15,
                                  context=ssl.create_default_context()) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(username, password)
                smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception("Could not deliver password reset email")
        return False


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:254]
        # Always give the same response, whether or not the account exists.
        user = db().execute("SELECT id, email FROM users WHERE email=?", (email,)).fetchone()
        if user:
            now = datetime.now(timezone.utc)
            last = db().execute(
                "SELECT created_at FROM password_reset_tokens "
                "WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],)
            ).fetchone()
            allowed = True
            if last:
                try:
                    allowed = now - datetime.fromisoformat(last["created_at"]) >= timedelta(seconds=60)
                except ValueError:
                    allowed = False
            if allowed:
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode()).hexdigest()
                expires = (now + timedelta(minutes=30)).isoformat()
                db().execute(
                    "INSERT INTO password_reset_tokens "
                    "(user_id,token_hash,expires_at,created_at) VALUES (?,?,?,?)",
                    (user["id"], token_hash, expires, now.isoformat())
                )
                db().commit()
                reset_url = url_for("reset_password", token=token, _external=True)
                send_password_reset_email(user["email"], reset_url)
        flash("If that email has an account, a password reset link will be sent shortly.", "success")
        return redirect(url_for("forgot_password"))
    return render_template("password_recovery.html", mode="forgot")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if len(token) > 256:
        abort(404)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    record = db().execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL",
        (token_hash,)
    ).fetchone()
    valid = False
    if record:
        try:
            valid = datetime.fromisoformat(record["expires_at"]) > datetime.now(timezone.utc)
        except ValueError:
            pass
    if not valid:
        flash("This reset link is invalid or expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 10 or len(password) > 128:
            flash("Use a password between 10 and 128 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            now = datetime.now(timezone.utc).isoformat()
            # Atomically claim the token so it cannot be used twice.
            cur = db().execute(
                "UPDATE password_reset_tokens SET used_at=? "
                "WHERE id=? AND used_at IS NULL AND expires_at>?",
                (now, record["id"], now)
            )
            if cur.rowcount != 1:
                db().rollback()
                flash("This link has already been used or expired.", "error")
                return redirect(url_for("forgot_password"))
            db().execute("UPDATE users SET password_hash=? WHERE id=?",
                         (generate_password_hash(password), record["user_id"]))
            db().execute("UPDATE password_reset_tokens SET used_at=? "
                         "WHERE user_id=? AND used_at IS NULL", (now, record["user_id"]))
            db().commit()
            session.clear()
            flash("Password updated. You can now sign in.", "success")
            return redirect(url_for("login"))
    return render_template("password_recovery.html", mode="reset")


# ==========================================
# LOGOUT
# ==========================================

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ==========================================
# DASHBOARD ROUTING
# ==========================================

@app.get("/dashboard")
@login_required()
def dashboard():
    if g.user["role"] == "buyer":
        return redirect(
            url_for("buyer_dashboard")
        )

    if g.user["role"] == "dealer":
        return redirect(
            url_for("dealer_dashboard")
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ==========================================
# BUYER VEHICLE INQUIRY
# ==========================================

@app.post("/inquire/<int:vid>")
@login_required("buyer")
def inquire(vid):
    v = db().execute("""
        SELECT v.*
        FROM vehicles v
        JOIN dealers d ON d.id=v.dealer_id
        WHERE v.id=?
          AND v.active=1
          AND d.approved=1
    """, (vid,)).fetchone()

    if not v:
        abort(404)

    station = request.form.get(
        "gas_station",
        "Shell"
    )

    if station not in GAS:
        abort(400)

    note = request.form.get(
        "note", ""
    ).strip()[:1000]

    cur = db().execute("""
        INSERT INTO leads(
            vehicle_id,
            buyer_id,
            dealer_id,
            buyer_note,
            gas_station,
            status
        )
        VALUES(?,?,?,?,?,?)
    """, (
        vid,
        g.user["id"],
        v["dealer_id"],
        note,
        station,
        "new"
    ))

    event(
        cur.lastrowid,
        "system",
        "Buyer inquiry received by WE-SELL. "
        "Awaiting dealership review."
    )

    db().commit()

    flash(
        "Your inquiry was received. "
        "WE-SELL will coordinate with the dealership.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=cur.lastrowid
        )
    )


# ==========================================
# BUYER DASHBOARD
# ==========================================

@app.get("/buyer")
@login_required("buyer")
def buyer_dashboard():
    leads = db().execute("""
        SELECT
            l.*,
            v.year,
            v.make,
            v.model,
            v.image_url
        FROM leads l
        JOIN vehicles v ON v.id=l.vehicle_id
        WHERE l.buyer_id=?
        ORDER BY l.id DESC
    """, (g.user["id"],)).fetchall()

    return render_template(
        "buyer.html",
        leads=leads
    )


# ==========================================
# DEALER GOOGLE ACCOUNT CONNECTION
# ==========================================

@app.get("/dealer/connect-google")
@login_required("dealer")
def dealer_connect_google():
    from flask import render_template_string
    linked = db().execute(
        "SELECT 1 FROM dealer_google_identities WHERE user_id=?",
        (g.user["id"],),
    ).fetchone() is not None
    return render_template_string("""
    <!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Connect Google | WE-SELL Dealer</title>
    <style>
    body{font-family:Arial,sans-serif;background:#f3f6fa;color:#09223d;margin:0}
    header{background:#041b34;color:white;padding:22px 6%;font-size:23px;font-weight:800}
    header span{color:#ffc400}main{max-width:530px;margin:70px auto;padding:30px;
    background:white;border-radius:18px;box-shadow:0 12px 35px #09223d19}
    p{line-height:1.7;color:#52657b}.btn{display:block;text-align:center;
    background:#ffc400;color:#041b34;padding:16px;border-radius:10px;
    text-decoration:none;font-weight:800;margin:20px 0}
    .back{color:#075ba8;text-decoration:none}
    </style></head><body><header><span>WE-SELL</span> | Dealer Portal</header>
    <main><h1>Google account connection</h1>
    {% with messages=get_flashed_messages() %}{% for m in messages %}<p>{{m}}</p>{% endfor %}{% endwith %}
    {% if linked %}<p>Your dealership user account is already connected to Google.</p>
    {% else %}<p>Connect your Google account while signed in with your dealership
    email and password. Future Google logins will open your dealer dashboard.</p>
    <a class="btn" href="{{link_url}}">Connect Google securely</a>{% endif %}
    <a class="back" href="{{dashboard_url}}">← Back to Dealer Dashboard</a>
    </main></body></html>
    """, linked=linked,
    link_url=url_for("social_auth.start_link", portal="dealer"),
    dashboard_url=url_for("dealer_dashboard"))


@app.get("/dealer/google-login")
def dealer_google_login():
    return redirect(url_for("social_auth.start_login", provider="google", portal="dealer"))


# ==========================================
# DEALER DASHBOARD
# ==========================================

@app.get("/dealer")
@login_required("dealer")
def dealer_dashboard():
    leads = db().execute("""
        SELECT
            l.*,
            v.year,
            v.make,
            v.model,
            v.vin,
            u.name AS buyer_name
        FROM leads l
        JOIN vehicles v ON v.id=l.vehicle_id
        JOIN users u ON u.id=l.buyer_id
        WHERE l.dealer_id=?
        ORDER BY l.id DESC
    """, (
        g.user["dealer_id"],
    )).fetchall()

    vehicles = db().execute("""
        SELECT *
        FROM vehicles
        WHERE dealer_id=?
        ORDER BY id DESC
    """, (
        g.user["dealer_id"],
    )).fetchall()

    return render_template(
        "dealer.html",
        leads=leads,
        vehicles=vehicles
    )


# ==========================================
# DEALERSHIP CONTACT PROFILE
# ==========================================

@app.route(
    "/dealer/profile",
    methods=["GET", "POST"]
)
@login_required("dealer")
def dealer_profile():
    dealer_id = g.user["dealer_id"]

    if dealer_id is None:
        abort(403)

    dealer = db().execute(
        "SELECT * FROM dealers WHERE id=?",
        (dealer_id,)
    ).fetchone()

    if dealer is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get(
            "name", ""
        ).strip()[:120]

        city = request.form.get(
            "city", ""
        ).strip()[:120]

        address = request.form.get(
            "address", ""
        ).strip()[:250]

        zip_code = request.form.get(
            "zip_code", ""
        ).strip()[:5]

        email = request.form.get(
            "email", ""
        ).strip().lower()[:254]

        sales_phone = request.form.get(
            "sales_phone", ""
        ).strip()[:30]

        service_phone = request.form.get(
            "service_phone", ""
        ).strip()[:30]

        if not name or not city:
            flash(
                "Dealership name and city are required.",
                "error"
            )

        elif (
            zip_code
            and not re.fullmatch(r"\d{5}", zip_code)
        ):
            flash(
                "ZIP code must contain five digits.",
                "error"
            )

        elif (
            email
            and not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email
            )
        ):
            flash(
                "Enter a valid dealership email address.",
                "error"
            )

        elif any(
            ch in address
            for ch in "\r\n"
        ):
            flash(
                "Enter a single-line street address.",
                "error"
            )

        elif any(
            not re.fullmatch(
                r"[0-9+(). \-]{7,30}",
                phone
            )
            for phone in (
                sales_phone,
                service_phone
            )
            if phone
        ):
            flash(
                "Enter valid sales and service phone numbers.",
                "error"
            )

        else:
            db().execute("""
                UPDATE dealers
                SET
                    name=?,
                    city=?,
                    address=?,
                    zip_code=?,
                    email=?,
                    sales_phone=?,
                    service_phone=?
                WHERE id=?
            """, (
                name,
                city,
                address,
                zip_code,
                email,
                sales_phone,
                service_phone,
                dealer_id
            ))

            db().commit()

            flash(
                "Dealership contact information updated.",
                "success"
            )

            return redirect(
                url_for("dealer_profile")
            )

    return render_template(
        "dealer_profile.html",
        dealer=dealer
    )


# ==========================================
# ADD VEHICLE
# ==========================================

@app.route(
    "/dealer/vehicles/new",
    methods=["GET", "POST"]
)
@login_required("dealer")
def add_vehicle():
    if request.method == "POST":
        try:
            year = int(request.form["year"])
            price = int(request.form["price"])
            mileage = int(request.form["mileage"])

            assert (
                1980 <= year
                <= datetime.now().year + 2
            )

            assert 0 <= price <= 10000000
            assert 0 <= mileage <= 2000000

            make = request.form[
                "make"
            ].strip()[:50]

            model = request.form[
                "model"
            ].strip()[:50]

            assert make and model

            vehicle_zip = request.form.get(
                "zip_code", ""
            ).strip()

            assert (
                not vehicle_zip
                or re.fullmatch(
                    r"\d{5}",
                    vehicle_zip
                )
            )

            condition = request.form.get(
                "condition", "used"
            ).strip().lower()

            assert condition in ("new", "used")

        except (
            ValueError,
            KeyError,
            AssertionError
        ):
            flash(
                "Check required vehicle fields "
                "and numeric values.",
                "error"
            )

            return render_template(
                "add_vehicle.html"
            )

        db().execute("""
            INSERT INTO vehicles(
                dealer_id,
                year,
                make,
                model,
                trim,
                price,
                mileage,
                vin,
                image_url,
                description,
                zip_code,
                condition
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            g.user["dealer_id"],
            year,
            make,
            model,
            request.form.get(
                "trim", ""
            ).strip()[:80],
            price,
            mileage,
            request.form.get(
                "vin", ""
            ).strip().upper()[:17],
            request.form.get(
                "image_url", ""
            ).strip()[:500],
            request.form.get(
                "description", ""
            ).strip()[:2000],
            vehicle_zip,
            condition
        ))

        db().commit()

        flash(
            "Vehicle listed.",
            "success"
        )

        return redirect(
            url_for("dealer_dashboard")
        )

    return render_template(
        "add_vehicle.html"
    )


# ==========================================
# ENABLE OR DISABLE VEHICLE
# ==========================================

@app.post(
    "/dealer/vehicles/<int:vid>/toggle"
)
@login_required("dealer")
def toggle_vehicle(vid):
    v = db().execute("""
        SELECT *
        FROM vehicles
        WHERE id=? AND dealer_id=?
    """, (
        vid,
        g.user["dealer_id"]
    )).fetchone()

    if not v:
        abort(404)

    db().execute(
        "UPDATE vehicles SET active=? WHERE id=?",
        (
            0 if v["active"] else 1,
            vid
        )
    )

    db().commit()

    return redirect(
        url_for("dealer_dashboard")
    )


# ==========================================
# LEAD DETAILS
# ==========================================

@app.get("/leads/<int:lead_id>")
@login_required()
def lead_detail(lead_id):
    lead = lead_for_role(lead_id)

    events = db().execute("""
        SELECT *
        FROM lead_events
        WHERE lead_id=?
        ORDER BY id DESC
    """, (lead_id,)).fetchall()

    reward = db().execute(
        "SELECT * FROM rewards WHERE lead_id=?",
        (lead_id,)
    ).fetchone()

    return render_template(
        "lead.html",
        lead=lead,
        events=events,
        reward=reward,
        gas=GAS
    )


# ==========================================
# DEALER RESPONSE
# ==========================================

@app.post(
    "/leads/<int:lead_id>/dealer-response"
)
@login_required("dealer")
def dealer_response(lead_id):
    lead = lead_for_role(lead_id)

    if lead["status"] not in (
        "new",
        "dealer_review",
        "appointment_proposed"
    ):
        abort(
            400,
            "This lead is not awaiting dealer response."
        )

    action = request.form.get("action")

    note = request.form.get(
        "note", ""
    ).strip()[:1000]

    if action == "propose":
        appt = request.form.get(
            "appointment_time", ""
        ).strip()

        try:
            parsed = datetime.fromisoformat(appt)

            assert parsed > datetime.now()

        except (
            ValueError,
            AssertionError
        ):
            flash(
                "Provide a future appointment time.",
                "error"
            )

            return redirect(
                url_for(
                    "lead_detail",
                    lead_id=lead_id
                )
            )

        db().execute("""
            UPDATE leads
            SET
                status=?,
                appointment_time=?,
                dealer_note=?
            WHERE id=?
        """, (
            "appointment_proposed",
            appt,
            note,
            lead_id
        ))

        event(
            lead_id,
            "dealer",
            "Dealer confirmed availability "
            "and proposed appointment: "
            + appt + ". " + note
        )

    elif action == "unavailable":
        db().execute("""
            UPDATE leads
            SET
                status=?,
                dealer_note=?
            WHERE id=?
        """, (
            "cancelled",
            note,
            lead_id
        ))

        event(
            lead_id,
            "dealer",
            "Vehicle unavailable. " + note
        )

    else:
        abort(400)

    db().commit()

    flash(
        "Response saved for the buyer in WE-SELL.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# ==========================================
# BUYER APPOINTMENT RESPONSE
# ==========================================

@app.post(
    "/leads/<int:lead_id>/buyer-response"
)
@login_required("buyer")
def buyer_response(lead_id):
    lead = lead_for_role(lead_id)

    if lead["status"] != "appointment_proposed":
        abort(400)

    action = request.form.get("action")

    status = (
        "confirmed"
        if action == "accept"
        else "cancelled"
        if action == "decline"
        else None
    )

    if not status:
        abort(400)

    db().execute(
        "UPDATE leads SET status=? WHERE id=?",
        (
            status,
            lead_id
        )
    )

    event(
        lead_id,
        "buyer",
        "Buyer " + (
            "accepted appointment."
            if status == "confirmed"
            else "declined appointment."
        )
    )

    db().commit()

    flash(
        "Appointment response saved.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# ==========================================
# DEALER REPORTS SALE
# ==========================================

@app.post("/leads/<int:lead_id>/sale")
@login_required("dealer")
def sale(lead_id):
    lead = lead_for_role(lead_id)

    if lead["status"] not in (
        "confirmed",
        "visited"
    ):
        abort(
            400,
            "An appointment must be confirmed first."
        )

    db().execute(
        "UPDATE leads SET status=? WHERE id=?",
        (
            "sold_pending",
            lead_id
        )
    )

    event(
        lead_id,
        "dealer",
        "Dealership reported completed purchase. "
        "Awaiting WE-SELL verification."
    )

    db().commit()

    flash(
        "Sale reported for WE-SELL verification.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# ==========================================
# ADMIN DASHBOARD
# ==========================================

@app.get("/admin")
@login_required("admin")
def admin_dashboard():
    leads = db().execute("""
        SELECT
            l.*,
            v.year,
            v.make,
            v.model,
            d.name AS dealer_name,
            u.name AS buyer_name
        FROM leads l
        JOIN vehicles v ON v.id=l.vehicle_id
        JOIN dealers d ON d.id=l.dealer_id
        JOIN users u ON u.id=l.buyer_id
        ORDER BY l.id DESC
    """).fetchall()

    stats = {
        key: db().execute(
            "SELECT COUNT(*) FROM " + table
        ).fetchone()[0]

        for key, table in [
            ("vehicles", "vehicles"),
            ("dealers", "dealers"),
            (
                "buyers",
                'users WHERE role="buyer"'
            ),
            ("leads", "leads")
        ]
    }

    return render_template(
        "admin.html",
        leads=leads,
        stats=stats
    )


# ==========================================
# ADMIN VERIFY SALE
# ==========================================

@app.post(
    "/admin/leads/<int:lead_id>/verify"
)
@login_required("admin")
def verify_sale(lead_id):
    lead = lead_for_role(lead_id)

    if lead["status"] != "sold_pending":
        abort(
            400,
            "Sale must first be reported by dealer."
        )

    db().execute("""
        UPDATE leads
        SET
            status=?,
            purchase_verified_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        "sold_verified",
        lead_id
    ))

    db().execute("""
        INSERT OR IGNORE INTO rewards(
            lead_id,
            station,
            amount,
            status
        )
        VALUES(?,?,25,?)
    """, (
        lead_id,
        lead["gas_station"],
        "pending"
    ))

    event(
        lead_id,
        "admin",
        "WE-SELL verified the purchase. "
        "$25 gas reward eligible; issuance pending."
    )

    db().commit()

    flash(
        "Purchase verified; gift-card reward queued.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# ==========================================
# ISSUE GIFT CARD REWARD
# ==========================================

@app.post(
    "/admin/leads/<int:lead_id>/issue-reward"
)
@login_required("admin")
def issue_reward(lead_id):
    lead = lead_for_role(lead_id)

    if lead["status"] != "sold_verified":
        abort(400)

    reward = db().execute(
        "SELECT * FROM rewards WHERE lead_id=?",
        (lead_id,)
    ).fetchone()

    if (
        not reward
        or reward["status"] == "issued"
    ):
        abort(400)

    db().execute("""
        UPDATE rewards
        SET
            status='issued',
            issued_at=CURRENT_TIMESTAMP
        WHERE lead_id=?
    """, (lead_id,))

    event(
        lead_id,
        "admin",
        "Gift-card delivery marked complete "
        "by administrator."
    )

    db().commit()

    flash(
        "Reward marked issued.",
        "success"
    )

    return redirect(
        url_for(
            "lead_detail",
            lead_id=lead_id
        )
    )


# ==========================================
# HOW IT WORKS
# ==========================================

@app.get("/how-it-works")
def how_it_works():
    return render_template("how.html")


# ==========================================
# DEALERS INFORMATION PAGE
# ==========================================

@app.get("/dealers")
def dealers_page():
    return render_template(
        "dealers_info.html"
    )


# ==========================================
# PUBLIC DEALERSHIP DIRECTORY
# ==========================================

@app.get("/dealers/all")
def dealer_directory():
    dealers = db().execute("""
        SELECT
            d.*,
            COUNT(v.id) AS vehicle_count,
            MIN(v.price) AS lowest_price
        FROM dealers d
        LEFT JOIN vehicles v
            ON v.dealer_id=d.id
            AND v.active=1
        WHERE d.approved=1
        GROUP BY d.id
        ORDER BY d.name COLLATE NOCASE
    """).fetchall()

    return render_template(
        "dealer_directory.html",
        dealers=dealers
    )


# ==========================================
# INDIVIDUAL DEALERSHIP INVENTORY
# ==========================================

@app.get(
    "/dealers/<int:dealer_id>/inventory"
)
def dealer_inventory(dealer_id):
    dealer = db().execute("""
        SELECT *
        FROM dealers
        WHERE id=? AND approved=1
    """, (dealer_id,)).fetchone()

    if dealer is None:
        abort(404)

    q = request.args.get(
        "q", ""
    ).strip()[:80]

    make = request.args.get(
        "make", ""
    ).strip()[:50]

    sort = request.args.get(
        "sort",
        "newest"
    )

    def optional_nonnegative_int(field):
        raw = request.args.get(
            field, ""
        ).strip()

        try:
            number = int(raw)

            if 0 <= number <= 10000000:
                return number

            return None

        except ValueError:
            return None

    min_price = optional_nonnegative_int(
        "min_price"
    )

    max_price = optional_nonnegative_int(
        "max_price"
    )

    max_mileage = optional_nonnegative_int(
        "max_mileage"
    )

    sql = """
        SELECT *
        FROM vehicles
        WHERE dealer_id=? AND active=1
    """

    params = [dealer_id]

    if q:
        sql += """
            AND (
                make LIKE ?
                OR model LIKE ?
                OR trim LIKE ?
                OR CAST(year AS TEXT) LIKE ?
            )
        """

        params.extend(
            ["%" + q + "%"] * 4
        )

    if make:
        sql += " AND make=?"
        params.append(make)

    if min_price is not None:
        sql += " AND price>=?"
        params.append(min_price)

    if max_price is not None:
        sql += " AND price<=?"
        params.append(max_price)

    if max_mileage is not None:
        sql += " AND mileage<=?"
        params.append(max_mileage)

    orders = {
        "newest": "created_at DESC, id DESC",
        "price_low": "price ASC, id DESC",
        "price_high": "price DESC, id DESC",
        "mileage_low": "mileage ASC, id DESC",
        "year_new": "year DESC, id DESC"
    }

    if sort not in orders:
        sort = "newest"

    sql += " ORDER BY " + orders[sort]

    vehicles = db().execute(
        sql,
        params
    ).fetchall()

    makes = db().execute("""
        SELECT DISTINCT make
        FROM vehicles
        WHERE dealer_id=? AND active=1
        ORDER BY make
    """, (dealer_id,)).fetchall()

    total = db().execute("""
        SELECT COUNT(*)
        FROM vehicles
        WHERE dealer_id=? AND active=1
    """, (dealer_id,)).fetchone()[0]

    return render_template(
        "dealer_inventory.html",
        dealer=dealer,
        vehicles=vehicles,
        makes=makes,
        total=total,
        q=q,
        selected_make=make,
        sort=sort,
        min_price=min_price,
        max_price=max_price,
        max_mileage=max_mileage
    )


# ==========================================
# REGISTER RENTAL COMPANY PORTAL
# ==========================================

app.register_blueprint(rental_portal)

# Google OAuth routes for securely linked rental and dealer accounts
app.register_blueprint(social_auth)
init_social_auth(app)


# ==========================================
# REGISTER INVENTORY SYNC API
# ==========================================

app.register_blueprint(inventory_sync)


# ==========================================
# INITIALIZE DATABASES
# ==========================================

init_db()
init_rental_portal()
init_inventory_sync()


# ==========================================
# RENTAL COMPANY ADMINISTRATION
# ==========================================

@app.get("/admin/rental-companies")
@login_required("admin")
def admin_rental_companies():
    # Rental accounts live in PostgreSQL, separately from the original
    # SQLite-backed buyer/dealer/admin accounts.
    from rental_portal import db as rental_db
    from flask import render_template_string

    with rental_db() as conn:
        companies = conn.execute("""
            SELECT id, company_name, contact_name, email, phone,
                   city, website, approved, created_at
            FROM rental_companies
            ORDER BY CASE WHEN approved = 0 THEN 0 ELSE 1 END,
                     created_at DESC, id DESC
        """).fetchall()

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Rental Company Approvals | WE-SELL</title>
      <style>
        *{box-sizing:border-box}
        body{margin:0;background:#f3f6fa;color:#09223d;font-family:Arial,sans-serif}
        header{background:#041b34;color:#fff;padding:23px max(22px,calc((100% - 1160px)/2));font-size:22px;font-weight:800}
        header b{color:#ffc400}
        main{max-width:1160px;margin:35px auto;padding:0 20px}
        a{color:#075ba8;text-decoration:none}
        .back{display:inline-block;margin-bottom:20px}
        .panel{background:white;border-radius:14px;padding:24px;box-shadow:0 6px 25px #09223d13}
        h1{margin:0 0 8px;font-size:27px}
        .intro{color:#596b7e;margin:0 0 22px}
        .table-wrap{overflow-x:auto}
        table{border-collapse:collapse;width:100%;min-width:750px}
        th,td{padding:13px 10px;border-bottom:1px solid #e5eaf0;text-align:left;vertical-align:middle;font-size:14px}
        th{color:#516477;font-size:12px;text-transform:uppercase}
        small{display:block;color:#65778a;margin-top:5px}
        .pill{display:inline-block;border-radius:20px;padding:6px 10px;background:#fff3d2;color:#795300;font-weight:bold;font-size:12px}
        .pill.yes{background:#e1f5e8;color:#17643b}
        .actions{display:flex;gap:7px;flex-wrap:wrap}
        button{border:0;border-radius:7px;padding:9px 12px;font-weight:bold;cursor:pointer}
        .approve{background:#ffc400;color:#041b34}
        .reject{background:#e8edf3;color:#263b50}
        .messages{padding:12px 16px;background:#e8f3ff;border-radius:8px;margin-bottom:18px}
      </style>
    </head>
    <body>
      <header><b>WE-SELL</b> | Administration</header>
      <main>
        <a class="back" href="{{ url_for('admin_dashboard') }}">← Back to Admin Dashboard</a>
        {% with messages=get_flashed_messages() %}
          {% for message in messages %}<div class="messages">{{ message }}</div>{% endfor %}
        {% endwith %}
        <div class="panel">
          <h1>Rental Company Approvals</h1>
          <p class="intro">Review and manage businesses registered with WE-SELL.</p>
          <div class="table-wrap"><table>
            <thead><tr><th>Company</th><th>Contact</th><th>City</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
            {% for company in companies %}
              <tr>
                <td><strong>{{ company.company_name }}</strong><small>{{ company.email }}</small></td>
                <td>{{ company.contact_name }}<small>{{ company.phone or '' }}</small></td>
                <td>{{ company.city or '—' }}</td>
                <td><span class="pill {{ 'yes' if company.approved else '' }}">{{ 'Approved' if company.approved else 'Pending / Not approved' }}</span></td>
                <td><div class="actions">
                  {% if not company.approved %}
                    <form method="post" action="{{ url_for('admin_rental_company_status', company_id=company.id) }}">
                      <input type="hidden" name="csrf" value="{{ csrf }}">
                      <input type="hidden" name="action" value="approve">
                      <button class="approve" type="submit">Approve</button>
                    </form>
                  {% else %}
                    <form method="post" action="{{ url_for('admin_rental_company_status', company_id=company.id) }}">
                      <input type="hidden" name="csrf" value="{{ csrf }}">
                      <input type="hidden" name="action" value="reject">
                      <button class="reject" type="submit" onclick="return confirm('Revoke approval for this company?')">Revoke approval</button>
                    </form>
                  {% endif %}
                </div></td>
              </tr>
            {% else %}
              <tr><td colspan="5">No rental companies have registered yet.</td></tr>
            {% endfor %}
            </tbody>
          </table></div>
        </div>
      </main>
    </body></html>
    """, companies=companies)


@app.post("/admin/rental-companies/<int:company_id>/status")
@login_required("admin")
def admin_rental_company_status(company_id):
    from rental_portal import db as rental_db

    action = request.form.get("action", "")
    if action not in ("approve", "reject"):
        abort(400)

    approved = 1 if action == "approve" else 0
    with rental_db() as conn:
        result = conn.execute(
            "UPDATE rental_companies SET approved=? WHERE id=?",
            (approved, company_id)
        )
        if result.rowcount != 1:
            abort(404)

    flash("Rental company approved." if approved else "Rental company approval revoked.", "success")
    return redirect(url_for("admin_rental_companies"))


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1"
    )
