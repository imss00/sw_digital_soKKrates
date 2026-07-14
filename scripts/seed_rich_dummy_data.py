#!/usr/bin/env python3
"""
Insert or remove *realistic* dummy source data (Chrome/Spotify/Calendar/YouTube) for
a given user + date, then run the real normalizer so unified_documents gets populated
exactly like production would.

Unlike scripts/seed_dummy_unified_documents.py (which writes placeholder text straight
into unified_documents), this seeds the upstream tables so downstream logic that reads
SpotifyHistory/YouTubeHistory directly (mood analysis, journal_input 3-tier fallback)
also gets real-looking data.

Supports multiple named personas (see PERSONAS below) so different test users can carry
different interest profiles without overwriting each other.

Usage:
  Insert:  ai_env/Scripts/python.exe scripts/seed_rich_dummy_data.py --action insert --user 1 --date 2026-06-27 --persona dev
  Cleanup: ai_env/Scripts/python.exe scripts/seed_rich_dummy_data.py --action cleanup --user 1 --persona dev

  Create a new dummy user + seed in one go:
  ai_env/Scripts/python.exe scripts/seed_rich_dummy_data.py --action insert --persona student \
      --date 2026-07-05 --create-user --email dummy.student@paperback.local --name "더미 대학생"
"""
import argparse
from datetime import datetime, timedelta, timezone

from backend.database import SessionLocal
from backend.models.user import User
from backend.models.browsing_history import BrowsingHistory
from backend.models.spotify_history import SpotifyHistory
from backend.models.calendar_event import CalendarEvent
from backend.models.youtube_history import YouTubeHistory
from backend.models.unified_document import UnifiedDocument
from backend.normalizer.normalize import normalize_daily

KST = timezone(timedelta(hours=9))


# ── 페르소나별 콘텐츠 ────────────────────────────────────────────
# 각 페르소나는 (articles, tracks, events, videos) 튜플을 반환하는 함수.
# `at(hour, minute)`은 target_date 기준 KST 시각을 만드는 헬퍼.

def _persona_dev(at):
    articles = [
        {
            "url": "https://techcrunch.com/ai-agents-software",
            "domain": "techcrunch.com",
            "title": "AI 에이전트가 바꾸는 소프트웨어 개발",
            "article_text": (
                "최근 AI 에이전트가 코드 작성부터 배포까지 소프트웨어 개발 전 과정에 "
                "관여하는 사례가 늘고 있다. 개발자들은 반복 작업을 에이전트에 위임하고 "
                "설계와 리뷰에 집중하는 방향으로 워크플로우를 바꾸고 있다. 전문가들은 "
                "이런 흐름이 팀 구조와 코드 리뷰 문화에도 영향을 줄 것이라 전망한다."
            ),
            "is_article": True,
            "visited_at": at(9, 15),
        },
        {
            "url": "https://realpython.com/async-python-guide",
            "domain": "realpython.com",
            "title": "파이썬 비동기 프로그래밍 완벽 가이드",
            "article_text": (
                "asyncio를 활용하면 I/O 바운드 작업의 처리량을 크게 늘릴 수 있다. "
                "이 글은 코루틴, 이벤트 루프, async/await 문법을 예제와 함께 설명하고, "
                "실전에서 자주 겪는 데드락과 예외 처리 함정을 짚는다."
            ),
            "is_article": True,
            "visited_at": at(13, 40),
        },
        {
            "url": "https://velog.io/coding-test-strategy",
            "domain": "velog.io",
            "title": "알고리즘 코딩테스트 준비 전략",
            "article_text": (
                "코딩테스트를 준비할 때는 그래프, DP, 그리디 순으로 유형별 패턴을 "
                "익히는 것이 효율적이다. 이 글은 최근 채용 트렌드에서 자주 나오는 "
                "유형과 시간 배분 전략을 정리한다."
            ),
            "is_article": True,
            "visited_at": at(21, 10),
        },
    ]

    tracks = [
        ("Rainy Day Study", "Chillhop Cafe", "Study Sessions", ["lo-fi"], 0.32, 0.22),
        ("Late Night Coffee", "Chillhop Cafe", "Study Sessions", ["lo-fi", "jazz"], 0.38, 0.28),
        ("Blue in Green", "Miles Davis Trio Tribute", "Kind of Blue Sessions", ["jazz"], 0.41, 0.30),
        ("Quiet Focus", "Ambient Circle", "Deep Work", ["ambient", "lo-fi"], 0.29, 0.18),
        ("Slow Rain", "Chillhop Cafe", "Study Sessions", ["lo-fi"], 0.33, 0.20),
    ]

    events = [
        {
            "summary": "팀 미팅 - 스프린트 리뷰",
            "description": "지난 스프린트 진행 상황 공유 및 다음 스프린트 계획",
            "start_time": at(10, 0),
            "end_time": at(11, 0),
            "duration_min": 60,
            "location": "회의실 A",
            "is_recurring": True,
            "attendee_count": 5,
        },
        {
            "summary": "코드 리뷰",
            "description": "AI 에이전트 파이프라인 PR 리뷰",
            "start_time": at(14, 0),
            "end_time": at(14, 30),
            "duration_min": 30,
            "location": None,
            "is_recurring": False,
            "attendee_count": 2,
        },
    ]

    videos = [
        {
            "video_id": "dAIagent01",
            "title": "AI 에이전트 만들기 튜토리얼 (파이썬)",
            "description": "LLM 기반 자율 에이전트를 처음부터 구현해보는 실습 강의",
            "channel_name": "코딩애플",
            "category_id": 28,  # 과학기술
            "tags": ["AI", "에이전트", "파이썬", "튜토리얼", "LLM"],
            "duration_sec": 1320,
            "watched_at": at(11, 30),
        },
        {
            "video_id": "dAIagent02",
            "title": "알고리즘 코딩테스트 그래프 문제 풀이",
            "description": "다익스트라, BFS/DFS 실전 문제 풀이",
            "channel_name": "코딩애플",
            "category_id": 27,  # 교육
            "tags": ["알고리즘", "코딩테스트", "그래프"],
            "duration_sec": 1800,
            "watched_at": at(19, 20),
        },
        {
            "video_id": "dLofiMix01",
            "title": "공부할 때 듣는 로파이 힙합 playlist",
            "description": "집중력을 높여주는 lo-fi hip hop 모음",
            "channel_name": "Lofi Girl",
            "category_id": 10,  # 음악
            "tags": ["lofi", "study music", "chill"],
            "duration_sec": 3600,
            "watched_at": at(20, 5),
        },
    ]
    return articles, tracks, events, videos


def _persona_student(at):
    """20대 초반 대학생: 패션·여행·맛집·데이트 장소 + 경제/주식 관심, 한국 밴드 + J-pop 취향."""
    articles = [
        {
            "url": "https://instyle.co.kr/2026-summer-dailylook",
            "domain": "instyle.co.kr",
            "title": "2026 여름 데일리룩 꿀템 5가지",
            "article_text": (
                "크롭 티셔츠와 와이드 팬츠 조합이 올여름 대학가에서 가장 자주 보이는 "
                "룩으로 떠올랐다. 여기에 로퍼나 스니커즈를 매치하면 캐주얼하면서도 "
                "정돈된 인상을 줄 수 있다. 액세서리는 과감하게, 컬러는 절제하는 것이 "
                "요즘 데일리룩의 핵심 공식이다."
            ),
            "is_article": True,
            "visited_at": at(8, 50),
        },
        {
            "url": "https://brunch.co.kr/domestic-small-town-trip",
            "domain": "brunch.co.kr",
            "title": "혼자 떠나기 좋은 국내 소도시 여행지 5곳",
            "article_text": (
                "강릉, 통영, 전주처럼 반나절이면 걸어서 다 돌아볼 수 있는 소도시들이 "
                "다시 주목받고 있다. 대중교통만으로 이동이 편하고, 숙소와 식비 부담도 "
                "적어 짧은 일정의 대학생 여행객에게 특히 인기다."
            ),
            "is_article": True,
            "visited_at": at(12, 5),
        },
        {
            "url": "https://diningcode.com/seongsu-date-course",
            "domain": "diningcode.com",
            "title": "성수동 데이트 코스 맛집 리스트",
            "article_text": (
                "성수동은 브런치 카페부터 감성 파스타집, 루프탑 바까지 도보로 이동하며 "
                "데이트 코스를 짤 수 있는 몇 안 되는 동네다. 이 글은 웨이팅이 짧으면서도 "
                "분위기 좋은 매장 위주로 코스를 추천한다."
            ),
            "is_article": True,
            "visited_at": at(15, 30),
        },
        {
            "url": "https://hankyung.com/2030-growth-stocks-2026h2",
            "domain": "hankyung.com",
            "title": "2026년 하반기 유망 성장주 총정리 - 2030 투자자가 주목할 종목",
            "article_text": (
                "20대 투자자 비중이 늘면서 소액으로 접근 가능한 2차전지·AI 관련 성장주에 "
                "관심이 쏠리고 있다. 전문가들은 분산 투자와 장기 보유 관점을 강조하며, "
                "단기 테마주 추종은 지양할 것을 조언한다."
            ),
            "is_article": True,
            "visited_at": at(21, 40),
        },
        {
            "url": "https://travelmania.co.kr/seoul-date-spots",
            "domain": "travelmania.co.kr",
            "title": "연인과 가기 좋은 서울 감성 카페 & 데이트 명소",
            "article_text": (
                "한강뷰 루프탑 카페부터 조용한 골목 안 북카페까지, 계절마다 분위기가 "
                "달라지는 서울 데이트 스팟을 정리했다. 평일 낮 방문을 추천하는 곳 위주로 "
                "웨이팅 팁도 함께 담았다."
            ),
            "is_article": True,
            "visited_at": at(22, 15),
        },
    ]

    tracks = [
        ("주저하는 연인들을 위해", "잔나비", "전설", ["k-indie", "rock"], 0.68, 0.62),
        ("한 페이지가 될 수 있게", "DAY6", "The Book of Us : Gravity", ["k-rock", "band"], 0.72, 0.70),
        ("TOMBOY", "혁오", "24 : How to find true love and happiness", ["k-indie", "alternative"], 0.60, 0.58),
        ("기억을 걷는 시간", "넬", "Newton's Apple", ["k-rock", "alternative"], 0.55, 0.50),
        ("Lemon", "요네즈 켄시", "STRAY SHEEP", ["j-pop"], 0.50, 0.55),
        ("うっせぇわ", "Ado", "うっせぇわ", ["j-pop", "rock"], 0.65, 0.85),
    ]

    events = [
        {
            "summary": "성수동 맛집 투어 - 친구 약속",
            "description": "브런치 카페 + 파스타 맛집 코스",
            "start_time": at(12, 0),
            "end_time": at(14, 0),
            "duration_min": 120,
            "location": "성수동",
            "is_recurring": False,
            "attendee_count": 3,
        },
        {
            "summary": "조별과제 회의 - 마케팅 발표 준비",
            "description": "발표 자료 역할 분담 및 리허설",
            "start_time": at(15, 0),
            "end_time": at(16, 0),
            "duration_min": 60,
            "location": "학교 스터디룸",
            "is_recurring": True,
            "attendee_count": 5,
        },
        {
            "summary": "주식 스터디 모임",
            "description": "이번 주 성장주 이슈 정리 및 포트폴리오 점검",
            "start_time": at(19, 0),
            "end_time": at(20, 30),
            "duration_min": 90,
            "location": "스터디카페",
            "is_recurring": True,
            "attendee_count": 4,
        },
    ]

    videos = [
        {
            "video_id": "dFashHaul01",
            "title": "2026 SS 데일리룩 하울 & 코디 꿀팁",
            "description": "크롭탑, 와이드팬츠로 만드는 대학생 데일리룩 코디법",
            "channel_name": "스타일다이어리",
            "category_id": 26,  # 노하우/스타일
            "tags": ["패션", "하울", "코디", "데일리룩", "여대생룩"],
            "duration_sec": 900,
            "watched_at": at(9, 30),
        },
        {
            "video_id": "dTravelVlg1",
            "title": "국내 소도시 여행 브이로그 - 강릉 2박3일",
            "description": "강릉 바다, 카페거리, 로컬 맛집을 다녀온 여행 브이로그",
            "channel_name": "떠나요둘이",
            "category_id": 19,  # 여행/이벤트
            "tags": ["여행", "브이로그", "강릉", "국내여행"],
            "duration_sec": 780,
            "watched_at": at(13, 10),
        },
        {
            "video_id": "dFoodDate1",
            "title": "성수동 데이트 코스 맛집 탐방",
            "description": "웨이팅 짧은 성수동 브런치·파스타 맛집 리뷰",
            "channel_name": "먹어보고말해",
            "category_id": 26,  # 노하우/스타일
            "tags": ["맛집", "데이트", "성수동", "카페투어"],
            "duration_sec": 660,
            "watched_at": at(16, 20),
        },
        {
            "video_id": "dStockStdy1",
            "title": "주식 초보 탈출 - 2030 투자자를 위한 성장주 분석",
            "description": "PER, 성장률로 성장주 고르는 기본기 강의",
            "channel_name": "재테크알려주는언니",
            "category_id": 27,  # 교육
            "tags": ["주식", "투자", "경제공부", "재테크"],
            "duration_sec": 1080,
            "watched_at": at(20, 40),
        },
        {
            "video_id": "dAdoMV1",
            "title": "Ado - うっせぇわ Official MV",
            "description": "Ado 데뷔곡 うっせぇわ 공식 뮤직비디오",
            "channel_name": "Ado Official",
            "category_id": 10,  # 음악
            "tags": ["jpop", "Ado", "일본음악"],
            "duration_sec": 258,
            "watched_at": at(22, 30),
        },
    ]
    return articles, tracks, events, videos


PERSONAS = {
    "dev": _persona_dev,
    "student": _persona_student,
}


def marker_for(persona: str) -> str:
    return f"dummy-seed-{persona}"


def ensure_user(db, email: str, name: str) -> int:
    user = db.query(User).filter(User.email == email).first()
    if user:
        print(f"User already exists: id={user.id} email={email}")
        return user.id
    user = User(email=email, name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created user: id={user.id} email={email} name={name}")
    return user.id


def insert_dummy(user_id: int, target_date: str, persona: str):
    db = SessionLocal()
    day = datetime.fromisoformat(target_date).replace(tzinfo=KST)
    marker = marker_for(persona)

    def at(hour, minute=0):
        return day.replace(hour=hour, minute=minute)

    articles, tracks, events, videos = PERSONAS[persona](at)

    for a in articles:
        a = dict(a)
        a["url"] = f"{a['url']}?{marker}"
        db.add(BrowsingHistory(user_id=user_id, **a))

    for i, (track, artist, album, genres, valence, energy) in enumerate(tracks):
        db.add(SpotifyHistory(
            user_id=user_id,
            spotify_track_id=f"DUMMY{persona.upper()[:4]}{i:03d}",
            track_name=track,
            artist_name=artist,
            artist_id=f"DUMMY{persona.upper()[:4]}ART{i:03d}",
            album_name=album,
            played_at=at(20, 0) + timedelta(minutes=i * 8),
            duration_ms=210000,
            valence=valence,
            energy=energy,
            danceability=0.5,
            tempo=100.0,
            acousticness=0.5,
            instrumentalness=0.3,
            genres=genres,
        ))

    for i, e in enumerate(events):
        e = dict(e)
        e["google_event_id"] = f"{marker}-{i}"
        db.add(CalendarEvent(user_id=user_id, **e))

    for v in videos:
        v = dict(v)
        v["channel_id"] = f"{marker}-channel"
        db.add(YouTubeHistory(user_id=user_id, source="dummy_seed", **v))

    db.commit()
    print(
        f"Inserted ({persona}): {len(articles)} chrome articles, {len(tracks)} spotify tracks, "
        f"{len(events)} calendar events, {len(videos)} youtube videos"
    )

    target = datetime.fromisoformat(target_date).date()
    result = normalize_daily(user_id, target, db)
    print(f"normalize_daily result: {result}")


def cleanup_dummy(user_id: int, persona: str):
    db = SessionLocal()
    marker = marker_for(persona)

    browsing = db.query(BrowsingHistory).filter(
        BrowsingHistory.user_id == user_id,
        BrowsingHistory.url.like(f"%{marker}%"),
    ).all()
    spotify = db.query(SpotifyHistory).filter(
        SpotifyHistory.user_id == user_id,
        SpotifyHistory.spotify_track_id.like(f"DUMMY{persona.upper()[:4]}%"),
    ).all()
    calendar = db.query(CalendarEvent).filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.google_event_id.like(f"{marker}%"),
    ).all()
    youtube = db.query(YouTubeHistory).filter(
        YouTubeHistory.user_id == user_id,
        YouTubeHistory.channel_id.like(f"{marker}%"),
    ).all()

    browsing_ids = [r.id for r in browsing]
    spotify_ids = [r.id for r in spotify]
    calendar_ids = [r.id for r in calendar]
    youtube_ids = [r.id for r in youtube]

    unified = db.query(UnifiedDocument).filter(
        UnifiedDocument.user_id == user_id,
        (
            (UnifiedDocument.source == "chrome") & (UnifiedDocument.source_id.in_(browsing_ids or [-1]))
        ) | (
            (UnifiedDocument.source == "spotify") & (UnifiedDocument.source_id.in_(spotify_ids or [-1]))
        ) | (
            (UnifiedDocument.source == "calendar") & (UnifiedDocument.source_id.in_(calendar_ids or [-1]))
        ) | (
            (UnifiedDocument.source == "youtube") & (UnifiedDocument.source_id.in_(youtube_ids or [-1]))
        )
    ).all()

    counts = {
        "browsing_history": len(browsing),
        "spotify_history": len(spotify),
        "calendar_events": len(calendar),
        "youtube_history": len(youtube),
        "unified_documents": len(unified),
    }

    for r in unified:
        db.delete(r)
    for r in browsing:
        db.delete(r)
    for r in spotify:
        db.delete(r)
    for r in calendar:
        db.delete(r)
    for r in youtube:
        db.delete(r)

    db.commit()
    print(f"Removed ({persona}): {counts}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["insert", "cleanup"], required=True)
    p.add_argument("--user", type=int, default=None)
    p.add_argument("--date", type=str, default="2026-06-27")
    p.add_argument("--persona", type=str, default="dev", choices=list(PERSONAS.keys()))
    p.add_argument("--create-user", action="store_true", help="persona용 신규 유저를 생성/재사용")
    p.add_argument("--email", type=str, default=None)
    p.add_argument("--name", type=str, default=None)
    args = p.parse_args()

    user_id = args.user
    if args.create_user:
        if not args.email or not args.name:
            raise SystemExit("--create-user 사용 시 --email, --name이 필요합니다.")
        db = SessionLocal()
        user_id = ensure_user(db, args.email, args.name)
    elif user_id is None:
        user_id = 1

    if args.action == "insert":
        insert_dummy(user_id, args.date, args.persona)
    else:
        cleanup_dummy(user_id, args.persona)


if __name__ == "__main__":
    main()
