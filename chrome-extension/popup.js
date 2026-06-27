// ============================================================
// PaperBack Agent - Popup Script
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {
  // 설정 불러오기
  const config = await chrome.storage.sync.get(["apiUrl", "authToken", "userId"]);
  document.getElementById("apiUrl").value = config.apiUrl || "https://swdigitalsokkrates-production.up.railway.app";
  document.getElementById("userId").value = config.userId || "";
  document.getElementById("authToken").value = config.authToken || "";

  // 통계 불러오기
  const data = await chrome.storage.local.get(["stats", "pendingRecords", "youtubeRecords"]);
  const stats = data.stats || {};
  const pending = (data.pendingRecords || []).length + (data.youtubeRecords || []).length;

  document.getElementById("todayCollected").textContent = `${stats.todayCollected || 0}건`;
  document.getElementById("todaySent").textContent = `${stats.todaySent || 0}건`;
  document.getElementById("pendingCount").textContent = `${pending}건`;

  // 서버 연결 상태 확인
  const apiUrl = config.apiUrl || "https://swdigitalsokkrates-production.up.railway.app";
  try {
    const resp = await fetch(`${apiUrl}/health`, { method: "GET" });
    if (resp.ok) {
      document.getElementById("connectionStatus").innerHTML =
        '<span class="dot green"></span>연결됨';
    }
  } catch (e) {
    // 연결 실패 → 기본값 (빨간 점) 유지
  }

  // 저장 버튼
  document.getElementById("saveBtn").addEventListener("click", async () => {
    const apiUrl = document.getElementById("apiUrl").value.trim();
    const userId = document.getElementById("userId").value.trim();
    const authToken = document.getElementById("authToken").value.trim();
    await chrome.storage.sync.set({ apiUrl, userId, authToken });

    const msg = document.getElementById("saveMsg");
    msg.style.display = "block";
    setTimeout(() => (msg.style.display = "none"), 2000);
  });

  // 지금 전송 버튼
  document.getElementById("sendNowBtn").addEventListener("click", async () => {
    const btn = document.getElementById("sendNowBtn");
    btn.textContent = "전송 중...";
    btn.disabled = true;

    // background의 알람 수동 트리거
    await chrome.alarms.create("collectAndSend", { delayInMinutes: 0.02 });

    setTimeout(async () => {
      const data = await chrome.storage.local.get(["stats", "pendingRecords", "youtubeRecords"]);
      const stats = data.stats || {};
      const pending = (data.pendingRecords || []).length + (data.youtubeRecords || []).length;

      document.getElementById("todayCollected").textContent = `${stats.todayCollected || 0}건`;
      document.getElementById("todaySent").textContent = `${stats.todaySent || 0}건`;
      document.getElementById("pendingCount").textContent = `${pending}건`;

      btn.textContent = "지금 전송하기";
      btn.disabled = false;
    }, 3000);
  });
});
