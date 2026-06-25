from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.user import User

router = APIRouter()


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
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": "user-read-recently-played user-top-read user-read-email",
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    return {"auth_url": url}


@router.get("/spotify/callback")
def spotify_callback(code: str, db: Session = Depends(get_db)):
    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "client_secret": settings.spotify_client_secret,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Spotify token exchange failed")
    tokens = resp.json()

    me_resp = httpx.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    if me_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch Spotify user info")
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
