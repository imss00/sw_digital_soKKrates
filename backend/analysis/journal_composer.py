"""
역할 B — B-1~B-6. AI 저널 구성 (OpenAI 버전)
OpenAI(gpt-4o-mini)로 회고 / 포커스 / 기사 소개 / 음악 / 사진 서사 생성.
(역할 A와 동일 provider로 통일 → OPENAI_API_KEY 하나로 동작. Gemini 한도/정지 이슈 회피.)

[설계 원칙]
- 각 섹션마다 2~3가지 프롬프트 변형(variant)을 랜덤 선택 → 매일 다른 분위기의 저널 생성
- 건이(역할 A)가 조립한 structured JSON을 최대한 활용 (youtube / music / headline / photo)
- compose_journal()은 dict(JSON) 반환 → 수빈 프론트엔드가 섹션별로 배치
- A5 양면 기준: 각 섹션 글자수 충분히 확보
    · 포커스(헤드라인) / 사진 캡션: 한 줄 (레이아웃상 길이 고정, 확장하지 않음)
    · 회고 / 기사소개: 8~10문장, 400~550자 내외 (본문 분량 섹션)
    · 음악: 어제 청취 6~8문장(300~500자) + 추천 곡 2개 각각 3~4문장(200~300자)
- 날조 금지: _available:false 섹션은 프롬프트에 포함하지 않음. 모든 프롬프트에
  "데이터에 없는 내용 지어내지 않기" 규칙을 공통으로 강제함.
- 모든 프롬프트는 공통 페르소나(PaperBack 기자)를 앞에 붙여 variant 간 톤 편차를 줄임.
- 섹션별 분량이 다르므로 max_tokens도 섹션별로 지정 (특히 기사 소개는 기사 3개를
  한 번에 생성하므로 최대 ~1,450자까지 나올 수 있어 넉넉히 잡음).
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
- "네, 작성했습니다" 같은 인사말이나 설명, 마크다운, 따옴표 없이 완성된 본문 텍스트만 출력하세요."""


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
# (설계상 "어제의 한 장면" 캡션 한 줄 — 분량 확장 대상 아님)
# ────────────────────────────────────────────────────────────────

_PHOTO_VARIANTS = [
    _wrap(
        """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 종합하여 "어제의 한 장면"을 담담하고 따뜻한 관찰자 시점으로, "~했다" 체 한 문장(50자 내외)으로 표현하세요.
감정 형용사 없이 장면 자체를 묘사하세요.

사진 분석:
{labels_text}"""
    ),
    _wrap(
        """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 한 편의 짧은 회상처럼, "~이었다" 또는 "~가 있었다" 체의 서정적인 한 문장(50자 내외)으로 표현하세요.
구체적인 사물이나 색감을 한 가지 언급하세요.

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
    result = _call_llm(prompt, max_tokens=200)
    return result or None


# ────────────────────────────────────────────────────────────────
# B-3. 오늘의 포커스
# (설계상 헤드라인 한 줄 — 분량 확장 대상 아님)
# ────────────────────────────────────────────────────────────────

_FOCUS_VARIANTS = [
    # variant A: 실행 중심
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루 가장 집중해야 할 행동 하나를 한 문장(40~60자)으로 제안하세요.
"오늘은 ~를 해보세요" 또는 "~에 집중하는 하루가 될 것입니다" 형태로 작성하세요.
관심사 키워드 중 최소 1개를 반드시 자연스럽게 포함하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}"""
    ),
    # variant B: 질문형 — 하루를 여는 화두
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 하루를 시작하며 스스로에게 던질 수 있는 질문 한 문장(40~60자)을 만들어주세요.
"오늘, ~을 해낼 수 있을까?" 또는 "~에 대해 한 걸음 더 나아갈 준비가 됐는가?" 같은 형태로 작성하세요.
관심사 키워드 중 최소 1개를 질문 속에 자연스럽게 녹이세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}"""
    ),
    # variant C: 짧은 선언문
    _wrap(
        """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루의 테마를 짧은 선언문(20~35자) 형태로 작성하세요.
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
    return _call_llm(prompt, max_tokens=200) or "오늘 하루도 충실하게.", idx


# ────────────────────────────────────────────────────────────────
# B-4. 어제 회고
# (본문 섹션 — 8~10문장, 400~550자로 확장. 일기식 감정 서술 금지 → 사실 나열식)
# ────────────────────────────────────────────────────────────────

# 회고는 "느꼈다/생각했다/깨달았다" 식으로 AI가 없는 감정·해석을 지어내면
# 사용자 입장에서 거짓 일기처럼 느껴진다는 피드백을 반영해, 데이터에 있는
# 사실(무엇을 보고 듣고 했는지)만 나열하도록 모든 variant에 공통 규칙을 둠.
_REFLECTION_BAN_NOTICE = """

[말투 — 반드시 지킬 것]
데이터에 없는 감정이나 해석을 지어내지 마세요. "느꼈다", "생각했다", "깨달았다",
"실감했다", "고민해보는 시간을 가졌다", "~함을 느꼈다" 같은 내면·감상 서술은 절대 쓰지 마세요.
오직 주어진 데이터에 근거해 "무엇을 보고, 듣고, 했는지"만 사실 그대로 나열하세요."""


def _wrap_reflection(body: str) -> str:
    """회고 전용: 공통 페르소나/출력 규칙에 사실 나열 금지 규칙을 추가로 붙인다."""
    return _wrap(body) + _REFLECTION_BAN_NOTICE


_REFLECTION_VARIANTS = [
    # variant A: 시간 흐름 서술 — 아침→저녁 (사실 나열)
    _wrap_reflection(
        """다음 데이터를 바탕으로 어제 하루 있었던 일을 8~10문장(400~550자)의 사실 나열로 정리해주세요.
시간 흐름(아침→낮→저녁)을 따라가며, "~했다" 체로 관찰 가능한 사실만 담담하게 서술하세요.
평가나 조언, 의미 부여 없이 기록하듯 쓰고, 구체적인 키워드나 활동을 최소 4개 포함하세요.
문장마다 새로운 사실이나 장면을 하나씩 담아, 같은 내용을 다른 말로 반복하지 마세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}"""
    ),
    # variant B: 키워드 중심 압축 서술 (사실 나열)
    _wrap_reflection(
        """다음 데이터를 바탕으로 어제 하루를 8~10문장(400~550자)의 사실 나열로 정리해주세요.
하루를 관통한 키워드 2~3개를 각각 한두 문장씩 풀어 쓰며, 무엇에 시간을 썼는지를
"~을 들었다", "~을 봤다", "~을 찾아봤다" 같은 관찰 동사로만 서술하세요.
마지막 한두 문장은 감상이 아니라, 하루 활동 전체를 요약하는 사실 문장으로 마무리하세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}"""
    ),
    # variant C: 감각(청각/시각/관심사) 중심 나열 (사실 나열)
    _wrap_reflection(
        """다음 데이터를 바탕으로 어제 하루를 8~10문장(400~550자)의 사실 나열로 정리해주세요.
청각(음악), 시각(영상/사진), 관심사(검색/콘텐츠)라는 세 영역을 각각 두세 문장씩 담아,
무엇을 들었고 무엇을 봤고 무엇에 관심을 두었는지 사실 그대로 서술하세요.
"~을 들었다", "~을 봤다", "~을 접했다" 같은 관찰 동사만 사용하고,
"~를 느끼며", "~를 생각하며" 같은 감정·해석 연결어는 쓰지 마세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}"""
    ),
]


def generate_reflection(analysis_result: dict, core_theme: str) -> tuple[str, int]:
    """핵심 테마 + structured 데이터 + 무드로 8~10문장 회고 생성. (텍스트, variant_idx) 반환."""
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

    variant, idx = _pick_variant(_REFLECTION_VARIANTS)
    prompt = variant.format(
        core_theme=core_theme,
        mood=mood_ko,
        mood_detail=mood_detail,
        yt_category=yt_category,
        yt_time=yt_time,
        music_mood=music_mood,
        photo_narrative=photo_narrative or "없음",
    )
    return _call_llm(prompt, max_tokens=1000) or "어제 하루의 기록을 불러오는 중입니다.", idx


# ────────────────────────────────────────────────────────────────
# B-5. 기사 소개 텍스트
# (본문 섹션 — 메인 기사 포함 8~10문장 내외로 확장)
# ────────────────────────────────────────────────────────────────

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
- 어조는 친근하되 정보 밀도가 높아야 합니다. 각 기사 소개는 "●" 로 시작하세요.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}"""
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
- 각 기사 소개는 "●" 로 시작하세요.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}"""
    ),
]


def generate_article_intros(
    articles: list[dict],
    core_theme: str,
    keywords: list[str],
    youtube_section: dict,
) -> tuple[str, int | None]:
    """추천 기사 3개를 저널에 실을 맞춤형 큐레이션 문구로 가공. (텍스트, variant_idx) 반환."""
    if not articles:
        return "오늘의 추천 기사를 준비 중입니다.", None

    articles_text = "\n".join(
        f"{i+1}. [{a.get('title', '')}] {a.get('summary', '')[:250]}"
        for i, a in enumerate(articles[:3])
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
    return _call_llm(prompt, max_tokens=2400) or "오늘의 추천 기사를 준비 중입니다.", idx


# ────────────────────────────────────────────────────────────────
# B-6. 음악 섹션 텍스트
# (본문 섹션 — 어제 청취 6~8문장(300~500자) + 추천 곡 2개 각각 3~4문장(200~300자)으로 확장)
# ────────────────────────────────────────────────────────────────

_MUSIC_VARIANTS = [
    # variant A: 어제 청취 중심 + 오늘 추천 (곡 2개 균형 소개)
    _wrap(
        """다음 음악 데이터를 바탕으로 어제 청취 감상과 오늘 추천 이유를 자연스럽게 서술하세요.
먼저 어제 들은 음악의 분위기를 6~8문장(300~500자)으로 묘사하세요.
그 다음 추천 곡 2개를 각각 "●곡명 / 아티스트" 형식으로 소개하되, 곡마다 3~4문장(200~300자)으로
추천 이유와 어울리는 상황, 곡의 분위기를 설명하세요. 두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}"""
    ),
    # variant B: 감정 여정 중심 (곡 2개 균형 소개)
    _wrap(
        """다음 음악 데이터를 바탕으로, 어제 하루의 감정 여정을 음악으로 표현해주세요.
"어제의 사운드트랙은 ~였다" 식의 표현으로 시작해 6~8문장(300~500자)에 걸쳐 그 감정의 흐름을 그리세요.
그 다음 오늘 추천 곡 2개를 각각 "●곡명 / 아티스트 — 설명" 형식으로 소개하되,
곡마다 3~4문장(200~300자)으로 이어서 소개하세요. 두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}"""
    ),
    # variant C: 곡마다 다른 각도로 소개 (앨범/아티스트 이야기 vs 어울리는 상황) — 분량은 균등
    _wrap(
        """다음 음악 데이터를 바탕으로 어제 청취 감상과 오늘 추천 이유를 자연스럽게 서술하세요.
먼저 어제 들은 음악의 분위기를 6~8문장(300~500자)으로 묘사하세요.
그 다음 추천 곡 1을 "●곡명 / 아티스트" 형식으로 제시하고, 곡이나 앨범, 아티스트에 얽힌 이야기를
3~4문장(200~300자)으로 소개하세요.
마지막으로 추천 곡 2도 "●곡명 / 아티스트" 형식으로 제시하고, 이 곡이 어울리는 상황이나 감정을
3~4문장(200~300자)으로 소개하세요. 두 곡의 분량은 비슷하게 맞추세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}"""
    ),
]


def generate_music_section(music_data: dict, mood_summary: dict) -> tuple[str, int | None]:
    """음악 섹션 텍스트 생성. (텍스트, variant_idx) 반환."""
    if not music_data.get("_available"):
        return "어제 Spotify 청취 기록이 없어 음악 추천을 건너뜁니다.", None

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
    return _call_llm(prompt, max_tokens=1800) or f"어제 무드: {mood_ko}\n추천 곡: {rec_1}, {rec_2}", idx


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
        "reflection": "...",        # 어제 회고 (8~10문장)
        "article_intros": "...",    # 추천 기사 소개 (기사당 6~10문장)
        "recommended_articles": [], # 기사 원본 리스트 (링크 포함)
        "music_text": "...",        # 음악 섹션 서술 텍스트 (8~10문장)
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
            "reflection": 1,
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
        "article_intros": sections.get("article_intros", ""),
        "recommended_articles": sections.get("recommended_articles", []),
        "music_text": sections.get("music_text", ""),
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
