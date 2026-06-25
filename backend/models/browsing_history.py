from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.sql import func

from backend.database import Base


class BrowsingHistory(Base):
    __tablename__ = "browsing_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    url = Column(Text, nullable=False)
    domain = Column(String(255))
    title = Column(Text)
    article_text = Column(Text)
    is_article = Column(Boolean, default=False)
    visited_at = Column(DateTime(timezone=True), nullable=False)
    time_spent_sec = Column(Integer)
    visit_count = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_browsing_user_date", "user_id", "visited_at"),
    )
