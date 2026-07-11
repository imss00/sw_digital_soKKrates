# PaperBack Agent — DB 구조 & 프론트 연동 가이드

작성일: 2026-07-11 / 기준: `backend/models/*.py`, `backend/routers/*.py` 실제 코드
서버: `https://paperback-agent.fly.dev` (Swagger: `/docs`)
DB: PostgreSQL (Supabase, 10개 테이블)

---

## 1. 전체 구조 한눈에 보기

```
users (계정 1개)
  ├─ browsing_history   (크롬 검색기록)
  ├─ spotify_history    (음악 재생기록)
  ├─ calendar_events    (구글 캘린더)
  ├─ youtube_history    (유튜브 시청기록)
  ├─ notion_pages       (노션 페이지) ※ 자동수집 안 됨, 사실상 0건
  ├─ photos             (사진 EXIF)
  │
  │   ↓ 매일 새벽 1시, celery가 위 6개 소스를 정규화
  │
  ├─ unified_documents  (통합 문서 + 임베딩/클러스터링 결과)
  │
  │   ↓ Phase 2-3 (임베딩→클러스터링→추천→LLM 생성)
  │
  ├─ journals           ★ 프론트가 실제로 가져다 쓰는 최종 결과 테이블
  └─ journal_runs       (저널 생성 상태/실패 추적)
```

모든 소스 테이블은 `user_id` 컬럼(FK → `users.id`)으로 연결됩니다.
**프론트가 직접 볼 일이 있는 테이블은 사실상 `journals` 하나입니다.** 나머지는 백엔드 내부 파이프라인용입니다.

---

## 2. 테이블별 상세

### `users` — 계정
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | int, PK | |
| email | string, unique | |
| name | string | |
| wake_up_time | string | 기본 "07:00" |
| timezone | string | 기본 "Asia/Seoul" |
| spotify_/google_/notion_*_token | 암호화 저장 | OAuth 토큰, 프론트에서 직접 다룰 일 없음 |
| created_at, updated_at | datetime | |

### `browsing_history` — 크롬 검색기록
`url`, `domain`, `title`, `article_text`, `is_article`, `visited_at`, `time_spent_sec`, `visit_count`

### `spotify_history` — 음악 재생기록
`track_name`, `artist_name`, `album_name`, `played_at`, `duration_ms`, 무드값(`valence`, `energy`, `danceability`, `tempo` 등), `genres`(배열)

### `calendar_events` — 구글 캘린더
`summary`, `description`, `start_time`, `end_time`, `duration_min`, `location`, `is_recurring`, `attendee_count`

### `youtube_history` — 유튜브 시청기록
`video_id`, `title`, `description`, `channel_name`, `tags`(배열), `duration_sec`, `watched_at`, `source`("takeout" 또는 "extension")

### `notion_pages` — 노션
`title`, `content_text`, `last_edited`
> ⚠️ 자동 수집 경로가 구현되어 있지 않음. 실제 데이터 없음(0건). 프론트에서 "노션 연동" 기능을 노출하면 안 됨.

### `photos` — 사진
`file_path`, `taken_at`, `latitude`/`longitude`(위치정밀도 완화됨), `camera_model`, `vision_labels`, `vision_narrative`
> `vision_labels`에는 Google Vision OCR 텍스트와 `LABEL_DETECTION` 장면 라벨이 JSON으로 저장됩니다. 새 업로드는 자동 라벨링되고, 기존 사진은 `scripts/backfill_photo_labels.py`로 백필합니다.

### `unified_documents` — 정규화된 통합 문서 (백엔드 내부용)
`source`(어느 원본 테이블인지), `content_text`, `title`, `occurred_at`, `mood_valence/energy`, `keywords`(배열), `embedding_json`, `cluster_id`, `is_processed`

### `journals` — ★ 완성된 저널 (프론트가 실제로 쓰는 테이블)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | int, PK | |
| user_id | int, FK | |
| target_date | date | 저널이 다루는 날짜 (기준: **어제**) |
| date_label | string | "2026년 7월 8일" — 화면 표시용 |
| headline | text | 오늘의 헤드라인 |
| reflection | text | 회고/한 줄 코멘트 |
| article_intros | JSON | 추천 아티클 인트로 |
| recommended_articles | JSON | 추천 아티클 목록 |
| music_text | JSON | 음악 섹션 텍스트 |
| music_tracks | JSON | 음악 트랙 목록 |
| schedule | text | 오늘 일정 요약 |
| keywords | 배열 | 관심 키워드 |
| photo_narrative | text | 사진 라벨이 있으면 "어제의 한 장면" 서사 |
| prompt_variants | JSON | 내부 로깅용, 화면에 안 씀 |
| created_at, updated_at | datetime | |

`(user_id, target_date)` 조합이 unique → 같은 날짜로 재생성해도 새 행이 안 쌓이고 덮어씀.

### `journal_runs` — 저널 생성 상태
`user_id`, `target_date`, `status`(`queued`/`running`/`succeeded`/`failed`/`skipped`), `stage`, `celery_task_id`, `error`, `journal_id`, `queued_at`, `started_at`, `finished_at`, `updated_at`

Phase 2-3가 실패했을 때 Celery 로그 없이도 어느 사용자/날짜/단계에서 실패했는지 확인하기 위한 운영 테이블입니다.

---

## 3. 프론트에서 쓸 API

### 인증
- 로그인은 OAuth (Google/Spotify) 콜백에서 서버가 JWT 발급 → 이후 요청에 `Authorization: Bearer <token>` 헤더로 전달
- 저널/사진 조회는 JWT가 필요합니다. `?user_id=`만으로 조회하는 개발 폴백은 현재 라우터에서 허용하지 않습니다.

### 저널 조회 — `GET /journal/{target_date}`
- `target_date`: `YYYY-MM-DD`
- 헤더: `Authorization: Bearer <JWT>`
- 200: `journals` 테이블 컬럼과 거의 1:1인 JSON (필드명은 위 표 그대로, `date_label`은 응답에서 `"date"` 키로 나감)
- 404: 아직 해당 날짜 저널이 생성 안 됨

### 저널 생성 트리거 (시연/테스트용) — `POST /webhook/generate-journal`
- 헤더: `X-Webhook-Secret` 필요
- 파라미터: `user_id`, `target_date`(생략 시 자동으로 "어제")
- 응답은 즉시 옴 (정규화만 동기 처리), 실제 저널 생성(임베딩~LLM)은 **비동기**라 몇 분 걸림
- 완료 여부는 `journal_runs` 테이블 또는 `GET /journal/{date}` 반복 조회로 확인 — 완료 전엔 계속 404

> 참고: 새벽 자동 스케줄(정규화 새벽 1시 → Phase 2-3)로도 매일 자동 생성되므로, 시연 때 굳이 수동 트리거 안 써도 전날 저널은 보통 존재함.

---

## 4. 프론트가 알아야 할 주의사항
1. `journals`는 하루에 한 번, **어제 날짜 기준**으로 생성됨 — "오늘" 날짜로 조회하면 대부분 404.
2. 노션 연동은 실제 자동 수집 경로가 없어 화면 노출 비권장. 사진 기반 서사(`photo_narrative`)는 Vision 라벨이 있는 사진에서만 생성됨.
3. 프린터 자동 출력은 별도 로컬 에이전트로 설계 중이며 API와 무관 (프론트 연동 범위 아님).
4. 운영 DB 직접 접근(Supabase) 권한은 프론트에 필요 없음 — 위 REST API로만 연동.
