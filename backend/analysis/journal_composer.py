"""
역할 B — B-1~B-6. AI 저널 구성 (OpenAI 버전)
OpenAI(gpt-4o-mini)로 회고 / 포커스 / 기사 소개 / 음악 / 사진 서사 생성.
(역할 A와 동일 provider로 통일 → OPENAI_API_KEY 하나로 동작. Gemini 한도/정지 이슈 회피.)

[설계 원칙]
- 각 섹션마다 2~3가지 프롬프트 변형(variant)을 랜덤 선택 → 매일 다른 분위기의 저널 생성
- 건이(역할 A)가 조립한 structured JSON을 최대한 활용 (youtube / music / headline / photo)
- compose_journal()은 dict(JSON) 반환 → 수빈 프론트엔드가 섹션별로 배치
- A5 양면 기준: 각 섹션 글자수 충분히 확보
    · 포커스(헤드라인): 2~3문장(100~200자) / 사진 캡션: 4~5문장(200~300자)
    · 회고: 완성된 문장이 아니라 4~8개 키워드를 "/" 로 구분한 문자열
      (사용자가 신문 여백에 손으로 직접 회고를 쓰도록 힌트만 제공)
    · 기사소개: 8~10문장, 400~550자 내외 (본문 분량 섹션)
    · 음악: 어제 청취 6~8문장(300~500자) + 추천 곡 2개 각각 3~4문장(200~300자)
- 날조 금지: _available:false 섹션은 프롬프트에 포함하지 않음. 모든 프롬프트에
  "데이터에 없는 내용 지어내지 않기" 규칙을 공통으로 강제함.
- 모든 프롬프트는 공통 페르소나(PaperBack 기자)를 앞에 붙여 variant 간 톤 편차를 줄임.
- 섹션별 분량이 다르므로 max_tokens도 섹션별로 지정 (특히 기사 소개는 기사 3개를
  한 번에 생성하므로 최대 ~1,450자까지 나올 수 있어 넉넉히 잡음).
- 기사 소개(3개)와 음악 섹션(어제청취+추천곡2개)은 각각 한 번의 LLM 호출로 여러
  항목을 생성하되, "===" 구분자 + [TAG] 형식으로 출력을 강제하고 _parse_tagged_blocks()로
  파싱해 항목별 dict/list로 반환 → 수빈이 카드 단위로 바로 배치할 수 있게 함.
  파싱 실패(형식 안 지킴) 시 항목별 폴백 문구로 안전하게 대체.
"""

import json
import random
import re
from datetime import date, datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.models.calendar_event import CalendarEvent
from backend.config import settings

KST = timezone(timedelta(hours=9))
GEN_MODEL = "gpt-4o-mini"  # 퀄 아쉬우면 이 문자열만 교체 (예: gpt-5.4-mini)

# 클라이언트는 프로세스당 1회만 생성(싱글턴). 키 없을 때 import에서 안 터지도록 지연 생성.
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key or None)
    return _client


# ────────────────────────────────────────────────────────────────
# 공통: 페르소나 프리앰블 / 출력 규칙 / 무드 매핑
# ────────────────────────────────────────────────────────────────

_PERSONA_PREFIX = """당신은 사용자 개인을 위한 일간지 'PaperBack'의 기자입니다.
격조 있지만 딱딱하지 않은 신문체를 사용하고, 과장된 감탄사나 이모지는 쓰지 않습니다.

"""

_OUTPUT_RULES = """

[출력 규칙]
- 주어진 데이터에 없는 사실을 지어내지 마세요. 값이 "없음"이면 해당 항목은 자연스럽게 생략하세요.
- "네, 작성했습니다" 같은 인사말이나 설명, 마크다운, 따옴표 없이 완성된 본문 텍스트만 출력하세요.
- 사용자가 이미 그렇게 느꼈다/생각했다고 단정하는 과거형 서술은 쓰지 마세요.
  "느꼈다", "실감했다", "감동받았다", "위로받았다", "깨달았다", "고민해보는 시간을 가졌다" 같은 표현은 금지합니다.
  반면 "~할 수 있다", "~일 것이다" 같은 가능성·예측 표현이나, 하루/장면/음악/기사 자체에 대한
  묘사·비유(예: "감동받을 수 있는 이야기다")는 사용해도 됩니다."""


def _wrap(body: str) -> str:
    """프롬프트 본문에 공통 페르소나/출력 규칙을 붙여준다."""
    return _PERSONA_PREFIX + body + _OUTPUT_RULES


# mood_summary가 줄 수 있는 값이 늘어나도 깨지지 않도록 매핑을 넉넉히 잡음.
# 매핑에 없는 값은 "알 수 없음"으로 남겨서 mood_summary 쪽 데이터 이슈를 눈치챌 수 있게 함.
# ⚠️ 은아/건 쪽 mood_summary가 실제로 어떤 값들을 내는지 한 번 맞춰볼 것.
_MOOD_KO_MAP = {
    "bright": "밝고 경쾌한",
    "calm": "고요하고 차분한",
    "energetic": "활기차고 들뜬",
    "melancholic": "차분하게 가라앉은",
    "tense": "긴장감 있는",
    "neutral": "잔잔한",
}
_MOOD_KO_FALLBACK = "알 수 없음"


def _mood_to_ko(mood_name: str) -> str:
    return _MOOD_KO_MAP.get(mood_name, _MOOD_KO_FALLBACK)


# ────────────────────────────────────────────────────────────────
# 유틸: 안전한 LLM 호출 + JSON 파싱
# ────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, max_tokens: int = 800) -> str:
    """OpenAI 호출. 실패 시 빈 문자열 반환.

    max_tokens는 섹션별 목표 분량에 맞춰 호출부에서 지정한다.
    (기사 소개처럼 여러 항목을 한 번에 생성하는 섹션은 기본값보다 훨씬 크게 잡아야 함)
    """
    try:
        resp = _get_client().chat.completions.create(
            model=GEN_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""


def _parse_json_safe(text: str, fallback):
    """마크다운 펜스 제거 후 JSON 파싱. 실패 시 fallback 반환."""
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return fallback


def _pick_variant(variants: list[str]) -> tuple[str, int]:
    """variant 리스트에서 랜덤 선택 + 선택된 인덱스도 같이 반환 (디버그/데모용)."""
    idx = random.randrange(len(variants))
    return variants[idx], idx


def _parse_tagged_blocks(text: str, expected_count: int) -> list[tuple[str, str]] | None:
    """"===" 로 구분된 "[TAG]\\n본문" 블록들을 순서대로 파싱해 (tag, body) 리스트로 반환.

    수빈(프론트엔드)이 기사/음악 섹션을 항목별로 따로 배치할 수 있도록, 한 번의 LLM
    호출로 여러 항목을 생성하되 출력은 태그로 구분해 구조화한다. 블록 개수가
    expected_count와 다르거나 태그/본문이 비어 있으면 None을 반환해 호출부가
    폴백 처리하게 한다 (모델이 형식을 안 지켰을 때 절반만 파싱해 쓰지 않기 위함).
    """
    if not text:
        return None
    blocks = [b.strip() for b in text.split("===")]
    if len(blocks) != expected_count:
        return None
    parsed: list[tuple[str, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            return None
        tag = lines[0].strip().strip("[]")
        body = "\n".join(lines[1:]).strip()
        if not tag or not body:
            return None
        parsed.append((tag, body))
    return parsed


# ────────────────────────────────────────────────────────────────
# B-1. 키워드 수집 (건이 파트가 채운 keywords 읽기 전용)
# ────────────────────────────────────────────────────────────────

def extract_keywords(user_id: int, target_date: date, db: Session) -> list[str]:
    """
    건이(역할 A)가 이미 채워준 keywords 컬럼을 읽어서 합산 반환.
    LLM 호출 없음 — 역할 경계 준수.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
            UnifiedDocument.is_processed == True,  # 건이 처리 완료된 것만
        )
        .all()
    )

    all_keywords: list[str] = []
    for doc in docs:
        if doc.keywords:
            all_keywords.extend(doc.keywords)

    # 순서 유지하면서 중복 제거
    return list(dict.fromkeys(all_keywords))


# ────────────────────────────────────────────────────────────────
# B-2. 사진 서사 생성
# (4~5문장, 200~300자로 확장)
# ────────────────────────────────────────────────────────────────

_PHOTO_VARIANTS = [
    _wrap(
        """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 종합하여 "어제의 한 장면"을 담담하고 따뜻한 관찰자 시점으로, "~했다" 체 4~5문장 (200~300자 내외)으로 표현하세요.
감정 형용사 없이 장면 자체를 묘사하세요. 사진에 대한 표현은 가능하되, 사용자의 감정을 직접 느낀 것처럼 작성하지 마세요.

사진 분석:
{labels_text}"""
    ),
    _wrap(
        """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 한 편의 짧은 회상처럼, "~이었다" 또는 "~가 있었다" 체의 서정적인 4~5문장 (200~300자 내외)으로 표현하세요.
구체적인 사물이나 색감을 한 가지 언급하세요. 사진에 대한 표현은 가능하되, 사용자의 감정을 직접 느낀 것처럼 작성하지 마세요.

사진 분석:
{labels_text}"""
    ),
]


def generate_photo_narrative(photo_labels: list[dict]) -> str | None:
    """사진 분석 결과(라벨, 위치, 시각)를 받아 '어제의 한 장면' 한 문장 생성."""
    if not photo_labels:
        return None

    labels_text = "\n".join(
        f"- 사진 {i+1}: {', '.join(p.get('labels', []))}, "
        f"위치: {p.get('location', '알 수 없음')}, 시각: {p.get('taken_at', '')}"
        for i, p in enumerate(photo_labels)
    )

    variant, _ = _pick_variant(_PHOTO_VARIANTS)
    prompt = variant.format(labels_text=labels_text)
    result = _call_llm(prompt, max_tokens=600)
    return result or None


# ────────────────────────────────────────────────────────────────
# B-3. 오늘의 포커스
# (2~3문장, 100~200자로 확장)
# ────────────────────────────────────────────────────────────────

_FOCUS_VARIANTS = [
    # variant A: 실행 중심
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루 가장 집중해야 할 행동 하나를 2~3 문장(100~200자)으로 제안하세요.
"오늘은 ~를 해보세요" 또는 "~에 집중하는 하루가 될 것입니다" 형태로 작성하세요.
관심사 키워드 중 최소 1개를 반드시 자연스럽게 포함하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}"""
    ),
    # variant B: 질문형 — 하루를 여는 화두
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 하루를 시작하며 스스로에게 던질 수 있는 질문을 포함해 2~3 문장(100~200자)으로 제안하세요.
"오늘, ~을 해낼 수 있을까?" 또는 "~에 대해 한 걸음 더 나아갈 준비가 됐는가?" 같은 형태로 작성하세요.
관심사 키워드 중 최소 1개를 질문 속에 자연스럽게 녹이세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}"""
    ),
    # variant C: 짧은 선언문
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루의 테마를 짧은 선언문 2~3 문장(100~200자)으로 제안하세요..
예: "오늘은 깊이 읽는 날." / "코드보다 설계를 먼저 생각하는 하루."
관심사 키워드 중 최소 1개를 선언문에 녹여내고, 마침표로 끝내며 명사형으로 마무리하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}"""
    ),
]


def generate_daily_focus(schedule: list[dict], keywords: list[str]) -> tuple[str, int]:
    """캘린더 일정 + 관심사 키워드로 오늘 집중할 한 줄 제안. (텍스트, variant_idx) 반환."""
    schedule_text = "\n".join(
        f"- {s.get('time', '')}: {s.get('title', '')}" for s in schedule
    ) or "일정 없음"
    interest_text = ", ".join(keywords[:10]) or "관심사 데이터 없음"

    variant, idx = _pick_variant(_FOCUS_VARIANTS)
    prompt = variant.format(schedule_text=schedule_text, interest_text=interest_text)
    return _call_llm(prompt, max_tokens=400) or "오늘 하루도 충실하게.", idx


# ────────────────────────────────────────────────────────────────
# B-4. 어제 회고
# (완성된 문장이 아니라 4~8개 키워드를 "/" 로 구분해 반환 — 사용자가 신문 여백에
#  손으로 직접 회고를 쓸 수 있도록 "회고 힌트"만 제공하는 방식으로 변경)
# ────────────────────────────────────────────────────────────────

_REFLECTION_PROMPT = _wrap(
    """다음 데이터를 바탕으로 어제 하루를 대표하는 키워드를 4~8개 뽑아주세요.
키워드는 문장이 아니라 "자취 요리", "혼밥", "레시피 추천", "헬스장", "인디밴드", "폭우" 처럼
2~6자 내외의 짧은 명사(구)여야 합니다. 문장이나 설명으로 풀어 쓰지 마세요.
사용자가 이 키워드만 보고 스스로 손으로 회고를 쓸 수 있도록, 활동·관심사·감정·날씨 등
서로 다른 영역에서 고르게 뽑고 같은 의미의 키워드를 중복해서 넣지 마세요.
데이터에 없는 영역은 억지로 채우지 말고 있는 데이터에서만 뽑으세요.
출력은 키워드를 " / " 로 이어붙인 한 줄짜리 문자열로만 하세요. 번호, 설명, 마크다운은 쓰지 마세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}"""
)


def generate_reflection(analysis_result: dict, core_theme: str) -> tuple[str, int]:
    """핵심 테마 + structured 데이터 + 무드로 회고용 키워드 4~8개를 "/" 구분 문자열로 생성.
    프롬프트 변형이 1개뿐이라 idx는 항상 0 (compose_journal의 prompt_variants 스키마 유지용)."""
    structured = analysis_result.get("structured", {})
    mood_summary = analysis_result.get("mood_summary", {})
    photo_narrative = analysis_result.get("photo_narrative", "")

    youtube = structured.get("youtube", {})
    music = structured.get("music", {})

    avg_valence = mood_summary.get("avg_valence")
    mood_name = mood_summary.get("mood", "")
    mood_ko = _mood_to_ko(mood_name)
    mood_detail = f"valence {avg_valence:.2f}" if avg_valence is not None else "수치 없음"

    yt_category = youtube.get("top_category") or "없음"
    yt_time = youtube.get("total_watch_time") or "없음"
    music_mood = music.get("rec_reason") or mood_ko

    prompt = _REFLECTION_PROMPT.format(
        core_theme=core_theme,
        mood=mood_ko,
        mood_detail=mood_detail,
        yt_category=yt_category,
        yt_time=yt_time,
        music_mood=music_mood,
        photo_narrative=photo_narrative or "없음",
    )
    return _call_llm(prompt, max_tokens=150) or "키워드를 불러오지 못했습니다.", 0


# ────────────────────────────────────────────────────────────────
# B-5. 기사 소개 텍스트
# (본문 섹션 — 메인 기사 포함 8~10문장 내외로 확장)
# ────────────────────────────────────────────────────────────────

# 기사/음악 공통: 한 번의 LLM 호출로 여러 항목을 만들되, "===" 구분자 + [TAG] 로
# 항목을 나눠서 출력하게 강제 → _parse_tagged_blocks()로 파싱해 프론트엔드가
# 항목별로(기사 카드 3개, 음악 텍스트 3종) 바로 배치할 수 있게 한다.
_ARTICLE_FORMAT_SUFFIX = """

[출력 형식 — 반드시 지킬 것]
정확히 3개 블록을 만들고, 블록은 위 추천 기사 목록과 같은 순서로 작성하세요.
블록 사이는 "===" 한 줄로만 구분하세요.
각 블록의 첫 줄은 그 기사가 메인이면 "[MAIN]", 아니면 "[SUB]"만 쓰고,
줄바꿈 후 소개문을 이어서 쓰세요. 번호, 마크다운, 그 외 텍스트는 쓰지 마세요."""

_ARTICLE_VARIANTS = [
    # variant A: 큐레이터 어조 — 맥락 연결형
    _wrap(
        """다음 추천 기사 3개 각각에 대해 제목을 포함한 소개문을 작성하세요.

[분량 — 반드시 지킬 것. 절대 2~3문장으로 줄이지 마세요]
- 사용자의 관심도가 가장 높을 것으로 예상되는 기사 1개를 메인 기사로 선정해 8~10문장(450~550자)으로 작성하세요.
- 나머지 기사는 각각 6~8문장(350~450자)으로 작성하세요.

[각 기사 소개는 아래 구조를 반드시 따를 것]
1) 기사 제목과 핵심 사실을 1~2문장으로 소개
2) 기사 내용을 구체적으로 풀어 설명하는 3~5문장 (배경, 세부 내용, 왜 중요한지 등 — 요약이 아니라 살을 붙여서)
3) 사용자의 관심사와 "자연스럽게" 연결되는 지점이 있을 때만 1~2문장으로 짚기

[주의]
- 사용자의 핵심 관심사·유튜브 시청 이력·키워드를 모든 기사에 억지로 연결하지 마세요.
  실제로 관련 있는 기사에서만 자연스럽게 언급하고, 관련 없으면 기사 자체의 매력과 정보만으로 소개하세요.
- 어조는 친근하되 정보 밀도가 높아야 합니다.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}""" + _ARTICLE_FORMAT_SUFFIX
    ),
    # variant B: 편집장 어조 — 왜 지금 읽어야 하는가
    _wrap(
        """다음 추천 기사 3개 각각에 대해, '왜 지금 이 기사를 읽어야 하는가'를 중심으로 소개문을 작성하세요.

[분량 — 반드시 지킬 것. 절대 2~3문장으로 줄이지 마세요]
- 사용자의 관심도가 가장 높을 것으로 예상되는 기사 1개를 메인 기사로 선정해 8~10문장(450~550자)으로 작성하세요.
- 나머지 기사는 각각 6~8문장(300~400자)으로 작성하세요.

[각 기사 소개는 아래 구조를 반드시 따를 것]
1) "지금 ~에 관심이 있다면", "~를 고민 중이라면" 같은 도입부 1~2문장
2) 기사 내용을 구체적으로 풀어 설명하는 4~5문장 (배경, 세부 내용, 핵심 주장 등 — 요약이 아니라 살을 붙여서)
3) 기사에서 얻을 수 있는 것을 구체적으로 언급하는 마무리 1~2문장

[주의]
- 사용자의 핵심 관심사·유튜브 시청 이력·키워드를 모든 기사에 억지로 연결하지 마세요.
  실제로 관련 있는 기사에서만 자연스럽게 언급하고, 관련 없으면 기사 자체의 매력과 정보만으로 소개하세요.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}""" + _ARTICLE_FORMAT_SUFFIX
    ),
]


def generate_article_intros(
    articles: list[dict],
    core_theme: str,
    keywords: list[str],
    youtube_section: dict,
) -> tuple[list[dict], int | None]:
    """추천 기사 3개를 각각 별도 소개문으로 가공.

    반환: ([{"title", "link", "intro", "is_main"}, ...], variant_idx).
    프론트엔드가 기사 카드 3개를 따로 배치할 수 있도록 기사별로 분리해서 반환한다.
    """
    articles = articles[:3]
    if not articles:
        return [], None

    articles_text = "\n".join(
        f"{i+1}. [{a.get('title', '')}] {a.get('summary', '')[:250]}"
        for i, a in enumerate(articles)
    )
    yt_category = youtube_section.get("top_category") or "없음"
    keywords_text = ", ".join(keywords[:8]) or "없음"

    variant, idx = _pick_variant(_ARTICLE_VARIANTS)
    prompt = variant.format(
        core_theme=core_theme,
        yt_category=yt_category,
        keywords=keywords_text,
        articles_text=articles_text,
    )
    # 기사 최대 3개(메인 1 + 나머지 2)를 한 번에 생성 → 최대 ~1,450자까지 나올 수 있어
    # 다른 섹션보다 훨씬 큰 max_tokens가 필요함.
    raw = _call_llm(prompt, max_tokens=2400)
    parsed = _parse_tagged_blocks(raw, len(articles))

    results: list[dict] = []
    for i, article in enumerate(articles):
        if parsed:
            tag, body = parsed[i]
            intro, is_main = body, tag == "MAIN"
        else:
            intro, is_main = "오늘의 추천 기사를 준비 중입니다.", i == 0
        results.append({
            "title": article.get("title", ""),
            "link": article.get("link", ""),
            "intro": intro,
            "is_main": is_main,
        })
    return results, idx


# ────────────────────────────────────────────────────────────────
# B-6. 음악 섹션 텍스트
# (본문 섹션 — 어제 청취 6~8문장(300~500자) + 추천 곡 2개 각각 3~4문장(200~300자).
#  프론트엔드 배치 편의를 위해 yesterday/rec_1/rec_2 텍스트를 분리해서 반환)
# ────────────────────────────────────────────────────────────────

_MUSIC_FORMAT_SUFFIX = """

[출력 형식 — 반드시 지킬 것]
정확히 3개 블록을 만들고, 블록 사이는 "===" 한 줄로만 구분하세요.
1번째 블록: 첫 줄에 "[YESTERDAY]"만 쓰고 줄바꿈 후 어제 청취 묘사를 이어서 쓰세요.
2번째 블록: 첫 줄에 "[REC1]"만 쓰고 줄바꿈 후 추천 곡 1 소개를 이어서 쓰세요.
3번째 블록: 첫 줄에 "[REC2]"만 쓰고 줄바꿈 후 추천 곡 2 소개를 이어서 쓰세요.
번호, 마크다운, 그 외 텍스트는 쓰지 마세요."""

_MUSIC_VARIANTS = [
    # variant A: 어제 청취 중심 + 오늘 추천 (곡 2개 균형 소개)
    _wrap(
        """다음 음악 데이터를 바탕으로 어제 청취 감상과 오늘 추천 이유를 자연스럽게 서술하세요.
어제 들은 음악의 분위기를 6~8문장(300~500자)으로 묘사하세요.
추천 곡 1과 추천 곡 2는 각각 3~4문장(200~300자)으로, 곡명과 아티스트를 자연스럽게 언급하며
추천 이유와 어울리는 상황, 곡의 분위기를 설명하세요. 두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}""" + _MUSIC_FORMAT_SUFFIX
    ),
    # variant B: 감정 여정 중심 (곡 2개 균형 소개)
    _wrap(
        """다음 음악 데이터를 바탕으로, 어제 하루의 감정 여정을 음악으로 표현해주세요.
"어제의 사운드트랙은 ~였다" 식의 표현으로 시작해 6~8문장(300~500자)에 걸쳐 그 감정의 흐름을 그리세요.
추천 곡 1과 추천 곡 2는 각각 3~4문장(200~300자)으로, 곡명과 아티스트를 자연스럽게 언급하며
소개하세요. 두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}""" + _MUSIC_FORMAT_SUFFIX
    ),
    # variant C: 곡마다 다른 각도로 소개 (앨범/아티스트 이야기 vs 어울리는 상황) — 분량은 균등
    _wrap(
        """다음 음악 데이터를 바탕으로 어제 청취 감상과 오늘 추천 이유를 자연스럽게 서술하세요.
어제 들은 음악의 분위기를 6~8문장(300~500자)으로 묘사하세요.
추천 곡 1은 곡이나 앨범, 아티스트에 얽힌 이야기를 3~4문장(200~300자)으로 소개하세요.
추천 곡 2는 이 곡이 어울리는 상황이나 감정을 3~4문장(200~300자)으로 소개하세요.
두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}""" + _MUSIC_FORMAT_SUFFIX
    ),
]


def generate_music_section(music_data: dict, mood_summary: dict) -> tuple[dict, int | None]:
    """음악 섹션 텍스트 생성.

    반환: ({"yesterday_text", "rec_1_text", "rec_2_text"}, variant_idx).
    프론트엔드가 "어제 들은 노래" / "추천곡1" / "추천곡2"를 따로 배치할 수 있도록 분리해서 반환한다.
    """
    if not music_data.get("_available"):
        return {
            "yesterday_text": "어제 Spotify 청취 기록이 없어 음악 추천을 건너뜁니다.",
            "rec_1_text": "",
            "rec_2_text": "",
        }, None

    mood_name = mood_summary.get("mood", "")
    mood_ko = _mood_to_ko(mood_name)

    yesterday_tracks = music_data.get("yesterday_tracks", [])
    yesterday_top = (
        ", ".join(f"{t['title']}({t['artist']})" for t in yesterday_tracks[:3])
        if yesterday_tracks else "없음"
    )

    def _fmt_track(track: dict | None) -> str:
        if not track:
            return "없음"
        parts = [track.get("title", ""), track.get("artist", "")]
        if track.get("album"):
            parts.append(f"앨범: {track['album']}")
        return " / ".join(p for p in parts if p)

    rec_1 = _fmt_track(music_data.get("rec_track_1"))
    rec_2 = _fmt_track(music_data.get("rec_track_2"))
    rec_reason = music_data.get("rec_reason") or "청취 패턴 기반 추천"

    variant, idx = _pick_variant(_MUSIC_VARIANTS)
    prompt = variant.format(
        mood_ko=mood_ko,
        yesterday_top=yesterday_top,
        rec_reason=rec_reason,
        rec_1=rec_1,
        rec_2=rec_2,
    )
    raw = _call_llm(prompt, max_tokens=1800)
    parsed = _parse_tagged_blocks(raw, 3)

    if parsed:
        body_by_tag = {tag: body for tag, body in parsed}
        yesterday_text = body_by_tag.get("YESTERDAY", "")
        rec_1_text = body_by_tag.get("REC1", "")
        rec_2_text = body_by_tag.get("REC2", "")
    else:
        yesterday_text = f"어제 무드: {mood_ko}"
        rec_1_text = rec_1
        rec_2_text = rec_2

    return {
        "yesterday_text": yesterday_text,
        "rec_1_text": rec_1_text,
        "rec_2_text": rec_2_text,
    }, idx


# ────────────────────────────────────────────────────────────────
# B-6. 최종 저널 조합 → JSON 반환
# ────────────────────────────────────────────────────────────────

def compose_journal(sections: dict) -> dict:
    """
    모든 섹션을 구조화 JSON으로 조합.
    수빈(프론트엔드)이 각 키를 신문 레이아웃 컴포넌트에 1:1 매핑.

    반환 구조:
    {
        "date": "2026년 7월 2일",
        "headline": "...",          # 오늘의 포커스 (1줄)
        "reflection": "...",        # 어제 회고 키워드 4~8개 ("/" 구분, 손글씨용 힌트)
        "article_intros": [         # 추천 기사 소개 — 기사 카드 3개를 각각 따로 배치하도록 분리
            {"title": "...", "link": "...", "intro": "...", "is_main": True},
            {"title": "...", "link": "...", "intro": "...", "is_main": False},
            {"title": "...", "link": "...", "intro": "...", "is_main": False},
        ],
        "recommended_articles": [], # 기사 원본 리스트 (링크 포함, article_intros와 별개로 유지)
        "music_text": {             # 음악 섹션 서술 텍스트 — 어제/추천곡1/추천곡2로 분리
            "yesterday_text": "...",
            "rec_1_text": "...",
            "rec_2_text": "...",
        },
        "music_tracks": {           # 추천 트랙 구조화 데이터
            "rec_track_1": {...},
            "rec_track_2": {...},
            "yesterday_top": [...],
        },
        "schedule": "...",          # 오늘 일정 텍스트
        "keywords": [...],          # 어제 관심 키워드
        "photo_narrative": "...",   # 어제의 한 장면 (있을 때만)
        "prompt_variants": {        # 디버그용: 이번에 선택된 variant 번호 (0-indexed)
            "focus": 0,
            "reflection": 0,
            "article": 0,
            "music": 1,
        }
    }
    """
    structured = sections.get("structured", {})
    music_data = structured.get("music", {})

    return {
        "date": sections.get("date", ""),
        "headline": sections.get("daily_focus", ""),
        "reflection": sections.get("reflection", ""),
        "article_intros": sections.get("article_intros", []),
        "recommended_articles": sections.get("recommended_articles", []),
        "music_text": sections.get("music_text", {}),
        "music_tracks": {
            "rec_track_1": music_data.get("rec_track_1"),
            "rec_track_2": music_data.get("rec_track_2"),
            "yesterday_top": music_data.get("yesterday_tracks", [])[:3],
        },
        "schedule": sections.get("schedule_text", ""),
        "keywords": sections.get("keywords", []),
        "photo_narrative": sections.get("photo_narrative", ""),
        "prompt_variants": sections.get("prompt_variants", {}),
    }


# ────────────────────────────────────────────────────────────────
# 통합 저널 생성 진입점
# ────────────────────────────────────────────────────────────────

def run_journal_composition(
    user_id: int,
    target_date: date,
    analysis_result: dict,
    db: Session,
) -> dict:
    """
    역할 B 전체 파이프라인 진입점.
    recommender.run_recommendation()의 analysis_result를 받아 저널 JSON 반환.

    Args:
        user_id: 사용자 ID
        target_date: 저널 날짜 (어제 기준 — 오늘 새벽 1시 실행)
        analysis_result: recommender.run_recommendation() 반환값
        db: SQLAlchemy 세션

    Returns:
        compose_journal()이 반환하는 구조화 JSON dict
    """
    # B-1. 건이가 채운 keywords 읽기
    keywords = extract_keywords(user_id, target_date, db)

    # 역할 A에서 넘겨받은 핵심 테마
    core_theme = analysis_result.get("core_theme", "특별한 관심사가 감지되지 않았습니다.")
    structured = analysis_result.get("structured", {})
    mood_summary = analysis_result.get("mood_summary", {})

    # 오늘(target_date + 1) 캘린더 일정 추출
    today = target_date + timedelta(days=1)
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=KST)
    today_end = today_start + timedelta(days=1)
    today_events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= today_start,
            CalendarEvent.start_time < today_end,
        )
        .order_by(CalendarEvent.start_time)
        .all()
    )
    schedule = [
        {
            "time": e.start_time.astimezone(KST).strftime("%H:%M"),
            "title": e.summary,
        }
        for e in today_events
    ]
    schedule_text = (
        "\n".join(f"{s['time']} {s['title']}" for s in schedule) or "일정 없음"
    )

    # B-2. 사진 서사 (_available:false면 None)
    photo_section = structured.get("photo", {})
    if photo_section.get("_available"):
        photo_narrative = generate_photo_narrative(
            analysis_result.get("photo_labels", [])
        )
    else:
        photo_narrative = None
    analysis_result["photo_narrative"] = photo_narrative

    # B-3. 오늘의 포커스
    daily_focus, focus_idx = generate_daily_focus(schedule, keywords)

    # B-4. 어제 회고
    reflection, reflection_idx = generate_reflection(analysis_result, core_theme)

    # B-5. 기사 소개
    youtube_section = structured.get("youtube", {})
    recommended_articles = structured.get("recommended_articles") or \
                           analysis_result.get("recommended_articles", [])
    article_intros, article_idx = generate_article_intros(
        recommended_articles, core_theme, keywords, youtube_section
    )

    # 음악 섹션
    music_data = structured.get("music", {})
    music_text, music_idx = generate_music_section(music_data, mood_summary)

    sections = {
        "date": f"{target_date.year}년 {target_date.month}월 {target_date.day}일",
        "daily_focus": daily_focus,
        "reflection": reflection,
        "photo_narrative": photo_narrative or "",
        "article_intros": article_intros,
        "recommended_articles": recommended_articles,
        "music_text": music_text,
        "schedule_text": schedule_text,
        "keywords": keywords,
        "structured": structured,
        "prompt_variants": {
            "focus": focus_idx,
            "reflection": reflection_idx,
            "article": article_idx,
            "music": music_idx,
        },
    }

    return compose_journal(sections)
