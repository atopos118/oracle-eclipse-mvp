(() => {
  const configUrl = "../deliverables/competition-2026/%E5%8F%82%E8%B5%9B%E9%93%BE%E6%8E%A5%E9%85%8D%E7%BD%AE.json";

  function configureLink(id, url, readyLabel) {
    const node = document.getElementById(id);
    if (!node || !url) return false;
    node.href = url;
    node.removeAttribute("aria-disabled");
    node.classList.add("is-ready");
    const label = node.querySelector("strong");
    if (label && readyLabel) label.textContent = readyLabel;
    return true;
  }

  const originLabel = document.getElementById("public-site-label");
  if (originLabel) originLabel.textContent = window.location.host || "当前站点";

  document.querySelectorAll('a[aria-disabled="true"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
    });
  });

  fetch(configUrl, { cache: "no-store" })
    .then((response) => response.ok ? response.json() : {})
    .then((links) => {
      const sourceReady = configureLink("source-link", links.sourceUrl, "打开源码仓库");
      const videoReady = configureLink("submission-video-link", links.videoUrl, "播放 1080P 视频");
      configureLink("video-link", links.videoUrl, "播放演示视频");
      configureLink("deck-link", links.deckUrl, "打开文件");
      const readiness = document.getElementById("submission-readiness");
      if (readiness && sourceReady && videoReady) {
        readiness.textContent = "互动站、演示视频、技术报告、参赛文件和源码入口均已就绪。";
        readiness.classList.add("is-complete");
      }
    })
    .catch(() => {});
})();
