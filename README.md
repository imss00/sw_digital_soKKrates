# PaperBack Agent

> 팀 소크크라테스 | 2026 AI·SW중심대학 디지털 경진대회 SW부문

---

## 배포된 API

| | URL |
|--|-----|
| **API 서버** | https://swdigitalsokkrates-production.up.railway.app |
| **Swagger 문서** | https://swdigitalsokkrates-production.up.railway.app/docs |
| **헬스체크** | https://swdigitalsokkrates-production.up.railway.app/health |

DB(Supabase), Redis(Upstash), 앱 서버(Railway) 모두 클라우드에 올라가 있습니다.  
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
keywords      : ← Phase 2에서 Claude가 채울 칸
embedding_json: ← Phase 2에서 OpenAI Embeddings가 채울 칸
cluster_id    : ← Phase 2에서 DBSCAN이 채울 칸
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

Railway 배포 서버에서 Celery Beat가 자동으로 실행 중입니다 (web + worker 단일 컨테이너).

| 태스크 | 시각 | 내용 |
|--------|------|------|
| `collect_daily` | 매일 00:30 KST | Calendar 수집 |
| `normalize_and_trigger` | 매일 01:00 KST | 수집 데이터 → unified_documents 정규화 → Phase 2 자동 트리거 |
| `collect_spotify_task` | 4시간마다 | Spotify 최근 재생 폴링 |

Chrome과 YouTube는 Extension이 실시간으로 서버에 push합니다.  
사진은 `POST /photos/upload`로 수동 업로드합니다.

---

## 테스트 사용자 추가 방법

팀원이 배포 서버에서 OAuth 로그인을 테스트하려면 앱 오너가 아래 두 곳에 이메일을 추가해야 합니다.

### Google
[Google Cloud Console](https://console.cloud.google.com) → API 및 서비스 → OAuth 동의 화면 → **테스트 사용자** → 이메일 추가

### Spotify
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → 앱 선택 → Settings → **User Management** → 이메일 추가  
(Development Mode 앱은 최대 25명까지 추가 가능)

---

## Phase 2-3 개발 가이드 (팀원용)

뼈대 코드가 `backend/analysis/`에 준비되어 있습니다. 함수 시그니처와 DB 연결은 완성되어 있고, 로직이 필요한 곳에 `TODO` 주석이 달려 있습니다. 그 위에 덮어쓰면 됩니다.

### 파일 구조

```
backend/analysis/
  embedder.py        ← 역할 A: OpenAI 임베딩 생성 + DB 저장
  clusterer.py       ← 역할 A: DBSCAN 클러스터링 + cluster_id 저장
  recommender.py     ← 역할 A: RSS 수집 + FAISS 유사도 검색 + Spotify 무드
  journal_composer.py← 역할 B: Claude 키워드/회고/포커스/기사소개/저널 편집

backend/tasks/
  analysis_tasks.py  ← Phase 2-3 Celery 태스크 (자정 정규화 완료 후 자동 실행)
```

### 실행 흐름

```
(자정) collection_tasks.normalize_and_trigger()
    → analysis_tasks.run_phase2(user_id, date)
        → embedder.embed_and_store()       # OpenAI 임베딩 → embedding_json 저장
        → clusterer.run_clustering()       # DBSCAN → cluster_id 저장
        → recommender.run_recommendation() # RSS + FAISS + Spotify 무드
        → journal_composer.run_journal_composition()  # Claude → 저널 텍스트
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

### FAISS 주의사항

Railway 배포 환경에서는 파일로 FAISS 인덱스를 저장하면 재배포 시 사라집니다.
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
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `OPENAI_API_KEY` | platform.openai.com |

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
2. Chrome Extension: `chrome://extensions` → 개발자 모드 → `chrome-extension/` 폴더 로드

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
Dockerfile        ← Railway 배포용 (Python 3.12)
railway.toml      ← Railway 빌드 설정
```
