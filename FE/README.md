# PaperBack Agent — FE

PaperBack Agent 백엔드(`https://paperback-agent.fly.dev`)가 생성한 "저널"(그날의 헤드라인, 추천 기사, 음악, 키워드 등)을 신문 형태로 보여주는 프론트엔드입니다. React + Vite로 만들었고, 별도 상태관리 라이브러리 없이 컴포넌트 로컬 state만 씁니다.

---

## 1. 전체 구성

### 화면 흐름

```
MailboxCalendar (메인 화면)
  └─ 날짜 클릭
       └─ NewspaperPage (선택한 날짜의 저널)
            └─ "← 우편함으로" 클릭 시 다시 메인으로
```

- **MailboxCalendar**: 벽돌 배경 위에 빨간 우편함 캘린더. 오늘 이전(오늘 포함) 날짜에는 편지가 꽂힌 것으로 표시되고 클릭 가능. 아직 오지 않은 날짜는 흐리지 않고 클릭만 막아둠(비활성).
- **NewspaperPage**: 선택한 날짜를 `YYYY-MM-DD`로 변환해 백엔드에 저널을 요청하고, 응답을 신문 레이아웃에 꽂아 보여줌. A4 양면 인쇄를 염두에 두고 만들어서 앞면/뒷면 개념으로 나뉘어 있음.

### 데이터 흐름

```
NewspaperPage
  └─ fetchJournal(targetDate)  (src/api/journal.js)
       ├─ USE_MOCK = true  → mockJournal.js의 더미 데이터 반환
       └─ USE_MOCK = false → GET /journal/{date}?user_id=... 실제 API 호출
```

응답이 없으면(404) `null`을 반환하고, 화면은 각 섹션마다 준비된 placeholder 문구를 대신 보여줍니다.

### 신문 레이아웃 (NewspaperPage 내부)

**앞면**
- 마스트헤드: 신문 제목(클릭해서 수정 가능, localStorage에 저장됨), 날짜, 발행 번호
- 오늘의 한 줄: `headline` + `reflection`을 `#태그` 형태로 표시
- 2열: (왼쪽) 오늘의 일정 + 손으로 채우는 타임테이블 / 사이드 기사 1  ·  (오른쪽) 헤드라인 기사(대표 기사)

**뒷면** (`back-page`, 인쇄 시 강제로 다음 장에서 시작)
- 2열: (왼쪽) 사이드 기사 2  ·  (오른쪽) 관심 키워드 Top 5 + 하루다짐(손글씨용 빈 칸)
- 하단: 어제의 플레이리스트(음악 회고 + 탑트랙)

### 저널 필드 → 화면 매핑

| 저널 필드 | 화면 위치 | 비고 |
|---|---|---|
| `headline` | 오늘의 한 줄 | AI가 요약한 하루 코멘트 |
| `reflection` | 오늘의 한 줄 태그 | `/` 기준으로 나눠서 `#태그`로 표시 |
| `article_intros` | 헤드라인 기사 / 사이드 기사 1·2 | `is_main: true`인 항목이 헤드라인 |
| `keywords` | 관심 키워드 Top 5 | 상위 5개만 사용 |
| `schedule` | 오늘의 일정 | 줄바꿈/쉼표/가운뎃점 기준으로 나눠 불릿 목록화 |
| `music_text.yesterday_text` | 어제의 플레이리스트 | |
| `music_tracks.yesterday_top` | 어제의 플레이리스트 목록 | |
| `photo_narrative` | 헤드라인 기사 사진 캡션(대체용) | 현재 백엔드가 실제 사진 파일을 저장하지 않아 그라데이션 placeholder 사용 중 |
| `recommended_articles`, `music_tracks.rec_track_1/2` | (아직 미사용) | 추가로 화면에 넣을 수 있음 |

---

## 2. 파일별 설명

```
FE/
├── index.html            엔트리 HTML. #root에 React 앱을 마운트
├── package.json           의존성 및 스크립트 정의
├── pakage.json             과거 오타로 생긴 파일. 아무 데서도 안 쓰임 — 삭제해도 무방
├── vite.config.js          Vite 설정 (React 플러그인만 사용)
└── src/
    ├── index.jsx           React 진입점. App_realistic.jsx를 렌더링
    ├── App_realistic.jsx    화면 전체(메인 컴포넌트, 스타일 포함) — 아래 참고
    ├── style.css            전역 스타일 진입점(현재는 폰트 smoothing 정도만)
    └── api/
        ├── journal.js       백엔드 API 호출 함수 (fetchJournal)
        └── mockJournal.js   더미 저널 데이터 (API 연결 전/백엔드 데이터 없을 때 사용)
```

### `src/index.jsx`
React 18 `createRoot`로 `<App />`을 `#root`에 마운트하는 진입점.

### `src/App_realistic.jsx`
이 프로젝트의 거의 전부가 들어있는 파일입니다.
- `MailboxCalendar` — 메인 캘린더 화면 컴포넌트
- `NewspaperPage` — 날짜별 신문 화면 컴포넌트 (데이터 fetch, 필드 매핑, 레이아웃 전부 포함)
- `App` — 위 두 화면을 `selectedDate` state로 전환하는 루트 컴포넌트
- `css` (문자열 상수) — 전체 스타일. `<style>{css}</style>`로 주입. 인쇄용(`@media print`)·모바일용(`@media max-width`) 스타일도 이 안에 포함

### `src/api/journal.js`
```js
fetchJournal(targetDate: "YYYY-MM-DD") => Promise<저널 객체 | null>
```
- `USE_MOCK`: `true`면 `mockJournal.js`의 더미 데이터를, `false`면 실제 배포 서버(`https://paperback-agent.fly.dev/journal/{date}`)를 호출
- `DEV_USER_ID`: 로그인 기능이 아직 없어서 임시로 고정해 둔 유저 ID. 로그인 붙으면 `Authorization: Bearer <JWT>` 헤더 방식으로 바꿔야 함
- 404는 에러가 아니라 "그 날짜엔 저널이 아직 없음"으로 처리해 `null` 반환

### `src/api/mockJournal.js`
`2026-07-05` 날짜 하나에 대한 실제 저널 예시 데이터(백엔드 팀이 더미 데이터로 만들어본 결과물)가 들어있습니다. `USE_MOCK = true`일 때만 사용됨.

---

## 3. 로컬에서 실행하는 방법

```bash
cd FE
npm install
npm run dev
```

터미널에 뜨는 주소(보통 `http://localhost:5173`)를 브라우저로 열면 됩니다.

### 확인 포인트
- 우편함 캘린더에서 **오늘 이전 날짜**를 클릭해야 편지가 꽂혀 있고 열람도 가능합니다 (미래 날짜는 비활성화).
- 브라우저 개발자도구 Console에 `[journal] 2026-07-08 {...}` 같은 로그가 찍히면 데이터를 정상적으로 받아온 것입니다. `null`이 찍히면 그 날짜엔 아직 백엔드에 저장된 저널이 없다는 뜻입니다(에러 아님).
- 실제 API 대신 더미 데이터로 화면만 확인하고 싶으면 `src/api/journal.js`의 `USE_MOCK`을 `true`로 바꾸면 됩니다.
- 인쇄 미리보기는 `Cmd+P` → 미리보기로 확인할 수 있습니다. A4 기준, 앞면/뒷면 2페이지로 나뉘도록 만들어져 있습니다.

### 참고
- `pakage.json`은 초기 오타로 생긴 파일이라 무시해도 됩니다(`package.json`이 정식 파일).
- 로그인/인증은 아직 붙어있지 않습니다 (`journal.js`의 `DEV_USER_ID` 참고).
