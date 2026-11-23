
import os
import logging

from flask import (
    Blueprint,
    current_app,
    redirect,
    url_for,
    flash,
    session,
    request,
)

from authlib.integrations.flask_client import OAuth

social_auth = Blueprint("social_auth", __name__)
oauth = OAuth()

logger = logging.getLogger(__name__)

VALID_PORTALS = {"dealer", "rental"}


def init_social_auth(app):
    """Initialize Google OAuth for WE-SELL."""

    oauth.init_app(app)

    google_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not google_id or not google_secret:
        app.logger.warning(
            "Google OAuth credentials are missing."
        )
        return

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


def portal_login_url(portal):
    """Return the login URL for a business portal."""

    if portal == "dealer":
        return url_for("login")

    return url_for("rental_portal.login")


@social_auth.get("/auth/<provider>/<portal>")
def start_login(provider, portal):
    """Start social sign-in."""

    if portal not in VALID_PORTALS:
        return "Invalid business portal", 400

    if provider != "google":
        return "Provider not configured yet", 404

    client = oauth.create_client("google")

    if client is None:
        flash(
            "Google Sign-In is not configured yet."
        )
        return redirect(portal_login_url(portal))

    callback_url = url_for(
        "social_auth.google_callback",
        portal=portal,
        _external=True,
        _scheme="https",
    )

    try:
        return client.authorize_redirect(callback_url)

    except Exception:
        logger.exception("Google OAuth start failed")

        flash(
            "Unable to connect to Google. "
            "Please try again."
        )

        return redirect(portal_login_url(portal))


@social_auth.get("/auth/google/callback/<portal>")
def google_callback(portal):
    """Handle Google's authentication response."""

    if portal not in VALID_PORTALS:
        return "Invalid business portal", 400

    client = oauth.create_client("google")

    if client is None:
        return "Google Sign-In is not configured", 503

    try:
        token = client.authorize_access_token()

        userinfo = token.get("userinfo")

        if not userinfo:
            userinfo = client.parse_id_token(token)

        if not userinfo:
            raise ValueError(
                "Google did not return user information."
            )

        google_sub = userinfo.get("sub")
        email = userinfo.get("email")
        email_verified = userinfo.get(
            "email_verified", False
        )

        if not google_sub:
            return "Google account ID is missing", 403

        if email_verified not in (True, "true", "True", 1):
            return "Google email is not verified", 403

        if not email:
            return "Google email is missing", 403

        # IMPORTANT:
        # Google identity verification does not
        # automatically authorize access to a
        # dealership or rental-company account.
        #
        # A secure account-linking process must
        # first associate Google's immutable
        # 'sub' identifier with an existing,
        # authorized WE-SELL business user.
        #
        # Never create an authenticated business
        # session based only on a matching email.
        #
        # Until that linking process is implemented,
        # do not set session["user_id"],
        # session["dealer_id"], or rental login state.

        current_app.logger.info(
            "Google identity verified for %s portal",
            portal,
        )

        return (
            "Google Sign-In was successful, but "
            "your WE-SELL business account has not "
            "been linked yet. Please sign in using "
            "your existing email and password.",
            200,
        )

    except Exception:
        logger.exception(
            "Google OAuth callback failed"
        )

        flash(
            "Google Sign-In failed. Please try again."
        )

        return redirect(portal_login_url(portal))
