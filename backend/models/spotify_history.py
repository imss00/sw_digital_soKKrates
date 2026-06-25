from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from backend.database import Base


class SpotifyHistory(Base):
    __tablename__ = "spotify_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    spotify_track_id = Column(String(22))
    track_name = Column(Text)
    artist_name = Column(Text)
    artist_id = Column(String(22))
    album_name = Column(Text)
    played_at = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Integer)

    valence = Column(Float)
    energy = Column(Float)
    danceability = Column(Float)
    tempo = Column(Float)
    acousticness = Column(Float)
    instrumentalness = Column(Float)
    genres = Column(ARRAY(Text))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "spotify_track_id", "played_at", name="uq_spotify_play"),
    )
