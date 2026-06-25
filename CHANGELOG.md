# PaperBack Agent - 개발 진행 기록

---

## 2026-06-26 (Day 2) - 환경 연결 + 버그 수정 + API 키 발급

### DB / Redis 연결

| 항목 | 내용 |
|------|------|
| Supabase IPv6 문제 해결 | Transaction Pooler URL(포트 6543)로 변경 → IPv4 지원, 무료 |
| Upstash Redis 연결 | `rediss://` (TLS) URL `.env` 반영 |
| 패키지 설치 | Python 3.13 호환 버전으로 `psycopg2-binary`, `faiss-cpu`, `numpy` 업데이트 |
| Alembic 마이그레이션 | `alembic upgrade head` → Supabase에 8개 테이블 생성 완료 |
| 서버 실행 확인 | `GET /health` → `{"status": "ok"}` |

### 치명적 버그 수정 (5개 파일)

| 버그 | 수정 내용 |
|------|----------|
| OAuth 콜백 토큰 미저장 | Spotify/Google 콜백에서 `/me`, `/userinfo` 호출 → email로 User 찾거나 생성 → 토큰 DB 저장 |
| 사용자 생성 로직 없음 | `_find_or_create_user()` 헬퍼 추가, OAuth 콜백에서 호출 |
| `db.merge()` 오용 | spotify/calendar/notion/youtube-detect 수집기 전부 존재 여부 확인 후 `db.add()` 로 교체 |
| 날짜 불일치 | `normalize_and_trigger`에서 `date.today()` → `date.today() - timedelta(days=1)` |
| Spotify audio_features 차단 | 신규 앱은 API 차단됨 → `GENRE_MOOD` 매핑 테이블로 장르 기반 valence/energy 추정 |

### 데이터 품질 개선

| 항목 | 내용 |
|------|------|
| Spotify content_text | 앨범명 추가 → `"트랙 - 아티스트. 앨범: XXX. 장르: YYY"` |
| YouTube 메타데이터 보강 | `youtube_enricher.py` 신규 작성. Takeout 업로드·Extension 감지 시 YouTube Data API v3로 description/tags/category/duration 자동 조회 (무료, 10,000건/일) |
| `GOOGLE_API_KEY` 추가 | config.py, .env, .env.example에 항목 추가 |

### GitHub

- `git init` + remote 추가 → 첫 커밋(46개 파일) → `main` 브랜치 push 완료
- README.md 작성 (Phase 1 설계 사상 + 실행 방법 + Phase 2 인터페이스)

### API 키 발급 현황

| 서비스 | 상태 |
|--------|------|
| Google (OAuth Client ID/Secret) | ✅ 발급 완료, `.env` 반영 |
| Google API Key (YouTube Data API v3) | ✅ 발급 완료, `.env` 반영 |
| Spotify (Client ID/Secret) | ✅ 발급 완료, `.env` 반영 |
| Notion Token | ⏳ 내일 진행 |
| Anthropic API Key | ⏳ Phase 2 때 |
| OpenAI API Key | ⏳ Phase 2 때 |

### 다음 할 일

- [ ] Notion Integration 토큰 발급
- [ ] Spotify OAuth 플로우 실제 테스트 (`GET /auth/spotify` → 브라우저 로그인)
- [ ] Google OAuth 플로우 테스트
- [ ] Chrome Extension 로드 + 브라우징 수집 확인
- [ ] `POST /webhook/normalize` 테스트 → unified_documents 확인

---

## 2026-06-24 (Day 0) - 3차: Chrome Extension 작성

### 생성된 파일 (6개)

| 파일 | 역할 |
|------|------|
| `chrome-extension/manifest.json` | MV3 매니페스트. permissions: history, activeTab, storage, alarms, tabs, unlimitedStorage |
| `chrome-extension/background.js` | Service Worker — 히스토리 수집(1시간마다) + 배치 전송 + 체류 시간 추적 + YouTube URL 감지 |
| `chrome-extension/content.js` | Content Script — Readability.js로 기사 본문 추출 (500자 이상만), background로 전달 |
| `chrome-extension/popup.html` | 팝업 UI — 연결 상태, 오늘 수집/전송 건수, 서버 URL 설정 |
| `chrome-extension/popup.js` | 팝업 로직 — 설정 저장, 연결 상태 확인, 수동 전송 버튼 |
| `chrome-extension/lib/Readability.js` | Mozilla Readability 라이브러리 (v0.5.0, 84KB) — CDN에서 다운로드 |

### 아이콘

| 파일 | 크기 |
|------|------|
| `chrome-extension/icons/icon16.png` | 16x16 placeholder (보라색 배경 + P) |
| `chrome-extension/icons/icon48.png` | 48x48 |
| `chrome-extension/icons/icon128.png` | 128x128 |

### 수정된 파일 (1개)

**`backend/routers/browsing.py`**

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | - | `POST /browsing/youtube-detect` 엔드포인트 | Chrome Extension이 감지한 YouTube URL을 youtube_history에 source='extension'으로 저장 |
| 추가 | visit_count 미수신 | `visit_count` 필드 추가 | BrowsingRecord 스키마에 visit_count 반영 |

### Chrome Extension 기능 상세

**background.js 핵심 기능:**
- `chrome.alarms`로 1시간마다 `collectAndSend` 실행 (setInterval 대신 — MV3 Service Worker 30초 제한 때문)
- `chrome.history.search()`로 마지막 수집 이후 방문 기록 최대 500건 수집
- 블랙리스트 도메인 필터링 (chrome://, 은행, Google 계정 등)
- 수집 데이터를 `chrome.storage.local`에 버퍼링 → 전송 실패 시 다음 사이클에서 재시도
- YouTube URL (`youtube.com/watch?v=`) 자동 감지 → 별도 배열로 분리하여 `/browsing/youtube-detect`로 전송
- 탭 포커스 추적 (`chrome.tabs.onActivated`, `chrome.windows.onFocusChanged`)으로 체류 시간 측정

**content.js 핵심 기능:**
- 모든 페이지에서 `document_idle` 시점에 Readability.js 실행
- 본문 500자 이상이면 기사로 판정, 최대 5000자 트렁케이션
- 검색 엔진, SNS 등은 스킵
- 추출 결과를 `chrome.runtime.sendMessage`로 background에 전달

### 설치 방법 (테스트용)
1. Chrome에서 `chrome://extensions` 접속
2. "개발자 모드" 활성화
3. "압축해제된 확장 프로그램을 로드합니다" 클릭
4. `chrome-extension/` 폴더 선택

---

## 2026-06-24 (Day 0) - 프로젝트 초기 세팅

### 1차: 프로젝트 구조 생성 + 전체 코드 작성

**생성된 파일 (35개)**

| 파일 | 역할 |
|------|------|
| `docker-compose.yml` | PostgreSQL 16 + Redis 7 컨테이너 정의 |
| `requirements.txt` | Python 패키지 전체 목록 |
| `.env` / `.env.example` | 환경변수 (API 키, DB URL 등) |
| `.gitignore` | git 제외 파일 목록 |
| `backend/main.py` | FastAPI 앱 (CORS + 라우터 5개 + /health) |
| `backend/config.py` | pydantic-settings 기반 설정 관리 |
| `backend/database.py` | SQLAlchemy 엔진 + 세션 + get_db() |
| `backend/models/user.py` | users 테이블 |
| `backend/models/browsing_history.py` | browsing_history 테이블 |
| `backend/models/spotify_history.py` | spotify_history 테이블 |
| `backend/models/calendar_event.py` | calendar_events 테이블 |
| `backend/models/youtube_history.py` | youtube_history 테이블 |
| `backend/models/notion_page.py` | notion_pages 테이블 |
| `backend/models/photo.py` | photos 테이블 |
| `backend/models/unified_document.py` | unified_documents 테이블 (Phase 2 인터페이스) |
| `backend/models/__init__.py` | 모델 전체 export |
| `backend/routers/auth.py` | Spotify/Google OAuth 인증 + 콜백 |
| `backend/routers/browsing.py` | Chrome Extension 배치 수신 (POST /browsing/batch) |
| `backend/routers/youtube.py` | Google Takeout JSON 업로드 + 파싱 |
| `backend/routers/photo.py` | 사진 다중 업로드 + EXIF 파싱 |
| `backend/routers/webhook.py` | 수동 트리거 (디버깅용) |
| `backend/collectors/spotify_collector.py` | Spotify 최근 50곡 + audio features + 장르 |
| `backend/collectors/calendar_collector.py` | 어제 Google Calendar 이벤트 수집 |
| `backend/collectors/notion_collector.py` | Notion 최근 수정 페이지 + 블록 텍스트 추출 |
| `backend/collectors/photo_processor.py` | Pillow EXIF 파싱 (GPS, 시간, 카메라) |
| `backend/normalizer/normalize.py` | 6개 소스 → unified_documents 정규화 |
| `backend/tasks/celery_app.py` | Celery 인스턴스 + beat 스케줄 3개 |
| `backend/tasks/collection_tasks.py` | 수집/정규화 Celery 태스크 |
| `backend/__init__.py` | - |
| `backend/routers/__init__.py` | - |
| `backend/schemas/__init__.py` | - |
| `backend/collectors/__init__.py` | - |
| `backend/normalizer/__init__.py` | - |
| `backend/tasks/__init__.py` | - |
| `backend/utils/__init__.py` | - |

---

### 2차: 스키마 점검 + 보완 수정

1차 코드를 전수 점검하여 **치명적 문제 3개 + 보완 필요 5개** 발견 후 수정.

#### 수정된 파일 (6개)

**1. `backend/models/user.py`**

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | - | `spotify_access_token` (Text) | API 호출에 access_token 필요 |
| 추가 | - | `spotify_token_expires_at` (DateTime) | 만료 시각 저장 → 자동 갱신 판단 |
| 추가 | - | `spotify_last_cursor_ms` (BigInteger) | 마지막 수집 시점 저장 → 4시간 폴링 시 중복 방지 |
| 추가 | - | `google_access_token` (Text) | Google API 호출용 |
| 추가 | - | `google_token_expires_at` (DateTime) | 만료 시각 |
| 추가 | - | `timezone` (String, default="Asia/Seoul") | 사용자 시간대 |

**2. `backend/models/browsing_history.py`**

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | - | `visit_count` (Integer, default=1) | Chrome history API 방문 횟수 반영 |
| 추가 | 인덱스 없음 | `INDEX(user_id, visited_at)` | "어제 데이터" 조회 성능 개선 |

**3. `backend/models/youtube_history.py`**

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | 유니크 제약 없음 | `UNIQUE(user_id, video_id, watched_at)` | Takeout 재업로드 시 중복 방지 |
| 추가 | 인덱스 없음 | `INDEX(user_id, watched_at)` | 날짜 조회 성능 |

**4. `backend/models/photo.py`**

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | - | `original_filename` (String) | 원본 파일명 보존 |
| 추가 | - | `width`, `height` (Integer) | 이미지 크기 정보 |
| 추가 | - | `vision_labels` (Text) | Phase 2 Google Vision API 라벨 저장용 |
| 추가 | - | `vision_narrative` (Text) | Phase 2 Claude "오늘의 장면" 서사 저장용 |
| 추가 | 인덱스 없음 | `INDEX(user_id, taken_at)` | 날짜 조회 성능 |

**5. `backend/models/unified_document.py`** (가장 중요한 수정)

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | 임베딩 컬럼 없음 | `embedding_json` (Text) | 1536차원 벡터를 JSON string으로 저장. pgvector 확장 없이도 동작 |
| 추가 | 처리 상태 없음 | `is_processed` (Boolean, default=False) | Phase 2가 "아직 분석 안 한 문서" 구별 가능 |
| 추가 | 중복 방지 없음 | `UNIQUE(user_id, source, source_id)` | normalize_daily 재실행 시 중복 삽입 방지 |

**6. `backend/collectors/spotify_collector.py`** (전면 재작성)

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | 토큰 갱신 없음 | `_refresh_spotify_token()` 함수 | access_token 만료 시 자동으로 refresh_token으로 재발급 |
| 수정 | `sp.current_user_recently_played(limit=50)` | `after=user.spotify_last_cursor_ms` 파라미터 추가 | 마지막 수집 이후 곡만 가져옴 |
| 추가 | 커서 저장 없음 | `user.spotify_last_cursor_ms = max_played_at_ms` | 다음 폴링에서 중복 방지 |

**7. `backend/normalizer/normalize.py`** (normalize_daily 함수 수정)

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | 바로 db.add() | 중복 체크 후 db.add() | `UNIQUE(user_id, source, source_id)` 위반 방지. 같은 source + source_id가 이미 있으면 스킵 |
| 추가 | - | `skipped_duplicate` 카운트 반환 | 결과에서 몇 건이 스킵됐는지 확인 가능 |

**8. `backend/routers/photo.py`** (수정)

| 변경 | 이전 | 이후 | 이유 |
|------|------|------|------|
| 추가 | - | `original_filename` 저장 | Photo 모델에 추가된 컬럼 반영 |
| 추가 | - | `width`, `height` 저장 (Pillow Image.size) | Photo 모델에 추가된 컬럼 반영 |
| 수정 | `taken_at=exif_data.get("taken_at", datetime.now())` | `taken_at=exif_data.get("taken_at") or datetime.now()` | EXIF 없을 때 현재 시각으로 폴백 |

---

## 아직 미완료

| 항목 | 상태 | 비고 |
|------|------|------|
| Docker 실행 + 테이블 생성 | 미실행 | `docker-compose up -d` + Alembic 필요 |
| Chrome Extension (JS) | 미작성 | MV3 + Readability.js |
| API 키 발급 | 미완료 | Spotify, Google, Notion, Anthropic, OpenAI |
| 실제 데이터 수집 테스트 | 미완료 | 각 수집기 수동 트리거 테스트 |
| 간편 입력 모드 (심사위원 데모) | 미작성 | quick_start 라우터 + 데모 모드 |
| Alembic 마이그레이션 설정 | 미완료 | alembic init + env.py 수정 |
| Git 초기화 + GitHub push | 보류 | 코드 더 작업 후 push 예정 |

---

## 현재 테이블 스키마 최종 정리

### users
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| email | VARCHAR(255) UNIQUE | 사용자 식별 |
| name | VARCHAR(100) | 표시명 |
| wake_up_time | VARCHAR(5) | 기상 시간 (저널 출력 시각 기준) |
| timezone | VARCHAR(50) | 시간대 (default: Asia/Seoul) |
| spotify_access_token | TEXT | Spotify API 호출용 |
| spotify_refresh_token | TEXT | 토큰 갱신용 |
| spotify_token_expires_at | TIMESTAMPTZ | 만료 시각 |
| spotify_last_cursor_ms | BIGINT | 폴링 커서 (중복 방지) |
| google_access_token | TEXT | Google API 호출용 |
| google_refresh_token | TEXT | 토큰 갱신용 |
| google_token_expires_at | TIMESTAMPTZ | 만료 시각 |
| notion_token | TEXT | Notion Internal Token |
| created_at / updated_at | TIMESTAMPTZ | 생성/수정 시각 |

### browsing_history
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| url | TEXT | 방문 URL |
| domain | VARCHAR(255) | 도메인 (카테고리 분류용) |
| title | TEXT | 페이지 제목 |
| article_text | TEXT | Readability.js 추출 기사 본문 (최대 5000자) |
| is_article | BOOLEAN | 기사 여부 |
| visited_at | TIMESTAMPTZ | 방문 시각 |
| time_spent_sec | INTEGER | 체류 시간 (추정) |
| visit_count | INTEGER | 방문 횟수 |
| **INDEX** | (user_id, visited_at) | 날짜 조회 성능 |

### spotify_history
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| spotify_track_id | VARCHAR(22) | 트랙 식별자 |
| track_name, artist_name, artist_id, album_name | TEXT/VARCHAR | 트랙 정보 |
| played_at | TIMESTAMPTZ | 재생 시각 |
| duration_ms | INTEGER | 곡 길이 |
| valence | FLOAT (0~1) | 밝기/행복도 (감정 분석 핵심) |
| energy | FLOAT (0~1) | 강렬도 |
| danceability, tempo, acousticness, instrumentalness | FLOAT | 오디오 특성 |
| genres | TEXT[] | 아티스트 장르 배열 |
| **UNIQUE** | (user_id, spotify_track_id, played_at) | 중복 방지 |

### calendar_events
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| google_event_id | VARCHAR(255) | Google 이벤트 ID |
| summary | TEXT | 일정 제목 (키워드 추출 소스) |
| description | TEXT | 일정 설명 |
| start_time, end_time | TIMESTAMPTZ | 시작/종료 |
| duration_min | INTEGER | 소요 시간 |
| location | TEXT | 장소 |
| is_recurring | BOOLEAN | 반복 일정 여부 |
| attendee_count | INTEGER | 참석자 수 |
| **UNIQUE** | (user_id, google_event_id) | 중복 방지 |

### youtube_history
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| video_id | VARCHAR(11) | YouTube 영상 ID |
| title, description | TEXT | 영상 정보 |
| channel_name, channel_id | VARCHAR | 채널 정보 |
| category_id | INTEGER | YouTube 카테고리 (10=음악, 22=블로그 등) |
| tags | TEXT[] | 영상 태그 |
| duration_sec | INTEGER | 영상 길이 |
| watched_at | TIMESTAMPTZ | 시청 시각 |
| source | VARCHAR(20) | takeout / extension |
| **UNIQUE** | (user_id, video_id, watched_at) | 중복 방지 |
| **INDEX** | (user_id, watched_at) | 날짜 조회 성능 |

### notion_pages
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| notion_page_id | VARCHAR(36) | Notion 페이지 ID |
| title | TEXT | 페이지 제목 |
| content_text | TEXT | 블록에서 추출한 전체 텍스트 |
| last_edited | TIMESTAMPTZ | 마지막 수정 시각 |
| **UNIQUE** | (user_id, notion_page_id) | 중복 방지 |

### photos
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| file_path | TEXT | 저장 경로 |
| original_filename | VARCHAR(255) | 원본 파일명 |
| taken_at | TIMESTAMPTZ | 촬영 시각 (EXIF) |
| latitude, longitude | FLOAT | GPS 좌표 (EXIF) |
| camera_model | TEXT | 카메라/폰 모델 |
| file_size | INTEGER | 파일 크기 |
| width, height | INTEGER | 이미지 크기 |
| vision_labels | TEXT | Phase 2: Vision API 라벨 (JSON) |
| vision_narrative | TEXT | Phase 2: Claude 서사 |
| **INDEX** | (user_id, taken_at) | 날짜 조회 성능 |

### unified_documents (Phase 2 인터페이스)
| 컬럼 | 타입 | 용도 |
|------|------|------|
| id | INTEGER PK | - |
| user_id | FK → users | - |
| source | VARCHAR(20) | chrome/spotify/calendar/youtube/notion/photo |
| source_id | INTEGER | 원본 테이블 id (역추적용) |
| content_text | TEXT NOT NULL | 분석 대상 텍스트 (최대 2000자) |
| content_type | VARCHAR(20) | article/music/event/video/note/photo |
| title | TEXT | 원본 제목 |
| occurred_at | TIMESTAMPTZ | 활동 발생 시각 |
| mood_valence | FLOAT (nullable) | 감정 밝기 (Spotify만) |
| mood_energy | FLOAT (nullable) | 감정 강도 (Spotify만) |
| keywords | TEXT[] | Phase 2: Claude 추출 키워드 |
| embedding_json | TEXT | Phase 2: 1536차원 벡터 (JSON string) |
| cluster_id | INTEGER | Phase 2: DBSCAN 클러스터 |
| is_processed | BOOLEAN (default false) | Phase 2: 분석 완료 여부 |
| **UNIQUE** | (user_id, source, source_id) | 정규화 중복 방지 |
| **INDEX** | (user_id, occurred_at) | 날짜 조회 성능 |
