import logging
from datetime import datetime, timezone

import spotipy
from sqlalchemy.orm import Session

from backend.models.spotify_history import SpotifyHistory
from backend.models.user import User
from backend.config import settings

logger = logging.getLogger(__name__)

# Spotify audio_features가 신규 앱에서 막혀 있어서 장르 기반으로 mood를 추정
GENRE_MOOD: dict[str, tuple[float, float]] = {
    "sad": (0.15, 0.25),
    "blues": (0.25, 0.30),
    "classical": (0.40, 0.20),
    "ambient": (0.35, 0.10),
    "lo-fi": (0.45, 0.25),
    "jazz": (0.50, 0.45),
    "soul": (0.55, 0.50),
    "r-n-b": (0.60, 0.60),
    "indie": (0.50, 0.50),
    "country": (0.60, 0.55),
    "folk": (0.50, 0.35),
    "pop": (0.65, 0.70),
    "k-pop": (0.70, 0.75),
    "hip-hop": (0.55, 0.75),
    "rap": (0.50, 0.80),
    "rock": (0.50, 0.80),
    "electronic": (0.60, 0.80),
    "dance": (0.75, 0.85),
    "edm": (0.70, 0.90),
    "metal": (0.30, 0.90),
}


def _estimate_mood_from_genres(genres: list[str]) -> tuple[float | None, float | None]:
    matched = []
    for genre in genres:
        g = genre.lower()
        for key, mood in GENRE_MOOD.items():
            if key in g:
                matched.append(mood)
                break
    if not matched:
        return None, None
    valence = sum(m[0] for m in matched) / len(matched)
    energy = sum(m[1] for m in matched) / len(matched)
    return round(valence, 3), round(energy, 3)


def _refresh_spotify_token(user: User, db: Session) -> str | None:
    """access_token 만료 시 refresh_token으로 갱신"""
    import httpx

    if user.spotify_access_token and user.spotify_token_expires_at:
        if datetime.now(timezone.utc) < user.spotify_token_expires_at:
            return user.spotify_access_token

    if not user.spotify_refresh_token:
        return None

    resp = httpx.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "refresh_token",
        "refresh_token": user.spotify_refresh_token,
        "client_id": settings.spotify_client_id,
        "client_secret": settings.spotify_client_secret,
    })

    if resp.status_code != 200:
        logger.error(
            "spotify token refresh failed user_id=%s status=%s body=%s",
            user.id, resp.status_code, resp.text[:300],
        )
        return None

    tokens = resp.json()
    from datetime import timedelta
    user.spotify_access_token = tokens["access_token"]
    user.spotify_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    if "refresh_token" in tokens:
        user.spotify_refresh_token = tokens["refresh_token"]
    db.commit()

    return tokens["access_token"]


def collect_spotify(user_id: int, db: Session) -> dict:
    """Spotify 최근 재생 기록 수집"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.spotify_refresh_token:
        return {"status": "skip", "reason": "no spotify token"}

    access_token = _refresh_spotify_token(user, db)
    if not access_token:
        logger.error("spotify collection skipped: token refresh failed user_id=%s", user_id)
        return {"status": "error", "reason": "token refresh failed"}

    sp = spotipy.Spotify(auth=access_token)

    try:
        kwargs = {"limit": 50}
        if user.spotify_last_cursor_ms:
            kwargs["after"] = user.spotify_last_cursor_ms
        results = sp.current_user_recently_played(**kwargs)
    except spotipy.exceptions.SpotifyException as e:
        logger.error("spotify recently_played call failed user_id=%s error=%s", user_id, e)
        return {"status": "error", "reason": str(e)}

    items = results.get("items", [])
    if not items:
        return {"status": "ok", "inserted": 0, "reason": "no new tracks"}

    track_ids = []
    artist_ids = set()
    records = []

    for item in items:
        track = item["track"]
        track_ids.append(track["id"])
        for artist in track["artists"]:
            artist_ids.add(artist["id"])

        records.append({
            "spotify_track_id": track["id"],
            "track_name": track["name"],
            "artist_name": ", ".join(a["name"] for a in track["artists"]),
            "artist_id": track["artists"][0]["id"],
            "album_name": track["album"]["name"],
            "played_at": item["played_at"],
            "duration_ms": track["duration_ms"],
        })

    # audio features (may be deprecated for new apps)
    features_map = {}
    try:
        features = sp.audio_features(track_ids)
        if features:
            for f in features:
                if f:
                    features_map[f["id"]] = f
    except Exception:
        pass

    # artist genres (cache within this call)
    genres_map = {}
    for aid in artist_ids:
        try:
            artist = sp.artist(aid)
            genres_map[aid] = artist.get("genres", [])
        except Exception:
            genres_map[aid] = []

    inserted = 0
    max_played_at_ms = user.spotify_last_cursor_ms or 0

    for rec in records:
        played_dt = datetime.fromisoformat(rec["played_at"].replace("Z", "+00:00"))
        played_ms = int(played_dt.timestamp() * 1000)

        existing = (
            db.query(SpotifyHistory)
            .filter_by(
                user_id=user_id,
                spotify_track_id=rec["spotify_track_id"],
                played_at=played_dt,
            )
            .first()
        )
        if existing:
            if played_ms > max_played_at_ms:
                max_played_at_ms = played_ms
            continue

        feat = features_map.get(rec["spotify_track_id"], {})
        genres = genres_map.get(rec["artist_id"], [])

        if feat:
            valence = feat.get("valence")
            energy = feat.get("energy")
            danceability = feat.get("danceability")
            tempo = feat.get("tempo")
            acousticness = feat.get("acousticness")
            instrumentalness = feat.get("instrumentalness")
        else:
            valence, energy = _estimate_mood_from_genres(genres)
            danceability = tempo = acousticness = instrumentalness = None

        entry = SpotifyHistory(
            user_id=user_id,
            spotify_track_id=rec["spotify_track_id"],
            track_name=rec["track_name"],
            artist_name=rec["artist_name"],
            artist_id=rec["artist_id"],
            album_name=rec["album_name"],
            played_at=played_dt,
            duration_ms=rec["duration_ms"],
            valence=valence,
            energy=energy,
            danceability=danceability,
            tempo=tempo,
            acousticness=acousticness,
            instrumentalness=instrumentalness,
            genres=genres,
        )
        db.add(entry)
        inserted += 1

        if played_ms > max_played_at_ms:
            max_played_at_ms = played_ms

    # 커서 업데이트 — 다음 폴링에서 이 시점 이후만 가져옴
    user.spotify_last_cursor_ms = max_played_at_ms
    db.commit()
    return {"status": "ok", "inserted": inserted}
