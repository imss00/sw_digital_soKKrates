# 보안/개인정보 처리 현황

2026-07-08 기준. PPT/기획안에 보안 관련 문구를 쓸 때 이 문서를 기준으로 삼을 것 — 실제 구현과 어긋나는 표현은 심사에서 코드 대조로 반박당할 수 있음.

## 구현된 것

### 1. OAuth 토큰 암호화 (at rest)
- `backend/utils/crypto.py`의 `EncryptedText` SQLAlchemy 컬럼 타입으로 Fernet(AES) 암호화.
- 대상: `users.spotify_access_token`, `spotify_refresh_token`, `google_access_token`, `google_refresh_token`, `notion_token`.
- 쓸 때 자동 암호화, 읽을 때 자동 복호화 — 애플리케이션 코드는 평문으로 다루지만 DB에는 암호문만 저장됨.
- 키는 `FERNET_KEY` 환경변수(`.env` / Fly secrets)로 관리. **DB가 통째로 유출되는 상황**(SQL 덤프, 백업 파일 탈취 등)에서 토큰 재사용을 막는 게 목적 — 앱 자체의 정상적인 토큰 사용(Spotify/Google API 호출)은 막지 않음, 막을 수도 없음(로그인 상태 유지에 토큰이 필요하므로).
- 기존에 평문으로 저장돼있던 토큰도 `scripts/encrypt_existing_tokens.py`로 백필 완료.

### 2. 정형(structured) PII 마스킹 — LLM 전송 전
- `backend/utils/pii_mask.py`의 `mask_pii()`로 이메일, 전화번호(010-xxxx-xxxx 등), 주민등록번호, 카드번호를 정규식으로 탐지해 `[EMAIL]`/`[PHONE]`/`[RRN]`/`[CARD]` 토큰으로 치환.
- 적용 시점: **정규화(normalize) 단계** — 원본 테이블(`browsing_history`, `calendar_events` 등)이 아니라, LLM(OpenAI 임베딩/저널 생성)에 실제로 들어가는 `unified_documents.content_text`를 만드는 시점에 적용.
  - 크롬/스포티파이/캘린더/유튜브/노션: 매일 밤 1시 `normalize_daily` celery task 실행 시.
  - 사진 스크린샷 OCR: `/photo/upload` 호출 즉시.
- 사진 EXIF GPS 좌표는 소수점 4자리(~11m 정밀도) → 2자리(~1.1km)로 낮춰서 정확한 자택/직장 위치가 드러나지 않게 함.
- 기존에 쌓여있던 `unified_documents` 727건도 `scripts/mask_existing_content.py`로 백필 완료(1건에서 실제 마스킹 발생 — 원 데이터 자체에 정형 PII가 거의 없었음).

### 3. Supabase RLS(Row-Level Security) 활성화
- 2026-07-06 Supabase가 보낸 "Table publicly accessible" 크리티컬 경고에 대응.
- 9개 public 테이블 전부 `ENABLE ROW LEVEL SECURITY` 적용(정책 없이 기본 전면 차단).
- 백엔드는 `postgres` 역할(`bypassrls=True`)로 직접 연결하므로 이 변경으로 인한 앱 동작 영향 없음. RLS가 막는 건 Supabase가 자동 노출하는 REST API(PostgREST, anon/service key로 접근하는 경로) — 우리 코드는 이 경로를 안 쓰지만, 꺼져 있으면 그 키를 아는 누구나(대시보드 접근 가능한 팀원 등) 접근 가능한 상태였음.

## 정직하게 써야 할 한계 (구현 안 됨 / 대회 범위에서 불가능)

### 1. 비정형(unstructured) PII는 마스킹 안 됨
- 캘린더 제목의 사람 이름("김철수와 회의"), 장소명처럼 문맥이 필요한 PII는 정규식으로 안전하게 잡을 수 없음.
- NER(개체명 인식) 모델(예: spaCy)이 필요한데, 무거운 의존성 추가 + 오탐/누락 리스크 + 정확도 검증에 시간이 필요해서 대회 일정(예선 7/15, 본선 7/20) 안에 안정적으로 구현·검증하기 어렵다고 판단해 범위에서 제외함.
- **PPT 문구**: "PII를 완벽히 배제" 같은 강한 표현 대신 "이메일·전화번호 등 정형 개인정보 마스킹 적용, 문맥 기반 비식별화는 확장 계획"으로 쓸 것.

### 2. 원본 테이블은 마스킹 안 됨
- `browsing_history`, `calendar_events`, `spotify_history`, `youtube_history` 등 원본 수집 테이블은 그대로 원문 저장됨(마스킹은 LLM에 나가는 사본에만 적용).
- "raw 데이터는 즉시 메모리에서 마스킹·휘발 처리"라는 표현은 여전히 사실이 아님 — raw 데이터는 Postgres에 영구 저장됨.

### 3. 이미 계산된 임베딩은 소급 안 됨
- 마스킹 적용 이전에 이미 OpenAI로 전송되어 계산된 임베딩 벡터(`embedding_json`)는, 지금 텍스트를 마스킹해도 "그때 원문이 전송된 사실" 자체를 되돌릴 수 없음.
- 재임베딩하지 않는 한 구조적으로 소급 불가능한 한계.

### 4. 삭제권/보존기한 정책 없음
- 사용자가 데이터 삭제를 요청했을 때 처리하는 API/플로우가 없음. 개인정보처리방침 상 "언제까지 보관"이라고 쓸 근거가 되는 자동 삭제/보존기한 로직도 없음.

## PPT 작성 시 권장 문구

> "OAuth 토큰은 Fernet(AES) 암호화 후 저장하며, LLM으로 전송되는 이벤트 데이터는 정규화 단계에서 이메일·전화번호 등 정형 개인정보를 마스킹 처리합니다. Supabase RLS를 적용해 데이터베이스 직접 노출 경로를 차단했습니다. 문맥 기반 비식별화(이름·장소 등)와 원본 데이터 자동 폐기는 향후 확장 과제입니다."
