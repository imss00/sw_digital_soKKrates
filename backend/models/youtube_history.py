from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from backend.database import Base


class YouTubeHistory(Base):
    __tablename__ = "youtube_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    video_id = Column(String(11), nullable=False)
    title = Column(Text)
    description = Column(Text)
    channel_name = Column(String(255))
    channel_id = Column(String(64))
    category_id = Column(Integer)
    tags = Column(ARRAY(Text))
    duration_sec = Column(Integer)
    watched_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(20), default="takeout")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "video_id", "watched_at", name="uq_youtube_watch"),
        Index("idx_youtube_user_date", "user_id", "watched_at"),
    )
