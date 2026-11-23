
import os
import re
import sqlite3
import secrets

from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
from functools import wraps

from flask import (
    Blueprint,
    request,
    session,
    redirect,
    url_for,
    flash,
    render_template,
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
# LOGIN AND SECURITY HELPERS
# ==========================================

def csrf_token():

    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)

    return session["csrf"]


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

    company_id = session.get("rental_company_id")

    if not company_id:
        return None

    with db() as conn:
        company = conn.execute(
            """
            SELECT *
            FROM rental_companies
            WHERE id=?
            """,
            (company_id,)
        ).fetchone()

    return company


# ==========================================
# SHARED PAGE DESIGN
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
    font-family: Arial, Helvetica, sans-serif;
    background: #f3f6fa;
    color: #071d36;
}

header {
    background: #041b34;
    color: white;
    padding: 22px 30px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 15px;
    flex-wrap: wrap;
}

header strong {
    color: #ffc400;
    font-size: 24px;
}

.header-title {
    margin-left: 10px;
    font-size: 15px;
    font-weight: 600;
}

.header-home {
    color: #ffffff;
    text-decoration: none;
    font-size: 13px;
    font-weight: 700;
    border: 1px solid #68819a;
    border-radius: 8px;
    padding: 10px 14px;
}

.header-home:hover {
    background: #123a60;
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

.home-return {
    margin-top: 28px;
    padding-top: 20px;
    border-top: 1px solid #e2e8f0;
}

.home-return a {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: 13px 20px;
    background: #061b34;
    color: #ffffff;
    border-radius: 9px;
    font-size: 14px;
    font-weight: 700;
    text-decoration: none;
}

.home-return a:hover {
    background: #123a60;
}

@media(max-width: 650px) {
    .grid {
        grid-template-columns: 1fr;
    }

    main {
        margin-top: 25px;
    }

    .panel {
        padding: 22px;
    }

    header {
        padding: 18px;
    }
}
</style>
</head>

<body>

<header>

    <div>
        <strong>WE-SELL</strong>
        <span class="header-title">
            Rental Company Portal
        </span>
    </div>

    <a class="header-home" href="/">
        ← Main Website
    </a>

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

    inner = render_template_string(
        content,
        **kwargs
    )

    return render_template_string(
        PAGE,
        title=title,
        content=inner
    )


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

                    conn.execute(
                        """
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
                        """,
                        (
                            company_name,
                            contact_name,
                            email,
                            generate_password_hash(password),
                            phone,
                            city,
                            website
                        )
                    )

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

        <div class="home-return">
            <a href="/">
                ← Back to WE-SELL Home
            </a>
        </div>

        </div>
        """,
        csrf=csrf_token(),
        login_url=url_for("rental_portal.login")
    )


# ==========================================
# COMPANY LOGIN — WE-SELL BUSINESS PORTAL
# ==========================================

@rental_portal.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        with db() as conn:
            company = conn.execute(
                """
                SELECT *
                FROM rental_companies
                WHERE email=?
                """,
                (email,)
            ).fetchone()

        if (
            company
            and check_password_hash(
                company["password_hash"],
                password
            )
        ):
            session.clear()
            session["rental_company_id"] = company["id"]

            return redirect(
                url_for("rental_portal.dashboard")
            )

        flash("Incorrect email or password.")

    return page(
        "Rental Company Login",
        """
        <style>
        .rental-login-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            background: #ffffff;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 15px 45px rgba(4,27,52,.12);
            min-height: 580px;
        }

        .rental-login-left {
            background: linear-gradient(
                145deg, #041b34, #0a355b
            );
            color: white;
            padding: 48px 36px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .rental-brand {
            font-size: 30px;
            font-weight: 900;
            color: #ffc400;
            letter-spacing: -1px;
        }

        .rental-brand-sub {
            color: #bad1e5;
            font-size: 12px;
            margin-top: 4px;
        }

        .rental-login-left h1 {
            font-size: 36px;
            line-height: 1.2;
            color: white;
            margin: 32px 0 18px;
        }

        .rental-login-left p {
            color: #d5e3f0;
            font-size: 15px;
            line-height: 1.8;
        }

        .rental-feature {
            display: flex;
            align-items: center;
            gap: 12px;
            color: #e6eef6;
            font-size: 14px;
            margin: 17px 0;
        }

        .rental-check {
            color: #ffc400;
            font-weight: bold;
            font-size: 19px;
        }

        .rental-login-left-footer {
            color: #b2cce0;
            font-size: 12px;
            margin-top: 35px;
        }

        .rental-login-right {
            padding: 42px 38px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .rental-login-right h2 {
            font-size: 29px;
            color: #041b34;
            margin: 0 0 9px;
        }

        .rental-login-description {
            color: #64748b;
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 20px;
        }

        .rental-login-right label {
            font-size: 13px;
            color: #102b46;
            font-weight: 700;
            margin: 15px 0 7px;
        }

        .rental-login-right input {
            width: 100%;
            border: 1px solid #d4deea;
            border-radius: 9px;
            padding: 14px;
            font-size: 14px;
            background: white;
        }

        .rental-login-right input:focus {
            outline: none;
            border-color: #00a99d;
            box-shadow: 0 0 0 3px rgba(0,169,157,.12);
        }

        .rental-login-submit {
            display: block;
            width: 100%;
            background: linear-gradient(
                90deg, #ffda61, #ffc400
            );
            color: #041b34;
            font-size: 15px;
            font-weight: 800;
            border: none;
            border-radius: 9px;
            padding: 15px;
            margin-top: 24px;
            cursor: pointer;
        }

        .rental-login-submit:hover {
            background: #edb800;
        }

        .rental-or {
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 25px 0 17px;
            color: #8290a0;
            font-size: 12px;
        }

        .rental-or:before,
        .rental-or:after {
            content: "";
            flex: 1;
            height: 1px;
            background: #e2e8f0;
        }

        .rental-social-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }

        .rental-social-option {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 9px;
            min-height: 49px;
            padding: 11px 8px;
            border: 1px solid #dce4ed;
            border-radius: 10px;
            background: #f8fafc;
            color: #26384e;
            font-size: 13px;
            font-weight: 700;
            margin: 0;
            opacity: .72;
            cursor: not-allowed;
        }

        .rental-social-option:disabled {
            background: #f8fafc;
            color: #26384e;
        }

        .rental-social-icon {
            font-size: 21px;
            font-weight: 900;
            line-height: 1;
        }

        .rental-google {
            color: #4285f4;
        }

        .rental-facebook {
            color: #1877f2;
        }

        .rental-linkedin {
            color: #0a66c2;
            font-size: 18px;
        }

        .rental-apple {
            color: #111827;
            font-size: 23px;
        }

        .rental-social-status {
            color: #64748b;
            font-size: 11px;
            text-align: center;
            margin: 12px 0 0;
        }

        .rental-register-link {
            margin-top: 27px;
            text-align: center;
            color: #64748b;
            font-size: 13px;
        }

        .rental-register-link a {
            color: #007f91;
            font-weight: 800;
            text-decoration: none;
        }

        .rental-home-link {
            margin-top: 25px;
            text-align: center;
        }

        .rental-home-link a {
            color: #64748b;
            font-size: 13px;
            font-weight: 700;
            text-decoration: none;
        }

        @media (max-width: 760px) {
            .rental-login-layout {
                grid-template-columns: 1fr;
            }

            .rental-login-left {
                padding: 30px 24px;
            }

            .rental-login-left h1 {
                font-size: 27px;
                margin: 22px 0 12px;
            }

            .rental-login-right {
                padding: 32px 24px;
            }
        }

        @media (max-width: 380px) {
            .rental-social-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>

        <div class="rental-login-layout">

            <!-- LEFT SIDE: BUSINESS INTRODUCTION -->

            <section class="rental-login-left">

                <div>

                    <div class="rental-brand">
                        WE-SELL
                    </div>

                    <div class="rental-brand-sub">
                        Advertising & Connections
                    </div>

                    <h1>
                        Grow Your<br>
                        Rental Business.
                    </h1>

                    <p>
                        Manage your rental vehicles,
                        advertise your inventory, and
                        connect with potential customers
                        through one professional platform.
                    </p>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Manage your rental fleet
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Advertise available vehicles
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Connect with rental customers
                    </div>

                    <div class="rental-feature">
                        <span class="rental-check">✓</span>
                        Access your business dashboard
                    </div>

                </div>

                <div class="rental-login-left-footer">
                    WE-SELL Business Portal
                </div>

            </section>

            <!-- RIGHT SIDE: LOGIN -->

            <section class="rental-login-right">

                <h2>Welcome Back</h2>

                <p class="rental-login-description">
                    Sign in to your rental company account
                    to manage your business.
                </p>

                <form method="POST">

                    <input
                        type="hidden"
                        name="csrf"
                        value="{{ csrf }}"
                    >

                    <label for="rental-email">
                        Business Email Address
                    </label>

                    <input
                        id="rental-email"
                        type="email"
                        name="email"
                        placeholder="Enter your email address"
                        autocomplete="email"
                        required
                    >

                    <label for="rental-password">
                        Password
                    </label>

                    <input
                        id="rental-password"
                        type="password"
                        name="password"
                        placeholder="Enter your password"
                        autocomplete="current-password"
                        required
                    >

                    <button
                        type="submit"
                        class="rental-login-submit"
                    >
                        Sign In to Dashboard →
                    </button>

                </form>

                <div class="rental-or">
                    Or continue with
                </div>

                <!-- SOCIAL SIGN-IN OPTIONS -->
                <!-- Buttons remain disabled until
                     secure OAuth account linking
                     has been implemented. -->

                <div class="rental-social-grid">

                    <!-- GOOGLE / GMAIL -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Google sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-google">
                            G
                        </span>
                        Google / Gmail
                    </button>

                    <!-- FACEBOOK -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Facebook sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-facebook">
                            f
                        </span>
                        Facebook
                    </button>

                    <!-- LINKEDIN -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="LinkedIn sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-linkedin">
                            in
                        </span>
                        LinkedIn
                    </button>

                    <!-- APPLE -->

                    <button
                        type="button"
                        class="rental-social-option"
                        disabled
                        title="Apple sign-in coming soon"
                    >
                        <span class="rental-social-icon rental-apple">
                            &#63743;
                        </span>
                        Apple
                    </button>

                </div>

                <p class="rental-social-status">
                    Social sign-in coming soon
                </p>

                <div class="rental-register-link">
                    New rental company?
                    <a href="{{ register_url }}">
                        Create a Business Account
                    </a>
                </div>

                <div class="rental-home-link">
                    <a href="/">
                        ← Return to WE-SELL Main Website
                    </a>
                </div>

            </section>

        </div>
        """,
        csrf=csrf_token(),
        register_url=url_for(
            "rental_portal.register"
        )
    )

# ==========================================
# RENTAL COMPANY DASHBOARD
# ==========================================

@rental_portal.get("/dashboard")
@rental_login_required
def dashboard():

    company = current_company()

    if not company:

        session.pop("rental_company_id", None)

        return redirect(
            url_for("rental_portal.login")
        )

    with db() as conn:

        vehicles = conn.execute(
            """
            SELECT *
            FROM rental_vehicles
            WHERE company_id=?
            ORDER BY id DESC
            """,
            (company["id"],)
        ).fetchall()

    total_vehicles = len(vehicles)

    active_vehicles = sum(
        1
        for vehicle in vehicles
        if vehicle["status"] in (
            "available",
            "active"
        )
    )

    inactive_vehicles = (
        total_vehicles - active_vehicles
    )

    return render_template(
        "rental_company_dashboard.html",
        company=company,
        vehicles=vehicles,
        total_vehicles=total_vehicles,
        active_vehicles=active_vehicles,
        inactive_vehicles=inactive_vehicles,
        csrf_token=csrf_token()
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

        session.pop("rental_company_id", None)

        return redirect(
            url_for("rental_portal.login")
        )

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
            ArithmeticError,
            InvalidOperation
        ):

            flash(
                "Please check your vehicle information."
            )

        else:

            with db() as conn:

                conn.execute(
                    """
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
                    """,
                    (
                        company["id"],
                        year,
                        make,
                        model,
                        category,
                        cents,
                        city,
                        description,
                        "available"
                    )
                )

            flash("Rental vehicle added.")

            return redirect(
                url_for("rental_portal.dashboard")
            )

    return page(
        "Add Rental Vehicle",
        """
        <div class="panel">

        <h1>Add Rental Vehicle</h1>

        <p>
        Add a vehicle to your WE-SELL
        rental company inventory.
        </p>

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

        <div class="home-return">

            <a href="{{ dashboard_url }}">
                ← Back to Rental Dashboard
            </a>

            <a href="/"
               style="margin-left:8px;">
                WE-SELL Home
            </a>

        </div>

        </div>
        """,
        csrf=csrf_token(),
        dashboard_url=url_for(
            "rental_portal.dashboard"
        )
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
