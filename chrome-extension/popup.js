const API_BASE = "https://swdigitalsokkrates-production.up.railway.app";

document.addEventListener("DOMContentLoaded", async () => {
  const { jwt } = await chrome.storage.local.get("jwt");

  if (jwt) {
    showLoggedIn(jwt);
  } else {
    showLoggedOut();
  }

  await refreshStats();

  // 로그인 버튼
  document.getElementById("loginBtn").addEventListener("click", () => {
    chrome.tabs.create({ url: `${API_BASE}/auth/google/extension` });
    window.close();
  });

  // 로그아웃 버튼
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await chrome.storage.local.remove("jwt");
    showLoggedOut();
  });

  // 지금 전송 버튼
  document.getElementById("sendNowBtn").addEventListener("click", async () => {
    const btn = document.getElementById("sendNowBtn");
    btn.textContent = "전송 중...";
    btn.disabled = true;

    await chrome.alarms.create("collectAndSend", { delayInMinutes: 0.02 });

    setTimeout(async () => {
      await refreshStats();
      btn.textContent = "지금 전송하기";
      btn.disabled = false;
    }, 3000);
  });
});

function showLoggedIn(jwt) {
  document.getElementById("loggedOut").style.display = "none";
  document.getElementById("loggedIn").style.display = "block";

  // JWT payload에서 이메일 힌트 표시 (없으면 생략)
  try {
    const payload = JSON.parse(atob(jwt.split(".")[1]));
    if (payload.email) {
      document.getElementById("userEmail").textContent = payload.email;
    }
  } catch {}

  // 서버 연결 상태
  fetch(`${API_BASE}/health`)
    .then((r) => {
      if (r.ok) {
        document.getElementById("connectionStatus").innerHTML =
          '<span class="dot green"></span>연결됨';
      }
    })
    .catch(() => {});
}

function showLoggedOut() {
  document.getElementById("loggedOut").style.display = "block";
  document.getElementById("loggedIn").style.display = "none";
}

async function refreshStats() {
  const data = await chrome.storage.local.get(["stats", "pendingRecords", "youtubeRecords"]);
  const stats = data.stats || {};
  const pending = (data.pendingRecords || []).length + (data.youtubeRecords || []).length;

  document.getElementById("todayCollected").textContent = `${stats.todayCollected || 0}건`;
  document.getElementById("todaySent").textContent = `${stats.todaySent || 0}건`;
  document.getElementById("pendingCount").textContent = `${pending}건`;
}
