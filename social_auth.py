
import os

from flask import Blueprint, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth

social_auth = Blueprint("social_auth", __name__)

oauth = OAuth()


def init_social_auth(app):
    """Configure OAuth providers for WE-SELL."""
    oauth.init_app(app)

    google_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if google_id and google_secret:
        oauth.register(
            name="google",
            client_id=google_id,
            client_secret=google_secret,
            server_metadata_url=(
                "https://accounts.google.com/"
                ".well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile"
            },
        )


@social_auth.get("/auth/<provider>/<portal>")
def start_login(provider, portal):
    if portal not in ("dealer", "rental"):
        return "Invalid business portal", 400

    if provider != "google":
        return "Provider not configured yet", 404

    client = oauth.create_client("google")

    if client is None:
        flash("Google sign-in is not configured yet.")
        return redirect(
            url_for("login")
            if portal == "dealer"
            else url_for("rental_portal.login")
        )

    callback_url = url_for(
        "social_auth.google_callback",
        portal=portal,
        _external=True
    )

    return client.authorize_redirect(callback_url)


@social_auth.get("/auth/google/callback/<portal>")
def google_callback(portal):
    if portal not in ("dealer", "rental"):
        return "Invalid business portal", 400

    client = oauth.create_client("google")

    if client is None:
        return "Google sign-in is not configured", 503

    try:
        token = client.authorize_access_token()
        userinfo = token.get("userinfo")

        if not userinfo:
            userinfo = client.parse_id_token(token)

        if not userinfo.get("email_verified"):
            return "Google email is not verified", 403

    except Exception:
        flash("Google sign-in failed. Please try again.")
        return redirect(
            url_for("login")
            if portal == "dealer"
            else url_for("rental_portal.login")
        )

    # Next step:
    # Connect Google's verified user identity to the
    # correct WE-SELL business account.
    #
    # Never grant access to an existing account
    # based only on a matching email address.
    #
    # Until account linking is implemented,
    # do not create an authenticated session.

    return (
        "Google verified your identity successfully. "
        "WE-SELL business account linking is not "
        "enabled yet.",
        200
    )
