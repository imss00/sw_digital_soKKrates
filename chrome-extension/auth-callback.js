// OAuth 완료 페이지에서 JWT를 읽어 background에 전달하고 탭을 닫는다.
(function () {
  const el = document.getElementById("paperback-auth-done");
  if (!el) return;

  const token = el.getAttribute("data-token");
  if (!token) return;

  chrome.runtime.sendMessage({ type: "JWT_RECEIVED", token }, () => {
    window.close();
  });
})();
