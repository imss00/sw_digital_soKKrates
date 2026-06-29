"""
역할 B — B-1~B-6. AI 저널 구성 (Gemini 통합 버전 🚀)
Gemini API로 키워드 추출 / 회고 / 포커스 / 기사 소개 / 최종 저널 편집.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from google import genai
from sqlalchemy.orm import Session

from backend.models.unified_document import UnifiedDocument
from backend.models.calendar_event import CalendarEvent

KST = timezone(timedelta(hours=9))
LLM_MODEL = "gemini-2.5-flash"

# Anthropic 대신 Google GenAI 클라이언트 사용
client = genai.Client()


# ── B-1. 키워드 추출 ───────────────────────────────────────────

def extract_keywords(user_id: int, target_date: date, db: Session) -> list[str]:
    """
    하루치 unified_documents를 Gemini에 보내 핵심 관심 키워드 10~15개 추출.
    추출된 키워드를 각 문서의 keywords 컬럼에도 저장.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=KST)
    day_end = day_start + timedelta(days=1)

    docs = (
        db.query(UnifiedDocument)
        .filter(
            UnifiedDocument.user_id == user_id,
            UnifiedDocument.occurred_at >= day_start,
            UnifiedDocument.occurred_at < day_end,
        )
        .all()
    )

    if not docs:
        return []

    doc_text = "\n".join(
        f"- [{d.source}] {getattr(d, 'title', '') or ''}: {d.content_text[:200]}"
        for d in docs
    )

    prompt = f"""다음은 사용자의 하루 디지털 활동 기록입니다.
핵심 관심 키워드를 10~15개 추출하세요.
너무 일반적인 단어(인터넷, 검색, 영상 등)는 제외하고 구체적인 관심사를 반영하세요.
마크다운 없이 오직 JSON 배열로만 반환하세요. 예: ["AI 에이전트", "러닝", "파이썬"]

활동 기록:
{doc_text}"""

    response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
    
    # Gemini가 마크다운(```json)을 붙여줄 경우를 대비한 안전한 파싱
    raw_text = response.text.strip()
    raw_text = re.sub(r'^```json\n|\n```$', '', raw_text).strip()
    
    try:
        keywords = json.loads(raw_text)
    except json.JSONDecodeError:
        keywords = ["키워드 추출 실패"] # 에러 방지용

    # unified_documents에 키워드 저장
    for doc in docs:
        doc.keywords = keywords
        doc.is_processed = True
    db.commit()

    return keywords


# ── B-2. 사진 서사 생성 ────────────────────────────────────────

def generate_photo_narrative(photo_labels: list[dict]) -> str | None:
    """
    사진 분석 결과(라벨, 위치, 시각)를 받아 '어제의 한 장면' 한 문장 생성.
    """
    if not photo_labels:
        return None

    labels_text = "\n".join(
        f"- 사진 {i+1}: {', '.join(p.get('labels', []))}, "
        f"위치: {p.get('location', '알 수 없음')}, 시각: {p.get('taken_at', '')}"
        for i, p in enumerate(photo_labels)
    )

    prompt = f"""다음은 사용자가 어제 촬영한 사진 분석 결과입니다.
이 사진들을 종합하여 "어제의 한 장면"을 따뜻하고 짧은 한 문장으로 표현하세요.
관찰자 시점으로, "~했다" 체로 작성하세요.

사진 분석:
{labels_text}"""

    response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
    return response.text.strip()


# ── B-3. 오늘의 포커스 ────────────────────────────────────────

def generate_daily_focus(schedule: list[dict], keywords: list[str]) -> str:
    """캘린더 일정 + 관심사 키워드로 오늘 집중할 한 줄 제안."""
    schedule_text = "\n".join(f"- {s.get('time', '')}: {s.get('title', '')}" for s in schedule)
    interest_text = ", ".join(keywords[:8])

    prompt = f"""오늘 일정과 최근 관심사를 바탕으로 오늘 하루의 포커스를 한 줄로 제안하세요.
구체적이고 실행 가능한 문장으로 작성하세요.

오늘 일정:
{schedule_text if schedule_text else "일정 없음"}

최근 관심사: {interest_text}"""

    response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
    return response.text.strip()


# ── B-4. 어제 회고 ───────────────────────────────────────────

def generate_reflection(analysis_result: dict, core_theme: str) -> str:
    """핵심 테마 + 무드 + 사진 서사로 2~3문장 회고 생성."""
    mood = analysis_result.get("mood_summary", {})
    photo_narrative = analysis_result.get("photo_narrative", "")

    prompt = f"""다음 데이터를 바탕으로 사용자의 어제 하루를 2~3문장으로 회고해주세요.
담백하고 따뜻한 톤으로, 평가나 조언 없이 기록하듯 "~했다" 체로 작성하세요.

어제의 핵심 관심사: {core_theme}
감정/무드: {mood.get("mood", "알 수 없음")} (valence: {mood.get("avg_valence")})
어제의 장면: {photo_narrative or "없음"}"""

    response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
    return response.text.strip()


# ── B-5. 기사 소개 텍스트 ────────────────────────────────────

def generate_article_intros(articles: list[dict], core_theme: str) -> str:
    """추천 기사 3개를 저널에 실을 맞춤형 큐레이션 문구로 가공."""
    if not articles:
        return "오늘의 추천 기사를 준비 중입니다."

    articles_text = "\n".join(
        f"{i+1}. [{a['title']}] {a.get('summary', '')[:200]}"
        for i, a in enumerate(articles)
    )

    prompt = f"""다음 추천 기사 각각에 대해 한 줄 소개와 추천 이유를 간결하게 작성하세요.
사용자의 현재 핵심 관심사 맥락을 짚어주며 친근하고 격려하는 어조로 작성하세요.

사용자의 현재 핵심 관심사 테마: 
{core_theme}

추천 기사 목록:
{articles_text}"""

    response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
    return response.text.strip()


# ── B-6. 최종 저널 편집 ──────────────────────────────────────

def compose_journal(sections: dict) -> str:
    """모든 섹션을 하나의 저널 텍스트로 조합. Phase 4(프린터)에 그대로 전달."""
    date_str = sections.get("date", "")
    return f"""PaperBack
{date_str}

◆ 오늘의 포커스
{sections.get("daily_focus", "")}

◆ 어제 회고
{sections.get("reflection", "")}

◆ 오늘의 읽을거리
{sections.get("article_intros", "")}

◆ 오늘의 플레이리스트
{sections.get("music_recommendation", "")}

◆ 오늘의 일정
{sections.get("schedule_text", "")}

좋은 하루 보내세요.
"""


# ── 통합 저널 생성 진입점 ─────────────────────────────────────

def run_journal_composition(
    user_id: int,
    target_date: date,
    analysis_result: dict,
    db: Session,
) -> str:
    """
    역할 B 전체 파이프라인 진입점.
    recommender.run_recommendation()의 analysis_result를 받아 저널 텍스트 반환.
    """
    keywords = extract_keywords(user_id, target_date, db)

    # 3단계에서 넘겨받은 핵심 테마 가져오기 (HyDE 기반 요약)
    core_theme = analysis_result.get("core_theme", "특별한 관심사가 감지되지 않았습니다.")

    # 오늘 캘린더 일정 추출
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
        {"time": e.start_time.astimezone(KST).strftime("%H:%M"), "title": e.summary}
        for e in today_events
    ]

    # 사진 서사 및 내용 분석
    photo_narrative = generate_photo_narrative(
        analysis_result.get("photo_labels", [])
    )
    analysis_result["photo_narrative"] = photo_narrative

    # 🌟 우리의 필살기 적용: core_theme을 회고와 기사 소개에 주입!
    reflection = generate_reflection(analysis_result, core_theme)
    daily_focus = generate_daily_focus(schedule, keywords)
    article_intros = generate_article_intros(
        analysis_result.get("recommended_articles", []), core_theme
    )

    mood = analysis_result.get("music_recommendation", {})
    if isinstance(mood, dict):
        mood_name = mood.get("mood", "?")
        avg_val = mood.get("avg_valence", "?")
        try:
            avg_val_fmt = f"{float(avg_val):.2f}"
        except Exception:
            avg_val_fmt = str(avg_val)
        music_text = f"어제 무드: {mood_name} (valence {avg_val_fmt})\nTODO: Spotify 플레이리스트 링크"
    else:
        music_text = str(mood)

    schedule_text = "\n".join(f"{s['time']} {s['title']}" for s in schedule) or "일정 없음"

    sections = {
        "date": target_date.strftime("%Y년 %-m월 %-d일"),
        "daily_focus": daily_focus,
        "reflection": reflection,
        "photo_narrative": photo_narrative or "",
        "article_intros": article_intros,
        "music_recommendation": music_text,
        "schedule_text": schedule_text,
        "keywords": keywords,
    }

    return compose_journal(sections)
