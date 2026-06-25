// ============================================================
// PaperBack Agent - Content Script
// Readability.js로 기사 본문 추출 + background로 전달
// ============================================================

(function () {
  // 이미 실행됐으면 스킵
  if (window.__paperbackExtracted) return;
  window.__paperbackExtracted = true;

  // 페이지 로드 완료 후 실행
  if (document.readyState === "complete") {
    extractArticle();
  } else {
    window.addEventListener("load", extractArticle);
  }

  function extractArticle() {
    // 스킵할 사이트
    const skipDomains = [
      "google.com/search",
      "naver.com/search",
      "youtube.com",
      "facebook.com",
      "instagram.com",
      "twitter.com",
      "x.com",
    ];

    const url = window.location.href;
    for (const domain of skipDomains) {
      if (url.includes(domain)) return;
    }

    try {
      // Readability.js 실행
      const documentClone = document.cloneNode(true);
      const reader = new Readability(documentClone);
      const article = reader.parse();

      if (!article) return;

      // 본문 텍스트 추출
      const text = article.textContent || "";
      const cleanText = text.replace(/\s+/g, " ").trim();

      // 500자 미만이면 기사가 아닌 것으로 판단
      if (cleanText.length < 500) return;

      // 최대 5000자로 제한
      const truncated = cleanText.substring(0, 5000);

      // background에 전달
      chrome.runtime.sendMessage(
        {
          type: "ARTICLE_EXTRACTED",
          url: window.location.href,
          text: truncated,
          title: article.title || document.title,
          excerpt: (article.excerpt || "").substring(0, 200),
          byline: article.byline || "",
          length: cleanText.length,
        },
        (response) => {
          if (chrome.runtime.lastError) {
            // 에러 무시 (확장 프로그램 컨텍스트가 무효화된 경우)
          }
        }
      );
    } catch (err) {
      // Readability 파싱 실패 → 조용히 무시
    }
  }
})();
