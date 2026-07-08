"""
정형(structured) PII 마스킹 — LLM(OpenAI 임베딩/저널 생성)로 보내기 전에
unified_documents.content_text에 적용한다.

이메일·전화번호·주민등록번호·카드번호처럼 패턴이 고정된 정형 PII만 다룬다.
캘린더 제목의 사람 이름("김철수와 회의")처럼 문맥이 필요한 비정형 PII는
정규식으로 안전하게 잡을 수 없어 범위 밖이다(NER 모델이 필요, 별도 확장 필요).
"""
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 한글은 Python re에서 \w(word char)로 취급되어 "5678이고"처럼 공백 없이 붙으면
# \b가 성립하지 않는다 — 자릿수 기반 lookaround(숫자 인접 여부)로 대체.
_RRN_RE = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")  # 주민등록번호: YYMMDD-[1-4]XXXXXX
_CARD_RE = re.compile(r"(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
_PHONE_RE = re.compile(
    r"(?<!\d)(\+82[-\s]?1[0-9]|01[016789])[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"
)

_PATTERNS = [
    (_RRN_RE, "[RRN]"),        # 카드번호(16자리)와 겹치지 않도록 13자리 패턴을 먼저 치환
    (_CARD_RE, "[CARD]"),
    (_PHONE_RE, "[PHONE]"),
    (_EMAIL_RE, "[EMAIL]"),
]


def mask_pii(text: str | None) -> str | None:
    """이메일/전화번호/주민등록번호/카드번호를 마스킹 토큰으로 치환한다."""
    if not text:
        return text
    for pattern, token in _PATTERNS:
        text = pattern.sub(token, text)
    return text
