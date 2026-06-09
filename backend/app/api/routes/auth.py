import base64
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials

from app.api.dependencies.auth import get_current_user
from app.config.settings import Settings, get_settings
from app.services.firebase_auth_service import AuthenticatedUser
from app.services.google_oauth_token_store import GoogleOAuthTokenStore, get_google_oauth_token_store

router = APIRouter(prefix="/auth/google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_MAX_AGE_SECONDS = 600


def _sign_state(payload: str, settings: Settings) -> str:
    digest = hmac.new(
        settings.google_oauth_state_secret_text.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _make_state(settings: Settings, *, current_user: AuthenticatedUser) -> str:
    payload = {
        "issued_at": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "operator_uid": current_user.uid,
        "operator_email": current_user.email,
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    signature = _sign_state(encoded_payload, settings)
    return f"{encoded_payload}.{signature}"


def _verify_state(state: str, settings: Settings) -> dict[str, object]:
    try:
        encoded_payload, signature = state.split(".", 1)
        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        issued_at = int(payload["issued_at"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state.") from exc

    expected = _sign_state(encoded_payload, settings)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state signature.")
    if time.time() - issued_at > STATE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=400, detail="Google OAuth state expired. Please connect again.")
    return payload


@router.get("/status")
async def get_google_oauth_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    token_store: GoogleOAuthTokenStore = Depends(get_google_oauth_token_store),
) -> dict[str, object]:
    settings = get_settings()
    stored_credentials = token_store.load_credentials_for_user(current_user.uid) if settings.has_google_oauth_config else None
    default_user = token_store.load_default_user()
    return {
        "configured": settings.has_google_oauth_config,
        "connected": bool(stored_credentials and stored_credentials.credentials.valid),
        "scopes": settings.google_oauth_scopes,
        "redirect_uri": settings.google_redirect_uri,
        "owner_uid": current_user.uid,
        "owner_email": current_user.email,
        "default_calendar_owner": default_user,
    }


@router.get("/login")
async def get_google_oauth_login(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.has_google_oauth_config:
        raise HTTPException(status_code=400, detail="Google OAuth is not configured.")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.google_oauth_scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": _make_state(settings, current_user=current_user),
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/callback")
async def handle_google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    token_store: GoogleOAuthTokenStore = Depends(get_google_oauth_token_store),
) -> RedirectResponse:
    settings = get_settings()
    if not settings.has_google_oauth_config:
        raise HTTPException(status_code=400, detail="Google OAuth is not configured.")

    state_payload = _verify_state(state, settings)
    operator_uid = str(state_payload.get("operator_uid") or "").strip()
    operator_email = str(state_payload.get("operator_email") or "").strip() or None
    if not operator_uid:
        return RedirectResponse(f"{settings.frontend_settings_url}?google_oauth=error", status_code=302)

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret_text,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_redirect_uri,
            },
        )

    if response.status_code >= 400:
        return RedirectResponse(f"{settings.frontend_settings_url}?google_oauth=error", status_code=302)

    token_payload = response.json()
    token_payload["scopes"] = settings.google_oauth_scopes
    credentials = Credentials(
        token=token_payload.get("access_token"),
        refresh_token=token_payload.get("refresh_token"),
        token_uri=GOOGLE_TOKEN_URL,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret_text,
        scopes=settings.google_oauth_scopes,
    )
    token_store.save_credentials(
        credentials,
        user_id=operator_uid,
        user_email=operator_email,
        set_as_default=True,
    )
    return RedirectResponse(f"{settings.frontend_settings_url}?google_oauth=connected", status_code=302)


@router.delete("/disconnect")
async def disconnect_google_oauth(
    current_user: AuthenticatedUser = Depends(get_current_user),
    token_store: GoogleOAuthTokenStore = Depends(get_google_oauth_token_store),
) -> dict[str, bool]:
    token_store.disconnect_user(current_user.uid)
    return {"connected": False}


@router.get("/session")
async def get_authenticated_session(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, object]:
    return {
        "uid": current_user.uid,
        "email": current_user.email,
        "name": current_user.name,
        "picture": current_user.picture,
        "email_verified": current_user.email_verified,
        "role": current_user.role,
        "sign_in_provider": current_user.sign_in_provider,
    }
