from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from backend.database import Base


class UnifiedDocument(Base):
    __tablename__ = "unified_documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source = Column(String(20), nullable=False)
    source_id = Column(Integer)

    # 텍스트 분석용
    content_text = Column(Text, nullable=False)
    content_type = Column(String(20))     # article, music, event, video, note, photo
    title = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False)

    # 감정/무드 (Spotify에서만 채워짐, Phase 2에서 다른 소스도 추론 가능)
    mood_valence = Column(Float)
    mood_energy = Column(Float)

    # Phase 2: 분석 결과
    keywords = Column(ARRAY(Text))
    embedding_json = Column(Text)         # 1536차원 벡터를 JSON string으로 저장 (pgvector 없이도 동작)
    cluster_id = Column(Integer)
    is_processed = Column(Boolean, default=False)  # Phase 2 분석 완료 여부

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_unified_user_date", "user_id", "occurred_at"),
        UniqueConstraint("user_id", "source", "source_id", name="uq_unified_source"),  # 중복 정규화 방지
    )
