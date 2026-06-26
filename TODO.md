# PaperBack Agent - TODO

## 즉시 해야 할 것 (DB 연결)

- [ ] Supabase IPv6 문제 해결 (팀원한테 IPv4 애드온 요청 or 대안 찾기)
- [ ] .env에 Upstash Redis URL 반영 (`rediss://default:****@concise-beetle-77370.upstash.io:6379`)
- [ ] DB 연결 성공 확인
- [ ] Alembic 설정 (`alembic init` → env.py 수정 → `alembic revision --autogenerate` → `alembic upgrade head`)
- [ ] 8개 테이블 생성 확인

## API 키 발급

- [ ] Spotify Developer Dashboard에서 앱 생성 → Client ID/Secret 발급
- [ ] Google Cloud Console에서 프로젝트 생성 → Calendar API + YouTube API 활성화 → OAuth 클라이언트 ID 생성
- [ ] Notion Integration 생성 → Internal Token 발급
- [ ] Anthropic API 키 발급 (Claude용)
- [ ] OpenAI API 키 발급 (Embeddings용)
- [ ] 모두 .env에 입력

## 테스트

- [ ] FastAPI 서버 실행 (`uvicorn backend.main:app --reload`)
- [ ] `GET /health` 응답 확인
- [ ] Spotify OAuth 플로우 테스트 (`GET /auth/spotify`)
- [ ] Google OAuth 플로우 테스트 (`GET /auth/google`)
- [ ] `POST /webhook/collect/spotify` 수동 트리거 → DB 확인
- [ ] `POST /webhook/collect/calendar` 수동 트리거 → DB 확인
- [ ] `POST /webhook/collect/notion` 수동 트리거 → DB 확인
- [ ] Chrome Extension 로드 (`chrome://extensions` → 개발자 모드 → 폴더 로드)
- [ ] 웹서핑 후 `POST /browsing/batch` 수신 확인
- [ ] 기사 페이지에서 Readability.js 본문 추출 확인
- [ ] `POST /webhook/normalize` 수동 트리거 → unified_documents 확인

## Git

- [ ] `paperback-agent/` 디렉토리에서 `git init`
- [ ] `.env`가 `.gitignore`에 포함되어 있는지 확인
- [ ] 첫 커밋
- [ ] GitHub remote 추가 (`imss00/sw_digital_soKKrates`)
- [ ] push

## 나중에 (배포 단계)

- [ ] Railway/Render 배포 (7/13~14)
- [ ] 심사위원용 데모 URL 확보
- [ ] 프론트엔드 팀과 간편 입력 모드 연동
