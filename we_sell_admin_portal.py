
"""Standalone WE-SELL owner portal for approving PostgreSQL rental accounts."""

import os
import secrets
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

from werkzeug.security import check_password_hash
from rental_portal import db as rental_db


owner_portal = Blueprint(
    "owner_portal",
    __name__,
    url_prefix="/we-sell-admin"
)


STYLE = """
*{box-sizing:border-box}
body{margin:0;background:#f2f5fa;font:15px Arial,sans-serif;color:#102945}
header{background:#061d37;color:#fff;padding:22px max(20px,calc((100% - 1150px)/2));display:flex;justify-content:space-between;align-items:center;gap:12px}
header strong{font-size:23px;color:#ffbf00}
header small{font-size:12px;letter-spacing:2px;color:#cbd9e7}
main{max-width:1150px;margin:36px auto;padding:0 20px}
.panel{background:white;border:1px solid #e1e7f0;border-radius:16px;padding:25px;box-shadow:0 7px 25px #1029450a}
h1{margin:0 0 8px;font-size:28px}
p{color:#61718a;line-height:1.6}
a{color:#145d9e;text-decoration:none}
button,.btn{border:0;border-radius:9px;padding:11px 15px;font-weight:700;cursor:pointer;background:#ffbf00;color:#061d37}
.secondary{background:#eaf0f7;color:#102945}
.danger{background:#ffe5e6;color:#9d2331}
input{width:100%;padding:14px;border:1px solid #cbd6e4;border-radius:9px;margin:7px 0 17px;font-size:15px}
label{font-weight:700}
.login{max-width:460px;margin:65px auto}
.msg{background:#e9f4ff;border-radius:8px;padding:12px 16px;margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin:25px 0}
.stat{padding:20px;border:1px solid #e1e7f0;border-radius:13px;background:#fff}
.stat b{display:block;font-size:30px;margin-bottom:7px}
.stat span{color:#60748b}
.table-wrap{overflow-x:auto}
table{width:100%;min-width:760px;border-collapse:collapse}
th,td{padding:15px 10px;text-align:left;border-bottom:1px solid #e6ecf2;vertical-align:middle}
th{font-size:12px;text-transform:uppercase;color:#6a7c8f}
small{color:#74859a}
.pill{display:inline-block;background:#fff1cb;color:#805600;padding:7px 10px;border-radius:20px;font-size:12px;font-weight:700}
.pill.ok{background:#e1f6e9;color:#1a7342}
.actions{display:flex;gap:8px}
.actions form{margin:0}
.header-actions{display:flex;align-items:center;gap:12px}
.header-actions a{color:#fff}
@media(max-width:600px){
    .stats{grid-template-columns:1fr}
    header{flex-wrap:wrap}
}
"""


# ============================================
# OWNER AUTHENTICATION
# ============================================

def owner_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("we_sell_owner") is not True:
            return redirect(
                url_for("owner_portal.login")
            )

        return fn(*args, **kwargs)

    return wrapper


# ============================================
# CSRF SECURITY
# ============================================

def csrf():
    token = session.get("owner_csrf")

    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["owner_csrf"] = token

    return token


def verify_csrf():
    token = request.form.get("csrf", "")
    saved_token = session.get("owner_csrf", "")

    if (
        not isinstance(saved_token, str)
        or not token
        or not saved_token
        or not secrets.compare_digest(
            token.encode("utf-8"),
            saved_token.encode("utf-8")
        )
    ):
        abort(
            400,
            "Invalid form token. Refresh the page and try again."
        )


# ============================================
# OWNER LOGIN
# ============================================

@owner_portal.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        verify_csrf()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        expected_email = os.environ.get(
            "WESELL_ADMIN_EMAIL", ""
        ).strip().lower()

        expected_hash = os.environ.get(
            "WESELL_ADMIN_PASSWORD_HASH", ""
        ).strip()

        valid = bool(
            expected_email
            and expected_hash
            and secrets.compare_digest(
                email.encode("utf-8"),
                expected_email.encode("utf-8")
            )
        )

        if valid:
            try:
                valid = check_password_hash(
                    expected_hash,
                    password
                )
            except (ValueError, TypeError):
                valid = False

        if valid:

            session.clear()
            session["we_sell_owner"] = True

            csrf()

            return redirect(
                url_for("owner_portal.dashboard")
            )

        flash(
            "Incorrect administrator credentials, "
            "or administrator access is not configured."
        )

    return render_template_string(
        """
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Owner Login | WE-SELL</title>

            <style>{{ style }}</style>
        </head>

        <body>

            <header>
                <div>
                    <strong>WE-SELL</strong>
                    <small>OWNER PORTAL</small>
                </div>

                <a style="color:white" href="/">
                    Main website
                </a>
            </header>

            <main>

                <div class="panel login">

                    <h1>Administrator Sign In</h1>

                    <p>
                        Private WE-SELL management access.
                        Rental companies and dealers cannot
                        sign in here.
                    </p>

                    {% for message in get_flashed_messages() %}
                        <div class="msg">
                            {{ message }}
                        </div>
                    {% endfor %}

                    <form method="post">

                        <input type="hidden"
                               name="csrf"
                               value="{{ csrf }}">

                        <label for="email">
                            Administrator email
                        </label>

                        <input id="email"
                               type="email"
                               name="email"
                               required
                               autocomplete="username">

                        <label for="password">
                            Password
                        </label>

                        <div style="position:relative;">
                            <input id="password"
                                   type="password"
                                   name="password"
                                   required
                                   autocomplete="current-password"
                                   style="padding-right:85px;">
                            <button type="button"
                                    aria-controls="password"
                                    aria-label="Show password"
                                    style="position:absolute;right:8px;top:12px;background:transparent;color:#102945;"
                                    onclick="const p=document.getElementById('password');const show=p.type==='password';p.type=show?'text':'password';this.textContent=show?'Hide':'Show';this.setAttribute('aria-label',show?'Hide password':'Show password');">
                                Show
                            </button>
                        </div>

                        <button style="width:100%">
                            Sign In to Owner Portal
                        </button>

                    </form>

                </div>

            </main>

        </body>
        </html>
        """,
        style=STYLE,
        csrf=csrf()
    )


# ============================================
# OWNER DASHBOARD
# ============================================

@owner_portal.get("/")
@owner_required
def dashboard():

    with rental_db() as conn:

        companies = conn.execute(
            """
            SELECT
                id,
                company_name,
                contact_name,
                email,
                phone,
                city,
                approved,
                created_at
            FROM rental_companies
            ORDER BY
                CASE
                    WHEN approved = 0 THEN 0
                    ELSE 1
                END,
                id DESC
            """
        ).fetchall()

    pending = sum(
        1 for company in companies
        if not company["approved"]
    )

    approved = len(companies) - pending

    return render_template_string(
        """
        <!doctype html>
        <html lang="en">

        <head>

            <meta charset="utf-8">

            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>
                Rental Approvals | WE-SELL Owner
            </title>

            <style>{{ style }}</style>

        </head>

        <body>

            <header>

                <div>
                    <strong>WE-SELL</strong>
                    <small>OWNER PORTAL</small>
                </div>

                <div class="header-actions">

                    <a href="/">
                        Main website
                    </a>

                    <form method="post"
                          action="{{ url_for('owner_portal.logout') }}">

                        <input type="hidden"
                               name="csrf"
                               value="{{ csrf }}">

                        <button class="secondary">
                            Sign Out
                        </button>

                    </form>

                </div>

            </header>

            <main>

                <h1>Rental Company Approvals</h1>

                <p>
                    Review companies applying to advertise
                    rental vehicles on WE-SELL.
                </p>

                <div class="stats">

                    <div class="stat">
                        <b>{{ companies|length }}</b>
                        <span>Total companies</span>
                    </div>

                    <div class="stat">
                        <b>{{ pending }}</b>
                        <span>Pending approval</span>
                    </div>

                    <div class="stat">
                        <b>{{ approved }}</b>
                        <span>Approved</span>
                    </div>

                </div>

                {% for message in get_flashed_messages() %}

                    <div class="msg">
                        {{ message }}
                    </div>

                {% endfor %}

                <div class="panel">

                    <h2>Registered Rental Companies</h2>

                    <div class="table-wrap">

                        <table>

                            <thead>

                                <tr>
                                    <th>Company</th>
                                    <th>Contact</th>
                                    <th>City</th>
                                    <th>Status</th>
                                    <th>Action</th>
                                </tr>

                            </thead>

                            <tbody>

                                {% for c in companies %}

                                <tr>

                                    <td>
                                        <b>{{ c.company_name }}</b>
                                        <br>
                                        <small>{{ c.email }}</small>
                                    </td>

                                    <td>
                                        {{ c.contact_name }}
                                        <br>
                                        <small>
                                            {{ c.phone or '' }}
                                        </small>
                                    </td>

                                    <td>
                                        {{ c.city or '—' }}
                                    </td>

                                    <td>

                                        <span class="pill {{ 'ok' if c.approved else '' }}">

                                            {{ 'Approved' if c.approved else 'Pending / Not approved' }}

                                        </span>

                                    </td>

                                    <td>

                                        <div class="actions">

                                            <form method="post"
                                                  action="{{ url_for('owner_portal.change_status', company_id=c.id) }}">

                                                <input type="hidden"
                                                       name="csrf"
                                                       value="{{ csrf }}">

                                                <input type="hidden"
                                                       name="action"
                                                       value="{{ 'revoke' if c.approved else 'approve' }}">

                                                <button class="{{ 'danger' if c.approved else '' }}"

                                                    {% if c.approved %}

                                                    onclick="return confirm('Revoke this company’s approval?')"

                                                    {% endif %}>

                                                    {{ 'Revoke' if c.approved else 'Approve' }}

                                                </button>

                                            </form>

                                        </div>

                                    </td>

                                </tr>

                                {% else %}

                                <tr>
                                    <td colspan="5">
                                        No rental companies
                                        have registered yet.
                                    </td>
                                </tr>

                                {% endfor %}

                            </tbody>

                        </table>

                    </div>

                </div>

            </main>

        </body>

        </html>
        """,
        style=STYLE,
        companies=companies,
        pending=pending,
        approved=approved,
        csrf=csrf()
    )


# ============================================
# APPROVE OR REVOKE RENTAL COMPANY
# ============================================

@owner_portal.post(
    "/rental-companies/<int:company_id>/status"
)
@owner_required
def change_status(company_id):

    verify_csrf()

    action = request.form.get("action")

    if action not in ("approve", "revoke"):
        abort(400, "Invalid approval action.")

    new_status = 1 if action == "approve" else 0

    with rental_db() as conn:

        result = conn.execute(
            """
            UPDATE rental_companies
            SET approved = ?
            WHERE id = ?
            """,
            (new_status, company_id)
        )

        if result.rowcount != 1:
            abort(404, "Rental company not found.")

    if action == "approve":
        flash("Rental company approved.")
    else:
        flash("Rental company approval revoked.")

    return redirect(
        url_for("owner_portal.dashboard")
    )


# ============================================
# OWNER LOGOUT
# ============================================

@owner_portal.post("/logout")
@owner_required
def logout():

    verify_csrf()

    session.clear()

    return redirect(
        url_for("owner_portal.login")
    )
