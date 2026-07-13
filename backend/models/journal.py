import re

from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.sql import func

from backend.database import Base

# journal_composer의 기사소개 프롬프트가 입력 데이터를 "기사 제목: ...", "기사 요약: ..."
# 라벨로 넘기는데, (구버전 프롬프트로 생성되어 이미 DB에 저장된 저널들 한정으로) LLM이 그
# 라벨과 제목을 출력 맨 앞에 그대로 복사해 넣은 경우가 있다(줄바꿈 없이 본문에 바로 이어붙은
# 경우도 있음). 프롬프트는 이후 생성분에 대해 고쳤지만 이미 저장된 과거 데이터는 소급
# 반영되지 않으므로, 조회 시점에 실제 기사 제목(title)을 기준으로 방어적으로 제거한다.
_LABEL_PREFIX_RE = re.compile(r"^기사\s*제목\s*[:：]\s*")
_SUMMARY_LABEL_RE = re.compile(r"^\s*기사\s*요약\s*[:：]\s*[^\n]*\n*")


def _strip_leaked_labels(text: str | None, title: str | None = None) -> str | None:
    if not text:
        return text
    text = text.strip()
    m = _LABEL_PREFIX_RE.match(text)
    if m:
        text = text[m.end():]
        if title:
            t = title.strip()
            if text[: len(t)].casefold() == t.casefold():
                text = text[len(t):]
        text = text.lstrip(" \t\"'“”·-—\n")
    text = _SUMMARY_LABEL_RE.sub("", text)
    return text.strip()

# journal_composer.compose_journal()의 결과 dict 키와 1:1로 대응하는 컬럼 이름 목록.
# 모델 정의, 저장(_save_journal), 조회 응답(to_dict) 세 군데가 각자 필드를 손으로 나열하면
# 하나만 고치고 나머지를 빠뜨리기 쉬워서, 이 목록 하나를 세 군데가 공유한다.
# "date"는 예외적으로 date_label 컬럼에 매핑된다(아래 Journal.to_dict/analysis_tasks._save_journal 참고).
JOURNAL_RESULT_FIELDS = [
    "headline",
    "reflection",
    "article_intros",
    "recommended_articles",
    "music_text",
    "music_tracks",
    "schedule",
    "keywords",
    "photo_narrative",
    "prompt_variants",
]


class Journal(Base):
    """journal_composer.compose_journal()의 결과를 저장하는 테이블.

    이전까지는 Phase 2-3 결과가 celery task 리턴값으로만 존재하고 DB에 남지 않아
    프론트엔드/프린터가 완성된 저널을 가져올 방법이 없었음 — 그 문제를 메우는 테이블.
    """

    __tablename__ = "journals"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_date = Column(Date, nullable=False)  # compose_journal()이 다루는 날짜(어제 기준)

    date_label = Column(String(50))       # "2026년 7월 8일" — 표시용
    headline = Column(Text)
    reflection = Column(Text)
    article_intros = Column(JSONB)
    recommended_articles = Column(JSONB)
    music_text = Column(JSONB)
    music_tracks = Column(JSONB)
    schedule = Column(Text)
    keywords = Column(ARRAY(Text))
    photo_narrative = Column(Text)
    prompt_variants = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # 같은 날짜로 재생성하면 새 행을 쌓지 않고 덮어쓰기(upsert) 위한 유니크 키
        UniqueConstraint("user_id", "target_date", name="uq_journal_user_date"),
    )

    def to_dict(self) -> dict:
        data = {"date": self.date_label}
        for field in JOURNAL_RESULT_FIELDS:
            data[field] = getattr(self, field)
        if data.get("article_intros"):
            data["article_intros"] = [
                {
                    **item,
                    "intro": _strip_leaked_labels(item.get("intro"), item.get("title")),
                }
                for item in data["article_intros"]
            ]
        data["created_at"] = self.created_at.isoformat() if self.created_at else None
        data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data
