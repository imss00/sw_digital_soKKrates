from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


class JournalRun(Base):
    __tablename__ = "journal_runs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_date = Column(Date, nullable=False)
    celery_task_id = Column(String(255))
    status = Column(String(20), nullable=False)
    stage = Column(String(50))
    error = Column(Text)
    journal_id = Column(Integer, ForeignKey("journals.id"))
    queued_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "target_date", name="uq_journal_run_user_date"),
    )
