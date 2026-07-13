// PaperBack Agent 백엔드에서 완성된 저널(추천 기사 포함)을 가져오는 API 레이어.
// 백엔드: GET /journal/{target_date}?user_id=... (또는 Authorization: Bearer <JWT>)
// 응답 필드: headline, reflection, article_intros, recommended_articles,
//           music_text, music_tracks, schedule, keywords, photo_narrative, ...
// (참고: repo README / backend/models/journal.py)

import { MOCK_JOURNAL_BY_DATE } from "./mockJournal";
import { getAuthHeaderIfReal } from "../auth";

const API_BASE = "https://paperback-agent.fly.dev";

// 구버전 journal_composer 프롬프트로 생성된 저널에는 LLM이 입력 라벨
// ("기사 제목: ...", "기사 요약: ...")을 소개문 맨 앞에 그대로 복사해 넣은 경우가
// 남아있다. 백엔드 Journal.to_dict()에도 같은 방어 로직이 있지만 배포가 안 되어
// 있을 수 있으니, 프론트에서 응답을 받는 즉시 한 번 더 방어적으로 제거한다.
const LABEL_PREFIX_RE = /^기사\s*제목\s*[:：]\s*/;
const SUMMARY_LABEL_RE = /^\s*기사\s*요약\s*[:：]\s*[^\n]*\n*/;

function stripLeakedLabel(text, title) {
  if (!text) return text;
  let result = text.trim();
  const m = result.match(LABEL_PREFIX_RE);
  if (m) {
    result = result.slice(m[0].length);
    if (title) {
      const t = title.trim();
      if (result.slice(0, t.length).toLowerCase() === t.toLowerCase()) {
        result = result.slice(t.length);
      }
    }
    result = result.replace(/^[\s"'“”·\-—]+/, "");
  }
  result = result.replace(SUMMARY_LABEL_RE, "");
  return result.trim();
}

function sanitizeJournal(journal) {
  if (!journal?.article_intros?.length) return journal;
  return {
    ...journal,
    article_intros: journal.article_intros.map((item) => ({
      ...item,
      intro: stripLeakedLabel(item.intro, item.title),
    })),
  };
}

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
    return sanitizeJournal(MOCK_JOURNAL_BY_DATE[targetDate] ?? null);
  }

  const authHeader = getAuthHeaderIfReal();
  const res = await fetch(`${API_BASE}/journal/${targetDate}`, { headers: authHeader ?? {} });

  if (res.status === 401) {
    return null;
  }
  if (res.status === 404) {
    return null; // 그 날짜엔 아직 생성된 저널이 없음
  }
  if (!res.ok) {
    throw new Error(`journal fetch failed: HTTP ${res.status}`);
  }
  return sanitizeJournal(await res.json());
}
