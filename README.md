# PaperBack Agent

> 팀 소크크라테스 | 2026 AI·SW중심대학 디지털 경진대회 SW부문

---

## 배포된 API

| | URL |
|--|-----|
| **API 서버** | https://paperback-agent.fly.dev |
| **Swagger 문서** | https://paperback-agent.fly.dev/docs |
| **헬스체크** | https://paperback-agent.fly.dev/health |

DB(Supabase), Redis(Upstash), 앱 서버(Fly.io) 모두 클라우드에 올라가 있습니다.  
**Phase 2-3 팀원은 로컬 환경 세팅 없이 위 URL로 바로 API를 호출하면 됩니다.**

---

## 이게 뭘 하는 코드인가

사람이 하루 동안 남긴 디지털 흔적을 자동으로 수집해서, AI 분석이 가능한 형태로 정규화하는 파이프라인입니다.

```
[Chrome] [Spotify] [Google Calendar] [YouTube] [사진]
        ↓ 각각의 수집기 (collector)
        ↓ 정규화 (normalizer)
 unified_documents 테이블  ← Phase 2(추천 시스템)가 여기서 가져감
                           ← Phase 3(AI 기사 구성)도 여기서 가져감
```

---

## Phase 2-3 팀원이 알아야 할 것

### 데이터 가져오기

`unified_documents` 테이블에서 `is_processed = False`인 행을 가져가면 됩니다.

```python
from backend.database import SessionLocal
from backend.models.unified_document import UnifiedDocument

db = SessionLocal()
docs = db.query(UnifiedDocument).filter(
    UnifiedDocument.user_id == 1,
    UnifiedDocument.is_processed == False,
).all()
```

### unified_documents 컬럼 구조

```
source        : "chrome" | "spotify" | "calendar" | "youtube" | "photo"
content_text  : 분석 대상 텍스트 (최대 2000자)
occurred_at   : 활동 발생 시각
mood_valence  : 감정 밝기 (Spotify만, 나머지는 null)
mood_energy   : 감정 강도 (Spotify만)
keywords      : ← Phase 2에서 LLM이 채울 칸
embedding_json: ← Phase 2에서 OpenAI Embeddings가 채울 칸
cluster_id    : ← Phase 2에서 HDBSCAN이 채울 칸
is_processed  : 처리 완료 시 True로 업데이트
```

소스 종류는 몰라도 됩니다. `content_text`만 읽으면 분석 가능합니다.

### 처리 완료 후 저장

```python
doc.keywords = ["AI", "논문", "추천시스템"]
doc.embedding_json = embedding_vector.tolist()
doc.cluster_id = 2
doc.is_processed = True
db.commit()
```

### DB 직접 연결이 필요하다면

`.env.example`을 복사해서 `.env`로 만들고 `DATABASE_URL`(Supabase), `REDIS_URL`(Upstash) 두 개만 채우면 됩니다. 나머지 API 키는 담당 파트에 맞게 추가.

---

## 왜 unified_documents라는 테이블을 따로 만들었나

6개 소스는 구조가 전부 다릅니다. Spotify는 숫자(valence, energy), Calendar는 시작/종료 시각, Chrome은 URL과 본문 텍스트.

Phase 2가 소스별로 각각 처리하면 코드가 복잡해지고, 소스가 추가될 때마다 추천 로직을 고쳐야 합니다. **수집 → 정규화 → 분석**을 분리해서 Phase 2는 소스 종류를 신경 쓰지 않아도 됩니다.

---

## 수집기별 설계 포인트

### Chrome Extension
브라우저 히스토리는 서버에서 직접 접근이 불가능합니다. Chrome Extension을 만들어서:
- 1시간마다 방문 기록을 서버로 배치 전송
- `Readability.js`(Mozilla)로 기사 본문을 추출해서 같이 전송
- YouTube URL을 감지하면 별도 엔드포인트로 분리해서 youtube_history에 저장

### Spotify
Spotify API는 최근 50곡까지만 한 번에 가져올 수 있습니다. 4시간마다 폴링하면서 `spotify_last_cursor_ms`를 users 테이블에 저장해서 중복을 방지합니다.

`audio_features` API(valence, energy)는 신규 앱에서 막혀 있어 장르 기반 mood 추정(`GENRE_MOOD` 매핑)으로 대체 구현되어 있습니다. Spotify Extended Quota 승인 시 실제 수치로 자동 전환됩니다.

> **현재 상태**: 테스트 완료 ✅. 단, Spotify 앱이 Development Mode라 테스트 가능 계정을 앱 오너가 직접 추가해야 합니다 (아래 "테스트 사용자 추가" 참고).

### Google Calendar
어제 일정만 수집합니다. `duration_min`, `attendee_count`, `is_recurring`을 저장해서 "오늘은 미팅이 많은 날"이라는 맥락을 뽑을 수 있게 합니다.

### 사진 EXIF + 스크린샷 OCR
직접 업로드 방식입니다. `Pillow`로 GPS 좌표, 촬영 시각을 파싱합니다.

PNG이거나 EXIF가 없는 파일은 스크린샷으로 판단하여 Google Vision API `TEXT_DETECTION`으로 텍스트를 추출합니다.

> **사진 자동 sync (미구현)**: React Native 앱 개발 시점에 갤러리 백그라운드 sync 구현 예정.

### Notion
> **현재 상태**: Notion Public Integration OAuth는 Notion 측 심사가 필요합니다. 코드는 구현되어 있으나 현재 비활성화.

---

## 자동 수집 스케줄

Fly.io 배포 서버에서 Celery Beat가 자동으로 실행 중입니다 (web + worker 단일 컨테이너).

| 태스크 | 시각 | 내용 |
|--------|------|------|
| `collect_daily` | 매일 00:30 KST | Calendar 수집 |
| `normalize_and_trigger` | 매일 01:00 KST | 수집 데이터 → unified_documents 정규화 → Phase 2 자동 트리거 |
| `collect_spotify_task` | 4시간마다 | Spotify 최근 재생 폴링 |

Chrome과 YouTube는 Extension이 실시간으로 서버에 push합니다.  
사진은 `POST /photos/upload`로 수동 업로드합니다.

---

## Phase 2-3 개발 가이드 (팀원용)

뼈대 코드가 `backend/analysis/`에 준비되어 있습니다. 함수 시그니처와 DB 연결은 완성되어 있고, 로직이 필요한 곳에 `TODO` 주석이 달려 있습니다. 그 위에 덮어쓰면 됩니다.

### 파일 구조

```
backend/analysis/
  embedder.py        ← 역할 A: OpenAI 임베딩 생성 + DB 저장 ✅구현완료
  clusterer.py       ← 역할 A: HDBSCAN 클러스터링 + cluster_id 저장 ✅구현완료
  recommender.py     ← 역할 A: RSS 수집 + FAISS + HyDE + Spotify 무드 + core_theme + 구조화 JSON ✅구현완료
  journal_input.py   ← 역할 A: 최종 구조화 JSON 어셈블러 (역할 B 입력) ✅구현완료
  journal_composer.py← 역할 B: Gemini 키워드/회고/포커스/기사소개/저널 편집

backend/tasks/
  analysis_tasks.py  ← Phase 2-3 Celery 태스크 (자정 정규화 완료 후 자동 실행)
```

### 실행 흐름

```
(자정) collection_tasks.normalize_and_trigger()
    → analysis_tasks.run_phase2(user_id, date)
        → embedder.embed_and_store()       # OpenAI 임베딩 → embedding_json 저장
        → clusterer.run_clustering()       # HDBSCAN → cluster_id 저장
        → recommender.run_recommendation() # RSS(한·영) + FAISS + HyDE + Spotify 무드
                                           #   + core_theme(OpenAI) + 구조화 JSON("structured")
        → journal_composer.run_journal_composition()  # Gemini → 저널 텍스트 (역할 B, 별도 마이그레이션 예정)
```

### 수동 테스트 방법

Swagger(`/docs`)에서 직접 호출하거나:

```bash
# 임베딩 + 클러스터링 + 저널 전체 파이프라인 수동 실행
POST /webhook/normalize?user_id=1   # 정규화 (Phase 1 → unified_documents)

# 그 다음 Python에서 직접:
from backend.tasks.analysis_tasks import run_phase2
run_phase2(user_id=1, target_date_str="2026-06-27")
```

### 역할 A 산출물 — 구조화 JSON (역할 B 입력 인터페이스)

`recommender.run_recommendation()`이 반환하는 dict는 역할 B(journal_composer)가 그대로 받습니다.
기존 키(`interest_clusters`/`recommended_articles`/`music_recommendation`/`mood_summary`)에 더해
역할 A가 다음을 채워 넘깁니다.

- **`core_theme`** (str) — 하루를 관통하는 핵심 테마 한 줄. 클러스터/문서 내용을 OpenAI(gpt-4o-mini)로 요약(실패 시 결정적 폴백). 역할 B의 회고·기사소개 재료.
- **`structured`** (dict) — 역할 A의 최종 구조화 JSON. `journal_input.assemble_journal_input()`이 조립.

```jsonc
{
  "date": "2026-06-27",
  "photo":    { "_available": false, ... },          // 장면 라벨(LABEL_DETECTION) 미수집 → 비움
  "youtube":  { "_available": true,  "youtube_keywords": [...], "top_category": "음악",
                "total_watch_time": "19시간 4분", ... },
  "music":    { "_available": true,  "yesterday_tracks": [{ "title","artist","count" }],
                "rec_track_1": { "title","artist","album","year","label" }, "rec_reason": "..." },
  "headline": { "top_category","music_genre","youtube_keyword","photo_keywords" },
  "recommended_articles": [ { "title","summary","link","relevance_score" } ]
}
```

**설계 원칙**
- **3단 폴백**: 구조화 원본값(YouTubeHistory/SpotifyHistory) → `content_text` 파싱 → placeholder.
- **날조 금지**: 데이터 근거 없으면 채우지 않고 각 섹션에 `_available`/`_source` 플래그를 달아 역할 B가 placeholder를 사실로 오해하지 않게 함.
- **Spotify 제약**: `audio_features`/`/recommendations`는 신규 앱에서 403. 무드는 장르 기반 추정(`GENRE_MOOD`), 추천곡 메타데이터(album/year/label)는 살아있는 **search + album 엔드포인트로 실값 조회**.
- **photo**: 현재 OCR(TEXT_DETECTION)만이라 장면 키워드 grounding 불가 → `_available:false`. (Phase 1에 LABEL_DETECTION 추가 시 해소)

### RSS 피드 (한·영 혼합)

한국인 사용자에 맞춰 한국 언론사 RSS를 추가했습니다 (`recommender.RSS_FEEDS`).
- **한국 종합**: 연합뉴스 · 경향신문 · 동아일보
- **한국 IT**: 전자신문 · IT동아
- **글로벌**: NYT Technology · The Verge

> 네이버 뉴스는 공식 RSS를 제공하지 않습니다(서비스 종료). 네이버 소스가 필요하면 네이버 검색 API(Client ID/Secret) 연동이 별도로 필요합니다.
> 일부 매체(The Verge 등)는 기본 UA를 차단하므로 수집기에 브라우저 User-Agent 헤더를 사용합니다.

### FAISS 주의사항

Fly.io 배포 환경에서는 파일로 FAISS 인덱스를 저장하면 재배포 시 사라집니다.
`recommender.py`는 **인메모리** 방식으로 설계되어 있습니다 (호출마다 당일 벡터로 재구성).
주간 누적이 필요하면 벡터를 DB에 쌓고 부팅 시 로드하는 방식으로 확장하세요.

---

## 로컬 실행 방법 (개발용)

### 1. 환경변수 설정
```bash
cp .env.example .env
# .env 파일을 열어서 항목 채우기
```

| 변수 | 발급처 |
|------|--------|
| `DATABASE_URL` | Supabase → Project Settings → Database (Transaction Pooler, 포트 6543) |
| `REDIS_URL` | Upstash → Database → Connect (`rediss://` 형식) |
| `GOOGLE_CLIENT_ID/SECRET` | console.cloud.google.com |
| `GOOGLE_API_KEY` | console.cloud.google.com (YouTube Data API v3) |
| `OPENAI_API_KEY` | platform.openai.com (**역할 A 임베딩+생성**. text-embedding-3-small · gpt-4o-mini) |
| `GEMINI_API_KEY` | aistudio.google.com (역할 B journal_composer 저널 생성용. 정지/한도 이슈로 마이그레이션 예정) |
| `ANTHROPIC_API_KEY` | console.anthropic.com (현재 미사용) |

> **LLM provider 구성 (2026-07 기준)**
> - **역할 A**(임베딩 + core_theme·HyDE 생성): **OpenAI로 통일** → `OPENAI_API_KEY` 하나면 됨. 유료라 무료한도·정지 이슈 없음, 비용은 하루 몇 번 호출 기준 월 몇 백 원.
>   - 임베딩: `text-embedding-3-small` (1536차원). 서버에 모델을 안 올리고 API 호출만 → Fly.io 256MB에도 부담 없음.
>   - 생성: `gpt-4o-mini` (`recommender.GEN_MODEL` 문자열만 바꾸면 다른 모델로 교체 가능).
> - **역할 B**(journal_composer): 아직 Gemini. 무료 한도/정지 이슈로 팀 별도 마이그레이션 예정.
> - ⚠️ 임베딩 provider가 바뀌면 벡터 차원도 바뀝니다(Gemini→OpenAI 1536). **과거 다른 provider로 임베딩된 데이터와 섞으면 차원 불일치**가 나니, 새로 테스트할 땐 해당 날짜 `embedding_json`을 비우고(재임베딩) 돌리세요.

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. 서버 실행
```bash
uvicorn backend.main:app --reload
```

### 4. Google OAuth 연동
1. `GET /auth/google` → 반환된 URL 브라우저에서 열기 → Google 로그인

### 5. Chrome Extension 설치

1. Chrome 주소창에 `chrome://extensions` 입력
2. 오른쪽 상단 **개발자 모드** 토글 켜기
3. **압축 해제된 확장 프로그램 로드** 클릭
4. 이 저장소의 `chrome-extension/` 폴더 선택
5. 브라우저 우측 상단에 PaperBack 아이콘이 생김

**로그인 방법**

1. PaperBack 아이콘 클릭 → 팝업 열기
2. **"Google로 로그인"** 버튼 클릭
3. 구글 계정 선택 → 권한 허용
4. "로그인 완료" 탭이 자동으로 닫히면 완료

로그인 후에는 별도 설정 없이 자동으로 작동합니다.
- 1시간마다 브라우징 기록 + 기사 본문 수집
- YouTube 시청 기록 실시간 감지
- 팝업의 **"지금 전송하기"** 버튼으로 즉시 전송 가능

---

## 프로젝트 구조

```
backend/
  models/         ← DB 테이블 정의
  collectors/     ← 소스별 수집 로직
  normalizer/     ← 6개 소스 → unified_documents 변환
  routers/        ← FastAPI 엔드포인트
  tasks/          ← Celery 스케줄러
chrome-extension/ ← 브라우저 히스토리 수집기
Dockerfile        ← 배포용 (Python 3.12)
fly.toml          ← Fly.io 배포 설정
railway.toml      ← Railway 빌드 설정 (미사용)
```
