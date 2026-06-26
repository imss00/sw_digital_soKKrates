import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import httpx
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User

router = APIRouter()


def _get_redis():
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


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

    _get_redis().setex(f"spotify_pkce:{state}", 600, code_verifier)

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
    r = _get_redis()
    code_verifier = r.get(f"spotify_pkce:{state}")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid or expired state — restart OAuth flow")
    r.delete(f"spotify_pkce:{state}")

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
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@router.get("/google/callback")
def google_callback(code: str, db: Session = Depends(get_db)):
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
