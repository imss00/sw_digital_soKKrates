# PaperBack Agent — 데이터 수집 파트 (Phase 1)

> 팀 소크크라테스 | 2026 AI·SW중심대학 디지털 경진대회 SW부문

---

## 이게 뭘 하는 코드인가

사람이 하루 동안 남긴 디지털 흔적 6가지를 자동으로 수집해서, 추천 시스템이 분석하기 좋은 형태로 정규화하는 파이프라인입니다.

```
[Chrome] [Spotify] [Google Calendar] [YouTube] [Notion] [사진]
        ↓ 각각의 수집기 (collector)
        ↓ 정규화 (normalizer)
 unified_documents 테이블  ← Phase 2(추천 시스템)가 여기서 가져감
```

---

## 왜 이 6가지인가

사람의 하루를 재구성하려면 **"무엇에 관심을 뒀는가"** 와 **"어떤 상태였는가"** 가 필요합니다.

| 소스 | 알 수 있는 것 |
|------|-------------|
| Chrome 브라우징 | 어떤 주제에 시간을 썼는가 (기사 본문까지 추출) |
| Spotify | 그날 감정 상태 (valence, energy 수치로 측정 가능) |
| Google Calendar | 어떤 일정이 있었는가, 얼마나 바쁜 하루였는가 |
| YouTube | 무엇을 소비했는가 |
| Notion | 어떤 생각을 기록했는가 |
| 사진 EXIF | 어디서 무엇을 했는가 (GPS + 시각) |

---

## 왜 unified_documents라는 테이블을 따로 만들었나

6개 소스는 구조가 전부 다릅니다. Spotify는 숫자(valence, energy), Calendar는 시작/종료 시각, Chrome은 URL과 본문 텍스트.

Phase 2(추천·분석)가 6개 소스를 각각 따로 처리하면 코드가 복잡해지고, 나중에 소스가 추가될 때마다 추천 로직을 고쳐야 합니다.

그래서 **수집 → 정규화 → 분석**을 분리했습니다.

```
unified_documents 컬럼:
  source        : "chrome" | "spotify" | "calendar" | "youtube" | "notion" | "photo"
  content_text  : 분석 대상 텍스트 (최대 2000자, 소스마다 다르게 조합)
  occurred_at   : 활동 발생 시각
  mood_valence  : 감정 밝기 (Spotify만, 나머지는 null)
  mood_energy   : 감정 강도 (Spotify만)
  keywords      : Phase 2에서 Claude가 채울 칸
  embedding_json: Phase 2에서 OpenAI Embeddings가 채울 칸
  cluster_id    : Phase 2에서 DBSCAN이 채울 칸
```

Phase 2는 `is_processed = False`인 행만 가져가서 처리하면 됩니다. 소스가 뭔지는 몰라도 됩니다.

---

## 수집기별 설계 포인트

### Chrome Extension
브라우저 히스토리는 서버에서 직접 접근이 불가능합니다. Chrome Extension을 만들어서:
- 1시간마다 방문 기록을 서버로 배치 전송
- `Readability.js`(Mozilla)로 기사 본문을 추출해서 같이 전송 — URL 제목만 있는 것보다 훨씬 의미있는 정보
- YouTube URL을 감지하면 별도 엔드포인트로 분리해서 youtube_history에 저장

### Spotify
Spotify API는 최근 50곡까지만 한 번에 가져올 수 있습니다. 4시간마다 폴링하면서 `spotify_last_cursor_ms`(마지막 수집 시점의 Unix ms)를 users 테이블에 저장해서 중복을 방지합니다.

`audio_features` API로 valence(0=슬픔, 1=행복), energy 수치를 가져옵니다. 이게 나중에 감정 기반 추천의 핵심 신호가 됩니다.

### Google Calendar
어제 일정만 수집합니다. `duration_min`(일정 길이), `attendee_count`(참석자 수), `is_recurring`(반복 일정 여부)를 저장해서 나중에 "오늘은 미팅이 많은 날이었다"는 맥락을 뽑을 수 있게 합니다.

### Notion
최근 24시간 내 수정된 페이지를 수집합니다. 페이지 제목뿐 아니라 블록 내용까지 텍스트로 추출합니다. Notion API rate limit(3 req/sec)이 있어서 요청마다 0.35초 대기합니다.

### 사진 EXIF
직접 업로드 방식입니다. `Pillow`로 GPS 좌표, 촬영 시각, 카메라 모델을 파싱합니다. Phase 2에서 Google Vision API + Claude로 사진 속 장면을 서사로 변환할 예정입니다.

---

## 자동 수집 스케줄

`Celery Beat`가 백그라운드에서 실행합니다.

| 태스크 | 시각 | 내용 |
|--------|------|------|
| `collect_daily` | 매일 00:30 KST | Calendar, Notion, 사진 EXIF 수집 |
| `normalize_and_trigger` | 매일 01:00 KST | 수집된 데이터 → unified_documents 정규화 |
| `collect_spotify_task` | 4시간마다 | Spotify 최근 재생 폴링 |

Chrome 브라우징과 YouTube는 Extension이 실시간으로 서버에 push합니다.

---

## 실행 방법

### 1. 환경변수 설정
```bash
cp .env.example .env
# .env 파일을 열어서 아래 항목 채우기
```

| 변수 | 발급처 |
|------|--------|
| `DATABASE_URL` | Supabase → Project Settings → Database (Transaction Pooler, 포트 6543) |
| `REDIS_URL` | Upstash → Database → Connect (rediss:// 형식) |
| `SPOTIFY_CLIENT_ID/SECRET` | developer.spotify.com |
| `GOOGLE_CLIENT_ID/SECRET` | console.cloud.google.com |
| `NOTION_TOKEN` | notion.so/my-integrations |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `OPENAI_API_KEY` | platform.openai.com |

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. DB 테이블 생성
```bash
alembic upgrade head
```

### 4. 서버 실행
```bash
uvicorn backend.main:app --reload
```

### 5. 연동 순서
1. `GET /auth/spotify` → 반환된 URL 브라우저에서 열기 → Spotify 로그인
2. `GET /auth/google` → 반환된 URL 브라우저에서 열기 → Google 로그인
3. Notion은 `.env`의 `NOTION_TOKEN`에 직접 입력
4. Chrome Extension: `chrome://extensions` → 개발자 모드 → `chrome-extension/` 폴더 로드

### 6. 수동 수집 테스트 (디버깅용)
```bash
POST /webhook/collect/spotify
POST /webhook/collect/calendar
POST /webhook/collect/notion
POST /webhook/normalize
```

---

## 프로젝트 구조

```
backend/
  models/         ← DB 테이블 정의 (8개)
  collectors/     ← 소스별 수집 로직
  normalizer/     ← 6개 소스 → unified_documents 변환
  routers/        ← FastAPI 엔드포인트
  tasks/          ← Celery 스케줄러
chrome-extension/ ← 브라우저 히스토리 수집기
```

---

## Phase 2로 넘어가는 인터페이스

Phase 2(추천·분석)는 `unified_documents` 테이블에서 `is_processed = False`인 행을 가져가면 됩니다.

```python
# Phase 2에서 이렇게 쓰면 됨
docs = db.query(UnifiedDocument).filter(
    UnifiedDocument.user_id == user_id,
    UnifiedDocument.is_processed == False,
).all()
```

분석 완료 후 `keywords`, `embedding_json`, `cluster_id`, `is_processed = True`를 채워서 저장하면 됩니다.
