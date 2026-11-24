
import os
import sqlite3
import psycopg2
from contextlib import contextmanager, closing
import logging

from flask import (
    Blueprint,
    current_app,
    redirect,
    url_for,
    flash,
    session,
    g,
)

from authlib.integrations.flask_client import OAuth
from authlib.common.security import generate_token

social_auth = Blueprint("social_auth", __name__)
oauth = OAuth()
logger = logging.getLogger(__name__)

PROVIDERS = ("google", "facebook")
PORTALS = ("dealer", "rental")


# ============================================
# INITIALIZE GOOGLE AND FACEBOOK
# ============================================

def init_social_auth(app):
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

    facebook_id = os.environ.get("FACEBOOK_CLIENT_ID")
    facebook_secret = os.environ.get("FACEBOOK_CLIENT_SECRET")

    if facebook_id and facebook_secret:
        oauth.register(
            name="facebook",
            client_id=facebook_id,
            client_secret=facebook_secret,
            access_token_url=(
                "https://graph.facebook.com/"
                "v24.0/oauth/access_token"
            ),
            authorize_url=(
                "https://www.facebook.com/"
                "v24.0/dialog/oauth"
            ),
            api_base_url=(
                "https://graph.facebook.com/v24.0/"
            ),
            client_kwargs={
                "scope": "public_profile,email"
            },
        )

    # Database tables are created on demand.
    # Do not connect to rental database at startup.
    # This prevents the previous Render startup crash.


# ============================================
# DATABASE CONNECTIONS
# ============================================

def dealer_db():
    path = os.environ.get(
        "WESELL_DB",
        os.path.join(current_app.root_path, "wesell.db"),
    )

    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def rental_db():
    from rental_portal import db
    with db() as conn:
        yield conn


# ============================================
# IDENTITY TABLES
# ============================================

def ensure_identity_table(conn, portal, provider):
    if portal not in PORTALS:
        raise ValueError("Invalid portal")

    if provider not in PROVIDERS:
        raise ValueError("Invalid provider")

    if portal == "rental":
        return

    table = identity_table(portal, provider)
    identity_field = identity_column(provider)
    account_field = account_column(portal)

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {identity_field} TEXT PRIMARY KEY,
            {account_field} INTEGER NOT NULL UNIQUE
        )
        """
    )

    conn.commit()


# ============================================
# HELPERS
# ============================================

def provider_client(provider):
    if provider not in PROVIDERS:
        return None

    return oauth.create_client(provider)


def portal_login_url(portal):
    if portal == "rental":
        return url_for("rental_portal.login")

    return url_for("login")


def portal_dashboard_url(portal):
    if portal == "rental":
        return url_for("rental_portal.dashboard")

    return url_for("dealer_dashboard")


def callback_url(provider="google"):
    if provider == "google":
        endpoint = "social_auth.google_callback"
    elif provider == "facebook":
        endpoint = "social_auth.facebook_callback"
    else:
        raise ValueError("Invalid provider")

    return url_for(
        endpoint,
        _external=True,
        _scheme="https",
    )


def identity_table(portal, provider):
    if portal not in PORTALS or provider not in PROVIDERS:
        raise ValueError("Invalid identity")

    return f"{portal}_{provider}_identities"


def identity_column(provider):
    if provider == "google":
        return "google_sub"

    if provider == "facebook":
        return "facebook_id"

    raise ValueError("Invalid provider")


def account_column(portal):
    if portal == "rental":
        return "company_id"

    return "user_id"


def clear_oauth_session():
    for key in (
        "social_provider",
        "social_portal",
        "social_intent",
        "social_link_id",
        "google_portal",
        "google_intent",
        "google_link_company_id",
        "google_link_user_id",
    ):
        session.pop(key, None)


def current_account_id(portal):
    if portal == "rental":
        return session.get("rental_company_id")

    return session.get("uid")


def verify_link_session(portal, account_id):
    if not account_id:
        return False

    if current_account_id(portal) != account_id:
        return False

    if portal == "dealer":
        user = getattr(g, "user", None)

        if not user:
            return False

        return (
            user["role"] == "dealer"
            and user["id"] == account_id
        )

    return True


# ============================================
# BEGIN SOCIAL LOGIN
# ============================================

def begin_social(provider, portal, intent):
    if provider not in PROVIDERS:
        return "Unsupported provider", 404

    if portal not in PORTALS:
        return "Invalid portal", 400

    if intent not in ("login", "link"):
        return "Invalid action", 400

    client = provider_client(provider)

    if client is None:
        flash(
            f"{provider.title()} Login is not configured.",
            "error",
        )
        return redirect(portal_login_url(portal))

    if intent == "link":
        account_id = current_account_id(portal)

        if not verify_link_session(portal, account_id):
            flash(
                "Sign in with your password before "
                "connecting a social account.",
                "error",
            )
            return redirect(portal_login_url(portal))
    else:
        account_id = None

    clear_oauth_session()

    session["social_provider"] = provider
    session["social_portal"] = portal
    session["social_intent"] = intent

    if intent == "link":
        session["social_link_id"] = account_id

    try:
        if provider == "google":
            return client.authorize_redirect(
                callback_url(provider),
                nonce=generate_token(32),
            )

        return client.authorize_redirect(
            callback_url(provider)
        )

    except Exception:
        logger.exception("Unable to begin social login")
        clear_oauth_session()

        flash(
            "Unable to start social login.",
            "error",
        )
        return redirect(portal_login_url(portal))


# ============================================
# LOGIN ROUTES
# ============================================

@social_auth.get("/auth/<provider>/<portal>")
def start_login(provider, portal):
    return begin_social(provider, portal, "login")


@social_auth.get("/auth/<provider>/link/<portal>")
def start_social_link(provider, portal):
    return begin_social(provider, portal, "link")


@social_auth.get("/auth/google/connect/<portal>")
def start_link(portal):
    return begin_social("google", portal, "link")


# ============================================
# GET GOOGLE IDENTITY
# ============================================

def get_google_identity(client):
    token = client.authorize_access_token()

    userinfo = token.get("userinfo")

    if not userinfo:
        userinfo = client.parse_id_token(token)

    if not userinfo:
        raise ValueError("Google identity unavailable")

    sub = userinfo.get("sub")
    verified = userinfo.get("email_verified", False)

    if not sub or verified not in (
        True,
        "true",
        1,
    ):
        raise ValueError("Google identity not verified")

    return str(sub)


# ============================================
# GET FACEBOOK IDENTITY
# ============================================

def get_facebook_identity(client):
    token = client.authorize_access_token()

    response = client.get(
        "me",
        params={
            "fields": "id,name,email"
        },
        token=token,
    )

    response.raise_for_status()

    profile = response.json()

    facebook_id = profile.get("id")

    if not facebook_id:
        raise ValueError("Facebook identity unavailable")

    return str(facebook_id)


# ============================================
# VERIFY BUSINESS ACCOUNT
# ============================================

def valid_dealer_account(conn, user_id):
    row = conn.execute(
        """
        SELECT u.id
        FROM users u
        JOIN dealers d ON d.id = u.dealer_id
        WHERE u.id = ?
          AND u.role = 'dealer'
          AND d.approved = 1
        """,
        (user_id,),
    ).fetchone()

    return row is not None


def valid_rental_account(conn, company_id):
    row = conn.execute(
        """
        SELECT id
        FROM rental_companies
        WHERE id = ?
        """,
        (company_id,),
    ).fetchone()

    return row is not None


def valid_business_account(conn, portal, account_id):
    if portal == "dealer":
        return valid_dealer_account(conn, account_id)

    return valid_rental_account(conn, account_id)


# ============================================
# LINK SOCIAL ACCOUNT
# ============================================

def link_social_identity(
    conn,
    provider,
    portal,
    provider_id,
    account_id,
):
    if not valid_business_account(
        conn,
        portal,
        account_id,
    ):
        return (
            "Business account not found or not approved.",
            403,
        )

    if portal == "rental":
        field = identity_column(provider)
        try:
            result = conn.execute(
                f"UPDATE rental_companies SET {field}=? WHERE id=? AND ({field} IS NULL OR {field}=?)",
                (provider_id, account_id, provider_id),
            )
        except psycopg2.IntegrityError:
            raise
        if result.rowcount != 1:
            return "This business already has another social account connected.", 409
        flash(f"{provider.title()} account connected.", "success")
        return redirect(portal_dashboard_url(portal))

    table = identity_table(portal, provider)
    identity_field = identity_column(provider)
    account_field = account_column(portal)

    other = conn.execute(
        f"""
        SELECT {account_field}
        FROM {table}
        WHERE {identity_field} = ?
        """,
        (provider_id,),
    ).fetchone()

    if other and other[account_field] != account_id:
        return (
            "This social account is already linked "
            "to another business.",
            409,
        )

    existing = conn.execute(
        f"""
        SELECT {identity_field}
        FROM {table}
        WHERE {account_field} = ?
        """,
        (account_id,),
    ).fetchone()

    if existing and existing[identity_field] != provider_id:
        return (
            "This business already has another "
            f"{provider.title()} account connected.",
            409,
        )

    conn.execute(
        f"""
        INSERT OR IGNORE INTO {table}
        ({identity_field}, {account_field})
        VALUES (?, ?)
        """,
        (provider_id, account_id),
    )

    conn.commit()

    flash(
        f"{provider.title()} account connected.",
        "success",
    )

    return redirect(portal_dashboard_url(portal))


# ============================================
# FIND SOCIAL ACCOUNT
# ============================================

def find_social_account(
    conn,
    provider,
    portal,
    provider_id,
):
    if portal == "rental":
        field = identity_column(provider)
        row = conn.execute(
            f"SELECT id FROM rental_companies WHERE {field}=?", (provider_id,)
        ).fetchone()
        return row["id"] if row else None

    table = identity_table(portal, provider)
    identity_field = identity_column(provider)
    account_field = account_column(portal)

    row = conn.execute(
        f"""
        SELECT {account_field}
        FROM {table}
        WHERE {identity_field} = ?
        """,
        (provider_id,),
    ).fetchone()

    if not row:
        return None

    account_id = row[account_field]

    if not valid_business_account(
        conn,
        portal,
        account_id,
    ):
        return None

    return account_id


# ============================================
# COMPLETE SOCIAL LOGIN
# ============================================

def complete_social_login(provider):
    expected_provider = session.get("social_provider")
    portal = session.get("social_portal")
    intent = session.get("social_intent")
    linking_id = session.get("social_link_id")

    if (
        expected_provider != provider
        or portal not in PORTALS
        or intent not in ("login", "link")
    ):
        clear_oauth_session()
        return "Invalid login session.", 400

    client = provider_client(provider)

    if client is None:
        clear_oauth_session()
        return "Social Login is not configured.", 503

    try:
        if provider == "google":
            provider_id = get_google_identity(client)
        else:
            provider_id = get_facebook_identity(client)

    except Exception:
        logger.exception("%s callback failed", provider)
        clear_oauth_session()

        flash(
            f"{provider.title()} Login failed.",
            "error",
        )
        return redirect(portal_login_url(portal))

    try:
        with (closing(dealer_db()) if portal == "dealer" else rental_db()) as conn:
            ensure_identity_table(
                conn,
                portal,
                provider,
            )

            if intent == "link":
                if not verify_link_session(
                    portal,
                    linking_id,
                ):
                    return (
                        "Please sign in with your "
                        "business password first.",
                        403,
                    )

                return link_social_identity(
                    conn,
                    provider,
                    portal,
                    provider_id,
                    linking_id,
                )

            account_id = find_social_account(
                conn,
                provider,
                portal,
                provider_id,
            )


    except psycopg2.IntegrityError:
        return "This social account is already linked to another business.", 409
    except (sqlite3.Error, psycopg2.Error, RuntimeError, TypeError):
        logger.exception("Social login database error")
        return (
            "Social Login is temporarily unavailable.",
            503,
        )

    finally:
        clear_oauth_session()

    if not account_id:
        flash(
            "No approved business account is connected "
            f"to this {provider.title()} account. "
            "Sign in with your password first, "
            "then connect your social account.",
            "error",
        )
        return redirect(portal_login_url(portal))

    session.clear()

    if portal == "dealer":
        session["uid"] = account_id
    else:
        session["rental_company_id"] = account_id

    session.permanent = True

    flash(
        f"Signed in with {provider.title()} successfully.",
        "success",
    )

    return redirect(portal_dashboard_url(portal))


# ============================================
# GOOGLE CALLBACK
# ============================================

@social_auth.get("/auth/google/callback")
def google_callback():
    return complete_social_login("google")


# ============================================
# FACEBOOK CALLBACK
# ============================================

@social_auth.get("/auth/facebook/callback")
def facebook_callback():
    return complete_social_login("facebook")
