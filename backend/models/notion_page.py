from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


class NotionPage(Base):
    __tablename__ = "notion_pages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notion_page_id = Column(String(36))
    title = Column(Text)
    content_text = Column(Text)
    last_edited = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "notion_page_id", name="uq_notion_page"),
    )
