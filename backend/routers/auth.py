import base64
import hashlib
import html
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User

router = APIRouter()

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

_PKCE_TTL_SECONDS = 600
_pkce_store: dict[str, tuple[str, float]] = {}
_pkce_lock = threading.Lock()
_GOOGLE_STATE_TTL_SECONDS = 600
_google_state_store: dict[str, tuple[str, float]] = {}
_google_state_lock = threading.Lock()


def _issue_jwt(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def issue_jwt_for_user(user_id: int) -> str:
    """다른 모듈(예: 자동 인쇄 파이프라인)에서 이 유저용 로그인 JWT를 발급할 때 쓰는 공개 진입점."""
    return _issue_jwt(user_id)


def decode_jwt(token: str) -> int:
    """JWT에서 user_id 추출. 유효하지 않으면 HTTPException 발생."""
    try:
        payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다. 다시 로그인해주세요.")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않습니다.")


def _pkce_set(state: str, code_verifier: str) -> None:
    with _pkce_lock:
        _pkce_store[state] = (code_verifier, time.time() + _PKCE_TTL_SECONDS)


def _pkce_pop(state: str) -> str | None:
    """state에 대응하는 code_verifier를 1회성으로 꺼낸다. 만료됐으면 None."""
    with _pkce_lock:
        entry = _pkce_store.pop(state, None)
    if entry is None:
        return None
    code_verifier, expires_at = entry
    if time.time() > expires_at:
        return None
    return code_verifier


def _new_oauth_state() -> str:
    return base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")


def _google_state_set(state: str, destination: str) -> None:
    with _google_state_lock:
        _google_state_store[state] = (destination, time.time() + _GOOGLE_STATE_TTL_SECONDS)


def _google_state_pop(state: str) -> str | None:
    """Google OAuth state를 1회성으로 검증하고 원래 로그인 대상을 반환한다."""
    with _google_state_lock:
        entry = _google_state_store.pop(state, None)
    if entry is None:
        return None
    destination, expires_at = entry
    if time.time() > expires_at:
        return None
    return destination


def _find_or_create_user(db: Session, email: str, name: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name)
        db.add(user)
        db.flush()
    return user


@router.get("/spotify")
def spotify_login():
    import urllib.parse

    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    state = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")

    _pkce_set(state, code_verifier)

    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": "user-read-recently-played user-top-read user-read-email",
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@router.get("/spotify/callback")
def spotify_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    code_verifier = _pkce_pop(state)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid or expired state — restart OAuth flow")

    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "code_verifier": code_verifier,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Spotify token exchange failed: {resp.text}")
    tokens = resp.json()

    me_resp = httpx.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    if me_resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to fetch Spotify user info: {me_resp.status_code} {me_resp.text}")
    me = me_resp.json()

    email = me.get("email") or f"spotify_{me['id']}@paperback.local"
    name = me.get("display_name") or me["id"]

    user = _find_or_create_user(db, email, name)
    user.spotify_access_token = tokens["access_token"]
    user.spotify_refresh_token = tokens.get("refresh_token") or user.spotify_refresh_token
    user.spotify_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    db.commit()

    return {"message": "Spotify 연동 완료", "user_id": user.id, "email": email}


@router.get("/google")
def google_login():
    import urllib.parse
    state = _new_oauth_state()
    _google_state_set(state, "web")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": (
            "https://www.googleapis.com/auth/calendar.readonly "
            "https://www.googleapis.com/auth/youtube.readonly "
            "https://www.googleapis.com/auth/userinfo.email "
            "https://www.googleapis.com/auth/userinfo.profile"
        ),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@router.get("/google/extension")
def google_extension_login():
    """Chrome Extension 전용 Google OAuth — 완료 후 JWT를 extension-done 페이지로 전달."""
    import urllib.parse
    state = _new_oauth_state()
    _google_state_set(state, "extension")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": (
            "https://www.googleapis.com/auth/calendar.readonly "
            "https://www.googleapis.com/auth/youtube.readonly "
            "https://www.googleapis.com/auth/userinfo.email "
            "https://www.googleapis.com/auth/userinfo.profile"
        ),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=url)


@router.get("/extension-done", response_class=HTMLResponse)
def extension_done(token: str):
    """Extension OAuth 완료 페이지 — auth-callback.js content script가 JWT를 읽어 저장."""
    escaped_token = html.escape(token, quote=True)
    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>PaperBack 로그인 완료</title>
  <style>
    body {{ font-family: sans-serif; display: flex; align-items: center;
           justify-content: center; height: 100vh; margin: 0; background: #f5f5f5; }}
    .box {{ text-align: center; padding: 40px; border-radius: 12px;
            background: #fff; box-shadow: 0 2px 16px rgba(0,0,0,.1); }}
    h2 {{ color: #4f46e5; }} p {{ color: #666; }}
  </style>
</head>
<body>
  <div class="box" id="paperback-auth-done" data-token="{escaped_token}">
    <h2>로그인 완료</h2>
    <p>이 탭은 자동으로 닫힙니다.</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_doc)


@router.get("/google/callback")
def google_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    destination = _google_state_pop(state)
    if destination is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state — restart OAuth flow")

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Google token exchange failed")
    tokens = resp.json()

    userinfo_resp = httpx.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    if userinfo_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch Google user info")
    userinfo = userinfo_resp.json()

    email = userinfo["email"]
    name = userinfo.get("name") or email

    user = _find_or_create_user(db, email, name)
    user.google_access_token = tokens["access_token"]
    user.google_refresh_token = tokens.get("refresh_token") or user.google_refresh_token
    user.google_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens.get("expires_in", 3600)
    )
    db.commit()

    if destination == "extension":
        token = _issue_jwt(user.id)
        return RedirectResponse(url=f"/auth/extension-done?token={token}")

    if destination == "web":
        token = _issue_jwt(user.id)
        return RedirectResponse(url=f"/?token={token}")

    return {"message": "Google 연동 완료", "user_id": user.id, "email": email}


@router.get("/notion")
def notion_login():
    import urllib.parse
    params = {
        "client_id": settings.notion_client_id,
        "redirect_uri": settings.notion_redirect_uri,
        "response_type": "code",
        "owner": "user",
    }
    url = "https://api.notion.com/v1/oauth/authorize?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@router.get("/notion/callback")
def notion_callback(code: str, db: Session = Depends(get_db)):
    import base64
    credentials = base64.b64encode(
        f"{settings.notion_client_id}:{settings.notion_client_secret}".encode()
    ).decode()

    resp = httpx.post(
        "https://api.notion.com/v1/oauth/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.notion_redirect_uri,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Notion token exchange failed: {resp.text}")
    tokens = resp.json()

    owner = tokens.get("owner", {})
    user_info = owner.get("user", {})
    person = user_info.get("person", {})
    email = person.get("email") or f"notion_{tokens.get('bot_id', 'unknown')}@paperback.local"
    name = user_info.get("name") or email

    user = _find_or_create_user(db, email, name)
    user.notion_token = tokens["access_token"]
    db.commit()

    return {"message": "Notion 연동 완료", "user_id": user.id, "email": email}
