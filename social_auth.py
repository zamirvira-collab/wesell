import os
import sqlite3
import logging

from flask import Blueprint, current_app, redirect, url_for, flash, session
from authlib.integrations.flask_client import OAuth

social_auth = Blueprint("social_auth", __name__)
oauth = OAuth()
logger = logging.getLogger(__name__)


def init_social_auth(app):
    """Initialize Google's OpenID Connect client."""
    oauth.init_app(app)
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid email profile"},
        )


def rental_db():
    from rental_portal import DB
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def google_client():
    return oauth.create_client("google")


def callback_url():
    # This EXACT URL must be registered in Google Cloud.
    return url_for("social_auth.google_callback", _external=True, _scheme="https")


def begin_google(portal, intent):
    if portal not in ("rental", "dealer"):
        return "Invalid portal", 400
    client = google_client()
    if client is None:
        flash("Google Sign-In is not configured.")
        return redirect(url_for("rental_portal.login") if portal == "rental" else url_for("login"))
    session["google_portal"] = portal
    session["google_intent"] = intent
    if intent == "link":
        if portal == "rental":
            session["google_link_company_id"] = session.get("rental_company_id")
        else:
            session["google_link_user_id"] = session.get("uid")
    else:
        session.pop("google_link_company_id", None)
        session.pop("google_link_user_id", None)
    return client.authorize_redirect(callback_url())


@social_auth.get("/auth/<provider>/<portal>")
def start_login(provider, portal):
    if provider != "google":
        return "Provider not configured", 404
    if portal not in ("dealer", "rental"):
        return "Invalid portal", 400
    return begin_google(portal, "login")


@social_auth.get("/auth/google/link/<portal>")
def start_link(portal):
    if portal not in ("rental", "dealer"):
        return "Unsupported portal", 400
    if portal == "rental" and not session.get("rental_company_id"):
        flash("Sign in with your rental-company password first.")
        return redirect(url_for("rental_portal.login"))
    if portal == "dealer":
        from flask import g
        if not session.get("uid") or not g.get("user") or g.user["role"] != "dealer":
            flash("Sign in to your dealer account with your password first.")
            return redirect(url_for("login"))
    return begin_google(portal, "link")


@social_auth.get("/auth/google/callback")
def google_callback():
    portal = session.pop("google_portal", None)
    intent = session.pop("google_intent", None)
    linking_company_id = session.pop("google_link_company_id", None)
    linking_user_id = session.pop("google_link_user_id", None)
    if portal not in ("rental", "dealer") or intent not in ("login", "link"):
        return "Invalid Google login session. Please try again.", 400
    client = google_client()
    if client is None:
        return "Google login is not configured", 503

    try:
        token = client.authorize_access_token()
        # Authlib validates the OIDC ID token including signature, nonce,
        # audience, issuer, and expiration when userinfo is populated.
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = client.parse_id_token(token)
        sub = userinfo.get("sub") if userinfo else None
        verified = userinfo.get("email_verified") if userinfo else False
        if not sub or verified not in (True, "true", 1):
            return "Google account verification failed", 403
    except Exception:
        logger.exception("Google callback error")
        flash("Google Sign-In failed. Please try again.")
        return redirect(url_for("rental_portal.login") if portal == "rental" else url_for("login"))

    if portal == "dealer":
        db_path = os.environ.get("WESELL_DB", os.path.join(current_app.root_path, "wesell.db"))
        conn = sqlite3.connect(db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            if intent == "link":
                if not linking_user_id or session.get("uid") != linking_user_id:
                    return "Sign in with your dealer password before connecting Google", 403
                user = conn.execute(
                    "SELECT id FROM users WHERE id=? AND role='dealer' AND dealer_id IS NOT NULL",
                    (linking_user_id,),
                ).fetchone()
                if not user:
                    return "Dealer account not found", 403
                other = conn.execute(
                    "SELECT user_id FROM dealer_google_identities WHERE google_sub=?", (sub,)
                ).fetchone()
                if other and other["user_id"] != linking_user_id:
                    return "This Google account is already linked to another dealer", 409
                existing = conn.execute(
                    "SELECT google_sub FROM dealer_google_identities WHERE user_id=?", (linking_user_id,)
                ).fetchone()
                if existing and existing["google_sub"] != sub:
                    return "This dealer account already has another Google account linked", 409
                conn.execute(
                    "INSERT OR IGNORE INTO dealer_google_identities(google_sub,user_id) VALUES (?,?)",
                    (sub, linking_user_id),
                )
                conn.commit()
                flash("Google account connected to your dealership.", "success")
                return redirect(url_for("dealer_dashboard"))

            row = conn.execute(
                """SELECT u.id FROM dealer_google_identities gi
                   JOIN users u ON u.id=gi.user_id
                   JOIN dealers d ON d.id=u.dealer_id
                   WHERE gi.google_sub=? AND u.role='dealer' AND d.approved=1""",
                (sub,),
            ).fetchone()
            if not row:
                flash("Sign in with your dealer password first, then connect Google from your dealer dashboard.", "error")
                return redirect(url_for("login"))
            user_id = row["id"]
        except sqlite3.Error:
            logger.exception("Dealer Google account database error")
            return "Dealer login is temporarily unavailable", 503
        finally:
            conn.close()
        session.clear()
        session["uid"] = user_id
        flash("Signed in to your dealership with Google.", "success")
        return redirect(url_for("dealer_dashboard"))

    conn = rental_db()
    try:
        if intent == "link":
            if not linking_company_id or session.get("rental_company_id") != linking_company_id:
                return "Sign in with your rental password before connecting Google", 403
            company = conn.execute(
                "SELECT id FROM rental_companies WHERE id=?", (linking_company_id,)
            ).fetchone()
            if not company:
                return "Rental company not found", 404
            other = conn.execute(
                "SELECT company_id FROM rental_google_identities WHERE google_sub=?", (sub,)
            ).fetchone()
            if other and other["company_id"] != linking_company_id:
                return "This Google account is already linked to another rental company", 409
            existing = conn.execute(
                "SELECT google_sub FROM rental_google_identities WHERE company_id=?", (linking_company_id,)
            ).fetchone()
            if existing and existing["google_sub"] != sub:
                return "This company already has another Google account linked", 409
            conn.execute(
                "INSERT OR IGNORE INTO rental_google_identities(google_sub,company_id) VALUES (?,?)",
                (sub, linking_company_id),
            )
            conn.commit()
            flash("Your Google account is now connected.", "success")
            return redirect(url_for("rental_portal.dashboard"))

        row = conn.execute(
            """SELECT c.id FROM rental_google_identities gi
               JOIN rental_companies c ON c.id=gi.company_id
               WHERE gi.google_sub=?""", (sub,)
        ).fetchone()
        if not row:
            flash("Sign in with your rental password first, then connect Google.", "error")
            return redirect(url_for("rental_portal.login"))
        company_id = row["id"]
    except sqlite3.Error:
        logger.exception("Rental Google account database error")
        return "Rental login is temporarily unavailable", 503
    finally:
        conn.close()
    session.clear()
    session["rental_company_id"] = company_id
    flash("Signed in with Google successfully.", "success")
    return redirect(url_for("rental_portal.dashboard"))
