// PaperBack Agent 백엔드에서 완성된 저널(추천 기사 포함)을 가져오는 API 레이어.
// 백엔드: GET /journal/{target_date}?user_id=... (또는 Authorization: Bearer <JWT>)
// 응답 필드: headline, reflection, article_intros, recommended_articles,
//           music_text, music_tracks, schedule, keywords, photo_narrative, ...
// (참고: repo README / backend/models/journal.py)

import { MOCK_JOURNAL_BY_DATE } from "./mockJournal";

const API_BASE = "https://paperback-agent.fly.dev";

// TODO: 로그인(Google OAuth) 붙으면 user_id 쿼리 대신
// Authorization: Bearer <JWT> 헤더 방식으로 교체.
// DB에서 확인된 실제 저널 행: user_id=3, target_date=2026-07-08.
const DEV_USER_ID = 3;

// 실제 백엔드 데이터가 준비될 때까지 화면 작업을 먼저 하기 위한 스위치.
// true면 실제 API를 호출하지 않고 mockJournal.js의 더미 데이터를 씀.
// 이제 DB에 실제 행(user_id=3, 2026-07-08)이 확인됐으니 false로 전환.
const USE_MOCK = false;

/**
 * @param {string} targetDate - "YYYY-MM-DD"
 * @returns {Promise<object|null>} 저널 데이터, 그 날짜에 아직 없으면 null
 */
export async function fetchJournal(targetDate) {
  if (USE_MOCK) {
    // 실제 네트워크 요청처럼 살짝 지연을 줘서 로딩 상태도 같이 테스트 가능하게 함.
    await new Promise((resolve) => setTimeout(resolve, 300));
    return MOCK_JOURNAL_BY_DATE[targetDate] ?? null;
  }

  const res = await fetch(
    `${API_BASE}/journal/${targetDate}?user_id=${DEV_USER_ID}`
  );

  if (res.status === 404) {
    return null; // 그 날짜엔 아직 생성된 저널이 없음
  }
  if (!res.ok) {
    throw new Error(`journal fetch failed: HTTP ${res.status}`);
  }
  return res.json();
}
