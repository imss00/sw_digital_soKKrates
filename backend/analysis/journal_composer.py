"""
역할 B — B-1~B-6. AI 저널 구성 (OpenAI 버전)
OpenAI(gpt-4o-mini)로 회고 / 포커스 / 기사 소개 / 음악 / 사진 서사 생성.
(역할 A와 동일 provider로 통일 → OPENAI_API_KEY 하나로 동작. Gemini 한도/정지 이슈 회피.)

[설계 원칙]
- 각 섹션마다 2~3가지 프롬프트 변형(variant)을 랜덤 선택 → 매일 다른 분위기의 저널 생성
- 건이(역할 A)가 조립한 structured JSON을 최대한 활용 (youtube / music / headline / photo)
- compose_journal()은 dict(JSON) 반환 → 수빈 프론트엔드가 섹션별로 배치
- A5 양면 기준: 각 섹션 글자수 충분히 확보 (회고 200~300자, 기사소개 섹션당 150~200자 등)
- 날조 금지: _available:false 섹션은 프롬프트에 포함하지 않음
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
# 유틸: 안전한 LLM 호출 + JSON 파싱
# ────────────────────────────────────────────────────────────────

def _call_llm(prompt: str) -> str:
    """OpenAI 호출. 실패 시 빈 문자열 반환."""
    try:
        resp = _get_client().chat.completions.create(
            model=GEN_MODEL,
            max_tokens=800,
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


# ────────────────────────────────────────────────────────────────
# B-1. 키워드 수집 (건이 파트가 채운 keywords 읽기 전용)
# ────────────────────────────────────────────────────────────────

def extract_keywords(user_id: int, target_date: date, db: Session) -> list[str]:
    """
    건이(역할 A)가 이미 채워준 keywords 컬럼을 읽어서 합산 반환.
    Gemini 호출 없음 — 역할 경계 준수.
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
# ────────────────────────────────────────────────────────────────

# 사진 서사 프롬프트 변형 2가지
_PHOTO_VARIANTS = [
    # variant A: 관찰자 시점, 담담한 기록체
    """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 종합하여 "어제의 한 장면"을 담담하고 따뜻한 관찰자 시점으로, "~했다" 체 한 문장(50자 내외)으로 표현하세요.
감정 형용사 없이 장면 자체를 묘사하세요.

사진 분석:
{labels_text}""",

    # variant B: 회상하듯 서정적
    """다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 한 편의 짧은 회상처럼, "~이었다" 또는 "~가 있었다" 체의 서정적인 한 문장(50자 내외)으로 표현하세요.
구체적인 사물이나 색감을 한 가지 언급하세요.

사진 분석:
{labels_text}""",
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

    prompt = random.choice(_PHOTO_VARIANTS).format(labels_text=labels_text)
    result = _call_llm(prompt)
    return result or None


# ────────────────────────────────────────────────────────────────
# B-3. 오늘의 포커스
# ────────────────────────────────────────────────────────────────

# 포커스 프롬프트 변형 3가지
_FOCUS_VARIANTS = [
    # variant A: 실행 중심
    """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루 가장 집중해야 할 행동 하나를 한 문장(40~60자)으로 제안하세요.
"오늘은 ~를 해보세요" 또는 "~에 집중하는 하루가 될 것입니다" 형태로 작성하세요.
구체적인 키워드를 반드시 한 개 이상 포함하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}""",

    # variant B: 질문형 — 하루를 여는 화두
    """오늘 일정과 최근 관심사를 바탕으로, 하루를 시작하며 스스로에게 던질 수 있는 질문 한 문장(40~60자)을 만들어주세요.
"오늘, ~을 해낼 수 있을까?" 또는 "~에 대해 한 걸음 더 나아갈 준비가 됐는가?" 같은 형태로 작성하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}""",

    # variant C: 짧은 선언문
    """오늘 일정과 최근 관심사를 바탕으로, 오늘 하루의 테마를 짧은 선언문(20~35자) 형태로 작성하세요.
예: "오늘은 깊이 읽는 날." / "코드보다 설계를 먼저 생각하는 하루."
마침표로 끝내고, 명사형으로 마무리하세요.

오늘 일정:
{schedule_text}

최근 관심사 키워드: {interest_text}""",
]


def generate_daily_focus(schedule: list[dict], keywords: list[str]) -> str:
    """캘린더 일정 + 관심사 키워드로 오늘 집중할 한 줄 제안."""
    schedule_text = "\n".join(
        f"- {s.get('time', '')}: {s.get('title', '')}" for s in schedule
    ) or "일정 없음"
    interest_text = ", ".join(keywords[:10]) or "관심사 데이터 없음"

    prompt = random.choice(_FOCUS_VARIANTS).format(
        schedule_text=schedule_text,
        interest_text=interest_text,
    )
    return _call_llm(prompt) or "오늘 하루도 충실하게."


# ────────────────────────────────────────────────────────────────
# B-4. 어제 회고
# ────────────────────────────────────────────────────────────────

# 회고 프롬프트 변형 3가지 (A5 한 컬럼 분량: 200~300자 목표)
_REFLECTION_VARIANTS = [
    # variant A: 시간 흐름 서술 — 아침→저녁
    """다음 데이터를 바탕으로 어제 하루를 3~4문장(200~280자)으로 회고해주세요.
시간 흐름(아침→낮→저녁)을 자연스럽게 따라가며, "~했다" 체로 담담하게 서술하세요.
평가나 조언 없이 기록하듯 쓰고, 구체적인 키워드나 활동을 최소 2개 포함하세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}""",

    # variant B: 키워드 중심 압축 서술
    """다음 데이터를 바탕으로 어제 하루를 3~4문장(200~280자)으로 회고해주세요.
하루를 관통한 키워드 2~3개를 중심으로, 무엇에 시간을 쏟았는지를 "~에 빠져 있었다", "~를 붙잡고 있었다" 같은 표현으로 서술하세요.
마지막 문장은 하루 전체를 한 단어로 압축하며 마무리하세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}""",

    # variant C: 감각 중심 묘사
    """다음 데이터를 바탕으로 어제 하루를 3~4문장(200~280자)으로 회고해주세요.
청각(음악), 시각(영상/사진), 사고(관심사)의 세 감각을 각각 한 문장씩 담아 서술하세요.
"~를 들으며", "~를 보며", "~를 생각하며" 같은 연결어를 활용해 자연스럽게 이어주세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood} ({mood_detail})
어제 본 영상 카테고리: {yt_category}
어제 유튜브 시청 시간: {yt_time}
어제 들은 음악 무드: {music_mood}
어제의 장면: {photo_narrative}""",
]


def generate_reflection(analysis_result: dict, core_theme: str) -> str:
    """핵심 테마 + structured 데이터 + 무드로 200~300자 회고 생성."""
    structured = analysis_result.get("structured", {})
    mood_summary = analysis_result.get("mood_summary", {})
    photo_narrative = analysis_result.get("photo_narrative", "")

    youtube = structured.get("youtube", {})
    music = structured.get("music", {})

    # mood 상세 설명
    avg_valence = mood_summary.get("avg_valence")
    mood_name = mood_summary.get("mood", "알 수 없음")
    mood_ko = {"bright": "밝고 경쾌한", "calm": "고요하고 차분한"}.get(mood_name, mood_name)
    mood_detail = f"valence {avg_valence:.2f}" if avg_valence is not None else "수치 없음"

    yt_category = youtube.get("top_category") or "없음"
    yt_time = youtube.get("total_watch_time") or "없음"
    music_mood = music.get("rec_reason") or mood_ko

    prompt = random.choice(_REFLECTION_VARIANTS).format(
        core_theme=core_theme,
        mood=mood_ko,
        mood_detail=mood_detail,
        yt_category=yt_category,
        yt_time=yt_time,
        music_mood=music_mood,
        photo_narrative=photo_narrative or "없음",
    )
    return _call_llm(prompt) or "어제 하루의 기록을 불러오는 중입니다."


# ────────────────────────────────────────────────────────────────
# B-5. 기사 소개 텍스트
# ────────────────────────────────────────────────────────────────

# 기사 소개 프롬프트 변형 2가지 (A5 기준 기사당 150~200자)
_ARTICLE_VARIANTS = [
    # variant A: 큐레이터 어조 — 맥락 연결형
    """다음 추천 기사 각각에 대해 제목을 포함한 소개문을 작성하세요.
각 기사당 2~3문장(150~200자)으로, 사용자의 관심사와 어떻게 연결되는지를 먼저 짚은 뒤 기사 핵심 내용을 소개하세요.
어조는 친근하되 정보 밀도가 높아야 합니다. 각 기사 소개는 "●" 로 시작하세요.
마크다운 없이 순수 텍스트로 작성하세요.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}""",

    # variant B: 편집장 어조 — 왜 지금 읽어야 하는가
    """다음 추천 기사 각각에 대해, '왜 지금 이 기사를 읽어야 하는가'를 중심으로 소개문을 작성하세요.
각 기사당 2~3문장(150~200자)으로, "지금 ~에 관심이 있다면", "~를 고민 중이라면" 같은 도입부로 시작하세요.
마지막 문장은 기사에서 얻을 수 있는 것을 구체적으로 언급하세요. 각 기사 소개는 "●" 로 시작하세요.
마크다운 없이 순수 텍스트로 작성하세요.

사용자의 핵심 관심사: {core_theme}
유튜브 시청 카테고리: {yt_category}
오늘의 키워드: {keywords}

추천 기사 목록:
{articles_text}""",
]


def generate_article_intros(
    articles: list[dict],
    core_theme: str,
    keywords: list[str],
    youtube_section: dict,
) -> str:
    """추천 기사 3개를 저널에 실을 맞춤형 큐레이션 문구로 가공."""
    if not articles:
        return "오늘의 추천 기사를 준비 중입니다."

    articles_text = "\n".join(
        f"{i+1}. [{a.get('title', '')}] {a.get('summary', '')[:250]}"
        for i, a in enumerate(articles[:3])
    )
    yt_category = youtube_section.get("top_category") or "없음"
    keywords_text = ", ".join(keywords[:8]) or "없음"

    prompt = random.choice(_ARTICLE_VARIANTS).format(
        core_theme=core_theme,
        yt_category=yt_category,
        keywords=keywords_text,
        articles_text=articles_text,
    )
    return _call_llm(prompt) or "오늘의 추천 기사를 준비 중입니다."


# ────────────────────────────────────────────────────────────────
# B-6. 음악 섹션 텍스트
# ────────────────────────────────────────────────────────────────

# 음악 섹션 프롬프트 변형 2가지
_MUSIC_VARIANTS = [
    # variant A: 어제 청취 중심 + 오늘 추천
    """다음 음악 데이터를 바탕으로 어제 청취 감상과 오늘 추천 이유를 자연스럽게 서술하세요.
총 3~4문장(150~200자)으로, 어제 들은 음악의 분위기를 먼저 묘사한 뒤 추천 곡 2개를 소개하세요.
추천 곡은 "●곡명 / 아티스트" 형식으로 포함하고, 각 곡에 한 줄 설명을 붙이세요.
마크다운 없이 순수 텍스트로 작성하세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}""",

    # variant B: 감정 여정 중심
    """다음 음악 데이터를 바탕으로, 어제 하루의 감정 여정을 음악으로 표현해주세요.
총 3~4문장(150~200자)으로, "어제의 사운드트랙은 ~였다" 식의 표현으로 시작한 뒤
오늘 추천 곡 2개를 "●곡명 / 아티스트 — 한 줄 설명" 형식으로 이어서 소개하세요.
마크다운 없이 순수 텍스트로 작성하세요.

어제 무드: {mood_ko}
어제 많이 들은 곡: {yesterday_top}
추천 이유: {rec_reason}
추천 곡 1: {rec_1}
추천 곡 2: {rec_2}""",
]


def generate_music_section(music_data: dict, mood_summary: dict) -> str:
    """음악 섹션 텍스트 생성."""
    if not music_data.get("_available"):
        return "어제 Spotify 청취 기록이 없어 음악 추천을 건너뜁니다."

    mood_name = mood_summary.get("mood", "")
    mood_ko = {"bright": "밝고 경쾌한", "calm": "고요하고 차분한"}.get(mood_name, "알 수 없음")

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

    prompt = random.choice(_MUSIC_VARIANTS).format(
        mood_ko=mood_ko,
        yesterday_top=yesterday_top,
        rec_reason=rec_reason,
        rec_1=rec_1,
        rec_2=rec_2,
    )
    return _call_llm(prompt) or f"어제 무드: {mood_ko}\n추천 곡: {rec_1}, {rec_2}"


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
        "reflection": "...",        # 어제 회고 (200~300자)
        "article_intros": "...",    # 추천 기사 소개 (기사당 150~200자)
        "recommended_articles": [], # 기사 원본 리스트 (링크 포함)
        "music_text": "...",        # 음악 섹션 서술 텍스트
        "music_tracks": {           # 추천 트랙 구조화 데이터
            "rec_track_1": {...},
            "rec_track_2": {...},
            "yesterday_top": [...],
        },
        "schedule": "...",          # 오늘 일정 텍스트
        "keywords": [...],          # 어제 관심 키워드
        "photo_narrative": "...",   # 어제의 한 장면 (있을 때만)
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
    daily_focus = generate_daily_focus(schedule, keywords)

    # B-4. 어제 회고
    reflection = generate_reflection(analysis_result, core_theme)

    # B-5. 기사 소개
    youtube_section = structured.get("youtube", {})
    recommended_articles = structured.get("recommended_articles") or \
                           analysis_result.get("recommended_articles", [])
    article_intros = generate_article_intros(
        recommended_articles, core_theme, keywords, youtube_section
    )

    # 음악 섹션
    music_data = structured.get("music", {})
    music_text = generate_music_section(music_data, mood_summary)

    sections = {
        "date": target_date.strftime("%Y년 %-m월 %-d일"),
        "daily_focus": daily_focus,
        "reflection": reflection,
        "photo_narrative": photo_narrative or "",
        "article_intros": article_intros,
        "recommended_articles": recommended_articles,
        "music_text": music_text,
        "schedule_text": schedule_text,
        "keywords": keywords,
        "structured": structured,
    }

    return compose_journal(sections)