// ============================================================
// PaperBack Agent - Background Service Worker
// 브라우징 히스토리 수집 + 배치 전송 + 체류 시간 추적
// ============================================================

const DEFAULT_API_URL = "https://swdigitalsokkrates-production.up.railway.app";
const COLLECT_INTERVAL_MINUTES = 60;

// 수집 제외 도메인
const BLACKLIST_DOMAINS = [
  "chrome://",
  "chrome-extension://",
  "about:",
  "edge://",
  "localhost",
  "accounts.google.com",
  "myaccount.google.com",
  "mail.google.com",
  "drive.google.com",
  "chrome.google.com/webstore",
  "banking",
  "bank",
];

// ---- 초기화 ----
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("collectAndSend", {
    delayInMinutes: 1,
    periodInMinutes: COLLECT_INTERVAL_MINUTES,
  });

  chrome.storage.local.set({
    lastCollectTime: Date.now() - 24 * 60 * 60 * 1000, // 24시간 전부터
    pendingRecords: [],
    articleBuffer: {},
    tabStartTimes: {},
    stats: { todayCollected: 0, todaySent: 0 },
  });

  console.log("[PaperBack] Extension installed, alarm set.");
});

// ---- 알람 리스너: 히스토리 수집 + 배치 전송 ----
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "collectAndSend") {
    await collectHistory();
    await sendBatch();
  }
});

// ---- 히스토리 수집 ----
async function collectHistory() {
  const data = await chrome.storage.local.get([
    "lastCollectTime",
    "pendingRecords",
    "articleBuffer",
    "tabStartTimes",
  ]);

  const lastCollectTime = data.lastCollectTime || Date.now() - 24 * 60 * 60 * 1000;
  const pendingRecords = data.pendingRecords || [];
  const articleBuffer = data.articleBuffer || {};
  const tabTimes = data.tabStartTimes || {};

  const historyItems = await chrome.history.search({
    text: "",
    startTime: lastCollectTime,
    maxResults: 500,
  });

  let newCount = 0;

  for (const item of historyItems) {
    if (shouldSkipUrl(item.url)) continue;

    const domain = extractDomain(item.url);
    const articleText = articleBuffer[item.url] || null;
    const timeSpent = tabTimes[item.url]
      ? Math.round(tabTimes[item.url] / 1000)
      : null;

    pendingRecords.push({
      url: item.url,
      domain: domain,
      title: item.title || "",
      article_text: articleText ? articleText.substring(0, 5000) : null,
      is_article: !!articleText,
      visited_at: new Date(item.lastVisitTime).toISOString(),
      time_spent_sec: timeSpent,
      visit_count: item.visitCount || 1,
    });

    newCount++;
  }

  // YouTube URL 감지 → 별도 분리
  const youtubeRecords = [];
  const nonYoutubeRecords = [];

  for (const record of pendingRecords) {
    if (record.url && record.url.includes("youtube.com/watch")) {
      youtubeRecords.push(record);
    } else {
      nonYoutubeRecords.push(record);
    }
  }

  await chrome.storage.local.set({
    lastCollectTime: Date.now(),
    pendingRecords: nonYoutubeRecords,
    youtubeRecords: youtubeRecords,
    articleBuffer: {},
    tabStartTimes: {},
  });

  // 통계 업데이트
  const stats = (await chrome.storage.local.get("stats")).stats || {};
  stats.todayCollected = (stats.todayCollected || 0) + newCount;
  await chrome.storage.local.set({ stats });

  console.log(`[PaperBack] Collected ${newCount} new history items.`);
}

// ---- 배치 전송 ----
async function sendBatch() {
  const { apiUrl: storedApiUrl, jwt } = await chrome.storage.local.get(["apiUrl", "jwt"]);
  const apiUrl = storedApiUrl || DEFAULT_API_URL;

  if (!jwt) {
    console.warn("[PaperBack] 로그인 필요 — 팝업에서 Google로 로그인해주세요.");
    return;
  }

  const data = await chrome.storage.local.get(["pendingRecords", "youtubeRecords"]);
  const pendingRecords = data.pendingRecords || [];
  const youtubeRecords = data.youtubeRecords || [];

  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${jwt}`,
  };

  // 브라우징 기록 전송
  if (pendingRecords.length > 0) {
    try {
      const response = await fetch(`${apiUrl}/browsing/batch`, {
        method: "POST",
        headers,
        body: JSON.stringify({ records: pendingRecords }),
      });

      if (response.ok) {
        const result = await response.json();
        console.log(`[PaperBack] Sent ${result.inserted} browsing records.`);
        await chrome.storage.local.set({ pendingRecords: [] });

        const stats = (await chrome.storage.local.get("stats")).stats || {};
        stats.todaySent = (stats.todaySent || 0) + result.inserted;
        await chrome.storage.local.set({ stats });
      } else if (response.status === 401) {
        console.warn("[PaperBack] 토큰 만료 — 다시 로그인 필요");
        await chrome.storage.local.remove("jwt");
      } else {
        console.error(`[PaperBack] Send failed: ${response.status}`);
      }
    } catch (err) {
      console.error("[PaperBack] Send error (will retry next cycle):", err.message);
    }
  }

  // YouTube 기록 전송
  if (youtubeRecords.length > 0) {
    try {
      const response = await fetch(`${apiUrl}/browsing/youtube-detect`, {
        method: "POST",
        headers,
        body: JSON.stringify({ records: youtubeRecords }),
      });

      if (response.ok) {
        console.log(`[PaperBack] Sent ${youtubeRecords.length} YouTube records.`);
        await chrome.storage.local.set({ youtubeRecords: [] });
      }
    } catch (err) {
      console.error("[PaperBack] YouTube send error:", err.message);
    }
  }
}

// ---- 체류 시간 추적 ----
let activeTabId = null;
let activeTabUrl = null;
let activeTabStart = null;

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  await saveTabTime();

  try {
    const tab = await chrome.tabs.get(activeInfo.tabId);
    activeTabId = activeInfo.tabId;
    activeTabUrl = tab.url;
    activeTabStart = Date.now();
  } catch (e) {
    activeTabId = null;
    activeTabUrl = null;
    activeTabStart = null;
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tabId === activeTabId && changeInfo.url) {
    saveTabTime();
    activeTabUrl = changeInfo.url;
    activeTabStart = Date.now();
  }
});

chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    saveTabTime();
    activeTabId = null;
    activeTabUrl = null;
    activeTabStart = null;
  }
});

async function saveTabTime() {
  if (!activeTabUrl || !activeTabStart) return;
  if (shouldSkipUrl(activeTabUrl)) return;

  const elapsed = Date.now() - activeTabStart;
  if (elapsed < 2000) return; // 2초 미만은 무시

  const data = await chrome.storage.local.get("tabStartTimes");
  const tabTimes = data.tabStartTimes || {};
  tabTimes[activeTabUrl] = (tabTimes[activeTabUrl] || 0) + elapsed;
  await chrome.storage.local.set({ tabStartTimes: tabTimes });
}

// ---- Content Script / auth-callback에서 메시지 수신 ----
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ARTICLE_EXTRACTED") {
    chrome.storage.local.get("articleBuffer", (data) => {
      const buffer = data.articleBuffer || {};
      buffer[message.url] = message.text;
      chrome.storage.local.set({ articleBuffer: buffer });
    });
    sendResponse({ status: "ok" });
  }

  if (message.type === "JWT_RECEIVED") {
    chrome.storage.local.set({ jwt: message.token }, () => {
      console.log("[PaperBack] JWT 저장 완료 — 로그인 성공");
    });
    sendResponse({ status: "ok" });
  }

  return true;
});

// ---- 유틸 함수 ----
function shouldSkipUrl(url) {
  if (!url) return true;
  for (const blocked of BLACKLIST_DOMAINS) {
    if (url.includes(blocked)) return true;
  }
  if (url.startsWith("chrome") || url.startsWith("about:") || url.startsWith("edge://")) {
    return true;
  }
  return false;
}

function extractDomain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}
