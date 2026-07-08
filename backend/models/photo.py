from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, Index
from sqlalchemy.sql import func

from backend.database import Base


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_path = Column(Text)
    original_filename = Column(String(255))
    content_hash = Column(String(64))  # 파일 바이트의 SHA256 — 자동 업로드 시 중복 방지용
    taken_at = Column(DateTime(timezone=True))
    latitude = Column(Float)
    longitude = Column(Float)
    camera_model = Column(Text)
    file_size = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)

    # Phase 2: Vision AI 분석 결과 저장
    vision_labels = Column(Text)       # Google Vision API 라벨 (JSON string)
    vision_narrative = Column(Text)    # Claude가 생성한 "오늘의 장면" 한 줄 서사

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_photo_user_date", "user_id", "taken_at"),
        Index("idx_photo_user_hash", "user_id", "content_hash", unique=True),
    )
