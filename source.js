const $ = (selector) => document.querySelector(selector);

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

function renderEvidence(register, sourceId) {
  const source = (register.sources || []).find((item) => String(item.sourceId) === sourceId);
  if (!source) {
    $("#source-evidence").innerHTML = '<p class="source-empty">来源已确认；与该来源关联的记录尚未进入当前公众内容。</p>';
    return;
  }
  $("#source-evidence").innerHTML = `
    <p class="source-citation">${escapeHTML(source.citation || "书目信息待补")}</p>
    ${(source.checks || []).map((item, index) => `
      <article class="source-evidence-row">
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div><strong>${escapeHTML(item.result)}</strong></div>
      </article>
    `).join("")}
  `;
}

function renderRecords(records, sourceId) {
  const related = records.filter((item) => (item.sourceIds || []).map(String).includes(sourceId));
  $("#source-records").innerHTML = related.length ? related.map((item) => {
    return `
      <article class="source-record-row">
        <div><span>${escapeHTML(item.catalogNumber || "著录待核")}</span><strong>${escapeHTML(item.inscription || item.headline)}</strong></div>
        <p>${escapeHTML(item.translation || "释义待补")}</p>
        <small>${escapeHTML(item.reviewLevel || "待确认")}</small>
      </article>
    `;
  }).join("") : '<p class="source-empty">该来源尚无知识通过审核进入当前公众版本。</p>';
}

async function init() {
  const sourceId = new URLSearchParams(location.search).get("id") || "";
  try {
    const response = await fetch("data/published-snapshot.json", { cache: "no-store" });
    if (!response.ok) throw new Error("发布版本读取失败");
    const snapshot = await response.json();
    const source = (snapshot.literatureMeta?.items || []).find((item) => String(item.id) === sourceId);
    if (!source) throw new Error("当前发布版本中没有这篇来源");

    document.title = `${source.title} · 来源详情`;
    $("#source-title").textContent = source.title;
    $("#source-byline").textContent = `${(source.authors || []).join("、") || "作者不详"} · ${source.publication || "来源不详"}`;
    $("#source-status-line").innerHTML = `<span>来源已确认</span><span>原始资料不公开</span>`;
    $("#source-review-status").textContent = "已确认来源";
  } catch (error) {
    $("#source-title").textContent = "来源详情暂不可用";
    $("#source-byline").textContent = error.message;
    $("#source-evidence").innerHTML = '<p class="source-empty">请返回研究依据列表重新选择。</p>';
    $("#source-records").innerHTML = "";
  }
}

document.addEventListener("DOMContentLoaded", init);
