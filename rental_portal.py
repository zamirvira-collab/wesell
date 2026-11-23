
import os
import re
import sqlite3
import secrets

from contextlib import contextmanager
from functools import wraps

from flask import (
    Blueprint,
    request,
    session,
    redirect,
    url_for,
    flash,
    abort,
    render_template_string
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# ==========================================
# WE-SELL RENTAL COMPANY PORTAL
# ==========================================

ROOT = os.path.dirname(os.path.abspath(__file__))

DB = os.environ.get(
    "WESELL_DB",
    os.path.join(ROOT, "wesell.db")
)

rental_portal = Blueprint(
    "rental_portal",
    __name__,
    url_prefix="/rental-company"
)


# ==========================================
# DATABASE CONNECTION
# ==========================================

@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def init_rental_portal():

    with db() as conn:

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS rental_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone TEXT DEFAULT '',
            city TEXT DEFAULT '',
            website TEXT DEFAULT '',
            approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rental_vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            make TEXT NOT NULL,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            daily_rate_cents INTEGER NOT NULL,
            pickup_city TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id)
                REFERENCES rental_companies(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_rental_company
        ON rental_vehicles(company_id);
        """)


# ==========================================
# HTML PAGE DESIGN
# ==========================================

PAGE = """
<!doctype html>
<html lang="en">

<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>{{ title }} | WE-SELL</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: #f3f6fa;
    color: #071d36;
}

header {
    background: #041b34;
    color: white;
    padding: 22px 30px;
}

header strong {
    color: #ffc400;
    font-size: 24px;
}

main {
    max-width: 1000px;
    margin: 45px auto;
    padding: 0 20px;
}

.panel {
    background: white;
    border-radius: 15px;
    padding: 30px;
    box-shadow: 0 8px 30px rgba(0,0,0,.08);
    margin-bottom: 25px;
}

h1, h2 {
    margin-top: 0;
}

label {
    display: block;
    font-weight: bold;
    margin: 15px 0 7px;
}

input, select, textarea {
    width: 100%;
    padding: 13px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 15px;
}

button, .btn {
    display: inline-block;
    background: #ffc400;
    color: #071d36;
    padding: 14px 22px;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: bold;
    cursor: pointer;
    text-decoration: none;
    margin-top: 18px;
}

button:hover, .btn:hover {
    background: #e9b100;
}

a {
    color: #075ba8;
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 18px;
}

.notice {
    background: #fff6d8;
    padding: 14px;
    border-radius: 8px;
    margin: 15px 0;
}

.message {
    padding: 13px;
    background: #e8f3ff;
    margin-bottom: 15px;
    border-radius: 8px;
}

.vehicle {
    border: 1px solid #e2e8f0;
    padding: 18px;
    margin-top: 12px;
    border-radius: 10px;
}

@media(max-width: 650px) {
    .grid {
        grid-template-columns: 1fr;
    }
}

</style>
</head>

<body>

<header>
    <strong>WE-SELL</strong>
    &nbsp; Rental Company Portal
</header>

<main>

{% with messages = get_flashed_messages() %}
    {% for message in messages %}
        <div class="message">{{ message }}</div>
    {% endfor %}
{% endwith %}

{{ content | safe }}

</main>
</body>
</html>
"""


def page(title, content, **kwargs):
    from flask import render_template_string

    inner = render_template_string(
        content,
        **kwargs
    )

    return render_template_string(
        PAGE,
        title=title,
        content=inner
    )


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)

    return session["csrf"]


# ==========================================
# LOGIN PROTECTION
# ==========================================

def rental_login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not session.get("rental_company_id"):
            return redirect(
                url_for("rental_portal.login")
            )

        return func(*args, **kwargs)

    return wrapper


def current_company():

    company_id = session.get(
        "rental_company_id"
    )

    if not company_id:
        return None

    with db() as conn:
        company = conn.execute("""
            SELECT *
            FROM rental_companies
            WHERE id=?
        """, (company_id,)).fetchone()

    return company


# ==========================================
# COMPANY REGISTRATION
# ==========================================

@rental_portal.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        company_name = request.form.get(
            "company_name", ""
        ).strip()[:150]

        contact_name = request.form.get(
            "contact_name", ""
        ).strip()[:120]

        email = request.form.get(
            "email", ""
        ).strip().lower()[:254]

        password = request.form.get(
            "password", ""
        )

        phone = request.form.get(
            "phone", ""
        ).strip()[:30]

        city = request.form.get(
            "city", ""
        ).strip()[:120]

        website = request.form.get(
            "website", ""
        ).strip()[:500]

        if (
            not company_name
            or not contact_name
            or not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email
            )
            or len(password) < 10
        ):
            flash(
                "Please complete all required fields. "
                "Password must contain at least 10 characters."
            )

        else:

            try:

                with db() as conn:

                    conn.execute("""
                        INSERT INTO rental_companies
                        (
                            company_name,
                            contact_name,
                            email,
                            password_hash,
                            phone,
                            city,
                            website,
                            approved
                        )
                        VALUES (?,?,?,?,?,?,?,0)
                    """, (
                        company_name,
                        contact_name,
                        email,
                        generate_password_hash(password),
                        phone,
                        city,
                        website
                    ))

                flash(
                    "Registration received. "
                    "Your company is awaiting WE-SELL approval."
                )

                return redirect(
                    url_for("rental_portal.login")
                )

            except sqlite3.IntegrityError:

                flash(
                    "This email is already registered."
                )

    return page(
        "Company Registration",
        """
        <div class="panel">

        <h1>Register Your Rental Company</h1>

        <p>
        Join WE-SELL and connect your rental
        vehicle inventory to our marketplace.
        </p>

        <form method="POST">

        <input type="hidden"
               name="csrf"
               value="{{ csrf }}">

        <label>Rental Company Name</label>
        <input name="company_name" required>

        <label>Contact Person</label>
        <input name="contact_name" required>

        <label>Business Email</label>
        <input type="email"
               name="email"
               required>

        <label>Password</label>
        <input type="password"
               name="password"
               minlength="10"
               required>

        <label>Phone Number</label>
        <input name="phone">

        <label>City</label>
        <input name="city">

        <label>Company Website</label>
        <input type="url"
               name="website"
               placeholder="https://example.com">

        <button type="submit">
            Register Company
        </button>

        </form>

        <p>
        Already registered?
        <a href="{{ login_url }}">Login here</a>
        </p>

        </div>
        """,
        csrf=csrf_token(),
        login_url=url_for("rental_portal.login")
    )


# ==========================================
# COMPANY LOGIN
# ==========================================

@rental_portal.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        with db() as conn:

            company = conn.execute("""
                SELECT *
                FROM rental_companies
                WHERE email=?
            """, (email,)).fetchone()

        if (
            company
            and check_password_hash(
                company["password_hash"],
                password
            )
        ):

            session.clear()

            session["rental_company_id"] = (
                company["id"]
            )

            return redirect(
                url_for("rental_portal.dashboard")
            )

        flash("Incorrect email or password.")

    return page(
        "Rental Company Login",
        """
        <div class="panel">

        <h1>Rental Company Login</h1>

        <form method="POST">

        <input type="hidden"
               name="csrf"
               value="{{ csrf }}">

        <label>Email Address</label>
        <input type="email"
               name="email"
               required>

        <label>Password</label>
        <input type="password"
               name="password"
               required>

        <button type="submit">
            Login to Portal
        </button>

        </form>

        <p>
        New rental company?
        <a href="{{ register_url }}">Register</a>
        </p>

        </div>
        """,
        csrf=csrf_token(),
        register_url=url_for(
            "rental_portal.register"
        )
    )


# ==========================================
# COMPANY DASHBOARD
# ==========================================

@rental_portal.get("/dashboard")
@rental_login_required
def dashboard():

    company = current_company()

    if not company:
        session.pop("rental_company_id", None)
        abort(401)

    with db() as conn:

        vehicles = conn.execute("""
            SELECT *
            FROM rental_vehicles
            WHERE company_id=?
            ORDER BY id DESC
        """, (company["id"],)).fetchall()

    return page(
        "Company Dashboard",
        """
        <div class="panel">

        <h1>{{ company.company_name }}</h1>

        <p>Rental Company Dashboard</p>

        {% if not company.approved %}
        <div class="notice">
        Your company is awaiting WE-SELL approval.
        Listings are not publicly visible yet.
        </div>
        {% endif %}

        <a class="btn" href="{{ add_url }}">
            + Add Rental Vehicle
        </a>

        <a class="btn" href="{{ sync_url }}">
            Inventory Synchronization
        </a>

        </div>

        <div class="panel">

        <h2>Your Rental Vehicles</h2>

        <p>
        Total Vehicles: {{ vehicles|length }}
        </p>

        {% for vehicle in vehicles %}

        <div class="vehicle">

        <h3>
        {{ vehicle.year }}
        {{ vehicle.make }}
        {{ vehicle.model }}
        </h3>

        <p>
        Category: {{ vehicle.category }}
        </p>

        <p>
        Daily Rate:
        ${{ "%.2f"|format(
            vehicle.daily_rate_cents / 100
        ) }}
        </p>

        <p>
        Pickup City: {{ vehicle.pickup_city }}
        </p>

        <p>
        Status: {{ vehicle.status }}
        </p>

        </div>

        {% else %}

        <p>No vehicles listed yet.</p>

        {% endfor %}

        </div>
        """,
        company=company,
        vehicles=vehicles,
        add_url=url_for(
            "rental_portal.add_vehicle"
        ),
        sync_url="/rental-sync/dashboard"
    )


# ==========================================
# ADD RENTAL VEHICLE
# ==========================================

@rental_portal.route(
    "/vehicles/new",
    methods=["GET", "POST"]
)
@rental_login_required
def add_vehicle():

    company = current_company()

    if not company:
        abort(401)

    if request.method == "POST":

        try:

            year = int(
                request.form.get("year", "")
            )

            make = request.form.get(
                "make", ""
            ).strip()[:80]

            model = request.form.get(
                "model", ""
            ).strip()[:80]

            category = request.form.get(
                "category", ""
            ).strip().lower()

            rate = request.form.get(
                "daily_rate", ""
            ).strip()

            from decimal import Decimal

            cents_value = Decimal(rate) * 100

            if (
                not cents_value.is_finite()
                or cents_value != cents_value.to_integral_value()
            ):
                raise ValueError()

            cents = int(cents_value)

            city = request.form.get(
                "pickup_city", ""
            ).strip()[:120]

            description = request.form.get(
                "description", ""
            ).strip()[:2000]

            if (
                not 1980 <= year <= 2100
                or not make
                or not model
                or not city
                or not 0 < cents <= 100000000
                or category not in (
                    "economy",
                    "sedan",
                    "suv",
                    "luxury",
                    "van"
                )
            ):
                raise ValueError()

        except (
            ValueError,
            ArithmeticError
        ):

            flash(
                "Please check your vehicle information."
            )

        else:

            with db() as conn:

                conn.execute("""
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
                    company["id"],
                    year,
                    make,
                    model,
                    category,
                    cents,
                    city,
                    description,
                    "available"
                ))

            flash("Rental vehicle added.")

            return redirect(
                url_for("rental_portal.dashboard")
            )

    return page(
        "Add Rental Vehicle",
        """
        <div class="panel">

        <h1>Add Rental Vehicle</h1>

        <form method="POST">

        <input type="hidden"
               name="csrf"
               value="{{ csrf }}">

        <div class="grid">

        <div>
        <label>Vehicle Year</label>
        <input type="number"
               name="year"
               min="1980"
               max="2100"
               required>
        </div>

        <div>
        <label>Vehicle Make</label>
        <input name="make" required>
        </div>

        <div>
        <label>Vehicle Model</label>
        <input name="model" required>
        </div>

        <div>
        <label>Vehicle Category</label>
        <select name="category" required>
            <option value="economy">Economy</option>
            <option value="sedan">Sedan</option>
            <option value="suv">SUV</option>
            <option value="luxury">Luxury</option>
            <option value="van">Van</option>
        </select>
        </div>

        <div>
        <label>Daily Rental Price ($)</label>
        <input type="number"
               name="daily_rate"
               step="0.01"
               min="0.01"
               required>
        </div>

        <div>
        <label>Pickup City</label>
        <input name="pickup_city" required>
        </div>

        </div>

        <label>Vehicle Description</label>
        <textarea name="description"
                  rows="4"></textarea>

        <button type="submit">
            Save Rental Vehicle
        </button>

        </form>

        </div>
        """,
        csrf=csrf_token()
    )


# ==========================================
# COMPANY LOGOUT
# ==========================================

@rental_portal.post("/logout")
@rental_login_required
def logout():

    session.clear()

    return redirect(
        url_for("rental_portal.login")
    )
