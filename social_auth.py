import os
import logging
import sqlite3

from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from authlib.integrations.flask_client import OAuth

social_auth = Blueprint("social_auth", __name__)
oauth = OAuth()
logger = logging.getLogger(__name__)


def init_social_auth(app):
    oauth.init_app(app)
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        oauth.register(
            name="google", client_id=client_id, client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )


def portal_login(portal):
    return url_for("rental_portal.login") if portal == "rental" else url_for("login")


def google_client():
    return oauth.create_client("google")


def begin_google(portal, purpose):
    client = google_client()
    if client is None:
        flash("Google Sign-In is not configured yet.")
        return redirect(portal_login(portal))
    # OAuth state is also managed and verified by Authlib.
    session["google_portal"] = portal
    session["google_purpose"] = purpose
    try:
        return client.authorize_redirect(url_for("social_auth.google_callback", _external=True, _scheme="https"))
    except Exception:
        logger.exception("Could not start Google OAuth")
        flash("Could not connect to Google. Please try again.")
        return redirect(portal_login(portal))


@social_auth.get("/auth/<provider>/<portal>")
def start_login(provider, portal):
    if provider != "google" or portal not in ("dealer", "rental"):
        return "Unsupported provider or portal", 404
    return begin_google(portal, "login")


@social_auth.get("/auth/google/link/<portal>")
def link_google(portal):
    if portal != "rental":
        return "Linking not available for this portal yet", 404
    # Require an existing password-authenticated rental session.
    company_id = session.get("rental_company_id")
    if not company_id:
        flash("Sign in with your rental-company password first.")
        return redirect(url_for("rental_portal.login"))
    from rental_portal import db
    with db() as conn:
        company = conn.execute("SELECT id FROM rental_companies WHERE id=?", (company_id,)).fetchone()
    if not company:
        return redirect(url_for("rental_portal.login"))
    session["google_link_company_id"] = company_id
    return begin_google("rental", "link")


@social_auth.get("/auth/google/callback")
def google_callback():
    # This exact callback path matches the Google Cloud configuration.
    portal = session.get("google_portal")
    purpose = session.get("google_purpose")
    if portal not in ("dealer", "rental") or purpose not in ("login", "link"):
        return "Sign-in session expired. Please try again.", 400
    client = google_client()
    if client is None:
        return "Google Sign-In is not configured", 503
    try:
        token = client.authorize_access_token()
        info = token.get("userinfo") or client.parse_id_token(token)
        sub = info.get("sub") if info else None
        if not sub or info.get("email_verified") not in (True, "true", "True", 1):
            return "Google account could not be verified", 403
    except Exception:
        logger.exception("Google OAuth callback failed")
        flash("Google Sign-In failed. Please try again.")
        return redirect(portal_login(portal))
    finally:
        session.pop("google_portal", None)
        session.pop("google_purpose", None)

    if portal != "rental":
        return "Dealer Google account linking is not enabled yet. Please use your password.", 403

    from rental_portal import db
    if purpose == "link":
        company_id = session.pop("google_link_company_id", None)
        if not company_id or company_id != session.get("rental_company_id"):
            return "Rental account session expired. Sign in again.", 403
        try:
            with db() as conn:
                company = conn.execute("SELECT id FROM rental_companies WHERE id=?", (company_id,)).fetchone()
                if not company:
                    return "Rental company not found", 404
                existing = conn.execute("SELECT id FROM rental_companies WHERE google_sub=?", (sub,)).fetchone()
                if existing and existing["id"] != company_id:
                    return "This Google account is already linked to another company", 409
                conn.execute("UPDATE rental_companies SET google_sub=? WHERE id=?", (sub, company_id))
        except sqlite3.IntegrityError:
            return "This Google account is already linked to another company", 409
        flash("Your Google account is now linked. You can use Google Sign-In next time.")
        return redirect(url_for("rental_portal.dashboard"))

    with db() as conn:
        company = conn.execute("SELECT id FROM rental_companies WHERE google_sub=?", (sub,)).fetchone()
    if not company:
        flash("This Google account is not linked yet. Sign in with your password, then visit Connect Google.")
        return redirect(url_for("rental_portal.login"))
    session.clear()
    session["rental_company_id"] = company["id"]
    flash("Signed in with Google successfully.")
    return redirect(url_for("rental_portal.dashboard"))
