from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger
from sqlalchemy.sql import func

from backend.database import Base
from backend.utils.crypto import EncryptedText


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(100))
    wake_up_time = Column(String(5), default="07:00")
    timezone = Column(String(50), default="Asia/Seoul")

    # Spotify OAuth
    spotify_access_token = Column(EncryptedText)
    spotify_refresh_token = Column(EncryptedText)
    spotify_token_expires_at = Column(DateTime(timezone=True))
    spotify_last_cursor_ms = Column(BigInteger)  # played_at의 Unix ms — 폴링 중복 방지

    # Google OAuth (Calendar + YouTube)
    google_access_token = Column(EncryptedText)
    google_refresh_token = Column(EncryptedText)
    google_token_expires_at = Column(DateTime(timezone=True))

    # Notion
    notion_token = Column(EncryptedText)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
