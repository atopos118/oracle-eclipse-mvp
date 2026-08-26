const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  activeSection: "overview", importKind: "pdf", outputKind: "record_table", artifactKinds: [],
  dashboard: null, sources: [], artifacts: [], snapshots: [], ocrRuns: [], siteContent: [], siteShortcodes: [], videoJobs: {},
  snapshotDetails: {}, expandedSnapshotId: null, lastSyncedAt: 0,
  selected: { source: null, artifact: null, siteContent: "hero" },
  sourcePage: 1, pdfZoom: 1,
  sourceListWidth: 324, studioSetupWidth: 360, studioListWidth: 350, pdfViewerWidth: 52,
  siteNavigationWidth: 286, siteEditorWidth: 680,
  fullscreenArtifactId: null, fullscreenReturnFocus: null,
  artifactPages: {}, artifactMediaRevision: {},
  artifactSlideTimers: {}, artifactSlidesPlaying: new Set(),
  boardZooms: {},
  richTextRange: null,
  siteContentDirty: new Set(),
  siteHtmlMode: "visual",
  siteGenerationMode: "section_package",
  siteGenerationReady: false,
  checked: { source: new Set(), artifact: new Set() },
  lastAnswer: null, deploymentMode: "local"
};

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}
function slidePlainText(value) {
  const template = document.createElement("template");
  template.innerHTML = String(value ?? "");
  template.content.querySelectorAll("script,style,iframe,object,svg,math").forEach((node) => node.remove());
  return String(template.content.textContent || "").replace(/(?:\*\*|__|~~|`{1,3})/g, "").replace(/\s+/g, " ").trim();
}
function slideDensityClass(page = {}) {
  const rich = Array.isArray(page.richText) ? page.richText : [];
  const bullets = Array.isArray(page.bullets) ? page.bullets : [];
  const size = [page.title, page.takeaway, ...bullets, ...rich.flatMap((item) => [item?.lead, item?.text])].map(slidePlainText).join("").length;
  return size > 280 ? "density-condensed" : size > 190 ? "density-compact" : "";
}
function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function formatFullDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
  });
}
function statusLabel(status) {
  return ({ imported: "处理中", parsed: "待确认", reviewed: "已确认", parse_failed: "处理失败", deleted: "已删除", candidate: "待确认", approved: "已确认", rejected: "已驳回", stale: "需重新复核", retired: "已停用", draft: "草稿", published: "已发布", withdrawn: "已撤回", public_stale: "已发布待替换", replacement_pending: "待替换发布", generated_note: "AI研究笔记" })[status] || status || "未知";
}
function statusChip(status) { return `<span class="status status-${escapeHTML(status)}">${escapeHTML(statusLabel(status))}</span>`; }
function artifactReviewStatus(status) { return status === "published" ? "approved" : status; }
function artifactReviewLabel(status) {
  return ({ draft: "草稿待审", approved: "已批准", stale: "需重新复核", rejected: "已驳回" })[artifactReviewStatus(status)] || statusLabel(status);
}
function artifactPublicationLabel(status) {
  return ({ private: "未发布", public: "已发布", withdrawn: "已撤回", public_stale: "旧版发布中", replacement_pending: "待更新发布" })[status] || "未发布";
}
function artifactStatePair(artifact) {
  const review = artifactReviewStatus(artifact.status);
  const publication = artifact.publication_state || "private";
  const publicationClass = publication === "public" ? "published" : publication;
  return `<span class="artifact-state"><small>审核</small><span class="status status-${escapeHTML(review)}">${escapeHTML(artifactReviewLabel(review))}</span></span><span class="artifact-state"><small>发布</small><span class="status status-${escapeHTML(publicationClass)}">${escapeHTML(artifactPublicationLabel(publication))}</span></span>`;
}
function recognitionLabel(status) {
  return ({ unverified: "文本未检验", text_ready: "文本层可用", ocr_pending: "OCR待重建", ocr_processing: "OCR处理中", ocr_needs_review: "OCR待确认", ocr_ready: "已确认", ocr_failed: "OCR失败" })[status] || "文本未检验";
}
function recognitionChip(status) { return `<span class="recognition recognition-${escapeHTML(status || "unverified")}">${escapeHTML(recognitionLabel(status))}</span>`; }
function sourceWorkflowChip(source) {
  if (source.source_role === "generated_note") return statusChip("generated_note");
  if (["deleted", "parse_failed", "imported"].includes(source.status)) return statusChip(source.status);
  if (String(source.recognition_status || "").startsWith("ocr_")) return recognitionChip(source.recognition_status);
  return statusChip(source.status);
}
function sourceConfirmationText(status, recognitionStatus) {
  if (status === "reviewed" && ["text_ready", "ocr_ready"].includes(recognitionStatus)) return "来源已确认";
  if (recognitionStatus === "ocr_needs_review") return "OCR待确认";
  return `来源待确认 · ${recognitionLabel(recognitionStatus)}`;
}
function setNavCollapsed(collapsed, persist = true) {
  document.body.classList.toggle("nav-collapsed", collapsed);
  const button = $("#nav-collapse-toggle");
  if (button) {
    button.setAttribute("aria-expanded", String(!collapsed));
    button.title = collapsed ? "展开导航" : "折叠导航";
    button.querySelector("span[aria-hidden]").textContent = collapsed ? "›" : "‹";
    button.querySelector(".sr-only").textContent = collapsed ? "展开导航" : "折叠导航";
  }
  if (persist) {
    try { localStorage.setItem("oracle-research-nav-collapsed", collapsed ? "1" : "0"); } catch (_) { /* private browsing */ }
  }
}
const paneSettings = {
  sourceList: { stateKey: "sourceListWidth", cssVariable: "--source-list-width", storageKey: "oracle-research-source-list-width", min: 260, max: 520, defaultValue: 324, unit: "px" },
  studioSetup: { stateKey: "studioSetupWidth", cssVariable: "--studio-setup-width", storageKey: "oracle-research-studio-setup-width", min: 280, max: 560, defaultValue: 360, unit: "px" },
  studioList: { stateKey: "studioListWidth", cssVariable: "--studio-list-width", storageKey: "oracle-research-studio-list-width", min: 280, max: 560, defaultValue: 350, unit: "px" },
  pdfViewer: { stateKey: "pdfViewerWidth", cssVariable: "--pdf-viewer-width", storageKey: "oracle-research-pdf-viewer-width", min: 32, max: 72, defaultValue: 52, unit: "%" },
  siteNavigation: { stateKey: "siteNavigationWidth", cssVariable: "--site-navigation-width", storageKey: "oracle-research-site-navigation-width", min: 240, max: 420, defaultValue: 286, unit: "px" },
  siteEditor: { stateKey: "siteEditorWidth", cssVariable: "--site-editor-width", storageKey: "oracle-research-site-editor-width", min: 480, max: 980, defaultValue: 680, unit: "px" }
};
function setPaneSize(name, value, persist = true) {
  const setting = paneSettings[name];
  if (!setting) return;
  const normalized = Math.round(Math.max(setting.min, Math.min(setting.max, Number(value) || setting.defaultValue)) * (setting.unit === "%" ? 10 : 1)) / (setting.unit === "%" ? 10 : 1);
  state[setting.stateKey] = normalized;
  document.documentElement.style.setProperty(setting.cssVariable, `${normalized}${setting.unit}`);
  $$(`[data-pane-resizer="${name}"]`).forEach((resizer) => resizer.setAttribute("aria-valuenow", String(Math.round(normalized))));
  if (persist) {
    try { localStorage.setItem(setting.storageKey, String(normalized)); } catch (_) { /* private browsing */ }
  }
}
function restorePaneSizes() {
  Object.entries(paneSettings).forEach(([name, setting]) => {
    let value = setting.defaultValue;
    try { value = Number(localStorage.getItem(setting.storageKey)) || setting.defaultValue; } catch (_) { /* private browsing */ }
    setPaneSize(name, value, false);
  });
}
let activePaneResize = null;
function startPaneResize(event, resizer) {
  if (window.matchMedia("(max-width: 960px)").matches) return;
  const name = resizer.dataset.paneResizer;
  const setting = paneSettings[name];
  if (!setting) return;
  activePaneResize = {
    name,
    startX: event.clientX,
    startValue: state[setting.stateKey],
    basis: Math.max(1, resizer.parentElement?.getBoundingClientRect().width || window.innerWidth)
  };
  resizer.classList.add("is-dragging");
  document.body.classList.add("is-resizing-pane");
  event.preventDefault();
}
function movePaneResize(event) {
  if (!activePaneResize) return;
  const setting = paneSettings[activePaneResize.name];
  const deltaX = event.clientX - activePaneResize.startX;
  const delta = setting.unit === "%" ? deltaX / activePaneResize.basis * 100 : deltaX;
  setPaneSize(activePaneResize.name, activePaneResize.startValue + delta, false);
  event.preventDefault();
}
function finishPaneResize() {
  if (!activePaneResize) return;
  const name = activePaneResize.name;
  const setting = paneSettings[name];
  $$(`[data-pane-resizer="${name}"]`).forEach((resizer) => resizer.classList.remove("is-dragging"));
  document.body.classList.remove("is-resizing-pane");
  activePaneResize = null;
  setPaneSize(name, state[setting.stateKey]);
}
function syncPdfZoom(value = state.pdfZoom) {
  state.pdfZoom = Math.max(0.5, Math.min(2, Number(value) || 1));
  const image = $("#source-pdf-page");
  const range = $("#pdf-zoom-range");
  const output = $("#pdf-zoom-value");
  if (range) range.value = String(Math.round(state.pdfZoom * 100));
  if (output) output.textContent = `${Math.round(state.pdfZoom * 100)}%`;
  if (image) {
    image.style.zoom = String(state.pdfZoom);
    image.style.maxWidth = state.pdfZoom > 1 ? "none" : "100%";
  }
}
function ensurePdfZoomControls() {
  const actions = $(".pdf-page-actions");
  const openLink = actions?.querySelector("a");
  if (!actions || !openLink || $("#pdf-zoom-range")) return;
  openLink.insertAdjacentHTML("beforebegin", `<div class="pdf-zoom-control"><span>缩放</span><button type="button" data-pdf-zoom-step="-10" title="缩小" aria-label="缩小">−</button><input id="pdf-zoom-range" type="range" min="50" max="200" step="10" value="${Math.round(state.pdfZoom * 100)}" aria-label="PDF缩放"><button type="button" data-pdf-zoom-step="10" title="放大" aria-label="放大">＋</button><output id="pdf-zoom-value">${Math.round(state.pdfZoom * 100)}%</output></div><button type="button" data-pdf-zoom-reset title="重置缩放" aria-label="重置缩放">↺</button>`);
  syncPdfZoom();
}
function recognitionPublishable(source) { return ["text_ready", "ocr_ready"].includes(source.recognition_status); }
function latestOcrRun(sourceId) { return state.ocrRuns.find((item) => item.source_id === sourceId); }
function hasCompleteOcrResult(source) {
  const run = latestOcrRun(source.id);
  return Boolean(run && Number(run.total_pages) > 0 && Number(run.processed_pages) === Number(run.total_pages));
}
async function request(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    const next = encodeURIComponent(`${location.pathname}${location.hash}`);
    location.replace(`/research/login.html?next=${next}`);
    throw new Error(data.error || "登录状态已失效，请重新登录");
  }
  if (!response.ok) throw new Error(data.error || `${response.status}`);
  return data;
}
function post(path, payload = {}) { return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
let toastTimer;
let ocrRefreshTimer;
let refreshSequence = 0;
let initialized = false;
function toast(message, error = false) { const node = $("#toast"); node.textContent = message; node.classList.toggle("is-error", error); node.classList.add("is-visible"); clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove("is-visible"), error ? 9000 : 3200); }
function setSyncState(message, mode = "ready") {
  const node = $("#workspace-sync-state");
  if (!node) return;
  node.classList.toggle("is-syncing", mode === "syncing");
  node.classList.toggle("is-error", mode === "error");
  const label = node.querySelector("span");
  if (label) label.textContent = message;
  node.title = mode === "ready" && state.lastSyncedAt ? `最近同步：${formatFullDate(state.lastSyncedAt)}` : message;
}
function workspaceSectionExists(section) {
  if (!section) return false;
  const node = document.getElementById(section);
  return Boolean(node && node.matches("[data-workspace-section]"));
}
function setSection(section) { state.activeSection = section; $$('[data-workspace-section]').forEach((node) => node.classList.toggle("is-active", node.id === section)); $$(".nav-item").forEach((button) => button.classList.toggle("is-active", button.dataset.section === section)); history.replaceState(null, "", `#${section}`); window.scrollTo({ top: 0, behavior: "smooth" }); }
window.addEventListener("hashchange", () => { const section = location.hash.slice(1); if (workspaceSectionExists(section)) setSection(section); });
function jsonText(value) { return JSON.stringify(value || {}, null, 2); }
function parseJSON(value) { try { return JSON.parse(value || "{}"); } catch (_) { throw new Error("正文不是有效 JSON，请检查括号和引号"); } }
function cleanAnswerText(value) { return String(value || "").replace(/\*{2,}/g, "").trim(); }
function entityTitle(item) { return item.title || item.headline || "未命名"; }

const siteContentMeta = {
  hero: { label: "Banner 横幅", caption: "图片、视频与动态轮播", index: "B" },
  science: { label: "栏目一 · 科学原理", caption: "机制、类型与观测安全", index: "1" },
  history: { label: "栏目二 · 甲骨时代", caption: "先人记录与认识边界", index: "2" },
  records: { label: "栏目三 · 日食记录", caption: "记录入口与范围说明", index: "3" }
};
function selectedSiteContent() { return state.siteContent.find((item) => item.content_key === state.selected.siteContent) || state.siteContent[0]; }
function siteReviewLabel(entry) { return entry?.status === "approved" ? "已批准" : "草稿"; }
function sitePublicationLabel(entry) {
  if (entry?.publication_state === "public") return "当前版本";
  if (entry?.publication_state === "outdated") return "待更新发布";
  return "尚未发布";
}
function siteTextField(name, label, value, { rows = 0, maxlength = 500, hint = "" } = {}) {
  const control = rows
    ? `<textarea name="${name}" rows="${rows}" maxlength="${maxlength}">${escapeHTML(value || "")}</textarea>`
    : `<input name="${name}" value="${escapeHTML(value || "")}" maxlength="${maxlength}">`;
  return `<label><span>${escapeHTML(label)}${hint ? `<small>${escapeHTML(hint)}</small>` : ""}</span>${control}</label>`;
}
const siteHTMLTags = new Set(["P", "H2", "H3", "H4", "UL", "OL", "LI", "STRONG", "EM", "BLOCKQUOTE", "A", "IMG", "FIGURE", "FIGCAPTION", "BR", "HR", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DIV", "SPAN"]);
function sanitizeSiteHTMLClient(rawHTML) {
  const template = document.createElement("template");
  template.innerHTML = String(rawHTML || "");
  [...template.content.querySelectorAll("*")].forEach((element) => {
    if (!siteHTMLTags.has(element.tagName)) {
      if (["SCRIPT", "STYLE", "IFRAME", "OBJECT", "SVG", "MATH"].includes(element.tagName)) element.remove();
      else element.replaceWith(...element.childNodes);
      return;
    }
    const attributes = [...element.attributes];
    attributes.forEach((attribute) => element.removeAttribute(attribute.name));
    if (element.tagName === "A") {
      const href = attributes.find((attribute) => attribute.name.toLowerCase() === "href")?.value || "";
      if (/^(?:https?:\/\/|mailto:|#)/i.test(href)) {
        element.setAttribute("href", href); element.setAttribute("target", "_blank"); element.setAttribute("rel", "noopener noreferrer");
      }
    }
    if (element.tagName === "IMG") {
      const src = attributes.find((attribute) => attribute.name.toLowerCase() === "src")?.value || "";
      if (!/^(?:\/?assets\/|\/api\/(?:research\/site-content\/assets|public\/site-media)\/)/i.test(src)) { element.remove(); return; }
      element.setAttribute("src", src);
      ["alt", "title"].forEach((name) => { const value = attributes.find((attribute) => attribute.name.toLowerCase() === name)?.value; if (value) element.setAttribute(name, value.slice(0, 300)); });
      element.setAttribute("loading", "lazy");
    }
    if (element.tagName === "FIGURE" && attributes.some((attribute) => attribute.name.toLowerCase() === "class" && attribute.value === "site-generated-visual")) element.setAttribute("class", "site-generated-visual");
    if (["TH", "TD"].includes(element.tagName)) ["colspan", "rowspan"].forEach((name) => { const value = attributes.find((attribute) => attribute.name.toLowerCase() === name)?.value; if (/^\d{1,2}$/.test(value || "")) element.setAttribute(name, value); });
  });
  return template.innerHTML;
}
function siteShortcodePreview(rawHTML) {
  const template = document.createElement("template");
  template.innerHTML = sanitizeSiteHTMLClient(rawHTML);
  const codes = new Map(state.siteShortcodes.map((item) => [item.code, item]));
  if (!codes.size) return template.innerHTML;
  const pattern = new RegExp(`(${[...codes.keys()].map((code) => code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    if (![...codes.keys()].some((code) => node.data.includes(code))) return;
    const fragment = document.createDocumentFragment();
    node.data.split(pattern).filter(Boolean).forEach((part) => {
      if (!codes.has(part)) { fragment.append(document.createTextNode(part)); return; }
      const placeholder = document.createElement("span"); placeholder.className = "site-shortcode-placeholder";
      placeholder.innerHTML = `<i>数据简码</i><strong>${escapeHTML(part)}</strong><small>发布后读取研究工作台已审核数据</small>`;
      fragment.append(placeholder);
    });
    node.replaceWith(fragment);
  });
  return template.innerHTML;
}
function siteHTMLBodyEditor(entry) {
  const body = sanitizeSiteHTMLClient(entry.body_html || "");
  const codes = state.siteShortcodes.map((item) => `<button type="button" data-site-shortcode="${escapeHTML(item.code)}"><strong>${escapeHTML(item.code)}</strong><small>${escapeHTML(item.renderer)}</small></button>`).join("");
  return `<section class="site-html-editor" data-site-html-editor><header><div class="site-html-modes" role="tablist" aria-label="正文编辑模式"><button type="button" data-site-html-mode="visual" class="${state.siteHtmlMode === "visual" ? "is-active" : ""}" role="tab" aria-selected="${state.siteHtmlMode === "visual"}">可视编辑</button><button type="button" data-site-html-mode="source" class="${state.siteHtmlMode === "source" ? "is-active" : ""}" role="tab" aria-selected="${state.siteHtmlMode === "source"}">HTML 源码</button></div><details class="site-shortcode-picker"><summary>插入数据简码</summary><div>${codes || "<small>暂无可用简码</small>"}</div></details></header><div class="site-html-visual ${state.siteHtmlMode === "visual" ? "is-active" : ""}" data-site-html-visual contenteditable="true" role="textbox" aria-multiline="true">${body}</div><textarea class="site-html-source ${state.siteHtmlMode === "source" ? "is-active" : ""}" data-site-html-source spellcheck="false">${escapeHTML(body)}</textarea><footer><span>仅保留安全 HTML；脚本、内嵌网页和未知简码会被拒绝。</span><output data-site-html-count>${body.length} 字符</output></footer></section>`;
}
function siteSectionCommonEditorHTML(entry) {
  return `<section class="site-section-basics"><div class="site-form-grid">${siteTextField("sectionKicker", "栏目引言", entry.kicker, { maxlength: 80 })}${siteTextField("sectionNavLabel", "导航名称", entry.nav_label, { maxlength: 30 })}</div>${siteTextField("sectionTitle", "栏目标题", entry.title, { maxlength: 120 })}${siteTextField("sectionSummary", "栏目摘要", entry.summary, { rows: 4, maxlength: 800 })}<div class="site-settings-row"><label class="site-toggle"><input name="sectionEnabled" type="checkbox" ${entry.enabled !== false ? "checked" : ""}><span>在公众站显示</span></label><label><span>栏目类型</span><select name="sectionType" ${entry.content_key === "hero" ? "disabled" : ""}><option value="standard" ${entry.section_type === "standard" ? "selected" : ""}>网页内容</option><option value="data" ${entry.section_type === "data" ? "selected" : ""}>研究数据栏目</option><option value="hero" ${entry.section_type === "hero" ? "selected" : ""}>Banner</option></select></label></div>${siteHTMLBodyEditor(entry)}</section>`;
}
function siteMediaUrl(url) {
  const value = String(url || "").trim();
  if (!value || /^(?:data:|blob:|https?:\/\/|\/)/i.test(value)) return value;
  return `/${value.replace(/^\.\//, "")}`;
}
function siteMediaPreview(url, type = "image", alt = "站点媒体预览") {
  const previewUrl = siteMediaUrl(url);
  if (!previewUrl) return '<div class="site-media-empty">尚未选择媒体</div>';
  return type === "video"
    ? `<video src="${escapeHTML(previewUrl)}" muted loop controls playsinline aria-label="${escapeHTML(alt)}" data-site-media-preview></video>`
    : `<img src="${escapeHTML(previewUrl)}" alt="${escapeHTML(alt)}" data-site-media-preview>`;
}
function handleSiteMediaError(event) {
  const media = event.target.closest?.("[data-site-media-preview]");
  if (!media) return;
  const fallback = document.createElement("div");
  fallback.className = "site-media-empty site-media-error";
  fallback.innerHTML = `<strong>媒体暂时无法显示</strong><small>${escapeHTML(media.getAttribute("src") || "素材地址无效")}</small>`;
  media.replaceWith(fallback);
}
function heroEditorHTML(content) {
  const slides = Array.isArray(content.slides) ? content.slides : [];
  return `<div class="site-settings-row"><label class="site-toggle"><input name="autoplay" type="checkbox" ${content.autoplay ? "checked" : ""}><span>自动轮播</span></label><label><span>默认间隔 <small>秒</small></span><input name="intervalSeconds" type="number" min="3" max="30" value="${Number(content.intervalSeconds) || 6}"></label></div><div class="site-slide-list">${slides.map((slide, index) => {
    const mediaUrl = slide.assetId ? `/api/research/site-content/assets/${slide.assetId}` : slide.mediaUrl;
    const posterUrl = slide.posterAssetId ? `/api/research/site-content/assets/${slide.posterAssetId}` : slide.posterUrl;
    return `<section class="site-slide-editor" data-site-slide="${index}"><header><div><span>画面 ${String(index + 1).padStart(2, "0")}</span><strong>${escapeHTML(slide.title || "未命名画面")}</strong></div><div><button type="button" data-site-slide-action="up" data-index="${index}" title="上移" aria-label="上移">↑</button><button type="button" data-site-slide-action="down" data-index="${index}" title="下移" aria-label="下移">↓</button><button type="button" data-site-slide-action="delete" data-index="${index}" title="删除" aria-label="删除">×</button></div></header><div class="site-slide-media">${siteMediaPreview(mediaUrl, slide.mediaType, slide.title)}<div class="site-media-controls"><label><span>媒体类型</span><select name="slide-${index}-mediaType"><option value="image" ${slide.mediaType !== "video" ? "selected" : ""}>图片</option><option value="video" ${slide.mediaType === "video" ? "selected" : ""}>视频</option></select></label><label class="site-upload-button">选择图片或视频<input type="file" data-site-asset-target="slide-media" data-index="${index}" accept="image/png,image/jpeg,image/webp,video/mp4,video/webm"></label><label class="site-upload-button">视频封面图<input type="file" data-site-asset-target="slide-poster" data-index="${index}" accept="image/png,image/jpeg,image/webp"></label><input type="hidden" name="slide-${index}-assetId" value="${escapeHTML(slide.assetId || "")}"><input type="hidden" name="slide-${index}-mediaUrl" value="${escapeHTML(slide.mediaUrl || "")}"><input type="hidden" name="slide-${index}-posterAssetId" value="${escapeHTML(slide.posterAssetId || "")}"><input type="hidden" name="slide-${index}-posterUrl" value="${escapeHTML(slide.posterUrl || "")}">${posterUrl ? `<small>已设置视频封面</small>` : ""}</div></div><div class="site-slide-fields"><label class="site-toggle"><input name="slide-${index}-enabled" type="checkbox" ${slide.enabled !== false ? "checked" : ""}><span>在轮播中启用</span></label>${siteTextField(`slide-${index}-overline`, "引导语", slide.overline, { maxlength: 100 })}${siteTextField(`slide-${index}-title`, "主标题", slide.title, { maxlength: 120 })}${siteTextField(`slide-${index}-lede`, "说明", slide.lede, { rows: 3, maxlength: 240 })}<div class="site-form-grid">${siteTextField(`slide-${index}-primaryLabel`, "主按钮", slide.primaryAction?.label, { maxlength: 30 })}${siteTextField(`slide-${index}-primaryHref`, "主按钮锚点", slide.primaryAction?.href, { maxlength: 40 })}${siteTextField(`slide-${index}-secondaryLabel`, "次按钮", slide.secondaryAction?.label, { maxlength: 30 })}${siteTextField(`slide-${index}-secondaryHref`, "次按钮锚点", slide.secondaryAction?.href, { maxlength: 40 })}${siteTextField(`slide-${index}-durationSeconds`, "停留秒数", slide.durationSeconds || 6, { maxlength: 2 })}</div>${siteTextField(`slide-${index}-caption`, "媒体说明", slide.caption, { maxlength: 120 })}</div></section>`;
  }).join("")}</div><button class="site-add-slide" type="button" data-site-slide-action="add">＋ 添加轮播画面</button>`;
}
function scienceEditorHTML(content) {
  const types = Array.isArray(content.eclipseTypes) ? content.eclipseTypes : [];
  return `<div class="site-form-grid">${siteTextField("orbitQuestion", "互动问题", content.orbitQuestion, { maxlength: 100 })}${siteTextField("orbitExplanation", "互动解释", content.orbitExplanation, { rows: 4, maxlength: 500 })}${siteTextField("typeKicker", "类型引导", content.typeKicker, { maxlength: 100 })}${siteTextField("typeHeading", "类型标题", content.typeHeading, { maxlength: 100 })}</div><div class="eclipse-type-editor">${types.map((type) => `<section data-site-eclipse-type="${escapeHTML(type.id)}"><header><span>${escapeHTML(({ total: "全", annular: "环", partial: "偏" })[type.id] || "食")}</span><strong>${escapeHTML(type.name)}</strong></header>${siteTextField(`type-${type.id}-name`, "名称", type.name, { maxlength: 30 })}${siteTextField(`type-${type.id}-short`, "一句话", type.short, { maxlength: 80 })}${siteTextField(`type-${type.id}-explanation`, "科学解释", type.explanation, { rows: 4, maxlength: 400 })}${siteTextField(`type-${type.id}-fact`, "关键事实", type.fact, { rows: 3, maxlength: 300 })}</section>`).join("")}</div>${siteTextField("safetyNote", "观测安全提醒", content.safetyNote, { rows: 3, maxlength: 400 })}`;
}
function historyEditorHTML(content) {
  const image = content.image || {};
  const previewUrl = image.assetId ? `/api/research/site-content/assets/${image.assetId}` : image.url;
  return `${siteTextField("quote", "重点提醒", content.quote, { rows: 3, maxlength: 400 })}${siteTextField("points", "认识与边界", (content.points || []).join("\n"), { rows: 7, maxlength: 1800, hint: "每行一条" })}<section class="site-history-media"><div>${siteMediaPreview(previewUrl, "image", image.alt)}</div><div><label class="site-upload-button">更换栏目图片<input type="file" data-site-asset-target="history-image" accept="image/png,image/jpeg,image/webp"></label><input type="hidden" name="imageAssetId" value="${escapeHTML(image.assetId || "")}"><input type="hidden" name="imageUrl" value="${escapeHTML(image.url || "")}">${siteTextField("imageAlt", "替代文字", image.alt, { maxlength: 160 })}${siteTextField("imageCaption", "图片说明", image.caption, { maxlength: 100 })}</div></section>`;
}
function recordsEditorHTML(content) {
  return `${siteTextField("searchPlaceholder", "搜索框提示", content.searchPlaceholder, { maxlength: 100 })}${siteTextField("scopeTitle", "公开范围标题", content.scopeTitle, { rows: 3, maxlength: 240 })}${siteTextField("scopeNote", "公开范围说明", content.scopeNote, { rows: 4, maxlength: 400 })}<div class="site-data-boundary"><strong>记录数据不在这里编辑</strong><p>卜辞、著录、年代、释义和争议继续来自审核发布的记录知识与记录表，栏目文案不能覆盖证据数据。</p></div>`;
}
function siteContentFormHTML(entry) {
  const body = entry.content_key === "hero" ? heroEditorHTML(entry.content) : entry.content_key === "science" ? scienceEditorHTML(entry.content) : entry.content_key === "history" ? historyEditorHTML(entry.content) : entry.content_key === "records" ? recordsEditorHTML(entry.content) : "";
  const componentSettings = body ? `<details class="site-component-settings"><summary>${entry.content_key === "hero" ? "Banner 轮播设置" : "内置数据组件设置"}</summary><div>${body}</div></details>` : "";
  return `<form id="site-content-form" data-site-key="${escapeHTML(entry.content_key)}"><div class="site-editor-fields">${siteSectionCommonEditorHTML(entry)}${componentSettings}</div></form>`;
}
function sitePreviewHTML(key, content, entry = selectedSiteContent()) {
  const kicker = entry?.kicker || content.kicker || "";
  const title = entry?.title || content.heading || "未命名栏目";
  const summary = entry?.summary || content.summary || "";
  const bodyPreview = entry?.body_html ? `<div class="site-preview-html">${siteShortcodePreview(entry.body_html)}</div>` : "";
  if (key === "hero") {
    const slide = (content.slides || []).find((item) => item.enabled !== false) || content.slides?.[0] || {};
    const mediaUrl = siteMediaUrl(slide.assetId ? `/api/research/site-content/assets/${slide.assetId}` : slide.mediaUrl);
    return `<div class="site-preview-hero">${slide.mediaType === "video" ? `<video src="${escapeHTML(mediaUrl || "")}" muted loop autoplay playsinline data-site-media-preview></video>` : `<img src="${escapeHTML(mediaUrl || "")}" alt="" data-site-media-preview>`}<div><span>${escapeHTML(slide.overline || "")}</span><strong>${escapeHTML(slide.title || "")}</strong><p>${escapeHTML(slide.lede || "")}</p><small>${(content.slides || []).length} 个轮播画面</small></div></div>`;
  }
  if (key === "science") return `<div class="site-preview-section is-science"><span>01</span><div><small>${escapeHTML(kicker)}</small><strong>${escapeHTML(title)}</strong><p>${escapeHTML(summary)}</p><div>${(content.eclipseTypes || []).map((item) => `<i>${escapeHTML(item.name)}</i>`).join("")}</div>${bodyPreview}</div></div>`;
  if (key === "history") {
    const image = content.image || {};
    const imageUrl = siteMediaUrl(image.assetId ? `/api/research/site-content/assets/${image.assetId}` : image.url);
    const media = imageUrl ? `<figure><img src="${escapeHTML(imageUrl)}" alt="${escapeHTML(image.alt || "甲骨时代栏目图片")}" data-site-media-preview><figcaption>${escapeHTML(image.caption || "栏目图片")}</figcaption></figure>` : '<div class="site-media-empty">尚未选择栏目图片</div>';
    return `<div class="site-preview-section is-history"><span>02</span><div><small>${escapeHTML(kicker)}</small><strong>${escapeHTML(title)}</strong><p>${escapeHTML(summary)}</p><blockquote>${escapeHTML(content.quote || "")}</blockquote>${bodyPreview}</div>${media}</div>`;
  }
  if (key === "records") return `<div class="site-preview-section is-records"><span>03</span><div><small>${escapeHTML(kicker)}</small><strong>${escapeHTML(title)}</strong><p>${escapeHTML(summary)}</p><em>${escapeHTML(content.scopeTitle || "")}</em>${bodyPreview}</div></div>`;
  return `<div class="site-preview-section is-generic"><span>§</span><div><small>${escapeHTML(kicker)}</small><strong>${escapeHTML(title)}</strong><p>${escapeHTML(summary)}</p>${bodyPreview || '<div class="site-media-empty">正文为空</div>'}</div></div>`;
}
function renderSiteContent() {
  const list = $("#site-content-list");
  if (!list) return;
  const approved = state.siteContent.filter((item) => item.status === "approved").length;
  $("#site-content-ready-count").textContent = `${approved} / ${state.siteContent.length} 已批准`;
  $("#site-content-count").textContent = `${state.siteContent.length} 个栏目`;
  list.innerHTML = state.siteContent.map((entry, index) => {
    const meta = siteContentMeta[entry.content_key] || { label: entry.title, caption: "站点内容", index: "·" };
    const caption = entry.section_type === "hero" ? "图片、视频与动态轮播" : entry.section_type === "data" ? "HTML 与研究数据简码" : "HTML 网页内容";
    const number = entry.section_type === "hero" ? "B" : String(index).padStart(2, "0");
    return `<article class="site-section-row ${entry.content_key === state.selected.siteContent ? "is-active" : ""} ${entry.enabled === false ? "is-hidden" : ""}" data-site-section-row="${escapeHTML(entry.content_key)}"><button type="button" data-site-content-key="${escapeHTML(entry.content_key)}"><span>${escapeHTML(number)}</span><div><strong>${escapeHTML(entry.title || meta.label)}</strong><small>${escapeHTML(caption)}</small></div><i class="${entry.status === "approved" ? "is-approved" : ""}">${escapeHTML(siteReviewLabel(entry))}</i></button><div class="site-section-row-actions"><button type="button" data-site-row-action="up" data-key="${escapeHTML(entry.content_key)}" ${index === 0 ? "disabled" : ""} title="上移" aria-label="上移">↑</button><button type="button" data-site-row-action="down" data-key="${escapeHTML(entry.content_key)}" ${index === state.siteContent.length - 1 ? "disabled" : ""} title="下移" aria-label="下移">↓</button><button type="button" data-site-row-action="toggle" data-key="${escapeHTML(entry.content_key)}" title="${entry.enabled === false ? "显示栏目" : "隐藏栏目"}" aria-label="${entry.enabled === false ? "显示栏目" : "隐藏栏目"}">${entry.enabled === false ? "○" : "●"}</button><button type="button" data-site-row-action="delete" data-key="${escapeHTML(entry.content_key)}" ${entry.content_key === "hero" ? "disabled" : ""} title="删除栏目" aria-label="删除栏目">×</button></div></article>`;
  }).join("") || '<p class="inspector-empty">尚无站点内容。</p>';
  const entry = selectedSiteContent();
  if (!entry) return;
  const reviewAction = entry.status === "approved" ? "unapprove" : "approve";
  $("#site-content-editor").innerHTML = `<div class="site-editor-head"><div><span>${escapeHTML(entry.nav_label || "公众页面")}</span><h2>${escapeHTML(entry.title)}</h2></div><div class="site-editor-head-actions"><div class="site-state-pair"><span>审核：<strong>${escapeHTML(siteReviewLabel(entry))}</strong></span><span>发布：<strong>${escapeHTML(sitePublicationLabel(entry))}</strong></span></div><button type="button" class="command ${reviewAction === "approve" ? "primary" : "site-review-unapprove"}" data-site-review="${reviewAction}">${reviewAction === "approve" ? "批准内容" : "取消批准"}</button></div></div><section class="site-live-preview"><header><span>页面预览</span><a href="/" target="_blank" rel="noreferrer">打开公众站 ↗</a></header><div id="site-preview-stage">${sitePreviewHTML(entry.content_key, entry.content, entry)}</div></section>${siteContentFormHTML(entry)}<div class="site-editor-footer"><small>保存后回到草稿状态；批准后仍需在“审核发布”中发布新版本。</small><div><button type="button" class="command primary" data-site-save>保存草稿</button></div></div>`;
  $("#site-content-audit").innerHTML = `<span>当前编辑记录</span><dl><div><dt>编辑方式</dt><dd>${entry.model === "manual" ? "手动编辑" : escapeHTML(entry.model)}</dd></div><div><dt>提示版本</dt><dd>${escapeHTML(entry.prompt_version || "-")}</dd></div><div><dt>更新时间</dt><dd>${escapeHTML(formatFullDate(entry.updated_at))}</dd></div></dl>`;
}
function renderSiteGenerationModes() {
  $$("[data-site-generation-mode]", $("#site-generation-modes")).forEach((button) => {
    const active = button.dataset.siteGenerationMode === state.siteGenerationMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const packageMode = state.siteGenerationMode === "section_package";
  const description = $("#site-generation-description");
  description.textContent = !state.siteGenerationReady
    ? "当前服务仍使用旧版栏目生成接口，请重启本地服务后使用。"
    : packageMode
      ? "生成当前栏目的完整内容包，并调用百炼生成一张栏目配图。"
      : "读取栏目引言、导航名、标题、摘要和现有内容，只生成安全 HTML 正文。";
  description.classList.toggle("is-pending", !state.siteGenerationReady);
  const generateButton = $("#generate-site-content");
  generateButton.textContent = packageMode ? "生成完整栏目" : "仅生成正文 HTML";
  generateButton.disabled = !state.siteGenerationReady;
  generateButton.title = state.siteGenerationReady ? "" : "重启本地服务后启用";
}
function readSiteContentForm() {
  const form = $("#site-content-form");
  if (!form) return null;
  const value = (name) => form.elements.namedItem(name)?.value || "";
  const checked = (name) => Boolean(form.elements.namedItem(name)?.checked);
  const key = form.dataset.siteKey;
  const title = value("sectionTitle");
  const kicker = value("sectionKicker");
  const summary = value("sectionSummary");
  const visual = form.querySelector("[data-site-html-visual]");
  const source = form.querySelector("[data-site-html-source]");
  const bodyHTML = sanitizeSiteHTMLClient(state.siteHtmlMode === "source" ? source?.value : visual?.innerHTML);
  const meta = {
    title,
    kicker,
    summary,
    nav_label: value("sectionNavLabel"),
    section_type: value("sectionType") || (key === "hero" ? "hero" : "standard"),
    body_html: bodyHTML,
    enabled: checked("sectionEnabled")
  };
  if (key === "hero") {
    const slides = [...form.querySelectorAll("[data-site-slide]")].map((row) => {
      const index = Number(row.dataset.siteSlide);
      return { id: selectedSiteContent()?.content?.slides?.[index]?.id || `hero-slide-${Date.now()}-${index}`, enabled: checked(`slide-${index}-enabled`), mediaType: value(`slide-${index}-mediaType`), assetId: value(`slide-${index}-assetId`), mediaUrl: value(`slide-${index}-mediaUrl`), posterAssetId: value(`slide-${index}-posterAssetId`), posterUrl: value(`slide-${index}-posterUrl`), overline: value(`slide-${index}-overline`), title: value(`slide-${index}-title`), lede: value(`slide-${index}-lede`), primaryAction: { label: value(`slide-${index}-primaryLabel`), href: value(`slide-${index}-primaryHref`) }, secondaryAction: { label: value(`slide-${index}-secondaryLabel`), href: value(`slide-${index}-secondaryHref`) }, caption: value(`slide-${index}-caption`), durationSeconds: Number(value(`slide-${index}-durationSeconds`)) || 6 };
    });
    return { content: { autoplay: checked("autoplay"), intervalSeconds: Number(value("intervalSeconds")) || 6, slides }, meta };
  }
  if (key === "science") return { content: { kicker, heading: title, summary, orbitQuestion: value("orbitQuestion"), orbitExplanation: value("orbitExplanation"), typeKicker: value("typeKicker"), typeHeading: value("typeHeading"), safetyNote: value("safetyNote"), eclipseTypes: ["total", "annular", "partial"].map((id) => ({ id, name: value(`type-${id}-name`), short: value(`type-${id}-short`), explanation: value(`type-${id}-explanation`), fact: value(`type-${id}-fact`) })) }, meta };
  if (key === "history") return { content: { kicker, heading: title, summary, quote: value("quote"), points: value("points").split(/\n+/).map((item) => item.trim()).filter(Boolean), image: { assetId: value("imageAssetId"), url: value("imageUrl"), alt: value("imageAlt"), caption: value("imageCaption") } }, meta };
  if (key === "records") return { content: { kicker, heading: title, summary, searchPlaceholder: value("searchPlaceholder"), scopeTitle: value("scopeTitle"), scopeNote: value("scopeNote") }, meta };
  return { content: selectedSiteContent()?.content || {}, meta };
}
function updateSitePreview() {
  const value = readSiteContentForm();
  const stage = $("#site-preview-stage");
  if (value && stage) stage.innerHTML = sitePreviewHTML(state.selected.siteContent, value.content, { ...selectedSiteContent(), ...value.meta });
}
function commitSiteFormToState() {
  const entry = selectedSiteContent();
  const value = readSiteContentForm();
  if (entry && value) { entry.content = value.content; Object.assign(entry, value.meta); }
  return entry;
}
function siteContentPayload(entry) {
  return { content: entry.content, title: entry.title, sectionType: entry.section_type, navLabel: entry.nav_label, kicker: entry.kicker, summary: entry.summary, bodyHtml: entry.body_html, enabled: entry.enabled !== false, sortOrder: entry.sort_order || 0 };
}
async function saveSiteContent() {
  const entry = commitSiteFormToState();
  if (!entry) return;
  try { await post(`/api/research/site-content/${entry.content_key}/save`, siteContentPayload(entry)); state.siteContentDirty.delete(entry.content_key); toast("栏目已保存为草稿"); await refresh(); } catch (error) { toast(error.message, true); }
}
async function reviewSiteContent(action) {
  const entry = selectedSiteContent();
  if (!entry) return;
  if (action === "approve" && entry.status !== "approved" && !window.confirm("批准后，该内容将在下次发布新版本时更新公众站。确认批准？")) return;
  try {
    const dirty = state.siteContentDirty.has(entry.content_key);
    if (dirty) { commitSiteFormToState(); await post(`/api/research/site-content/${entry.content_key}/save`, siteContentPayload(entry)); state.siteContentDirty.delete(entry.content_key); }
    if (action === "approve" || !dirty) await post(`/api/research/site-content/${entry.content_key}/review`, { action });
    toast(action === "approve" ? "内容已批准，等待发布新版本" : "已取消批准，当前公众版本不受影响");
    await refresh();
  } catch (error) { toast(error.message, true); }
}
async function generateSiteContentDraft() {
  const entry = selectedSiteContent();
  if (!entry) return;
  if (!state.siteGenerationReady) return toast("请先重启本地服务，再使用新版栏目生成", true);
  const button = $("#generate-site-content");
  const mode = state.siteGenerationMode;
  const instruction = $("#site-content-instruction").value.trim();
  const label = mode === "section_package" ? "完整栏目" : "正文 HTML";
  if (!window.confirm(`AI 将替换当前${label}草稿；已发布页面不会立即改变。继续生成？`)) return;
  button.disabled = true; button.textContent = "正在生成";
  try {
    if (state.siteContentDirty.has(entry.content_key)) { commitSiteFormToState(); await post(`/api/research/site-content/${entry.content_key}/save`, siteContentPayload(entry)); state.siteContentDirty.delete(entry.content_key); }
    const result = await post(`/api/research/site-content/${entry.content_key}/generate`, { mode, instruction });
    toast(result.generation_warning || `AI ${label}已生成并保存为草稿`); await refresh();
  } catch (error) { toast(error.message, true); } finally { button.disabled = false; renderSiteGenerationModes(); }
}
async function uploadSiteAsset(input) {
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 24 * 1024 * 1024) { input.value = ""; return toast("站点媒体不能超过24MB", true); }
  const entry = commitSiteFormToState();
  if (!entry) return;
  input.disabled = true;
  try {
    const asset = await post("/api/research/site-content/assets", { filename: file.name, mimeType: file.type, contentBase64: await fileToBase64(file) });
    if (input.dataset.siteAssetTarget === "history-image") entry.content.image.assetId = asset.id;
    else {
      const slide = entry.content.slides[Number(input.dataset.index)];
      if (input.dataset.siteAssetTarget === "slide-poster") slide.posterAssetId = asset.id;
      else { slide.assetId = asset.id; slide.mediaType = asset.mediaType; }
    }
    state.siteContentDirty.add(entry.content_key);
    toast("媒体已上传到私有站点素材区；保存并批准后才能发布"); renderSiteContent();
  } catch (error) { toast(error.message, true); } finally { input.disabled = false; }
}
function changeHeroSlides(action, index) {
  const entry = commitSiteFormToState();
  if (!entry || entry.content_key !== "hero") return;
  const slides = entry.content.slides;
  if (action === "add") slides.push({ id: `hero-slide-${Date.now()}`, enabled: true, mediaType: "image", mediaUrl: "assets/hero-eclipse.webp", assetId: "", posterUrl: "", posterAssetId: "", overline: "新的观察视角", title: "日食，从一次观察开始", lede: "在这里补充这一画面的公众讲解。", primaryAction: { label: "看懂日食", href: "#science" }, secondaryAction: { label: "读甲骨记录", href: "#oracle" }, caption: "传播素材，非甲骨原片", durationSeconds: 6 });
  if (action === "delete") {
    if (slides.length <= 1) return toast("Banner 至少保留一个画面", true);
    slides.splice(index, 1);
  }
  if (action === "up" && index > 0) [slides[index - 1], slides[index]] = [slides[index], slides[index - 1]];
  if (action === "down" && index < slides.length - 1) [slides[index + 1], slides[index]] = [slides[index], slides[index + 1]];
  state.siteContentDirty.add(entry.content_key);
  renderSiteContent();
}

function setSiteHTMLMode(mode) {
  const shell = $("[data-site-html-editor]");
  if (!shell || !["visual", "source"].includes(mode)) return;
  const visual = shell.querySelector("[data-site-html-visual]");
  const source = shell.querySelector("[data-site-html-source]");
  if (mode === "source") source.value = sanitizeSiteHTMLClient(visual.innerHTML);
  else visual.innerHTML = sanitizeSiteHTMLClient(source.value);
  state.siteHtmlMode = mode;
  $$('[data-site-html-mode]', shell).forEach((button) => { const active = button.dataset.siteHtmlMode === mode; button.classList.toggle("is-active", active); button.setAttribute("aria-selected", String(active)); });
  visual.classList.toggle("is-active", mode === "visual"); source.classList.toggle("is-active", mode === "source");
  state.siteContentDirty.add(state.selected.siteContent); updateSitePreview();
}
function insertSiteShortcode(code) {
  const shell = $("[data-site-html-editor]");
  if (!shell || !state.siteShortcodes.some((item) => item.code === code)) return;
  if (state.siteHtmlMode === "source") {
    const source = shell.querySelector("[data-site-html-source]");
    const start = source.selectionStart; source.setRangeText(code, start, source.selectionEnd, "end"); source.focus();
  } else {
    const visual = shell.querySelector("[data-site-html-visual]");
    visual.focus(); document.execCommand("insertText", false, code);
  }
  state.siteContentDirty.add(state.selected.siteContent); updateSitePreview();
}
async function siteSectionRowAction(action, contentKey) {
  const index = state.siteContent.findIndex((item) => item.content_key === contentKey);
  if (index < 0) return;
  if (["up", "down"].includes(action)) {
    const target = action === "up" ? index - 1 : index + 1;
    if (target < 0 || target >= state.siteContent.length) return;
    const keys = state.siteContent.map((item) => item.content_key);
    [keys[index], keys[target]] = [keys[target], keys[index]];
    try { await post("/api/research/site-content/reorder", { contentKeys: keys }); toast("栏目顺序已保存，等待批准与发布"); await refresh(); } catch (error) { toast(error.message, true); }
    return;
  }
  const entry = state.siteContent[index];
  if (action === "toggle") {
    if (contentKey === state.selected.siteContent) commitSiteFormToState();
    entry.enabled = entry.enabled === false;
    try { await post(`/api/research/site-content/${contentKey}/save`, siteContentPayload(entry)); toast(entry.enabled ? "栏目已设为显示" : "栏目已设为隐藏"); await refresh(); } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === "delete") {
    if (!window.confirm(`删除栏目“${entry.title}”？当前公众版本不会立即改变，下一次发布后移除。`)) return;
    try { await post(`/api/research/site-content/${contentKey}/delete`, {}); state.selected.siteContent = state.siteContent[Math.max(0, index - 1)]?.content_key || "hero"; toast("栏目已删除，等待发布新版本"); await refresh(); } catch (error) { toast(error.message, true); }
  }
}
async function createSiteSection(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  try {
    const created = await post("/api/research/site-content", values);
    state.selected.siteContent = created.content_key;
    form.reset(); $("#site-section-dialog").close(); toast("新栏目已创建为草稿"); await refresh();
  } catch (error) { toast(error.message, true); }
}

const richTextTags = new Set(["P", "H2", "H3", "H4", "UL", "OL", "LI", "STRONG", "EM", "BLOCKQUOTE", "A", "IMG", "FIGURE", "FIGCAPTION", "SPAN", "BR"]);
const artifactIconNames = ["sun", "moon", "telescope", "book-open", "scale", "clock-3", "sparkles", "chart", "presentation"];
const artifactIconLabels = { sun: "太阳", moon: "月球", telescope: "观测", "book-open": "文献", scale: "争议", "clock-3": "时间", sparkles: "重点", chart: "图表", presentation: "演示" };
function artifactIconHTML(name) {
  const icon = artifactIconNames.includes(name) ? name : "book-open";
  return `<span data-icon="${icon}" class="artifact-icon artifact-icon-${icon}" aria-hidden="true"></span>`;
}
function artifactIconOptions(selected = "book-open") {
  return artifactIconNames.map((name) => `<option value="${name}" ${name === selected ? "selected" : ""}>${escapeHTML(artifactIconLabels[name])}</option>`).join("");
}
function sanitizeRichHTMLClient(rawHTML, artifactId, publicMode = false) {
  const template = document.createElement("template");
  template.innerHTML = String(rawHTML || "");
  [...template.content.querySelectorAll("*")].forEach((element) => {
    if (!richTextTags.has(element.tagName)) {
      if (["SCRIPT", "STYLE", "IFRAME", "OBJECT"].includes(element.tagName)) element.remove();
      else element.replaceWith(...element.childNodes);
      return;
    }
    const attributes = [...element.attributes];
    attributes.forEach((attribute) => element.removeAttribute(attribute.name));
    if (element.tagName === "SPAN") {
      const icon = attributes.find((item) => item.name.toLowerCase() === "data-icon")?.value || "";
      if (!artifactIconNames.includes(icon)) { element.replaceWith(...element.childNodes); return; }
      element.setAttribute("data-icon", icon);
      element.setAttribute("class", `artifact-icon artifact-icon-${icon}`);
      element.setAttribute("aria-hidden", "true");
    }
    if (element.tagName === "A") {
      const href = attributes.find((item) => item.name.toLowerCase() === "href")?.value || "";
      if (/^(https?:\/\/|mailto:|#)/i.test(href)) {
        element.setAttribute("href", href);
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
      }
    }
    if (element.tagName === "IMG") {
      const source = attributes.find((item) => item.name.toLowerCase() === "src")?.value || "";
      const escapedId = String(artifactId).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const match = source.match(new RegExp(`^/api/(?:research|public)/artifacts/${escapedId}/images/([0-9a-f]{64}\\.(?:png|jpg|webp))$`));
      if (!match) { element.remove(); return; }
      const area = publicMode ? "public" : "research";
      element.setAttribute("src", `/api/${area}/artifacts/${artifactId}/images/${match[1]}`);
      ["alt", "title"].forEach((name) => {
        const value = attributes.find((item) => item.name.toLowerCase() === name)?.value;
        if (value) element.setAttribute(name, value.slice(0, 300));
      });
      element.setAttribute("loading", "lazy");
    }
  });
  return template.innerHTML;
}
function plainTextToEditorHTML(text = "") {
  const normalized = String(text || "").replace(/\r\n?/g, "\n").trim();
  if (!normalized) return "<p><br></p>";
  return normalized.split(/\n{2,}/).map((paragraph) => `<p>${escapeHTML(paragraph).replaceAll("\n", "<br>")}</p>`).join("");
}
function advancedArtifactJSON(artifact, optional = false) {
  const field = `<textarea name="content" rows="14">${escapeHTML(jsonText(artifact.content))}</textarea>`;
  if (!optional) return `<label>内容 JSON${field}</label>`;
  return `<details class="advanced-artifact-json"><summary>高级 JSON</summary><p>仅在需要调整底层字段时使用。勾选后，保存会以此处 JSON 覆盖可视化编辑器内容。</p><label class="advanced-json-toggle"><input type="checkbox" name="useAdvancedContent">保存时使用高级 JSON</label><label>完整内容${field}</label></details>`;
}
function recordTableEditorHTML(content = {}) {
  const columns = Array.isArray(content.columns) && content.columns.length ? content.columns.map(String) : ["卜辞", "著录", "年代", "状态", "争议"];
  const rows = Array.isArray(content.rows) ? content.rows : [];
  return `<section class="artifact-editor record-table-editor" data-record-table-editor><div class="artifact-editor-head"><div><strong>在线表格</strong><small>${rows.length} 行 · ${columns.length} 列，单元格支持换行</small></div><div class="artifact-editor-actions"><button type="button" data-table-action="add-row">＋ 行</button><button type="button" data-table-action="add-column">＋ 列</button></div></div><div class="record-table-scroll"><table><thead><tr><th class="record-row-number">序</th>${columns.map((column, index) => `<th><div class="record-column-head"><input value="${escapeHTML(column)}" data-table-column="${index}" aria-label="第${index + 1}列列名"><button type="button" data-table-column-delete="${index}" title="删除此列" aria-label="删除${escapeHTML(column)}列">×</button></div></th>`).join("")}<th class="record-row-command"><span class="sr-only">行操作</span></th></tr></thead><tbody>${rows.map((row, rowIndex) => `<tr><th class="record-row-number">${rowIndex + 1}</th>${columns.map((column, columnIndex) => `<td><textarea data-table-cell data-row="${rowIndex}" data-column="${columnIndex}" aria-label="第${rowIndex + 1}行${escapeHTML(column)}">${escapeHTML(row?.[column] ?? "")}</textarea></td>`).join("")}<td class="record-row-command"><button type="button" data-table-row-delete="${rowIndex}" title="删除此行" aria-label="删除第${rowIndex + 1}行">×</button></td></tr>`).join("")}</tbody></table></div>${rows.length ? "" : '<div class="record-table-empty">表格暂无记录，点击“＋ 行”开始填写。</div>'}<small class="editor-boundary">保存后作品将回到待审核；来源关系不会因表格编辑而改变。</small></section>`;
}
function richVisualPlansHTML(artifact) {
  const visuals = Array.isArray(artifact.content?.visuals) ? artifact.content.visuals : [];
  if (!visuals.length) return '<div class="rich-visual-plan-empty">当前作品没有待生成的配图计划，可在工具栏使用“AI 配图”输入自定义提示词。</div>';
  return visuals.map((visual, index) => `<article class="rich-visual-plan"><div><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHTML(visual.afterHeading || "当前位置")}</strong><p>${escapeHTML(visual.caption || visual.alt || "科普内容配图")}</p></div><button type="button" data-rich-generate-image data-visual-id="${escapeHTML(visual.id || `visual-${index + 1}`)}">生成并插入</button></article>`).join("");
}
function richTextEditorHTML(artifact) {
  const storedHTML = typeof artifact.content?.html === "string" ? artifact.content.html : plainTextToEditorHTML(artifact.content?.text || "");
  const safeHTML = sanitizeRichHTMLClient(storedHTML, artifact.id);
  return `<section class="artifact-editor rich-text-editor" data-rich-editor-shell data-artifact-id="${escapeHTML(artifact.id)}"><div class="artifact-editor-head"><div><strong>图文正文</strong><small>富文本、受控图标与按位置生成配图</small></div><span class="editor-save-state">编辑后请保存</span></div><div class="rich-editor-toolbar" role="toolbar" aria-label="图文编辑工具"><button type="button" data-rich-command="undo" title="撤销" aria-label="撤销">↶</button><button type="button" data-rich-command="redo" title="重做" aria-label="重做">↷</button><span class="toolbar-divider"></span><select data-rich-block title="段落样式" aria-label="段落样式"><option value="p">正文</option><option value="h2">二级标题</option><option value="h3">三级标题</option><option value="blockquote">引用</option></select><button type="button" class="format-letter" data-rich-command="bold" title="加粗" aria-label="加粗"><strong>B</strong></button><button type="button" class="format-letter" data-rich-command="italic" title="斜体" aria-label="斜体"><em>I</em></button><button type="button" data-rich-command="insertUnorderedList" title="无序列表" aria-label="无序列表">•≡</button><button type="button" data-rich-command="insertOrderedList" title="有序列表" aria-label="有序列表">1≡</button><button type="button" data-rich-command="createLink" title="插入链接" aria-label="插入链接">↗</button><span class="toolbar-divider"></span><select data-rich-icon-select title="插入图标" aria-label="选择图标">${artifactIconOptions()}</select><button type="button" data-rich-insert-icon title="插入所选图标" aria-label="插入图标">${artifactIconHTML("sparkles")}</button><button type="button" data-rich-image-trigger title="上传图片" aria-label="上传图片">▧</button><button type="button" class="rich-ai-image-button" data-rich-generate-image title="百炼生成并插入配图">AI 配图</button><button type="button" data-rich-command="removeFormat" title="清除格式" aria-label="清除格式">Tx</button><input type="file" data-rich-image accept="image/png,image/jpeg,image/webp" hidden></div><div class="rich-editor-canvas" contenteditable="true" role="textbox" aria-multiline="true" spellcheck="true">${safeHTML}</div><details class="rich-visual-plans" ${Array.isArray(artifact.content?.visuals) && artifact.content.visuals.length ? "open" : ""}><summary>配图计划 · ${Array.isArray(artifact.content?.visuals) ? artifact.content.visuals.length : 0}</summary><div>${richVisualPlansHTML(artifact)}</div></details><small class="editor-boundary">图标来自受控 Lucide 集；AI配图和上传图片是作品派生资源，不进入证据库。生成或编辑后作品会回到待审核。</small></section>`;
}

function splitEditorLines(value) { return String(value || "").split("\n").map((item) => item.trim()).filter(Boolean); }
function slideDeckEditorHTML(artifact) {
  const content = artifact.content || {};
  const slides = Array.isArray(content.slides) ? content.slides : [];
  const playback = content.playback || {};
  const currentSlide = Math.max(0, Math.min(slides.length - 1, artifactPage(artifact, slides.length + 1) - 1));
  const slideHTML = slides.map((slide, index) => {
    const visual = slide.visual || {};
    const diagram = slide.diagram || {};
    const chart = slide.chart || {};
    const transition = slide.transition || {};
    const richText = Array.isArray(slide.richText) ? slide.richText.map((item) => `${item.lead || ""} | ${item.text || ""}`.replace(/^ \| /, "")).join("\n") : "";
    const diagramText = Array.isArray(diagram.nodes) ? diagram.nodes.map((item) => `${item.label || ""} | ${item.detail || ""}`).join("\n") : "";
    const seriesText = Array.isArray(chart.series) ? chart.series.map((item) => `${item.name || "数值"} | ${(item.values || []).join(", ")}`).join("\n") : "";
    return `<details class="slide-editor-page" data-slide-editor-page data-slide-index="${index}" ${index === currentSlide ? "open" : ""}><summary><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHTML(slide.title || `第${index + 1}页`)}</strong><small>${escapeHTML(slide.layout || "statement")}</small></summary><div class="slide-editor-grid"><label class="slide-field-wide">结论式标题<input data-slide-field="title" value="${escapeHTML(slide.title || "")}" maxlength="180"></label><label class="slide-field-wide">核心结论<textarea data-slide-field="takeaway" rows="2">${escapeHTML(slide.takeaway || "")}</textarea></label><label>版式<select data-slide-field="layout">${["statement", "image-right", "image-left", "process", "comparison", "chart", "quote"].map((value) => `<option value="${value}" ${slide.layout === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>图标<select data-slide-field="icon">${artifactIconOptions(slide.icon)}</select></label><label class="slide-field-wide">富文本段落 <small>每行：引导词 | 正文</small><textarea data-slide-field="richText" rows="4">${escapeHTML(richText)}</textarea></label><label class="slide-field-wide">要点 <small>每行一项</small><textarea data-slide-field="bullets" rows="4">${escapeHTML((slide.bullets || []).join("\n"))}</textarea></label><fieldset class="slide-visual-editor slide-field-wide"><legend>页面配图</legend><label>配图提示词<textarea data-slide-field="visualPrompt" rows="3">${escapeHTML(visual.prompt || "")}</textarea></label><div class="slide-two-fields"><label>替代文字<input data-slide-field="visualAlt" value="${escapeHTML(visual.alt || "")}"></label><label>图注<input data-slide-field="visualCaption" value="${escapeHTML(visual.caption || "")}"></label></div><div class="slide-generated-media">${visual.asset ? `<img src="/api/research/artifacts/${encodeURIComponent(artifact.id)}/images/${escapeHTML(visual.asset)}" alt="${escapeHTML(visual.alt || "页面配图")}" loading="lazy">` : '<span>尚未生成页面配图</span>'}<button type="button" data-generate-slide-image data-id="${escapeHTML(artifact.id)}" data-slide="${index}">${visual.asset ? "重新生成" : "生成当前页配图"}</button></div></fieldset><fieldset><legend>智能图形</legend><label>流程节点 <small>每行：节点 | 说明</small><textarea data-slide-field="diagramNodes" rows="5">${escapeHTML(diagramText)}</textarea></label></fieldset><fieldset><legend>数据图表</legend><label>类型<select data-slide-field="chartType"><option value="">不使用图表</option>${["bar", "line", "pie", "doughnut"].map((value) => `<option value="${value}" ${chart.type === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>图表标题<input data-slide-field="chartTitle" value="${escapeHTML(chart.title || "")}"></label><label>分类 <small>用 | 分隔</small><input data-slide-field="chartCategories" value="${escapeHTML((chart.categories || []).join(" | "))}"></label><label>系列 <small>每行：名称 | 数值, 数值</small><textarea data-slide-field="chartSeries" rows="4">${escapeHTML(seriesText)}</textarea></label></fieldset><label class="slide-field-wide">讲者备注<textarea data-slide-field="speakerNotes" rows="3">${escapeHTML(slide.speakerNotes || "")}</textarea></label><label class="slide-field-wide">资料依据 <small>每行一项</small><textarea data-slide-field="citations" rows="3">${escapeHTML((slide.citations || []).join("\n"))}</textarea></label><fieldset class="slide-transition-editor slide-field-wide"><legend>播放与转场</legend><label>转场<select data-slide-field="transitionType">${["none", "fade", "push", "wipe", "split", "cover"].map((value) => `<option value="${value}" ${transition.type === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>时长（秒）<input type="number" min="0.2" max="3" step="0.1" data-slide-field="transitionDuration" value="${Number(transition.duration || 0.7)}"></label><label>自动换页（秒）<input type="number" min="3" max="60" step="1" data-slide-field="advanceAfter" value="${Number(transition.advanceAfter || playback.seconds || 8)}"></label></fieldset></div></details>`;
  }).join("");
  return `<section class="artifact-editor slide-deck-editor" data-slide-deck-editor><div class="artifact-editor-head"><div><strong>增强幻灯片</strong><small>${slides.length} 页正文 · 富文本、图标、配图、智能图形、图表与转场</small></div><span class="editor-save-state">编辑后请保存</span></div><div class="slide-deck-settings"><label>副标题<input data-deck-field="subtitle" value="${escapeHTML(content.subtitle || "")}"></label><label class="slide-playback-check"><input type="checkbox" data-deck-field="autoAdvance" ${playback.autoAdvance ? "checked" : ""}>自动播放</label><label>默认换页秒数<input type="number" min="3" max="60" data-deck-field="seconds" value="${Number(playback.seconds || 8)}"></label><label class="slide-playback-check"><input type="checkbox" data-deck-field="loop" ${playback.loop ? "checked" : ""}>循环播放</label><label>默认转场<select data-deck-field="transition">${["none", "fade", "push", "wipe", "split", "cover"].map((value) => `<option value="${value}" ${playback.transition === value ? "selected" : ""}>${value}</option>`).join("")}</select></label></div><div class="slide-editor-pages">${slideHTML}</div><small class="editor-boundary">只有资料明确提供真实数值时才使用图表；机制、流程与证据链使用可编辑智能图形。生成配图后作品自动回到待审核。</small></section>`;
}
function boardNodeTypeLabel(type) { return ({ note: "研究笔记", evidence: "证据", source: "资料", artifact: "作品" })[type] || "研究笔记"; }
function boardReferenceSummary(node) {
  const reference = node.reference || {};
  if (!reference.type && !reference.label && !reference.id) return "未绑定来源";
  const label = reference.label || reference.id || "已绑定引用";
  return `${label}${reference.page ? ` · 第${reference.page}页` : ""}`;
}
function boardNodeHTML(node, selected = false, root = false) {
  const reference = node.reference || {};
  const type = ["note", "evidence", "source", "artifact"].includes(node.type) ? node.type : "note";
  return `<article class="board-node board-type-${escapeHTML(type)} board-color-${escapeHTML(node.color || "gold")} ${selected ? "is-selected" : ""} ${root ? "is-root" : ""}" data-board-node data-node-id="${escapeHTML(node.id)}" data-node-type="${escapeHTML(type)}" data-node-title-value="${escapeHTML(node.title || "")}" data-node-body-value="${escapeHTML(node.body || "")}" data-node-color="${escapeHTML(node.color || "gold")}" data-x="${Number(node.x) || 0}" data-y="${Number(node.y) || 0}" data-width="${Number(node.width) || 230}" data-height="${Number(node.height) || 140}" data-reference-type="${escapeHTML(reference.type || "")}" data-reference-id="${escapeHTML(reference.id || "")}" data-reference-label="${escapeHTML(reference.label || "")}" data-reference-page="${escapeHTML(reference.page || "")}" style="left:${Number(node.x) || 0}px;top:${Number(node.y) || 0}px;width:${Number(node.width) || 230}px;height:${Number(node.height) || 140}px"><header data-board-drag title="拖动节点"><span data-board-node-type-label>${escapeHTML(boardNodeTypeLabel(type))}</span><i aria-hidden="true">⠿</i></header><button type="button" class="board-node-content" data-board-node-select aria-label="编辑${escapeHTML(node.title || "节点")}"><strong data-board-node-title>${escapeHTML(node.title || "未命名节点")}</strong><p data-board-node-body>${escapeHTML(node.body || "添加研究说明")}</p><small data-board-node-reference>${escapeHTML(boardReferenceSummary(node))}</small></button></article>`;
}
function boardEdgeGeometry(source, target) {
  const sourceX = Number(source.x) + Number(source.width) / 2;
  const sourceY = Number(source.y) + Number(source.height) / 2;
  const targetX = Number(target.x) + Number(target.width) / 2;
  const targetY = Number(target.y) + Number(target.height) / 2;
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  if (Math.abs(dx) >= Math.abs(dy)) {
    const direction = dx >= 0 ? 1 : -1;
    const x1 = sourceX + direction * Number(source.width) / 2;
    const x2 = targetX - direction * Number(target.width) / 2;
    const bend = Math.max(48, Math.abs(x2 - x1) * 0.48);
    return { x1, y1: sourceY, x2, y2: targetY, path: `M ${x1} ${sourceY} C ${x1 + direction * bend} ${sourceY}, ${x2 - direction * bend} ${targetY}, ${x2} ${targetY}` };
  }
  const direction = dy >= 0 ? 1 : -1;
  const y1 = sourceY + direction * Number(source.height) / 2;
  const y2 = targetY - direction * Number(target.height) / 2;
  const bend = Math.max(42, Math.abs(y2 - y1) * 0.48);
  return { x1: sourceX, y1, x2: targetX, y2, path: `M ${sourceX} ${y1} C ${sourceX} ${y1 + direction * bend}, ${targetX} ${y2 - direction * bend}, ${targetX} ${y2}` };
}
function boardEdgeSVG(edge, nodes) {
  const source = nodes.find((node) => node.id === edge.from);
  const target = nodes.find((node) => node.id === edge.to);
  if (!source || !target) return "";
  const geometry = boardEdgeGeometry(source, target);
  return `<g data-board-edge="${escapeHTML(edge.id)}" data-from="${escapeHTML(edge.from)}" data-to="${escapeHTML(edge.to)}" data-label="${escapeHTML(edge.label || "")}"><path d="${geometry.path}" marker-end="url(#board-arrow)"></path>${edge.label ? `<text x="${(geometry.x1 + geometry.x2) / 2}" y="${(geometry.y1 + geometry.y2) / 2 - 9}">${escapeHTML(edge.label)}</text>` : ""}</g>`;
}
function boardPreset(width, height) {
  const key = `${Math.round(width)}x${Math.round(height)}`;
  return ({ "1200x760": "desktop", "1600x900": "wide", "900x1400": "portrait", "2200x1400": "large" })[key] || "custom";
}
function boardSizeMenuHTML(width, height) {
  const preset = boardPreset(width, height);
  return `<details class="board-size-menu"><summary title="调整版面大小"><span aria-hidden="true">▣</span><span data-board-size-label>${Math.round(width)} × ${Math.round(height)}</span></summary><div class="board-size-popover"><label>版面预设<select data-board-preset><option value="desktop" ${preset === "desktop" ? "selected" : ""}>研究桌面 · 1200 × 760</option><option value="wide" ${preset === "wide" ? "selected" : ""}>演示宽屏 · 1600 × 900</option><option value="portrait" ${preset === "portrait" ? "selected" : ""}>纵向长图 · 900 × 1400</option><option value="large" ${preset === "large" ? "selected" : ""}>大型研究图 · 2200 × 1400</option><option value="custom" ${preset === "custom" ? "selected" : ""}>自定义</option></select></label><div class="board-size-fields"><label>宽<input type="number" min="720" max="4000" step="20" value="${Math.round(width)}" data-board-size-input="width"></label><span>×</span><label>高<input type="number" min="480" max="3000" step="20" value="${Math.round(height)}" data-board-size-input="height"></label></div><button type="button" data-board-action="resize">应用版面</button><small>节点超出新边界时会自动收回，不改变内容和来源关系。</small></div></details>`;
}
function boardPropertiesHTML(node, artifact, edges = []) {
  if (!node) return '<div class="board-properties-empty">选择节点后编辑属性和引用。</div>';
  const reference = node.reference || {};
  const sourceOptions = [...new Map((artifact.sources || []).map((source) => [source.source_id, source])).values()].map((source) => `<option value="${escapeHTML(source.source_id)}">${escapeHTML(source.source_title || source.source_id)}</option>`).join("");
  const relations = edges.filter((edge) => edge.from === node.id || edge.to === node.id);
  return `<div class="board-properties-head"><div><span>节点属性</span><strong>${escapeHTML(node.title || "未命名节点")}</strong></div><button type="button" data-board-node-delete title="删除节点" aria-label="删除节点">×</button></div><label>标题<input data-board-property="title" value="${escapeHTML(node.title || "")}" maxlength="160"></label><label>说明<textarea data-board-property="body" rows="5" maxlength="4000">${escapeHTML(node.body || "")}</textarea></label><div class="board-property-grid"><label>类型<select data-board-property="type"><option value="note" ${node.type === "note" ? "selected" : ""}>研究笔记</option><option value="evidence" ${node.type === "evidence" ? "selected" : ""}>证据</option><option value="source" ${node.type === "source" ? "selected" : ""}>资料</option><option value="artifact" ${node.type === "artifact" ? "selected" : ""}>作品</option></select></label><label>颜色<select data-board-property="color"><option value="gold" ${node.color === "gold" ? "selected" : ""}>金色</option><option value="blue" ${node.color === "blue" ? "selected" : ""}>蓝色</option><option value="green" ${node.color === "green" ? "selected" : ""}>绿色</option><option value="red" ${node.color === "red" ? "selected" : ""}>红色</option><option value="gray" ${node.color === "gray" ? "selected" : ""}>灰色</option></select></label></div><div class="board-reference-fields"><strong>引用绑定</strong><div class="board-property-grid"><label>引用类型<select data-board-property="referenceType"><option value="" ${!reference.type ? "selected" : ""}>不绑定</option><option value="source" ${reference.type === "source" ? "selected" : ""}>资料</option><option value="knowledge" ${reference.type === "knowledge" ? "selected" : ""}>知识</option><option value="artifact" ${reference.type === "artifact" ? "selected" : ""}>作品</option></select></label><label>PDF页码<input data-board-property="referencePage" value="${escapeHTML(reference.page || "")}" maxlength="80"></label></div><label>引用编号<input data-board-property="referenceId" value="${escapeHTML(reference.id || "")}" list="board-source-options-${escapeHTML(artifact.id)}" maxlength="500"><datalist id="board-source-options-${escapeHTML(artifact.id)}">${sourceOptions}</datalist></label><label>显示名称<input data-board-property="referenceLabel" value="${escapeHTML(reference.label || "")}" maxlength="500"></label></div><div class="board-relations"><strong>节点关系</strong>${relations.length ? relations.map((edge) => `<div><input data-board-edge-label="${escapeHTML(edge.id)}" value="${escapeHTML(edge.label || "")}" placeholder="关系说明"><span>${escapeHTML(edge.from === node.id ? "指向" : "来自")} ${escapeHTML(edge.from === node.id ? edge.to : edge.from)}</span><button type="button" data-board-edge-delete="${escapeHTML(edge.id)}" title="删除关系" aria-label="删除关系">×</button></div>`).join("") : "<small>尚无关系，点击工具栏的连接按钮后依次选择两个节点。</small>"}</div>`;
}
function boardEditorHTML(artifact) {
  const content = artifact.content || {};
  const nodes = Array.isArray(content.nodes) ? content.nodes : [];
  const edges = Array.isArray(content.edges) ? content.edges : [];
  const viewport = content.viewport || { width: 1200, height: 760 };
  const width = Math.max(720, Number(viewport.width) || 1200);
  const height = Math.max(480, Number(viewport.height) || 760);
  const zoom = state.boardZooms[artifact.id] || 0.8;
  const selected = nodes[0] || null;
  const edgeData = escapeHTML(JSON.stringify(edges));
  return `<section class="artifact-editor board-editor" data-board-editor data-artifact-id="${escapeHTML(artifact.id)}" data-layout="${escapeHTML(content.layout || (artifact.kind === "mind_map" ? "mind_map" : "free"))}" data-viewport-width="${width}" data-viewport-height="${height}" data-board-edges="${edgeData}" data-selected-node="${escapeHTML(selected?.id || "")}" data-board-zoom="${zoom}"><div class="artifact-editor-head board-editor-head"><div><strong>${artifact.kind === "mind_map" ? "思维导图" : "研究白板"}</strong><small>${nodes.length} 个节点 · ${edges.length} 条关系，引用不复制证据所有权</small></div><div class="artifact-editor-actions board-toolbar"><button type="button" data-board-action="add-note" title="添加研究笔记">＋ 笔记</button><button type="button" data-board-action="add-evidence" title="添加证据节点">＋ 证据</button><button type="button" data-board-action="connect" title="依次选择两个节点建立关系">⌁</button><button type="button" data-board-action="auto-layout" title="自动整理节点">排列</button>${boardSizeMenuHTML(width, height)}<button type="button" data-board-action="zoom-out" title="缩小" aria-label="缩小">−</button><button type="button" data-board-action="zoom-in" title="放大" aria-label="放大">＋</button><button type="button" data-board-action="fit" title="适合窗口" aria-label="适合窗口">↺</button><output data-board-zoom-label>${Math.round(zoom * 100)}%</output></div></div><div class="board-workspace"><div class="board-scroll"><div class="board-scaled" style="width:${width * zoom}px;height:${height * zoom}px"><div class="board-world" style="width:${width}px;height:${height}px;transform:scale(${zoom})"><svg class="board-edge-layer" viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><marker id="board-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs><g data-board-edge-content>${edges.map((edge) => boardEdgeSVG(edge, nodes)).join("")}</g></svg>${nodes.map((node, index) => boardNodeHTML(node, index === 0, artifact.kind === "mind_map" && index === 0)).join("")}</div></div></div><aside class="board-properties" data-board-properties>${boardPropertiesHTML(selected, artifact, edges)}</aside></div><div class="board-connect-hint" data-board-connect-hint>连接模式：先选择起点，再选择终点；再次点击连接按钮可退出。</div><small class="editor-boundary">白板是作品草稿。节点可以引用资料、知识或作品，但不会进入证据库；保存后作品回到待审核。</small></section>`;
}
function artifactEditorHTML(artifact) {
  if (artifact.kind === "record_table") return recordTableEditorHTML(artifact.content) + advancedArtifactJSON(artifact, true);
  if (artifact.kind === "slide_deck") return slideDeckEditorHTML(artifact) + advancedArtifactJSON(artifact, true);
  if (["whiteboard", "mind_map"].includes(artifact.kind)) return boardEditorHTML(artifact) + advancedArtifactJSON(artifact, true);
  if (typeof artifact.content?.text === "string" || typeof artifact.content?.html === "string") return richTextEditorHTML(artifact) + advancedArtifactJSON(artifact, true);
  return advancedArtifactJSON(artifact);
}

function renderMetrics() {
  const counts = state.dashboard?.counts || {};
  $("#metric-sources").textContent = counts.sources ?? 0;
  $("#metric-reviewed").textContent = `${counts.reviewedSources ?? 0} 已确认`;
  $("#metric-ocr").textContent = (counts.ocrPending ?? 0) + (counts.ocrProcessing ?? 0) + (counts.ocrNeedsReview ?? 0);
  $("#metric-ocr-note").textContent = `${counts.ocrProcessing ?? 0} 处理中 · ${counts.ocrNeedsReview ?? 0} 待确认`;
  $("#metric-candidates").textContent = counts.evidenceSources ?? counts.sources ?? 0;
  $("#metric-knowledge").textContent = counts.researchNotes ?? 0;
  $("#metric-artifacts").textContent = counts.draftArtifacts ?? 0;
  $("#metric-stale").textContent = counts.staleItems ?? 0;
  $("#nav-source-progress").textContent = `${counts.reviewedSources ?? 0} / 7`;
  $("#nav-progress-bar").style.width = `${Math.min(100, ((counts.reviewedSources ?? 0) / 7) * 100)}%`;
  const snapshot = state.dashboard?.latestSnapshot;
  $("#snapshot-id").textContent = snapshot?.id || "尚未发布";
  const countsMeta = snapshot?.item_counts || {};
  $("#snapshot-counts").textContent = snapshot ? `${countsMeta.records || 0} 条记录 · ${countsMeta.works || 0} 项作品` : "-";
}
function compactRows(items, type) {
  if (!items.length) return '<p class="empty-row">暂无内容</p>';
  return items.slice(0, 4).map((item) => `<article class="compact-row"><div><strong>${escapeHTML(entityTitle(item))}</strong><small>${escapeHTML(type === "source" ? item.kind.toUpperCase() : item.kind || item.knowledge_type || "")} · ${formatDate(item.updated_at)}</small></div>${statusChip(item.status)}</article>`).join("");
}

function sourceActions(source) {
  const actions = [];
  if (source.source_role === "generated_note") {
    actions.push(`<span class="note-boundary">非证据</span>`);
    actions.push(`<button class="delete" data-source-action="delete" data-id="${source.id}">删除</button>`);
    return actions.join("");
  }
  if (source.status === "parse_failed") actions.push(`<button data-source-action="parse" data-id="${source.id}">重试处理</button>`);
  if (source.kind === "pdf" && source.recognition_status === "ocr_failed" && hasCompleteOcrResult(source)) actions.push(`<button data-source-action="ocr-reassess" data-id="${source.id}">重新评估</button>`);
  if (source.kind === "pdf" && ["unverified", "ocr_pending", "ocr_failed"].includes(source.recognition_status)) actions.push(`<button data-source-action="ocr" data-id="${source.id}">${source.recognition_status === "ocr_failed" ? "重新OCR" : "OCR重建"}</button>`);
  if (source.status === "parsed" && source.recognition_status === "text_ready") actions.push(`<button data-source-action="review" data-id="${source.id}">确认资料</button>`);
  if (source.status === "reviewed") actions.push(`<button data-source-action="unreview" data-id="${source.id}">取消确认</button>`);
  actions.push(`<button class="delete" data-source-action="delete" data-id="${source.id}">删除</button>`);
  return actions.join("");
}
function noteCitationLinks(source) {
  const provenance = source.provenance || {};
  const citations = Array.isArray(provenance.citations) ? provenance.citations : [];
  const fallbackIds = Array.isArray(provenance.sourceIds) ? provenance.sourceIds : [];
  const items = citations.length ? citations : fallbackIds.map((sourceId) => ({ sourceId, locator: "", locatorType: "" }));
  const groups = new Map();
  items.forEach((citation) => {
    const sourceId = String(citation?.sourceId || "");
    const locator = String(citation?.locator || "");
    const linkedSource = state.sources.find((item) => item.id === sourceId);
    const locatorType = String(citation?.locatorType || (linkedSource?.kind === "pdf" ? "pdf_page" : "text_block"));
    if (!sourceId) return;
    const key = `${sourceId}\u0000${locatorType}`;
    if (!groups.has(key)) groups.set(key, { sourceId, locatorType, locators: [], labels: [] });
    const group = groups.get(key);
    if (locator && !group.locators.includes(locator)) group.locators.push(locator);
    if (citation?.label && !group.labels.includes(String(citation.label))) group.labels.push(String(citation.label));
  });
  const links = [...groups.values()].map((group) => {
    const { sourceId, locatorType, locators, labels } = group;
    const linkedSource = state.sources.find((item) => item.id === sourceId);
    const sourceTitle = linkedSource?.title || "原始资料";
    const locatorRange = compactLocatorValues(locators);
    const locationLabel = locatorRange
      ? `${locatorType === "pdf_page" ? "PDF第" : "原文分段"}${locatorRange}${locatorType === "pdf_page" ? "页" : ""}`
      : (labels.join("、") || "资料原文");
    const firstLocator = [...locators].sort((left, right) => {
      const leftNumber = Number(left), rightNumber = Number(right);
      if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
      return String(left).localeCompare(String(right), "zh-CN");
    })[0] || "";
    return `<button type="button" class="note-citation-link" data-note-source-id="${escapeHTML(sourceId)}" data-note-locator="${escapeHTML(firstLocator)}"><span><strong>${escapeHTML(sourceTitle)}</strong><small>${escapeHTML(locationLabel)}</small></span><span class="note-citation-action">查看原文</span></button>`;
  });
  return links.length ? `<div class="note-citation-list">${links.join("")}</div>` : '<p class="muted">该笔记没有保存可定位的原始资料引用。</p>';
}
async function openNoteCitation(button) {
  const sourceId = button.dataset.noteSourceId;
  const source = state.sources.find((item) => item.id === sourceId && item.source_role !== "generated_note");
  if (!source) return toast("引用的原始资料已删除或当前不可用", true);
  state.selected.source = sourceId;
  state.sourcePage = source.kind === "pdf" ? Math.max(1, Number(button.dataset.noteLocator) || 1) : 1;
  setSection("sources");
  renderSources();
  renderSourceInspector();
  await loadUnits(sourceId);
  document.querySelector("#source-inspector")?.scrollIntoView({ block: "start", behavior: "smooth" });
}
function renderSources() {
  $("#source-count").textContent = `${state.sources.length} 项`;
  $("#source-list").innerHTML = state.sources.length ? state.sources.map((source) => `<article class="entity-row ${state.selected.source === source.id ? "is-selected" : ""}" data-entity="source" data-id="${source.id}"><label class="entity-check"><input type="checkbox" data-check="source" value="${source.id}" ${state.checked.source.has(source.id) ? "checked" : ""}><span></span></label><button class="entity-main" data-select="source" data-id="${source.id}"><strong>${escapeHTML(source.title)}</strong><small>${escapeHTML(source.kind.toUpperCase())} · ${source.page_count || 0}${source.kind === "pdf" ? "页" : "段"} · ${formatDate(source.updated_at)}</small></button><div class="entity-side">${sourceWorkflowChip(source)}<div class="row-actions">${sourceActions(source)}</div></div></article>`).join("") : '<p class="empty-row">暂无资料</p>';
  const researchable = state.sources.filter((source) => source.source_role === "evidence" && source.status === "reviewed" && recognitionPublishable(source));
  $("#studio-source-list").innerHTML = researchable.length ? researchable.map((source) => `<label class="source-check"><input type="checkbox" name="studio-source" value="${source.id}" checked><span><strong>${escapeHTML(source.title)}</strong><small>来源已确认</small></span></label>`).join("") : '<span class="empty-row">暂无已确认资料，请先在资料库完成确认</span>';
  $("#source-selected-count").textContent = state.checked.source.size ? `已选 ${state.checked.source.size} 项` : "未选择";
}
function renderSourceInspector() {
  const source = state.sources.find((item) => item.id === state.selected.source);
  if (!source) { $("#source-inspector").innerHTML = '<div class="inspector-empty">选择一项资料查看质量状态、确认记录和依赖关系。</div>'; return; }
  if (source.source_role === "generated_note") {
    const provenance = source.provenance || {};
    $("#source-inspector").innerHTML = `<div class="inspector-head"><div><span class="eyebrow">AI研究笔记</span><h2>${escapeHTML(source.title)}</h2></div>${statusChip("generated_note")}</div><form class="inspector-form" data-form="source" data-id="${source.id}"><label>笔记标题<input name="title" value="${escapeHTML(source.title)}"></label><div class="research-ready-note">该笔记来自问答结果，仅作为研究记录保存，不作为证据、不参与资料问答、不进入公众快照。</div><div class="inspector-actions"><button type="submit">保存标题</button><button type="button" data-inspector-action="source-delete" data-id="${source.id}">删除笔记</button><button type="button" data-inspector-action="units" data-id="${source.id}">查看笔记正文</button></div></form><section class="inspector-subsection note-body-section"><strong>笔记正文</strong><div id="source-units" class="note-body-units"><p class="muted">正在读取保存的问答内容…</p></div></section><div class="inspector-subsection"><strong>依据资料</strong>${noteCitationLinks(source)}</div><div class="inspector-subsection"><strong>生成信息</strong><p class="muted">${escapeHTML(provenance.model || "本地模型")} · ${escapeHTML(provenance.question || "未记录问题")}</p></div>`;
    return;
  }
  const localMode = state.deploymentMode !== "public_demo";
  const unitLabel = localMode ? (source.kind === "pdf" ? `${source.page_count || 0} 个PDF页面` : `${source.page_count || 0} 个原文分段`) : "";
  const run = latestOcrRun(source.id);
  const quality = source.quality_report || {};
  const progress = localMode && run && ["queued", "processing"].includes(run.status) ? `<div class="ocr-progress"><div><strong>OCR识别进度</strong><span>${run.processed_pages || 0} / ${run.total_pages || source.page_count || 0} 页</span></div><progress value="${run.processed_pages || 0}" max="${run.total_pages || source.page_count || 1}"></progress><small>${escapeHTML(run.model || "百炼视觉OCR")} · 后台顺序处理</small></div>` : "";
  const problemPages = (quality.problemPageNumbers || []).length ? `；重点核对第 ${quality.problemPageNumbers.join("、")} 页` : "";
  const returnedPages = run ? Number(run.processed_pages || 0) : (quality.recognizedPages ?? quality.passedPages ?? "-");
  const totalPages = run ? Number(run.total_pages || source.page_count || 0) : (quality.pages ?? source.page_count ?? "-");
  const reviewSummary = Number(quality.reviewPages || 0) ? `；${quality.reviewPages} 页建议复核` : "";
  const failedSummary = Number(quality.failedPages || 0) ? `；${quality.failedPages} 页识别失败` : "";
  const qualityPanel = `<div class="quality-panel"><div><span title="衡量文字是否清晰可读，不代表学术内容已经核验">文本可读度</span><strong>${source.quality_score == null ? "待检测" : `${Math.round(Number(source.quality_score) * 100)}%`}</strong></div>${localMode ? `<div><span>${run ? "OCR已返回" : "可读页面"}</span><strong>${returnedPages} / ${totalPages}</strong></div>` : ""}<p>${escapeHTML((quality.reasons || []).join("；") || recognitionLabel(source.recognition_status))}</p></div>`;
  let recognitionActions = "";
  if (source.kind === "pdf" && source.recognition_status === "ocr_failed" && hasCompleteOcrResult(source)) recognitionActions += `<button class="command primary" type="button" data-inspector-action="ocr-reassess" data-id="${source.id}">重新评估已有文本</button>`;
  if (source.kind === "pdf" && ["unverified", "ocr_pending", "ocr_failed"].includes(source.recognition_status)) recognitionActions += `<button type="button" data-inspector-action="ocr" data-id="${source.id}">${source.recognition_status === "ocr_failed" ? "重新调用百炼OCR" : "开始百炼OCR"}</button>`;
  if (source.recognition_status === "ocr_needs_review") recognitionActions += `<button class="command primary" type="button" data-inspector-action="ocr-approve" data-id="${source.id}">确认OCR文本</button><button type="button" data-inspector-action="ocr-reject" data-id="${source.id}">退回重识别</button>`;
  const sourceReviewAction = source.status === "reviewed" ? `<button type="button" data-inspector-action="unreview" data-id="${source.id}">取消确认</button>` : source.status === "parsed" && source.recognition_status === "text_ready" ? `<button type="button" data-inspector-action="review" data-id="${source.id}">确认资料</button>` : "";
  const readyMessage = source.status !== "reviewed" ? "该资料尚未确认，可校核PDF与识别原文，但不会进入问答或输出。" : "来源已经确认，可用于资料问答、作品生成和公众发布审核。";
  const sourceFileUrl = `/api/research/source-file?sourceId=${encodeURIComponent(source.id)}`;
  const unitsAction = localMode && source.kind !== "pdf" ? `<button type="button" data-inspector-action="units" data-id="${source.id}">查看原文</button>` : "";
  const sourceMaterial = localMode && source.kind === "pdf" ? `<section class="pdf-review-workspace"><div class="pdf-viewer-pane"><div class="material-pane-head"><div><strong>PDF 原页</strong><small id="pdf-page-indicator">第 ${state.sourcePage} / ${source.page_count || 1} 页</small></div><div class="pdf-page-actions"><button type="button" data-pdf-step="-1" title="上一页" aria-label="上一页">←</button><button type="button" data-pdf-step="1" title="下一页" aria-label="下一页">→</button><a href="${sourceFileUrl}#page=${state.sourcePage}" target="_blank" rel="noreferrer">打开PDF</a></div></div><div class="pdf-page-stage"><img id="source-pdf-page" src="/api/research/source-page?sourceId=${encodeURIComponent(source.id)}&page=${state.sourcePage}" alt="${escapeHTML(source.title)}第${state.sourcePage}页"></div></div><div class="pane-resizer nested-pane-resizer" data-pane-resizer="pdfViewer" role="separator" aria-label="调整PDF原页与识别文本宽度" aria-orientation="vertical" aria-valuemin="32" aria-valuemax="72" aria-valuenow="${Math.round(state.pdfViewerWidth)}" tabindex="0"></div><div class="pdf-text-pane"><div class="material-pane-head"><div><strong>页码与原文</strong><small>点击页码，两侧同步切换</small></div></div><div id="source-units" class="source-unit-list"><p class="muted">正在读取当前解析版本…</p></div></div></section>` : localMode ? `<div id="source-units" class="inspector-subsection"><p class="muted">查看当前解析版本的原文、提取方式和质量分数。</p></div>` : `<section class="inspector-subsection"><p class="muted">公网演示模式不显示 PDF 原文、OCR 文本和页码。</p></section>`;
  $("#source-inspector").innerHTML = `<div class="inspector-head"><div><span class="eyebrow">资料详情</span><h2>${escapeHTML(source.title)}</h2></div><div class="inspector-statuses">${sourceWorkflowChip(source)}</div></div><form class="inspector-form" data-form="source" data-id="${source.id}"><label>资料标题<input name="title" value="${escapeHTML(source.title)}"></label><div class="inspector-meta"><span>${escapeHTML(source.kind.toUpperCase())}</span><span>${escapeHTML(unitLabel)}</span><span>解析版本 ${source.parse_version || 0}</span></div>${qualityPanel}${progress}<p class="research-ready-note">${escapeHTML(readyMessage)}</p><div class="inspector-actions"><button type="submit">保存标题</button>${recognitionActions}${sourceReviewAction}${unitsAction}<button type="button" data-inspector-action="reviews" data-review-type="source" data-id="${source.id}">确认记录</button></div><details class="advanced-source-actions"><summary>高级操作</summary><p>原始文本层重新处理只用于诊断；PDF乱码应优先使用OCR重建。任何来源版本变化都会使依赖知识和作品转为“需重新复核”。</p><button type="button" data-inspector-action="reparse" data-id="${source.id}">重新提取PDF文本层</button></details></form>${sourceMaterial}<div id="source-review-history" class="inspector-subsection"></div>`;
  ensurePdfZoomControls();
}

function artifactContentPreview(artifact) { const content = artifact.content || {}; if (["whiteboard", "mind_map"].includes(artifact.kind)) return `${artifact.kind === "mind_map" ? "思维导图" : "研究白板"} · ${(content.nodes || []).length} 个节点`; if (Array.isArray(content.rows)) return `记录表 · ${content.rows.length} 行`; if (Array.isArray(content.items)) return `观点对照 · ${content.items.length} 条`; if (Array.isArray(content.cards)) return `科普图卡 · ${content.cards.length} 张`; if (Array.isArray(content.slides)) return `讲解幻灯片 · ${content.slides.length + 1} 页`; if (Array.isArray(content.scenes)) return `可播放视频 · ${content.scenes.length} 个镜头`; if (artifact.kind === "audio_guide") return `正式音频 · ${String(content.text || "").length} 字文稿`; return String(content.text || "").slice(0, 90); }
function artifactPage(artifact, total) {
  const current = Number(state.artifactPages[artifact.id] || 0);
  return Math.max(0, Math.min(Math.max(0, total - 1), current));
}
function artifactPager(artifact, total, current) {
  if (!total) return "";
  return `<div class="artifact-reader-controls"><button type="button" data-artifact-page-step="-1" data-id="${escapeHTML(artifact.id)}" ${current === 0 ? "disabled" : ""} title="上一页" aria-label="上一页">←</button><div class="artifact-reader-pages" aria-label="选择页面">${Array.from({ length: total }, (_, index) => `<button type="button" data-artifact-page-index="${index}" data-id="${escapeHTML(artifact.id)}" class="${index === current ? "is-active" : ""}" aria-label="第${index + 1}页" aria-current="${index === current ? "page" : "false"}">${index + 1}</button>`).join("")}</div><span>${current + 1} / ${total}</span><button type="button" data-artifact-page-step="1" data-id="${escapeHTML(artifact.id)}" ${current === total - 1 ? "disabled" : ""} title="下一页" aria-label="下一页">→</button></div>`;
}
function compactLocatorValues(values) {
  const numeric = [...new Set((values || []).filter((value) => /^\d+$/.test(String(value))).map(Number))].sort((a, b) => a - b);
  const other = [...new Set((values || []).map(String).filter((value) => value && !/^\d+$/.test(value)))];
  const ranges = [];
  if (numeric.length) {
    let start = numeric[0], previous = numeric[0];
    numeric.slice(1).forEach((value) => { if (value === previous + 1) { previous = value; return; } ranges.push(start === previous ? String(start) : `${start}~${previous}`); start = previous = value; });
    ranges.push(start === previous ? String(start) : `${start}~${previous}`);
  }
  return [...ranges, ...other].join("、");
}
function groupArtifactSources(artifact) {
  if (Array.isArray(artifact.source_groups) && artifact.source_groups.length) return artifact.source_groups;
  const groups = new Map();
  (artifact.sources || []).forEach((source) => {
    const key = [source.source_id, source.source_title, source.source_status, source.source_recognition_status].join("\u0000");
    if (!groups.has(key)) groups.set(key, { ...source, locator_values: [] });
    if (source.locator_type && groups.get(key).locator_type && source.locator_type !== groups.get(key).locator_type) groups.get(key).locator_type = "mixed";
    if (source.locator_value && !groups.get(key).locator_values.includes(String(source.locator_value))) groups.get(key).locator_values.push(String(source.locator_value));
  });
  return [...groups.values()].map((group) => ({ ...group, locator_range: compactLocatorValues(group.locator_values) }));
}
function slideChartPreviewHTML(chart = {}) {
  const categories = Array.isArray(chart.categories) ? chart.categories : [];
  const series = Array.isArray(chart.series) ? chart.series : [];
  if (!chart.type || categories.length < 2 || !series.length) return "";
  const values = series[0].values || [];
  const maximum = Math.max(1, ...values.map((value) => Math.abs(Number(value) || 0)));
  if (["pie", "doughnut"].includes(chart.type)) {
    const total = values.reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0) || 1;
    let cursor = 0;
    const colors = ["#bd9132", "#256e68", "#a94235", "#476b93", "#5e6a75"];
    const stops = values.map((value, index) => { const start = cursor; cursor += Math.max(0, Number(value) || 0) / total * 360; return `${colors[index % colors.length]} ${start}deg ${cursor}deg`; }).join(",");
    return `<figure class="slide-chart-preview is-${escapeHTML(chart.type)}"><figcaption>${escapeHTML(chart.title || "资料数据")}</figcaption><div class="slide-pie" style="background:conic-gradient(${stops})"><i></i></div><ol>${categories.map((category, index) => `<li><span style="background:${colors[index % colors.length]}"></span>${escapeHTML(category)} <strong>${escapeHTML(values[index] ?? 0)}</strong></li>`).join("")}</ol></figure>`;
  }
  return `<figure class="slide-chart-preview is-${escapeHTML(chart.type)}"><figcaption>${escapeHTML(chart.title || "资料数据")}</figcaption><div class="slide-bars">${categories.map((category, index) => `<div><span style="--bar:${Math.max(4, Math.abs(Number(values[index]) || 0) / maximum * 100)}%"></span><small>${escapeHTML(category)}</small><strong>${escapeHTML(values[index] ?? 0)}</strong></div>`).join("")}</div></figure>`;
}
function slideDiagramPreviewHTML(diagram = {}) {
  const nodes = Array.isArray(diagram.nodes) ? diagram.nodes : [];
  if (!nodes.length) return "";
  return `<div class="slide-process-preview">${nodes.map((node, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHTML(node.label || "节点")}</strong><small>${escapeHTML(node.detail || "")}</small></article>`).join('<i aria-hidden="true">→</i>')}</div>`;
}
function researchSlidePageHTML(artifact, page, current) {
  if (page.cover) return `<div class="slide-cover-copy"><span>甲骨里的日光缺口</span><h3>${escapeHTML(slidePlainText(page.title) || "讲解幻灯片")}</h3><p>${escapeHTML(slidePlainText(page.subtitle) || "基于已确认资料生成的可审核讲解幻灯片")}</p></div>`;
  const bullets = (Array.isArray(page.bullets) ? page.bullets : []).map(slidePlainText).filter(Boolean);
  const rich = Array.isArray(page.richText) ? page.richText : [];
  const citations = (Array.isArray(page.citations) ? page.citations : [page.citations]).map(slidePlainText).filter(Boolean).slice(0, 3);
  const visual = page.visual || {};
  const image = visual.asset ? `<figure class="slide-page-image"><img src="/api/research/artifacts/${encodeURIComponent(artifact.id)}/images/${escapeHTML(visual.asset)}" alt="${escapeHTML(slidePlainText(visual.alt) || "页面配图")}" loading="lazy"><figcaption>${escapeHTML(slidePlainText(visual.caption))}</figcaption></figure>` : "";
  const diagram = slideDiagramPreviewHTML(page.diagram);
  const chart = slideChartPreviewHTML(page.chart);
  const visualHTML = image || chart || diagram;
  const title = slidePlainText(page.title) || `第${current}页`;
  const takeaway = slidePlainText(page.takeaway);
  const textHTML = `<div class="slide-copy-column"><div class="slide-title-row">${artifactIconHTML(page.icon)}<span>${String(current).padStart(2, "0")}</span></div><h3>${escapeHTML(title)}</h3>${takeaway ? `<p class="slide-takeaway">${escapeHTML(takeaway)}</p>` : ""}${rich.length ? `<div class="slide-rich-lines">${rich.map((item) => { const lead = slidePlainText(item?.lead); const text = slidePlainText(item?.text); return `<p>${lead ? `<strong>${escapeHTML(lead)}</strong>` : ""}${escapeHTML(text)}</p>`; }).join("")}</div>` : `<ul>${bullets.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>`}</div>`;
  return `<div class="slide-page-layout layout-${escapeHTML(page.layout || "statement")} ${slideDensityClass(page)}">${textHTML}${visualHTML ? `<div class="slide-visual-column">${visualHTML}</div>` : ""}<small class="slide-citations">资料依据：${escapeHTML(citations.join("；") || "页码待补充")}</small></div>`;
}
function artifactMediaPreview(artifact) {
  const content = artifact.content || {};
  if (artifact.kind === "audio_guide") {
    const audioUrl = `/api/research/artifacts/${encodeURIComponent(artifact.id)}/export?format=wav`;
    const speech = state.artifactKinds.find((item) => item.id === "audio_guide")?.export || {};
    return `<section class="media-preview audio-media-preview"><div class="media-preview-head"><div><span>正式音频作品</span><strong>百炼语音 · WAV</strong></div><small>${escapeHTML(speech.model || "qwen3-tts-flash")} · ${escapeHTML(speech.voice || "Cherry")}</small></div><div class="audio-player-row"><audio controls preload="none" src="${audioUrl}">当前浏览器不支持音频播放。</audio><a class="audio-player-download" href="${audioUrl}" download>下载 WAV</a></div></section>`;
  }
  if (artifact.kind === "visual_card_set") {
    const cards = Array.isArray(content.cards) ? content.cards : [];
    if (!cards.length) return '<section class="media-preview"><p class="muted">图卡内容待补充</p></section>';
    const current = artifactPage(artifact, cards.length);
    const card = cards[current] || {};
    const imageExport = state.artifactKinds.find((item) => item.id === "visual_card_set")?.export || {};
    const imageModel = imageExport.model || "wan2.2-t2i-flash";
    const revision = state.artifactMediaRevision[artifact.id] || artifact.updated_at || "current";
    const canGenerate = imageExport.generationMode === "explicit-per-card" && imageExport.reviewOnGenerate === true;
    const generateAction = canGenerate ? `<button type="button" class="generate-card-image" data-generate-card-image data-id="${escapeHTML(artifact.id)}" data-card="${current}">百炼生成当前插图</button>` : '<span class="media-restart-note">重启服务后可生成百炼插图</span>';
    const previewUrl = `/api/research/artifacts/${encodeURIComponent(artifact.id)}/export?card=${current}&v=${encodeURIComponent(revision)}`;
    const title = card.title || `图卡 ${current + 1}`;
    const body = Array.isArray(card.body) ? card.body : [card.body || "内容待补充"];
    const evidence = card.evidence || card.citations || [];
    const evidenceText = (Array.isArray(evidence) ? evidence : [evidence]).join("；") || "页码待补充";
    return `<section class="media-preview artifact-reader"><div class="media-preview-head"><div><span>科普图卡在线阅读</span><strong>${escapeHTML(title)}</strong></div><small>${canGenerate ? `百炼 ${escapeHTML(imageModel)} 插图 · ` : ""}WebP 轻量预览</small></div><div class="artifact-reader-stage visual-card-reader"><picture><source srcset="${previewUrl}&format=webp" type="image/webp"><img src="${previewUrl}&format=png" alt="${escapeHTML(title)}" width="1080" height="1350" loading="lazy" decoding="async"></picture></div><section class="artifact-card-copy" aria-label="图卡文字版"><strong>${escapeHTML(title)}</strong><ul>${body.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul><small>资料依据：${escapeHTML(evidenceText)}</small></section><div class="artifact-reader-footer">${artifactPager(artifact, cards.length, current)}${generateAction}</div></section>`;
  }
  if (artifact.kind === "slide_deck") {
    const slides = Array.isArray(content.slides) ? content.slides : [];
    if (!slides.length) return '<section class="media-preview"><p class="muted">幻灯片内容待补充</p></section>';
    const pages = [{ cover: true, title: artifact.title, subtitle: content.subtitle }, ...slides];
    const current = artifactPage(artifact, pages.length);
    const page = pages[current] || {};
    const transition = page.transition?.type || content.playback?.transition || "fade";
    const playing = state.artifactSlidesPlaying.has(artifact.id);
    const notes = !page.cover && page.speakerNotes ? `<details class="slide-speaker-notes"><summary>讲者备注</summary><p>${escapeHTML(page.speakerNotes)}</p></details>` : "";
    return `<section class="media-preview artifact-reader"><div class="media-preview-head"><div><span>幻灯片在线演示</span><strong>${pages.length} 页 · 16:9</strong></div><small>可编辑图文、智能图形、图表、备注与转场</small></div><div class="artifact-reader-stage slide-reader-page ${page.cover ? "is-cover" : ""} transition-${escapeHTML(transition)}">${researchSlidePageHTML(artifact, page, current)}</div><div class="slide-playback-controls">${artifactPager(artifact, pages.length, current)}<button type="button" data-artifact-slide-play data-id="${escapeHTML(artifact.id)}" aria-pressed="${playing}">${playing ? "暂停" : "播放"}</button></div>${notes}</section>`;
  }
  if (artifact.kind === "video_package") {
    const scenes = Array.isArray(content.scenes) ? content.scenes : [];
    const video = { ...(content.video || {}), ...(state.videoJobs[artifact.id] || {}) };
    const status = video.status || "not_started";
    const segment = Number(video.segment || 0);
    const segments = Number(video.segments || 0);
    const generating = status === "running" || status === "queued";
    const progressLabel = status === "running" && segment && segments ? `视频生成中 · 第 ${segment}/${segments} 段` : status === "queued" ? "视频任务排队中" : status === "running" ? "视频生成中" : status === "failed" ? "视频生成失败" : "尚未生成视频成片";
    const player = status === "ready" ? `<video class="artifact-video-player" controls preload="metadata" playsinline src="/api/research/artifacts/${encodeURIComponent(artifact.id)}/video">当前浏览器不支持视频播放。</video>` : `<div class="video-generation-state"><strong>${progressLabel}</strong>${video.duration ? `<small>测试模式目标：5 个镜头 × 3 秒 = 15 秒 · 854×480（480p）</small>` : ""}${video.error ? `<small>${escapeHTML(video.error)}</small>` : ""}<div class="video-mode-actions"><button type="button" data-generate-video data-video-mode="test" data-id="${escapeHTML(artifact.id)}" ${generating ? "disabled" : ""}>${generating ? "正在生成" : status === "failed" ? "重新生成测试视频" : "生成测试视频"}</button><button type="button" disabled title="正式模式暂未制作">正式模式（暂未制作）</button></div></div>`;
    const meta = state.artifactKinds.find((item) => item.id === "video_package")?.export || {};
    return `<section class="media-preview"><div class="media-preview-head"><div><span>可播放视频</span><strong>${Math.round(Number(video.duration || content.durationSeconds || 0)) || "-"} 秒 · ${scenes.length} 个镜头</strong></div><small>百炼 ${escapeHTML(video.model || meta.model || "happyhorse-1.1-t2v")} · 成片需重新审核</small></div>${player}<div class="video-timeline">${scenes.map((scene, index) => `<article><time>${escapeHTML(`${scene.start ?? scene.startSeconds ?? 0}–${scene.end ?? scene.endSeconds ?? ""}s`)}</time><div><strong>${escapeHTML(scene.onScreenText || `镜头 ${index + 1}`)}</strong><small>${escapeHTML(scene.visual || "画面待设计")}</small></div></article>`).join("") || '<p class="muted">视频分镜待补充</p>'}</div></section>`;
  }
  return "";
}
function artifactExportAction(artifact) {
  const meta = state.artifactKinds.find((item) => item.id === artifact.kind)?.export;
  if (!meta) return "";
  const videoReady = artifact.kind === "video_package" && artifact.content?.video?.status === "ready";
  const href = videoReady
    ? `/api/research/artifacts/${encodeURIComponent(artifact.id)}/video`
    : `/api/research/artifacts/${encodeURIComponent(artifact.id)}/export?format=${encodeURIComponent(meta.format)}`;
  const label = videoReady ? meta.label : (meta.packageLabel || meta.label || "导出作品");
  return `<a class="inspector-link media-export-link" href="${href}" download>${escapeHTML(label)}</a>`;
}

async function generateVideo(button) {
  const artifactId = button.dataset.id;
  if (!artifactId) return;
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "提交视频任务";
  try {
    const mode = button.dataset.videoMode || "test";
    const initialJob = await post(`/api/research/artifacts/${encodeURIComponent(artifactId)}/generate-video`, { mode });
    state.videoJobs[artifactId] = initialJob;
    toast("视频任务已提交，生成完成后会显示播放器");
    const poll = async () => {
      try {
        const job = await request(`/api/research/artifacts/${encodeURIComponent(artifactId)}/video-status`);
        state.videoJobs[artifactId] = job;
        if (["queued", "running"].includes(job.status)) {
          renderArtifactInspector();
          return setTimeout(poll, 5000);
        }
        await refresh();
        if (job.status === "failed") toast(job.error || "视频生成失败", true);
        else toast("视频成片已生成，作品已回到待审核");
      } catch (error) {
        toast(error.message || "视频状态查询失败", true);
      }
    };
    setTimeout(poll, 1500);
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = original;
  }
}
function renderArtifacts() {
  $("#artifact-count").textContent = `${state.artifacts.length} 项作品`;
  $("#artifact-list").innerHTML = state.artifacts.length ? state.artifacts.map((artifact) => `<article class="entity-row ${state.selected.artifact === artifact.id ? "is-selected" : ""}" data-entity="artifact" data-id="${artifact.id}"><label class="entity-check"><input type="checkbox" data-check="artifact" value="${artifact.id}" ${state.checked.artifact.has(artifact.id) ? "checked" : ""}><span></span></label><button class="entity-main" data-select="artifact" data-id="${artifact.id}"><strong>${escapeHTML(artifact.title)}</strong><small>${escapeHTML(artifact.kind)} · ${escapeHTML(artifactContentPreview(artifact))}</small></button><div class="entity-side artifact-states">${artifactStatePair(artifact)}</div></article>`).join("") : '<p class="empty-row">尚未生成作品草稿</p>';
  $("#artifact-selected-count").textContent = state.checked.artifact.size ? `已选 ${state.checked.artifact.size} 项` : "未选择";
}
function artifactHasPrimaryEditor(artifact) {
  return ["record_table", "slide_deck", "whiteboard", "mind_map"].includes(artifact.kind) || typeof artifact.content?.text === "string" || typeof artifact.content?.html === "string";
}
function syncArtifactFullscreen() {
  const workspace = $("[data-artifact-workspace]");
  const active = Boolean(workspace && state.fullscreenArtifactId && workspace.dataset.artifactId === state.fullscreenArtifactId);
  document.body.classList.toggle("artifact-editor-fullscreen-open", active);
  workspace?.classList.toggle("is-fullscreen", active);
  const trigger = $("[data-artifact-fullscreen-open]");
  if (trigger) trigger.setAttribute("aria-pressed", String(active));
  if (!active && state.fullscreenArtifactId) state.fullscreenArtifactId = null;
}
function setArtifactFullscreen(open) {
  const workspace = $("[data-artifact-workspace]");
  if (open && workspace) {
    state.fullscreenReturnFocus = $("[data-artifact-fullscreen-open]");
    state.fullscreenArtifactId = workspace.dataset.artifactId;
  } else {
    state.fullscreenArtifactId = null;
  }
  syncArtifactFullscreen();
  if (open) $("[data-artifact-fullscreen-close]")?.focus();
  else {
    const returnFocus = state.fullscreenReturnFocus?.isConnected ? state.fullscreenReturnFocus : $("[data-artifact-fullscreen-open]");
    returnFocus?.focus();
    state.fullscreenReturnFocus = null;
  }
}
function renderArtifactInspector() {
  const artifact = state.artifacts.find((item) => item.id === state.selected.artifact);
  if (!artifact) { state.fullscreenArtifactId = null; syncArtifactFullscreen(); $("#artifact-inspector").innerHTML = '<div class="inspector-empty">选择作品查看完整内容、来源关系和发布状态。</div>'; return; }
  const reviewStatus = artifactReviewStatus(artifact.status);
  const canReview = reviewStatus === "draft" || reviewStatus === "stale";
  const unreviewedSources = [...new Map((artifact.sources || []).filter((source) => source.source_status !== "reviewed" || !["text_ready", "ocr_ready"].includes(source.source_recognition_status)).map((source) => [source.source_id, source])).values()];
  const approvalNote = unreviewedSources.length ? `<p class="approval-blocked">尚不能批准：${unreviewedSources.map((source) => escapeHTML(source.source_title || source.source_id)).join("、")}尚未完成来源确认。</p>` : "";
  const publicState = artifact.publication_state;
  const publicAction = ["public", "public_stale", "replacement_pending"].includes(publicState) ? `<button type="button" data-inspector-action="artifact-withdraw" data-id="${artifact.id}">取消发布</button>` : "";
  const deleteAction = ["public", "public_stale", "replacement_pending"].includes(publicState) ? "" : `<button type="button" data-inspector-action="artifact-delete" data-id="${artifact.id}">删除作品</button>`;
  const approveLabel = reviewStatus === "stale" ? "完成复核" : "批准作品";
  const approveAction = canReview ? `<button type="button" class="command primary" data-inspector-action="artifact-approve" data-id="${artifact.id}" ${unreviewedSources.length ? "disabled title=\"来源尚未确认\"" : ""}>${approveLabel}</button>` : "";
  const generationInstruction = artifact.generation_instruction ? escapeHTML(artifact.generation_instruction) : "未设置，使用作品类型默认要求";
  const primaryEditorClass = artifactHasPrimaryEditor(artifact) ? "has-primary-editor" : "has-structured-editor";
  $("#artifact-inspector").innerHTML = `<div class="inspector-head artifact-inspector-head"><div><span class="eyebrow">作品详情 · ${escapeHTML(artifact.kind)}</span><h2>${escapeHTML(artifact.title)}</h2></div><div class="artifact-inspector-tools"><div class="inspector-statuses artifact-states">${artifactStatePair(artifact)}</div><button class="inspector-fullscreen-button" type="button" data-artifact-fullscreen-open aria-pressed="false" title="全屏编辑当前作品"><span aria-hidden="true">⛶</span><span>全屏编辑</span></button></div></div><div class="artifact-editing-workspace ${primaryEditorClass} artifact-kind-${escapeHTML(artifact.kind)}" data-artifact-workspace data-artifact-id="${escapeHTML(artifact.id)}"><div class="fullscreen-editor-bar"><div><small>正在编辑</small><strong>${escapeHTML(artifact.title)}</strong></div><div><button class="command primary" type="button" data-artifact-fullscreen-save>保存修改</button><button type="button" data-artifact-fullscreen-close title="退出全屏编辑"><span aria-hidden="true">×</span><span>退出全屏</span></button></div></div>${artifactMediaPreview(artifact)}<form class="inspector-form" data-form="artifact" data-id="${artifact.id}"><label class="artifact-kind-field">作品类型<select name="kind">${state.artifactKinds.map((item) => `<option value="${escapeHTML(item.id)}" ${item.id === artifact.kind ? "selected" : ""}>${escapeHTML(item.title)}</option>`).join("")}</select></label><label class="artifact-title-field">标题<input name="title" value="${escapeHTML(artifact.title)}"></label><div class="generation-audit"><span>本次生成要求</span><p>${generationInstruction}</p><small>这是生成时保存的审计信息；手工编辑正文不会改写它。</small></div>${artifactEditorHTML(artifact)}${approvalNote}<div class="inspector-actions"><button class="command primary" type="submit">保存修改</button>${artifactExportAction(artifact)}${approveAction}${publicAction}${deleteAction}<button type="button" data-inspector-action="reviews" data-review-type="artifact" data-id="${artifact.id}">审核历史</button></div></form></div><div class="inspector-subsection"><strong>来源关系</strong><p class="muted">${groupArtifactSources(artifact).map((source) => `${escapeHTML(source.source_title || source.source_id)} · ${escapeHTML(sourceConfirmationText(source.source_status, source.source_recognition_status))}${source.locator_range ? ` · ${escapeHTML(source.locator_type)} ${escapeHTML(source.locator_range)}` : ""}`).join("<br>") || "来源关系待补"}</p><small class="muted">界面合并连续页码，底层仍保留逐页证据关系。审核状态记录内容是否可用；发布状态记录公众端是否正在展示。媒体导出是当前草稿的派生文件，不会进入证据库；编辑或来源更新后应重新导出并复核。</small><div id="review-history"></div></div>`;
  syncArtifactFullscreen();
}
function renderPublish() {
  const stale = state.artifacts.filter((item) => artifactReviewStatus(item.status) === "stale").length;
  const drafts = state.artifacts.filter((item) => artifactReviewStatus(item.status) === "draft").length;
  const ocrBlocked = state.sources.filter((source) => !recognitionPublishable(source)).length;
  const siteTotal = state.siteContent.length;
  const siteApproved = state.siteContent.filter((item) => item.status === "approved").length;
  const siteDrafts = state.siteContent.filter((item) => item.status !== "approved").length;
  const siteOutdated = state.siteContent.filter((item) => item.publication_state === "outdated").length;
  const sitePending = new Set(state.siteContent.filter((item) => item.status !== "approved" || item.publication_state === "outdated").map((item) => item.content_key)).size;
  const pendingTotal = stale + drafts + ocrBlocked + sitePending;
  $("#publish-readiness").textContent = pendingTotal ? `${pendingTotal} 项待处理或待发布` : "可发布";
  $("#publish-check-count").textContent = pendingTotal;
  $("#publish-checks").innerHTML = `<div class="check-row ${ocrBlocked ? "is-warn" : ""}"><strong>${ocrBlocked ? `还有 ${ocrBlocked} 篇资料未通过OCR质量门` : "OCR文本质量通过"}</strong><small>${ocrBlocked ? "保留当前公众版本，完成OCR确认后再发布" : "没有低质量来源"}</small></div><div class="check-row ${drafts ? "is-warn" : ""}"><strong>${drafts ? `还有 ${drafts} 项作品草稿` : "作品审核通过"}</strong><small>${drafts ? "编辑、批准或删除" : "没有未审核作品"}</small></div><div class="check-row ${stale ? "is-warn" : ""}"><strong>${stale ? `还有 ${stale} 项作品需要重新审核` : "来源关系完整"}</strong><small>${stale ? "来源更新后不会自动覆盖公众端" : "当前没有失效依赖"}</small></div><div class="check-row ${sitePending ? "is-warn" : ""}"><strong>站点内容 ${siteApproved} / ${siteTotal || 4} 已批准${siteDrafts ? ` · ${siteDrafts} 个草稿` : ""}</strong><small>${siteOutdated ? `${siteOutdated} 个内容区与当前公众版本不同；发布新版本后才会更新` : "四个内容区均已进入当前公众版本"}</small></div>`;
  const publishableWorks = state.artifacts.filter((item) => artifactReviewStatus(item.status) === "approved" && item.publication_state !== "withdrawn").length;
  const reviewedSources = state.dashboard?.counts?.reviewedSources || 0;
  $("#release-content-summary").textContent = `本次预计发布 ${publishableWorks} 项作品 · ${siteApproved}/${siteTotal || 4} 个站点内容区 · ${reviewedSources} 篇资料已确认`;
  $("#snapshot-history-count").textContent = state.snapshots.length;
  $("#snapshot-history").innerHTML = state.snapshots.length ? state.snapshots.map((snapshot) => {
    const current = Boolean(snapshot.current);
    const expanded = state.expandedSnapshotId === snapshot.id;
    const detail = state.snapshotDetails[snapshot.id];
    const title = snapshot.title || detail?.title || "历史发布版本";
    const description = snapshot.description || detail?.description || "未填写版本说明";
    const controls = [`<button data-snapshot-action="details" data-id="${escapeHTML(snapshot.id)}" aria-expanded="${expanded}">${expanded ? "收起详情" : "查看详情"}</button>`];
    if (!current && snapshot.restorable) controls.push(`<button data-snapshot-action="restore" data-id="${escapeHTML(snapshot.id)}">恢复此版本</button>`);
    if (!current) controls.push(`<button class="delete" data-snapshot-action="delete" data-id="${escapeHTML(snapshot.id)}">删除</button>`);
    const detailHTML = expanded ? `<div class="history-detail">${detail ? snapshotDetailHTML(detail) : '<p class="muted">正在读取版本详情…</p>'}</div>` : "";
    return `<article class="history-row ${current ? "is-current" : ""}"><div class="history-main"><div class="history-title-line"><strong>${escapeHTML(title)}</strong>${current ? '<span class="current-label">当前版本</span>' : ""}</div><p>${escapeHTML(description)}</p><small>${formatDate(snapshot.created_at)} · ${snapshot.item_counts?.records || 0} 条记录 · ${snapshot.item_counts?.works || 0} 项作品 · ${snapshot.item_counts?.siteContent || 0} 个站点内容区</small><code>${escapeHTML(snapshot.id)}</code></div><div class="history-actions">${controls.join("")}</div>${detailHTML}</article>`;
  }).join("") : '<p class="empty-row">尚无发布版本</p>';
}
function snapshotDetailHTML(detail) {
  const counts = detail.itemCounts || {};
  const works = detail.works || [];
  const siteContent = detail.siteContent || [];
  return `<dl class="version-facts"><div><dt>发布时间</dt><dd>${escapeHTML(formatFullDate(detail.publishedAt || detail.createdAt))}</dd></div><div><dt>发布人</dt><dd>${escapeHTML(detail.createdBy || "本地审核人")}</dd></div><div><dt>内容统计</dt><dd>${counts.records || 0} 条记录 · ${counts.knowledge || 0} 项知识 · ${counts.works || 0} 项作品 · ${counts.siteContent || siteContent.length || 0} 个站点内容区 · ${counts.reviewedSources || 0} 篇资料</dd></div>${detail.restoredFrom ? `<div><dt>恢复来源</dt><dd><code>${escapeHTML(detail.restoredFrom)}</code></dd></div>` : ""}<div class="version-hash"><dt>校验值</dt><dd><code>${escapeHTML(detail.hash || "-")}</code></dd></div></dl><div class="version-work-list"><strong>站点内容</strong>${siteContent.length ? `<ul>${siteContent.map((item) => `<li><span>${escapeHTML(item.title)}</span><small>${escapeHTML(siteContentMeta[item.key]?.caption || "公众页面")}</small></li>`).join("")}</ul>` : '<p class="muted">此历史版本尚未包含可编辑站点内容</p>'}</div><div class="version-work-list"><strong>作品清单</strong>${works.length ? `<ul>${works.map((work) => `<li><span>${escapeHTML(work.title)}</span><small>${escapeHTML(state.artifactKinds.find((kind) => kind.id === work.kind)?.title || work.kind || "未分类")}</small></li>`).join("")}</ul>` : '<p class="muted">此版本未发布作品</p>'}</div>`;
}
function renderArtifactKindControls() {
  const select = $("#output-kind-select");
  if (!select || !state.artifactKinds.length) return;
  if (!$(".board-output-modes")) {
    select.closest("label")?.insertAdjacentHTML("beforebegin", '<div class="field-label media-field-label">研究结构 <small>节点引用保留来源关系</small></div><div class="output-modes board-output-modes"><button type="button" data-output-kind="whiteboard"><strong>研究白板</strong><small>自由整理证据关系</small></button><button type="button" data-output-kind="mind_map"><strong>思维导图</strong><small>中心主题与分支</small></button></div>');
    $$(".board-output-modes [data-output-kind]").forEach((button) => button.addEventListener("click", () => { state.outputKind = button.dataset.outputKind; select.value = state.outputKind; $$("[data-output-kind]").forEach((item) => item.classList.toggle("is-active", item === button)); }));
  }
  select.innerHTML = state.artifactKinds.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.title)}</option>`).join("");
  select.value = state.artifactKinds.some((item) => item.id === state.outputKind) ? state.outputKind : state.artifactKinds[0].id;
}
function renderAll() { renderMetrics(); $("#overview-sources").innerHTML = compactRows(state.sources, "source"); $("#overview-artifacts").innerHTML = compactRows(state.artifacts, "artifact"); renderArtifactKindControls(); renderSources(); renderSourceInspector(); const source = state.sources.find((item) => item.id === state.selected.source); if (source?.kind === "pdf" || source?.source_role === "generated_note") loadUnits(source.id); renderSiteGenerationModes(); renderSiteContent(); renderArtifacts(); renderArtifactInspector(); renderPublish(); }

async function refresh({ announce = false } = {}) {
  const sequence = ++refreshSequence;
  setSyncState("正在同步", "syncing");
  const button = $("#refresh-dashboard");
  if (button) button.classList.add("is-syncing");
  try {
  const responses = await Promise.allSettled([
    request("/api/research/dashboard"),
    request("/api/research/sources"),
    request("/api/research/artifacts"),
    request("/api/research/snapshots").catch(() => ({ items: [] })),
    request("/api/research/ocr-runs").catch(() => ({ items: [] })),
    request("/api/research/artifact-kinds").catch(() => ({ items: [] })),
    request("/api/research/site-content").catch(() => ({ items: [], shortcodes: [], generationModes: [] }))
  ]);
  const dashboardResult = responses[0];
  if (dashboardResult.status === "rejected") throw dashboardResult.reason;
  const dashboard = dashboardResult.value;
  const sources = responses[1].status === "fulfilled" ? responses[1].value : { items: dashboard.sources || [] };
  const artifacts = responses[2].status === "fulfilled" ? responses[2].value : { items: dashboard.artifacts || [] };
  const snapshots = responses[3].status === "fulfilled" ? responses[3].value : { items: [] };
  const ocrRuns = responses[4].status === "fulfilled" ? responses[4].value : { items: [] };
  const kinds = responses[5].status === "fulfilled" ? responses[5].value : { items: [] };
  const site = responses[6].status === "fulfilled" ? responses[6].value : { items: [], shortcodes: [], generationModes: [] };
  if (sequence !== refreshSequence) return;
  state.dashboard = dashboard; state.sources = sources.items || []; state.artifacts = artifacts.items || []; state.snapshots = snapshots.items || []; state.ocrRuns = ocrRuns.items || []; state.artifactKinds = kinds.items || []; state.siteContent = site.items || []; state.siteShortcodes = site.shortcodes || []; state.siteGenerationReady = ["section_package", "html_body"].every((mode) => (site.generationModes || []).some((item) => item.id === mode)); if (!state.siteContent.some((item) => item.content_key === state.selected.siteContent)) state.selected.siteContent = state.siteContent[0]?.content_key || "hero"; state.lastSyncedAt = Date.now(); renderAll();
  setSyncState(`已同步 ${new Date(state.lastSyncedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`);
  if (announce) toast("已读取最新资料、作品和版本");
  clearTimeout(ocrRefreshTimer);
  if (state.ocrRuns.some((run) => ["queued", "processing"].includes(run.status))) ocrRefreshTimer = setTimeout(() => refresh().catch((error) => toast(error.message, true)), 4000);
  } catch (error) {
    if (sequence === refreshSequence) setSyncState("同步失败", "error");
    throw error;
  } finally {
    if (sequence === refreshSequence && button) button.classList.remove("is-syncing");
  }
}
async function refreshWithRetry(attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await refresh();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        setSyncState(`正在重新同步 ${attempt + 1}/${attempts}`, "syncing");
        await new Promise((resolve) => setTimeout(resolve, attempt * 500));
      }
    }
  }
  throw lastError;
}
async function fileToBase64(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file); }); }
async function importSource(event) { event.preventDefault(); const button = $("#import-submit"); button.disabled = true; button.textContent = "资料处理中"; try { let payload; if (state.importKind === "pdf") { const file = $("#pdf-file").files[0]; if (!file) throw new Error("请选择PDF文件"); if (file.size > 25 * 1024 * 1024) throw new Error("PDF超过25MB限制"); payload = { kind: "pdf", title: $("#pdf-title").value.trim(), filename: file.name, contentBase64: await fileToBase64(file) }; } else if (state.importKind === "url") payload = { kind: "url", title: $("#url-title").value.trim(), url: $("#url-value").value.trim() }; else payload = { kind: "manual", title: $("#manual-title").value.trim(), text: $("#manual-text").value.trim() }; const result = await post("/api/research/import", payload); if (result.autoParse?.status === "parse_failed") toast(`资料已保存，但自动处理失败：${result.autoParse.error || "请重试"}`, true); else if (result.autoParse?.recognitionStatus === "ocr_pending") toast("资料已汇入，但PDF文本层质量异常，请启动百炼OCR", true); else toast(result.duplicate ? "检测到重复资料，已定位现有记录" : "资料已汇入并通过文本质量检测"); event.target.reset(); $("#pdf-file-name").textContent = "选择文件"; await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; button.textContent = "＋ 汇入资料"; } }
async function sourceAction(button) { const action = button.dataset.sourceAction; const id = button.dataset.id; if (action === "delete" && !window.confirm("删除后，依赖知识和作品将标记为需要重新审核。确认删除？")) return; if (action === "reparse" && !window.confirm("重新提取PDF文本层会使依赖内容失效；乱码PDF应优先使用OCR。确认继续？")) return; if (action === "ocr" && !window.confirm("将把该PDF逐页渲染为图片并发送至阿里云百炼OCR；原PDF和数据库不会上传。确认开始？")) return; if (action === "ocr-reassess" && !window.confirm("将使用新版质量规则重新评估本机已有OCR文本，不调用百炼、不产生费用。确认继续？")) return; if (action === "ocr-reject" && !window.confirm("退回后该资料将重新进入OCR待处理状态。确认退回？")) return; button.disabled = true; try { const result = await post(`/api/research/sources/${id}/${action}`); toast(action === "ocr" ? "OCR任务已进入后台队列" : action === "ocr-reassess" ? "已有OCR文本已重新评估，请继续人工确认" : `${button.textContent.trim()}完成`); await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } }
async function sourceBulk(action) {
  let items;
  if (action === "ocr") items = state.sources.filter((item) => state.checked.source.has(item.id) && item.kind === "pdf" && ["unverified", "ocr_pending", "ocr_failed"].includes(item.recognition_status));
  else if (action === "review") items = state.sources.filter((item) => state.checked.source.has(item.id) && item.status === "parsed" && item.recognition_status === "text_ready");
  else items = state.sources.filter((item) => state.checked.source.has(item.id) && item.status === "reviewed");
  if (!items.length) return toast(action === "ocr" ? "所选资料中没有可启动OCR的PDF" : action === "review" ? "所选资料中没有需要确认的正常文本资料" : "所选资料中没有已确认项", true);
  if (action === "ocr" && !window.confirm(`将把所选 ${items.length} 篇PDF逐页发送至阿里云百炼OCR，并按顺序后台处理。确认开始？`)) return;
  try { for (const item of items) await post(`/api/research/sources/${item.id}/${action}`); toast(action === "ocr" ? `已加入 ${items.length} 项OCR任务` : `已处理 ${items.length} 项资料`); state.checked.source.clear(); await refresh(); } catch (error) { toast(error.message, true); }
}
async function reviewItem(type, id, action) { try { const artifact = state.artifacts.find((item) => item.id === id); const wasStale = artifactReviewStatus(artifact?.status) === "stale"; const path = action === "withdraw" ? `/api/research/artifacts/${id}/withdraw` : `/api/research/artifacts/${id}/review`; await post(path, action === "withdraw" ? {} : { action }); toast(action === "approve" ? (wasStale ? "作品已完成复核，等待发布新版本" : "作品已批准，进入发布准备") : action === "withdraw" ? "作品已撤销发布，并生成新的公众版本" : "状态已更新"); await refresh(); } catch (error) { toast(error.message, true); } }
async function bulkReview(kind, action) { let ids = [...state.checked[kind]]; if (!ids.length) return toast("请先选择作品", true); try { ids = state.artifacts.filter((item) => ["draft", "stale"].includes(artifactReviewStatus(item.status)) && ids.includes(item.id)).map((item) => item.id); if (!ids.length) return toast("所选作品中没有待审核或待复核项", true); await post("/api/research/artifacts/bulk-review", { ids, action }); toast("所选作品已通过审核"); state.checked[kind].clear(); await refresh(); } catch (error) { toast(error.message, true); } }
function syncPdfPage(page, updateImage = true) {
  const source = state.sources.find((item) => item.id === state.selected.source);
  if (!source || source.kind !== "pdf") return;
  const pageNumber = Math.max(1, Math.min(Number(page) || 1, Number(source.page_count) || 1));
  state.sourcePage = pageNumber;
  const indicator = $("#pdf-page-indicator");
  if (indicator) indicator.textContent = `第 ${pageNumber} / ${source.page_count || 1} 页`;
  if (updateImage) {
    const image = $("#source-pdf-page");
    if (image) {
      image.src = `/api/research/source-page?sourceId=${encodeURIComponent(source.id)}&page=${pageNumber}`;
      image.alt = `${source.title}第${pageNumber}页`;
      image.onload = () => syncPdfZoom();
    }
  }
  $$("[data-pdf-unit]").forEach((item) => {
    const active = Number(item.dataset.pdfUnit) === pageNumber;
    item.classList.toggle("is-current", active);
    item.open = active;
  });
}
async function loadUnits(id) {
  try {
    const result = await request(`/api/research/units?sourceId=${encodeURIComponent(id)}`);
    const target = $("#source-units");
    if (!target || state.selected.source !== id) return;
    const currentSource = state.sources.find((item) => item.id === id);
    const isResearchNote = currentSource?.source_role === "generated_note";
    target.innerHTML = result.items.length ? result.items.map((unit) => {
      const isPdfPage = unit.locator_type === "pdf_page";
      const page = Number(unit.locator_value) || 1;
      const label = isResearchNote ? "保存的问答正文" : isPdfPage ? `PDF 第${page}页` : `原文分段 ${unit.locator_value}`;
      const qualityLabel = ({ passed: "已识别", needs_review: "建议复核", failed: "识别失败" })[unit.quality_status] || "待核对";
      const method = isResearchNote ? "研究笔记 · 不作为证据" : unit.extraction_method === "bailian_ocr" ? `百炼OCR · ${Math.round(Number(unit.quality_score || 0) * 100)}% · ${qualityLabel}` : `${unit.extraction_method || "文本层"} · ${unit.quality_status === "passed" ? "质量通过" : qualityLabel}`;
      const expanded = isResearchNote || (isPdfPage && page === state.sourcePage);
      return `<details class="unit-row ${isPdfPage && page === state.sourcePage ? "is-current" : ""}" ${isPdfPage ? `data-pdf-unit="${page}"` : ""} ${expanded ? "open" : ""}><summary ${isPdfPage ? `data-pdf-page="${page}"` : ""}><span>${escapeHTML(label)}</span><small>${escapeHTML(method)}</small></summary><p>${escapeHTML(unit.text_content || "该页未提取到文本")}</p></details>`;
    }).join("") : '<p class="muted">暂无可查看的页码或原文</p>';
    syncPdfPage(state.sourcePage, false);
    syncPdfZoom();
  } catch (error) { toast(error.message, true); }
}
async function loadReviews(type, id) { try { const result = await request(`/api/research/reviews?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`); const target = type === "source" ? $("#source-review-history") : $("#review-history"); if (!target) return; target.innerHTML = result.items.length ? `<div class="review-timeline">${result.items.map((item) => `<article><strong>${escapeHTML(item.action)}</strong><small>${formatDate(item.created_at)} · ${escapeHTML(item.reviewer)}</small><p>${escapeHTML(item.note || "无备注")}</p></article>`).join("")}</div>` : '<p class="muted">暂无审核记录</p>'; } catch (error) { toast(error.message, true); } }
function readRecordTableEditor(form, artifact) {
  const editor = form.querySelector("[data-record-table-editor]");
  if (!editor) throw new Error("没有找到在线表格");
  const columns = $$('[data-table-column]', editor).map((input) => input.value.trim());
  if (!columns.length || columns.some((column) => !column)) throw new Error("列名不能为空");
  if (new Set(columns).size !== columns.length) throw new Error("列名不能重复");
  const rows = $$('tbody tr', editor).map((row) => Object.fromEntries(columns.map((column, index) => [column, row.querySelector(`[data-table-cell][data-column="${index}"]`)?.value || ""])));
  return { ...(artifact.content || {}), columns, rows };
}
function boardArtifact(shell) { return state.artifacts.find((item) => item.id === shell?.dataset.artifactId); }
function boardNodeObject(node) {
  return {
    id: node.dataset.nodeId,
    type: node.dataset.nodeType || "note",
    title: node.dataset.nodeTitleValue || "未命名节点",
    body: node.dataset.nodeBodyValue || "",
    x: Number(node.dataset.x) || 0,
    y: Number(node.dataset.y) || 0,
    width: Number(node.dataset.width) || 230,
    height: Number(node.dataset.height) || 140,
    color: node.dataset.nodeColor || "gold",
    reference: {
      type: node.dataset.referenceType || "",
      id: node.dataset.referenceId || "",
      label: node.dataset.referenceLabel || "",
      page: node.dataset.referencePage || ""
    }
  };
}
function boardNodes(shell) { return $$('[data-board-node]', shell).map(boardNodeObject); }
function boardEdges(shell) {
  if (!shell._boardEdges) {
    try { shell._boardEdges = JSON.parse(shell.dataset.boardEdges || "[]"); }
    catch (_) { shell._boardEdges = []; }
  }
  return shell._boardEdges;
}
function setBoardEdges(shell, edges) {
  shell._boardEdges = edges;
  shell.dataset.boardEdges = JSON.stringify(edges);
}
function redrawBoardEdges(shell) {
  const layer = shell.querySelector("[data-board-edge-content]");
  if (layer) layer.innerHTML = boardEdges(shell).map((edge) => boardEdgeSVG(edge, boardNodes(shell))).join("");
}
function boardNodeElement(shell, id) { return $$('[data-board-node]', shell).find((node) => node.dataset.nodeId === id); }
function selectBoardNode(shell, id) {
  const node = boardNodeElement(shell, id);
  if (!node) return;
  shell.dataset.selectedNode = id;
  $$('[data-board-node]', shell).forEach((item) => item.classList.toggle("is-selected", item === node));
  const properties = shell.querySelector("[data-board-properties]");
  const artifact = boardArtifact(shell);
  if (properties && artifact) properties.innerHTML = boardPropertiesHTML(boardNodeObject(node), artifact, boardEdges(shell));
}
function applyBoardZoom(shell, value) {
  const zoom = Math.max(0.4, Math.min(1.5, Number(value) || 0.8));
  const width = Number(shell.dataset.viewportWidth) || 1200;
  const height = Number(shell.dataset.viewportHeight) || 760;
  shell.dataset.boardZoom = String(zoom);
  state.boardZooms[shell.dataset.artifactId] = zoom;
  const scaled = shell.querySelector(".board-scaled");
  const world = shell.querySelector(".board-world");
  if (scaled) { scaled.style.width = `${width * zoom}px`; scaled.style.height = `${height * zoom}px`; }
  if (world) world.style.transform = `scale(${zoom})`;
  const label = shell.querySelector("[data-board-zoom-label]");
  if (label) label.textContent = `${Math.round(zoom * 100)}%`;
}
function fitBoard(shell) {
  const scroll = shell.querySelector(".board-scroll");
  const width = Number(shell.dataset.viewportWidth) || 1200;
  const height = Number(shell.dataset.viewportHeight) || 760;
  const availableWidth = Math.max(320, (scroll?.clientWidth || 900) - 28);
  const availableHeight = Math.max(320, (scroll?.clientHeight || 570) - 28);
  return applyBoardZoom(shell, Math.min(1, availableWidth / width, availableHeight / height));
}
function applyBoardViewport(shell, requestedWidth, requestedHeight) {
  const width = Math.round(Math.max(720, Math.min(4000, Number(requestedWidth) || 1200)));
  const height = Math.round(Math.max(480, Math.min(3000, Number(requestedHeight) || 760)));
  shell.dataset.viewportWidth = String(width);
  shell.dataset.viewportHeight = String(height);
  const world = shell.querySelector(".board-world");
  if (world) { world.style.width = `${width}px`; world.style.height = `${height}px`; }
  const edgeLayer = shell.querySelector(".board-edge-layer");
  if (edgeLayer) edgeLayer.setAttribute("viewBox", `0 0 ${width} ${height}`);
  $$('[data-board-node]', shell).forEach((node) => {
    const nodeWidth = Number(node.dataset.width) || 230;
    const nodeHeight = Number(node.dataset.height) || 140;
    const x = Math.max(0, Math.min(width - nodeWidth, Number(node.dataset.x) || 0));
    const y = Math.max(0, Math.min(height - nodeHeight, Number(node.dataset.y) || 0));
    node.dataset.x = String(Math.round(x));
    node.dataset.y = String(Math.round(y));
    node.style.left = `${Math.round(x)}px`;
    node.style.top = `${Math.round(y)}px`;
  });
  const widthInput = shell.querySelector('[data-board-size-input="width"]');
  const heightInput = shell.querySelector('[data-board-size-input="height"]');
  const preset = shell.querySelector("[data-board-preset]");
  const label = shell.querySelector("[data-board-size-label]");
  if (widthInput) widthInput.value = String(width);
  if (heightInput) heightInput.value = String(height);
  if (preset) preset.value = boardPreset(width, height);
  if (label) label.textContent = `${width} × ${height}`;
  redrawBoardEdges(shell);
  fitBoard(shell);
}
function handleBoardSizePreset(select) {
  const shell = select.closest("[data-board-editor]");
  if (!shell) return;
  const sizes = { desktop: [1200, 760], wide: [1600, 900], portrait: [900, 1400], large: [2200, 1400] };
  const size = sizes[select.value];
  if (!size) return;
  const widthInput = shell.querySelector('[data-board-size-input="width"]');
  const heightInput = shell.querySelector('[data-board-size-input="height"]');
  if (widthInput) widthInput.value = String(size[0]);
  if (heightInput) heightInput.value = String(size[1]);
}
function addBoardNode(shell, type) {
  const nodes = boardNodes(shell);
  if (nodes.length >= 120) return toast("白板最多支持120个节点", true);
  let index = nodes.length + 1;
  let id = `node-${index}`;
  while (nodes.some((node) => node.id === id)) id = `node-${++index}`;
  const width = Number(shell.dataset.viewportWidth) || 1200;
  const height = Number(shell.dataset.viewportHeight) || 760;
  const node = {
    id, type, title: type === "evidence" ? "新证据" : "新研究笔记", body: "",
    x: Math.min(width - 230, 70 + (nodes.length % 4) * 260),
    y: Math.min(height - 140, 70 + (Math.floor(nodes.length / 4) % 4) * 170),
    width: 230, height: 140, color: type === "evidence" ? "blue" : "gold",
    reference: { type: "", id: "", label: "", page: "" }
  };
  shell.querySelector(".board-world")?.insertAdjacentHTML("beforeend", boardNodeHTML(node));
  selectBoardNode(shell, id);
  redrawBoardEdges(shell);
}
function deleteBoardNode(shell) {
  const nodes = boardNodes(shell);
  if (nodes.length <= 1) return toast("白板至少保留一个节点", true);
  const id = shell.dataset.selectedNode;
  boardNodeElement(shell, id)?.remove();
  setBoardEdges(shell, boardEdges(shell).filter((edge) => edge.from !== id && edge.to !== id));
  redrawBoardEdges(shell);
  const next = boardNodes(shell)[0];
  if (next) selectBoardNode(shell, next.id);
}
function connectBoardNode(shell, nodeId) {
  if (!shell.classList.contains("is-connecting")) return false;
  const start = shell.dataset.connectStart;
  if (!start) {
    shell.dataset.connectStart = nodeId;
    boardNodeElement(shell, nodeId)?.classList.add("is-connect-start");
    return true;
  }
  if (start === nodeId) return true;
  const edges = boardEdges(shell);
  if (!edges.some((edge) => edge.from === start && edge.to === nodeId)) {
    const id = `edge-${Date.now().toString(36)}`;
    setBoardEdges(shell, [...edges, { id, from: start, to: nodeId, label: "关联" }]);
  }
  boardNodeElement(shell, start)?.classList.remove("is-connect-start");
  shell.dataset.connectStart = "";
  redrawBoardEdges(shell);
  selectBoardNode(shell, nodeId);
  return true;
}
function autoLayoutBoard(shell) {
  const nodes = $$('[data-board-node]', shell);
  const width = Number(shell.dataset.viewportWidth) || 1200;
  const height = Number(shell.dataset.viewportHeight) || 760;
  if (shell.dataset.layout === "mind_map") {
    nodes.forEach((node, index) => {
      const nodeWidth = Number(node.dataset.width) || 230;
      const nodeHeight = Number(node.dataset.height) || 140;
      let x = width / 2 - nodeWidth / 2;
      let y = height / 2 - nodeHeight / 2;
      if (index) {
        const angle = ((index - 1) / Math.max(1, nodes.length - 1)) * Math.PI * 2;
        x = width / 2 + Math.cos(angle) * Math.min(420, width * 0.34) - nodeWidth / 2;
        y = height / 2 + Math.sin(angle) * Math.min(260, height * 0.34) - nodeHeight / 2;
      }
      node.dataset.x = String(Math.max(0, Math.min(width - nodeWidth, x)));
      node.dataset.y = String(Math.max(0, Math.min(height - nodeHeight, y)));
      node.style.left = `${node.dataset.x}px`; node.style.top = `${node.dataset.y}px`;
    });
  } else {
    const columns = Math.max(1, Math.floor((width - 60) / 270));
    nodes.forEach((node, index) => {
      const x = 40 + (index % columns) * 270;
      const y = Math.min(height - (Number(node.dataset.height) || 140), 40 + Math.floor(index / columns) * 180);
      node.dataset.x = String(x); node.dataset.y = String(y);
      node.style.left = `${x}px`; node.style.top = `${y}px`;
    });
  }
  redrawBoardEdges(shell);
}
function handleBoardAction(target) {
  const shell = target.closest("[data-board-editor]");
  if (!shell) return;
  if (target.matches("[data-board-node-select]")) {
    const id = target.closest("[data-board-node]")?.dataset.nodeId;
    if (id) { selectBoardNode(shell, id); connectBoardNode(shell, id); }
    return;
  }
  if (target.matches("[data-board-node-delete]")) return deleteBoardNode(shell);
  if (target.matches("[data-board-edge-delete]")) {
    setBoardEdges(shell, boardEdges(shell).filter((edge) => edge.id !== target.dataset.boardEdgeDelete));
    redrawBoardEdges(shell); selectBoardNode(shell, shell.dataset.selectedNode); return;
  }
  const action = target.dataset.boardAction;
  if (!action) return;
  if (action === "add-note") return addBoardNode(shell, "note");
  if (action === "add-evidence") return addBoardNode(shell, "evidence");
  if (action === "zoom-in") return applyBoardZoom(shell, Number(shell.dataset.boardZoom) + 0.1);
  if (action === "zoom-out") return applyBoardZoom(shell, Number(shell.dataset.boardZoom) - 0.1);
  if (action === "fit") return fitBoard(shell);
  if (action === "resize") {
    const widthInput = shell.querySelector('[data-board-size-input="width"]');
    const heightInput = shell.querySelector('[data-board-size-input="height"]');
    applyBoardViewport(shell, widthInput?.value, heightInput?.value);
    target.closest("details")?.removeAttribute("open");
    return toast("版面大小已更新，保存作品后生效");
  }
  if (action === "auto-layout") return autoLayoutBoard(shell);
  if (action === "connect") {
    const active = !shell.classList.contains("is-connecting");
    shell.classList.toggle("is-connecting", active);
    shell.dataset.connectStart = "";
    $$('[data-board-node]', shell).forEach((node) => node.classList.remove("is-connect-start"));
    target.classList.toggle("is-active", active);
  }
}
function handleBoardPropertyInput(input) {
  const shell = input.closest("[data-board-editor]");
  if (!shell) return;
  if (input.matches("[data-board-edge-label]")) {
    const edge = boardEdges(shell).find((item) => item.id === input.dataset.boardEdgeLabel);
    if (edge) { edge.label = input.value; setBoardEdges(shell, boardEdges(shell)); redrawBoardEdges(shell); }
    return;
  }
  const node = boardNodeElement(shell, shell.dataset.selectedNode);
  if (!node) return;
  const field = input.dataset.boardProperty;
  if (field === "title") { node.dataset.nodeTitleValue = input.value; node.querySelector("[data-board-node-title]").textContent = input.value || "未命名节点"; }
  if (field === "body") { node.dataset.nodeBodyValue = input.value; node.querySelector("[data-board-node-body]").textContent = input.value || "添加研究说明"; }
  if (field === "type") {
    node.dataset.nodeType = input.value;
    node.className = node.className.replace(/board-type-\w+/g, "").trim();
    node.classList.add(`board-type-${input.value}`, "is-selected");
    node.querySelector("[data-board-node-type-label]").textContent = boardNodeTypeLabel(input.value);
  }
  if (field === "color") { node.className = node.className.replace(/board-color-\w+/g, "").trim(); node.classList.add(`board-color-${input.value}`, "is-selected"); node.dataset.nodeColor = input.value; }
  const referenceMap = { referenceType: "referenceType", referenceId: "referenceId", referenceLabel: "referenceLabel", referencePage: "referencePage" };
  if (referenceMap[field]) {
    node.dataset[referenceMap[field]] = input.value;
    if (field === "referenceId" && !node.dataset.referenceLabel) {
      const source = boardArtifact(shell)?.sources?.find((item) => item.source_id === input.value);
      if (source) {
        node.dataset.referenceLabel = source.source_title || source.source_id;
        const labelInput = shell.querySelector('[data-board-property="referenceLabel"]');
        if (labelInput) labelInput.value = node.dataset.referenceLabel;
      }
    }
    node.querySelector("[data-board-node-reference]").textContent = boardReferenceSummary(boardNodeObject(node));
  }
  const heading = shell.querySelector(".board-properties-head strong");
  if (heading && field === "title") heading.textContent = input.value || "未命名节点";
}
let boardDrag = null;
function handleBoardPointerDown(event) {
  const handle = event.target.closest("[data-board-drag]");
  if (!handle) return;
  const node = handle.closest("[data-board-node]");
  const shell = handle.closest("[data-board-editor]");
  if (!node || !shell) return;
  selectBoardNode(shell, node.dataset.nodeId);
  boardDrag = { shell, node, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, x: Number(node.dataset.x) || 0, y: Number(node.dataset.y) || 0 };
  handle.setPointerCapture?.(event.pointerId);
  node.classList.add("is-dragging");
  event.preventDefault();
}
function handleBoardPointerMove(event) {
  if (!boardDrag || boardDrag.pointerId !== event.pointerId) return;
  const { shell, node } = boardDrag;
  const zoom = Number(shell.dataset.boardZoom) || 1;
  const width = Number(shell.dataset.viewportWidth) || 1200;
  const height = Number(shell.dataset.viewportHeight) || 760;
  const x = Math.max(0, Math.min(width - Number(node.dataset.width), boardDrag.x + (event.clientX - boardDrag.startX) / zoom));
  const y = Math.max(0, Math.min(height - Number(node.dataset.height), boardDrag.y + (event.clientY - boardDrag.startY) / zoom));
  node.dataset.x = String(Math.round(x)); node.dataset.y = String(Math.round(y));
  node.style.left = `${Math.round(x)}px`; node.style.top = `${Math.round(y)}px`;
  redrawBoardEdges(shell);
}
function handleBoardPointerUp(event) {
  if (!boardDrag || boardDrag.pointerId !== event.pointerId) return;
  boardDrag.node.classList.remove("is-dragging");
  boardDrag = null;
}
function readBoardEditor(form, artifact) {
  const shell = form.querySelector("[data-board-editor]");
  if (!shell) throw new Error("没有找到白板编辑器");
  return {
    ...(artifact.content || {}),
    layout: shell.dataset.layout || (artifact.kind === "mind_map" ? "mind_map" : "free"),
    viewport: { width: Number(shell.dataset.viewportWidth) || 1200, height: Number(shell.dataset.viewportHeight) || 760 },
    nodes: boardNodes(shell),
    edges: boardEdges(shell).map((edge) => ({ id: edge.id, from: edge.from, to: edge.to, label: edge.label || "" }))
  };
}
function readSlideDeckEditor(form, artifact) {
  const shell = form.querySelector("[data-slide-deck-editor]");
  if (!shell) throw new Error("没有找到幻灯片编辑器");
  const deckField = (name) => shell.querySelector(`[data-deck-field="${name}"]`);
  const slides = [...shell.querySelectorAll("[data-slide-editor-page]")].map((page) => {
    const field = (name) => page.querySelector(`[data-slide-field="${name}"]`);
    const richText = splitEditorLines(field("richText")?.value).map((line) => {
      const [lead, ...rest] = line.split("|");
      return rest.length ? { lead: lead.trim(), text: rest.join("|").trim() } : { lead: "", text: lead.trim() };
    });
    const diagramNodes = splitEditorLines(field("diagramNodes")?.value).map((line) => {
      const [label, ...rest] = line.split("|");
      return { label: label.trim(), detail: rest.join("|").trim() };
    }).filter((item) => item.label);
    const categories = String(field("chartCategories")?.value || "").split("|").map((item) => item.trim()).filter(Boolean);
    const series = splitEditorLines(field("chartSeries")?.value).map((line) => {
      const [name, ...rest] = line.split("|");
      const values = rest.join("|").split(",").map((item) => Number(item.trim()));
      return { name: name.trim() || "数值", values };
    }).filter((item) => item.values.length && item.values.every(Number.isFinite));
    const original = artifact.content?.slides?.[Number(page.dataset.slideIndex)] || {};
    return {
      ...original,
      title: field("title")?.value || "",
      takeaway: field("takeaway")?.value || "",
      layout: field("layout")?.value || "statement",
      icon: field("icon")?.value || "book-open",
      richText,
      bullets: splitEditorLines(field("bullets")?.value),
      visual: {
        ...(original.visual || {}),
        prompt: field("visualPrompt")?.value || "",
        alt: field("visualAlt")?.value || "",
        caption: field("visualCaption")?.value || "",
      },
      diagram: { type: diagramNodes.length ? "process" : "", nodes: diagramNodes },
      chart: {
        type: field("chartType")?.value || "",
        title: field("chartTitle")?.value || "",
        categories,
        series,
      },
      speakerNotes: field("speakerNotes")?.value || "",
      citations: splitEditorLines(field("citations")?.value),
      transition: {
        type: field("transitionType")?.value || "fade",
        duration: Number(field("transitionDuration")?.value || 0.7),
        advanceAfter: Number(field("advanceAfter")?.value || 8),
      },
    };
  });
  return {
    ...(artifact.content || {}),
    subtitle: deckField("subtitle")?.value || "",
    playback: {
      autoAdvance: Boolean(deckField("autoAdvance")?.checked),
      seconds: Number(deckField("seconds")?.value || 8),
      loop: Boolean(deckField("loop")?.checked),
      transition: deckField("transition")?.value || "fade",
    },
    slides,
  };
}
function collectArtifactContent(form, artifact) {
  if (form.elements.useAdvancedContent?.checked) return parseJSON(form.elements.content.value);
  if (artifact.kind === "record_table") return readRecordTableEditor(form, artifact);
  if (artifact.kind === "slide_deck") return readSlideDeckEditor(form, artifact);
  if (["whiteboard", "mind_map"].includes(artifact.kind)) return readBoardEditor(form, artifact);
  const richEditor = form.querySelector(".rich-editor-canvas");
  if (richEditor) return { ...(artifact.content || {}), html: richEditor.innerHTML, text: richEditor.innerText.trim() };
  return parseJSON(form.elements.content.value);
}
function updateRecordTableEditor(editor, content) {
  editor.outerHTML = recordTableEditorHTML(content);
}
function handleRecordTableAction(target) {
  const form = target.closest('form[data-form="artifact"]');
  const editor = target.closest("[data-record-table-editor]");
  const artifact = state.artifacts.find((item) => item.id === form?.dataset.id);
  if (!form || !editor || !artifact) return;
  const content = readRecordTableEditor(form, artifact);
  if (target.matches("[data-table-action='add-row']")) {
    content.rows.push(Object.fromEntries(content.columns.map((column) => [column, ""])));
  } else if (target.matches("[data-table-action='add-column']")) {
    let suffix = 1;
    let column = "新字段";
    while (content.columns.includes(column)) column = `新字段${++suffix}`;
    content.columns.push(column);
    content.rows = content.rows.map((row) => ({ ...row, [column]: "" }));
  } else if (target.matches("[data-table-column-delete]")) {
    if (content.columns.length === 1) return toast("记录表至少保留一列", true);
    const index = Number(target.dataset.tableColumnDelete);
    const removed = content.columns[index];
    content.columns.splice(index, 1);
    content.rows = content.rows.map((row) => Object.fromEntries(Object.entries(row).filter(([key]) => key !== removed)));
  } else if (target.matches("[data-table-row-delete]")) {
    content.rows.splice(Number(target.dataset.tableRowDelete), 1);
  }
  updateRecordTableEditor(editor, content);
}
function rememberRichSelection(editor) {
  const selection = window.getSelection();
  if (selection?.rangeCount && editor.contains(selection.anchorNode)) state.richTextRange = selection.getRangeAt(0).cloneRange();
}
function restoreRichSelection(editor) {
  const selection = window.getSelection();
  selection.removeAllRanges();
  if (state.richTextRange && document.contains(state.richTextRange.commonAncestorContainer) && editor.contains(state.richTextRange.commonAncestorContainer)) selection.addRange(state.richTextRange);
  else {
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    selection.addRange(range);
  }
}
function runRichTextCommand(button) {
  const shell = button.closest("[data-rich-editor-shell]");
  const editor = shell?.querySelector(".rich-editor-canvas");
  if (!editor) return;
  rememberRichSelection(editor);
  restoreRichSelection(editor);
  editor.focus();
  document.execCommand("defaultParagraphSeparator", false, "p");
  const command = button.dataset.richCommand;
  if (command === "createLink") {
    const url = window.prompt("输入链接地址（http、https 或 mailto）", "https://");
    if (!url) return;
    if (!/^(https?:\/\/|mailto:|#)/i.test(url)) return toast("链接地址格式无效", true);
    document.execCommand("createLink", false, url);
  } else document.execCommand(command, false, null);
  rememberRichSelection(editor);
  shell.querySelector(".editor-save-state").textContent = "有未保存修改";
}
function applyRichTextBlock(select) {
  const shell = select.closest("[data-rich-editor-shell]");
  const editor = shell?.querySelector(".rich-editor-canvas");
  if (!editor) return;
  restoreRichSelection(editor);
  editor.focus();
  document.execCommand("formatBlock", false, select.value);
  rememberRichSelection(editor);
  shell.querySelector(".editor-save-state").textContent = "有未保存修改";
}
async function uploadRichTextImage(input) {
  const file = input.files?.[0];
  const shell = input.closest("[data-rich-editor-shell]");
  const editor = shell?.querySelector(".rich-editor-canvas");
  if (!file || !shell || !editor) return;
  if (file.size > 5 * 1024 * 1024) { input.value = ""; return toast("图片超过5MB限制", true); }
  const trigger = shell.querySelector("[data-rich-image-trigger]");
  trigger.disabled = true;
  try {
    const result = await post(`/api/research/artifacts/${encodeURIComponent(shell.dataset.artifactId)}/images`, { filename: file.name, contentBase64: await fileToBase64(file) });
    restoreRichSelection(editor);
    editor.focus();
    const caption = escapeHTML(file.name.replace(/\.[^.]+$/, ""));
    const fragment = `<figure><img src="${escapeHTML(result.url)}" alt="${caption}"><figcaption>${caption}</figcaption></figure><p><br></p>`;
    document.execCommand("insertHTML", false, fragment);
    rememberRichSelection(editor);
    shell.querySelector(".editor-save-state").textContent = "图片已插入，等待保存";
    toast("图片已插入作品正文");
  } catch (error) { toast(error.message, true); }
  finally { trigger.disabled = false; input.value = ""; }
}
function insertRichIcon(button) {
  const shell = button.closest("[data-rich-editor-shell]");
  const editor = shell?.querySelector(".rich-editor-canvas");
  const icon = shell?.querySelector("[data-rich-icon-select]")?.value || "book-open";
  if (!editor || !artifactIconNames.includes(icon)) return;
  restoreRichSelection(editor);
  editor.focus();
  document.execCommand("insertHTML", false, `${artifactIconHTML(icon)}&#8203;`);
  rememberRichSelection(editor);
  shell.querySelector(".editor-save-state").textContent = "有未保存修改";
}
function insertGeneratedRichFigure(editor, result) {
  const figure = `<figure><img src="${escapeHTML(result.url)}" alt="${escapeHTML(result.alt || "科普内容配图")}">${result.caption ? `<figcaption>${escapeHTML(result.caption)}</figcaption>` : ""}</figure><p><br></p>`;
  const heading = String(result.afterHeading || "").trim();
  const target = heading ? [...editor.querySelectorAll("h2,h3,h4")].find((item) => item.textContent.trim().includes(heading)) : null;
  if (target) target.insertAdjacentHTML("afterend", figure);
  else {
    restoreRichSelection(editor);
    editor.focus();
    document.execCommand("insertHTML", false, figure);
  }
}
async function generateRichTextImage(button) {
  const shell = button.closest("[data-rich-editor-shell]");
  const form = button.closest('form[data-form="artifact"]');
  const artifact = state.artifacts.find((item) => item.id === form?.dataset.id);
  const editor = shell?.querySelector(".rich-editor-canvas");
  if (!shell || !form || !artifact || !editor) return;
  rememberRichSelection(editor);
  const visualId = button.dataset.visualId || "";
  const plan = (artifact.content?.visuals || []).find((item) => item.id === visualId) || {};
  const defaultPrompt = plan.prompt || `为《${artifact.title}》创作一幅无文字的科学传播插图，准确表现日食机制或文献研究，不伪造甲骨原片和甲骨文字。`;
  const prompt = window.prompt("检查或补充百炼配图提示词", defaultPrompt);
  if (!prompt?.trim()) return;
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "生成中";
  try {
    const result = await post(`/api/research/artifacts/${encodeURIComponent(artifact.id)}/generate-rich-image`, {
      visualId,
      prompt: prompt.trim(),
      alt: plan.alt || "科普内容配图",
      caption: plan.caption || "AI生成的科学传播插图，公开前需完成视觉审核。",
    });
    insertGeneratedRichFigure(editor, result);
    await post(`/api/research/artifacts/${encodeURIComponent(artifact.id)}/edit`, {
      kind: form.elements.kind.value,
      title: form.elements.title.value,
      content: collectArtifactContent(form, artifact),
    });
    state.artifactMediaRevision[artifact.id] = Date.now();
    toast("配图已按建议位置插入并保存，作品已回到待审核");
    await refresh();
  } catch (error) {
    toast(error.message, true);
    if (button.isConnected) { button.disabled = false; button.textContent = originalText; }
  }
}
async function generateSlideImage(button) {
  const form = button.closest('form[data-form="artifact"]');
  const artifact = state.artifacts.find((item) => item.id === form?.dataset.id);
  const page = button.closest("[data-slide-editor-page]");
  if (!form || !artifact || !page) return;
  const slideIndex = Number(button.dataset.slide || page.dataset.slideIndex || 0);
  const prompt = page.querySelector('[data-slide-field="visualPrompt"]')?.value.trim();
  if (!prompt) return toast("请先填写当前页配图提示词", true);
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "百炼生成中";
  try {
    await post(`/api/research/artifacts/${encodeURIComponent(artifact.id)}/edit`, {
      kind: form.elements.kind.value,
      title: form.elements.title.value,
      content: collectArtifactContent(form, artifact),
    });
    await post(`/api/research/artifacts/${encodeURIComponent(artifact.id)}/generate-slide-image`, {
      slideIndex,
      prompt,
      alt: page.querySelector('[data-slide-field="visualAlt"]')?.value || "幻灯片配图",
      caption: page.querySelector('[data-slide-field="visualCaption"]')?.value || "",
    });
    state.artifactMediaRevision[artifact.id] = Date.now();
    toast(`第 ${slideIndex + 1} 页配图已生成，作品已回到待审核`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
    if (button.isConnected) { button.disabled = false; button.textContent = originalText; }
  }
}
async function submitInspector(form) {
  const submit = form.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const type = form.dataset.form;
    if (type === "source") {
      await post(`/api/research/sources/${form.dataset.id}/edit`, { title: form.elements.title.value });
      toast("资料标题已保存");
    } else {
      const artifact = state.artifacts.find((item) => item.id === form.dataset.id);
      if (!artifact) throw new Error("作品不存在");
      await post(`/api/research/artifacts/${form.dataset.id}/edit`, { kind: form.elements.kind.value, title: form.elements.title.value, content: collectArtifactContent(form, artifact) });
      toast("修改已保存，作品回到待审核");
    }
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { if (submit?.isConnected) submit.disabled = false; }
}
function selectedStudioSourceIds() { return $$('input[name="studio-source"]:checked').map((input) => input.value); }
function renderResearchAnswer(result) {
  const normalized = { ...result, answer: cleanAnswerText(result.answer) };
  state.lastAnswer = normalized;
  result = normalized;
  const reviewLabel = result.reviewStatus === "reviewed" ? "来源均已确认" : "包含未确认资料";
  const citations = (result.citations || []).map((citation) => `<li><span>${escapeHTML(citation.label)}</span><small>${citation.reviewStatus === "reviewed" ? "已确认" : "未确认"}</small></li>`).join("");
  $("#research-answer").innerHTML = `<div class="research-answer-head"><strong>资料回答</strong><span class="answer-review answer-${escapeHTML(result.reviewStatus)}">${reviewLabel}</span></div><div class="research-answer-body">${escapeHTML(result.answer)}</div>${result.warning ? `<p class="answer-warning">${escapeHTML(result.warning)}</p>` : ""}<div class="answer-boundary">${escapeHTML(result.boundary || "私有研究结果，公开前必须人工审核。")}</div>${citations ? `<details class="answer-citations" open><summary>查看引用页码（${result.citations.length}）</summary><ol>${citations}</ol></details>` : ""}<div class="answer-actions"><button type="button" data-answer-action="note">保存为AI研究笔记</button><button type="button" data-answer-action="artifact">另存为作品草稿</button></div>`;
}
async function askResearch(event) {
  event.preventDefault();
  const question = $("#research-question").value.trim();
  const sourceIds = selectedStudioSourceIds();
  if (!question) return toast("请输入研究问题", true);
  if (!sourceIds.length) return toast("请至少选择一项资料", true);
  const button = $("#research-ask-submit");
  button.disabled = true;
  button.textContent = "检索资料中";
  $("#research-answer").innerHTML = '<p class="answer-loading">正在检索所选资料并组织回答…</p>';
  try {
    const result = await post("/api/research/ask", { question, sourceIds });
    renderResearchAnswer(result);
  } catch (error) {
    $("#research-answer").innerHTML = `<p class="answer-error">${escapeHTML(error.message)}</p>`;
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "提问";
  }
}
async function saveAnswerAsNote() {
  if (!state.lastAnswer) return toast("请先完成一次问答", true);
  try {
    const note = await post("/api/research/notes/from-answer", { title: `问答笔记 · ${state.lastAnswer.question.slice(0, 26)}`, question: state.lastAnswer.question, answer: state.lastAnswer.answer, sourceIds: state.lastAnswer.sourceIds, citations: state.lastAnswer.citations, model: state.lastAnswer.model });
    state.selected.source = note.id;
    toast("已保存为AI研究笔记；它不会再次作为证据检索");
    await refresh();
  } catch (error) { toast(error.message, true); }
}
async function saveAnswerAsArtifact() {
  if (!state.lastAnswer) return toast("请先完成一次问答", true);
  const kind = $("#output-kind-select").value || "research_qa";
  try {
    const artifact = await post("/api/research/artifacts/from-answer", { kind, title: `${state.artifactKinds.find((item) => item.id === kind)?.title || "研究问答"} · ${state.lastAnswer.question.slice(0, 24)}`, question: state.lastAnswer.question, answer: state.lastAnswer.answer, sourceIds: state.lastAnswer.sourceIds, citations: state.lastAnswer.citations, model: state.lastAnswer.model });
    state.selected.artifact = artifact.id;
    toast("已保存为作品草稿，并自动选中");
    await refresh();
  } catch (error) { toast(error.message, true); }
}
async function publish(event) {
  event?.preventDefault();
  const title = $("#release-title").value.trim();
  const description = $("#release-description").value.trim();
  const label = title || "公众内容更新";
  if (!window.confirm(`即将发布“${label}”并更新公众端。原始 PDF 不会公开，确认继续？`)) return;
  const button = $("#publish-snapshot");
  button.disabled = true;
  button.textContent = "正在发布";
  try {
    const result = await post("/api/research/publish", { title, description });
    $("#release-form").reset();
    $("#release-description-count").textContent = "0";
    state.expandedSnapshotId = result.snapshotId;
    toast(`已发布版本 ${result.snapshotId}`);
    await refresh();
    await loadSnapshotDetail(result.snapshotId);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "发布新版本"; }
}
async function restoreSnapshot(id) { if (!window.confirm("恢复会生成一个新的发布版本，不会删除当前版本。确认恢复？")) return; try { const result = await post(`/api/research/snapshots/${id}/restore`); toast(`已恢复此版本 ${result.snapshotId}`); await refresh(); } catch (error) { toast(error.message, true); } }
async function loadSnapshotDetail(id) {
  state.expandedSnapshotId = id;
  renderPublish();
  if (state.snapshotDetails[id]) return;
  try {
    state.snapshotDetails[id] = await request(`/api/research/snapshots/${encodeURIComponent(id)}`);
    renderPublish();
  } catch (error) {
    state.expandedSnapshotId = null;
    renderPublish();
    toast(error.message, true);
  }
}
async function snapshotAction(button) {
  const action = button.dataset.snapshotAction;
  const id = button.dataset.id;
  if (action === "details") {
    if (state.expandedSnapshotId === id) {
      state.expandedSnapshotId = null;
      renderPublish();
      return;
    }
    await loadSnapshotDetail(id);
    return;
  }
  if (action === "restore") return restoreSnapshot(id);
  if (action === "delete") {
    const snapshot = state.snapshots.find((item) => item.id === id);
    if (snapshot?.current) return toast("当前公众版本不能删除，请先发布或恢复其他版本", true);
    if (!window.confirm("删除后将移除此历史版本及其归档文件，但不会删除资料、知识或作品。确认删除？")) return;
    button.disabled = true;
    try {
      await post(`/api/research/snapshots/${encodeURIComponent(id)}/delete`);
      delete state.snapshotDetails[id];
      if (state.expandedSnapshotId === id) state.expandedSnapshotId = null;
      toast("历史版本已删除");
      await refresh();
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  }
}
async function testBailian() { const button = $("#model-state"); button.disabled = true; button.textContent = "检测百炼连接"; try { const result = await post("/api/research/bailian/test"); button.textContent = `百炼已连接 · ${result.model}`; button.title = `已连接 ${result.endpoint}`; toast(`百炼连接成功 · ${result.model}`); } catch (error) { button.textContent = "百炼连接受阻"; button.title = error.message; toast(error.message, true); } finally { button.disabled = false; } }
async function generateCardImage(button) {
  const artifactId = button.dataset.id;
  const cardIndex = Number(button.dataset.card || 0);
  button.disabled = true;
  button.textContent = "百炼生成中";
  try {
    const result = await post(`/api/research/artifacts/${encodeURIComponent(artifactId)}/generate-card-image`, { cardIndex });
    state.artifactMediaRevision[artifactId] = Date.now();
    toast(`第 ${cardIndex + 1} 张插图已生成，作品已退回草稿，请批准后发布`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "百炼生成当前插图";
  }
}
function stopArtifactSlidePlayback(artifactId) {
  clearTimeout(state.artifactSlideTimers[artifactId]);
  delete state.artifactSlideTimers[artifactId];
  state.artifactSlidesPlaying.delete(artifactId);
}
function scheduleArtifactSlidePlayback(artifact) {
  clearTimeout(state.artifactSlideTimers[artifact.id]);
  if (!state.artifactSlidesPlaying.has(artifact.id)) return;
  const slides = artifact.content?.slides || [];
  const total = slides.length + 1;
  const current = artifactPage(artifact, total);
  const page = current > 0 ? slides[current - 1] || {} : {};
  const seconds = Number(page.transition?.advanceAfter || artifact.content?.playback?.seconds || 8);
  state.artifactSlideTimers[artifact.id] = setTimeout(() => {
    let next = current + 1;
    if (next >= total) {
      if (artifact.content?.playback?.loop) next = 0;
      else { stopArtifactSlidePlayback(artifact.id); renderArtifactInspector(); return; }
    }
    state.artifactPages[artifact.id] = next;
    renderArtifactInspector();
    scheduleArtifactSlidePlayback(artifact);
  }, Math.max(3, seconds) * 1000);
}
function toggleArtifactSlidePlayback(button) {
  const artifact = state.artifacts.find((item) => item.id === button.dataset.id);
  if (!artifact) return;
  if (state.artifactSlidesPlaying.has(artifact.id)) stopArtifactSlidePlayback(artifact.id);
  else { state.artifactSlidesPlaying.add(artifact.id); scheduleArtifactSlidePlayback(artifact); }
  renderArtifactInspector();
}

function bind() {
  let savedNavCollapsed = false;
  try { savedNavCollapsed = localStorage.getItem("oracle-research-nav-collapsed") === "1"; } catch (_) { /* private browsing */ }
  setNavCollapsed(savedNavCollapsed, false);
  restorePaneSizes();
  $("#nav-collapse-toggle").addEventListener("click", () => setNavCollapsed(!document.body.classList.contains("nav-collapsed")));
  document.addEventListener("pointerdown", (event) => { const resizer = event.target.closest("[data-pane-resizer]"); if (resizer) startPaneResize(event, resizer); });
  document.addEventListener("pointermove", movePaneResize);
  document.addEventListener("pointerup", finishPaneResize);
  document.addEventListener("pointercancel", finishPaneResize);
  document.addEventListener("keydown", (event) => {
    const resizer = event.target.closest("[data-pane-resizer]");
    if (resizer && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
      const setting = paneSettings[resizer.dataset.paneResizer];
      const step = setting?.unit === "%" ? 2 : 16;
      if (setting) { event.preventDefault(); setPaneSize(resizer.dataset.paneResizer, state[setting.stateKey] + (event.key === "ArrowRight" ? step : -step)); }
      return;
    }
    if (event.key === "Escape" && state.fullscreenArtifactId) { event.preventDefault(); setArtifactFullscreen(false); return; }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && document.body.classList.contains("artifact-editor-fullscreen-open")) {
      const form = $("[data-artifact-workspace] form[data-form=artifact]");
      if (form) { event.preventDefault(); form.requestSubmit(); }
    }
  });
  document.addEventListener("dblclick", (event) => { const resizer = event.target.closest("[data-pane-resizer]"); if (resizer) setPaneSize(resizer.dataset.paneResizer, paneSettings[resizer.dataset.paneResizer]?.defaultValue); });
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setSection(button.dataset.section))); $$("[data-go]").forEach((button) => button.addEventListener("click", () => setSection(button.dataset.go)));
  $$('[data-import-tab]').forEach((button) => button.addEventListener("click", () => { state.importKind = button.dataset.importTab; $$('[data-import-tab]').forEach((item) => item.classList.toggle("is-active", item === button)); $$('[data-import-panel]').forEach((panel) => panel.classList.toggle("is-active", panel.dataset.importPanel === state.importKind)); }));
  $("#pdf-file").addEventListener("change", (event) => { $("#pdf-file-name").textContent = event.target.files[0]?.name || "选择文件"; }); $("#import-form").addEventListener("submit", importSource); $("#refresh-dashboard").addEventListener("click", () => refresh({ announce: true }).catch((error) => toast(error.message, true)));
  $("#source-list").addEventListener("click", (event) => { const action = event.target.closest("[data-source-action]"); if (action) return sourceAction(action); const select = event.target.closest("[data-select=source]"); if (select) { state.selected.source = select.dataset.id; state.sourcePage = 1; renderSources(); renderSourceInspector(); const source = state.sources.find((item) => item.id === state.selected.source); if (source?.kind === "pdf" || source?.source_role === "generated_note") loadUnits(source.id); } });
  $("#artifact-list").addEventListener("click", (event) => { const select = event.target.closest("[data-select=artifact]"); if (select) { state.selected.artifact = select.dataset.id; renderArtifacts(); renderArtifactInspector(); } });
  $("#site-content-list").addEventListener("click", (event) => { const action = event.target.closest("[data-site-row-action]"); if (action) return siteSectionRowAction(action.dataset.siteRowAction, action.dataset.key); const button = event.target.closest("[data-site-content-key]"); if (!button) return; commitSiteFormToState(); state.selected.siteContent = button.dataset.siteContentKey; renderSiteContent(); });
  $("#site-content-editor").addEventListener("error", handleSiteMediaError, true);
  $("#site-content-editor").addEventListener("click", (event) => { const htmlMode = event.target.closest("[data-site-html-mode]"); if (htmlMode) return setSiteHTMLMode(htmlMode.dataset.siteHtmlMode); const shortcode = event.target.closest("[data-site-shortcode]"); if (shortcode) return insertSiteShortcode(shortcode.dataset.siteShortcode); const slideAction = event.target.closest("[data-site-slide-action]"); if (slideAction) return changeHeroSlides(slideAction.dataset.siteSlideAction, Number(slideAction.dataset.index)); if (event.target.closest("[data-site-save]")) return saveSiteContent(); const review = event.target.closest("[data-site-review]"); if (review) return reviewSiteContent(review.dataset.siteReview); });
  $("#source-inspector").addEventListener("submit", (event) => { event.preventDefault(); submitInspector(event.target); }); $("#artifact-inspector").addEventListener("submit", (event) => { event.preventDefault(); submitInspector(event.target); });
  document.addEventListener("change", (event) => {
    const siteAsset = event.target.closest("[data-site-asset-target]");
    if (siteAsset) return uploadSiteAsset(siteAsset);
    const boardPresetSelect = event.target.closest("[data-board-preset]");
    if (boardPresetSelect) return handleBoardSizePreset(boardPresetSelect);
    const boardProperty = event.target.closest("[data-board-property], [data-board-edge-label]");
    if (boardProperty) return handleBoardPropertyInput(boardProperty);
    const imageInput = event.target.closest("[data-rich-image]");
    if (imageInput) return uploadRichTextImage(imageInput);
    const blockSelect = event.target.closest("[data-rich-block]");
    if (blockSelect) return applyRichTextBlock(blockSelect);
    const input = event.target.closest("[data-check]");
    if (!input) return;
    const set = state.checked[input.dataset.check];
    input.checked ? set.add(input.value) : set.delete(input.value);
    renderSources(); renderArtifacts();
  });
  [["source-select-all", "source"], ["artifact-select-all", "artifact"]].forEach(([id, kind]) => $("#" + id).addEventListener("change", (event) => {
    state.checked[kind].clear();
    if (event.target.checked) {
      if (kind === "source") state.sources.forEach((item) => state.checked.source.add(item.id));
      if (kind === "artifact") state.artifacts.forEach((item) => state.checked.artifact.add(item.id));
    }
    renderSources(); renderArtifacts();
  }));
  $("#source-list").addEventListener("click", (event) => { const button = event.target.closest("[data-source-bulk]"); if (button) sourceBulk(button.dataset.sourceBulk); }); $$('[data-source-bulk]').forEach((button) => button.addEventListener("click", () => sourceBulk(button.dataset.sourceBulk)));
  $$('[data-artifact-bulk]').forEach((button) => button.addEventListener("click", () => bulkReview("artifact", button.dataset.artifactBulk)));
  $("#research-ask-form").addEventListener("submit", askResearch);
  $("#generate-artifact").addEventListener("click", async () => { const sourceIds = selectedStudioSourceIds(); if (!sourceIds.length) return toast("请先确认并选择资料", true); const button = $("#generate-artifact"); const generationInstruction = $("#generation-instruction").value.trim(); const kind = $("#output-kind-select").value || state.outputKind || "record_table"; button.disabled = true; button.textContent = ["whiteboard", "mind_map"].includes(kind) ? "正在整理节点" : "生成中"; try { const context = await post("/api/research/artifacts/generate", { kind, sourceIds, generationInstruction }); state.selected.artifact = context.id; const model = String(context.model || ""); const fallbackReason = model.includes("after-bailian-timeout") ? "百炼响应超时" : model.includes("after-bailian-invalid-json") || model.includes("after-bailian-invalid-schema") ? "百炼返回结构不完整" : ""; toast(fallbackReason ? `${fallbackReason}，已用本地证据模板生成 ${context.title || "作品草稿"}` : `已生成 ${context.title || "作品草稿"}，已自动选中`); await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; button.textContent = "生成草稿"; } });
  $$("[data-output-kind]").forEach((button) => button.addEventListener("click", () => { state.outputKind = button.dataset.outputKind; $("#output-kind-select").value = state.outputKind; $$("[data-output-kind]").forEach((item) => item.classList.toggle("is-active", item === button)); }));
  $("#output-kind-select").addEventListener("change", (event) => { state.outputKind = event.target.value; $$("[data-output-kind]").forEach((item) => item.classList.toggle("is-active", item.dataset.outputKind === state.outputKind)); });
  $("#generation-instruction").addEventListener("input", (event) => { $("#generation-instruction-count").textContent = String(event.target.value.length); });
  document.addEventListener("mousedown", (event) => {
    const control = event.target.closest("[data-rich-command], [data-rich-image-trigger], [data-rich-block], [data-rich-insert-icon], [data-rich-generate-image]");
    const editor = control?.closest("[data-rich-editor-shell]")?.querySelector(".rich-editor-canvas");
    if (editor) rememberRichSelection(editor);
  });
  document.addEventListener("pointerdown", handleBoardPointerDown);
  document.addEventListener("pointermove", handleBoardPointerMove);
  document.addEventListener("pointerup", handleBoardPointerUp);
  document.addEventListener("pointercancel", handleBoardPointerUp);
  document.addEventListener("click", (event) => {
    const boardControl = event.target.closest("[data-board-action], [data-board-node-select], [data-board-node-delete], [data-board-edge-delete]");
    if (boardControl) return handleBoardAction(boardControl);
    const tableAction = event.target.closest("[data-table-action], [data-table-column-delete], [data-table-row-delete]");
    if (tableAction) return handleRecordTableAction(tableAction);
    const richCommand = event.target.closest("[data-rich-command]");
    if (richCommand) return runRichTextCommand(richCommand);
    const richIcon = event.target.closest("[data-rich-insert-icon]");
    if (richIcon) return insertRichIcon(richIcon);
    const richGeneratedImage = event.target.closest("[data-rich-generate-image]");
    if (richGeneratedImage) return generateRichTextImage(richGeneratedImage);
    const slideGeneratedImage = event.target.closest("[data-generate-slide-image]");
    if (slideGeneratedImage) return generateSlideImage(slideGeneratedImage);
    const imageTrigger = event.target.closest("[data-rich-image-trigger]");
    if (imageTrigger) {
      const editor = imageTrigger.closest("[data-rich-editor-shell]")?.querySelector(".rich-editor-canvas");
      if (editor) rememberRichSelection(editor);
      return imageTrigger.closest("[data-rich-editor-shell]")?.querySelector("[data-rich-image]")?.click();
    }
    const fullscreenOpen = event.target.closest("[data-artifact-fullscreen-open]");
    if (fullscreenOpen) return setArtifactFullscreen(true);
    const fullscreenClose = event.target.closest("[data-artifact-fullscreen-close]");
    if (fullscreenClose) return setArtifactFullscreen(false);
    const fullscreenSave = event.target.closest("[data-artifact-fullscreen-save]");
    if (fullscreenSave) return $("[data-artifact-workspace] form[data-form=artifact]")?.requestSubmit();
  });
  document.addEventListener("click", (event) => { const slidePlay = event.target.closest("[data-artifact-slide-play]"); if (slidePlay) return toggleArtifactSlidePlayback(slidePlay); const artifactStep = event.target.closest("[data-artifact-page-step]"); if (artifactStep) { const artifact = state.artifacts.find((item) => item.id === artifactStep.dataset.id); if (!artifact) return; const total = artifact.kind === "slide_deck" ? (artifact.content?.slides || []).length + 1 : (artifact.content?.cards || []).length; state.artifactPages[artifact.id] = Math.max(0, Math.min(total - 1, artifactPage(artifact, total) + Number(artifactStep.dataset.artifactPageStep))); return renderArtifactInspector(); } const artifactIndex = event.target.closest("[data-artifact-page-index]"); if (artifactIndex) { state.artifactPages[artifactIndex.dataset.id] = Number(artifactIndex.dataset.artifactPageIndex); return renderArtifactInspector(); } const generateImage = event.target.closest("[data-generate-card-image]"); if (generateImage) return generateCardImage(generateImage); const pageLink = event.target.closest("[data-pdf-page]"); if (pageLink) { event.preventDefault(); return syncPdfPage(pageLink.dataset.pdfPage); } const pageStep = event.target.closest("[data-pdf-step]"); if (pageStep) return syncPdfPage(state.sourcePage + Number(pageStep.dataset.pdfStep)); const answerAction = event.target.closest("[data-answer-action]"); if (answerAction) return answerAction.dataset.answerAction === "note" ? saveAnswerAsNote() : saveAnswerAsArtifact(); const action = event.target.closest("[data-inspector-action]"); if (!action) return; event.preventDefault(); const type = action.dataset.inspectorAction; if (type === "units") return loadUnits(action.dataset.id); if (type === "reviews") return loadReviews(action.dataset.reviewType, action.dataset.id); if (type === "source-delete") { action.dataset.sourceAction = "delete"; return sourceAction(action); } if (["review", "unreview", "reparse", "ocr", "ocr-reassess", "ocr-approve", "ocr-reject"].includes(type)) { action.dataset.sourceAction = type; return sourceAction(action); } if (type === "artifact-delete") { if (!window.confirm("删除后作品将从研究工作台移除，已发布作品需先撤销发布。确认删除？")) return; return post(`/api/research/artifacts/${action.dataset.id}/delete`).then(() => { state.selected.artifact = null; toast("作品已删除"); return refresh(); }).catch((error) => toast(error.message, true)); } if (type.startsWith("artifact-")) return reviewItem("artifact", action.dataset.id, type.endsWith("approve") ? "approve" : "withdraw"); });
  document.addEventListener("click", (event) => {
    const videoButton = event.target.closest("[data-generate-video]");
    if (videoButton) return generateVideo(videoButton);
  });
  document.addEventListener("click", (event) => { const noteCitation = event.target.closest("[data-note-source-id]"); if (noteCitation) { event.preventDefault(); return openNoteCitation(noteCitation); } });
  document.addEventListener("input", (event) => {
    if (event.target.id === "pdf-zoom-range") syncPdfZoom(Number(event.target.value) / 100);
    if (event.target.closest("#site-content-form")) {
      const shell = event.target.closest("[data-site-html-editor]");
      if (shell) {
        const visual = shell.querySelector("[data-site-html-visual]"); const source = shell.querySelector("[data-site-html-source]");
        if (event.target.matches("[data-site-html-visual]")) source.value = sanitizeSiteHTMLClient(visual.innerHTML);
        if (event.target.matches("[data-site-html-source]")) visual.innerHTML = sanitizeSiteHTMLClient(source.value);
        const count = shell.querySelector("[data-site-html-count]"); if (count) count.textContent = `${source.value.length} 字符`;
      }
      state.siteContentDirty.add(state.selected.siteContent); updateSitePreview();
    }
    if (event.target.id === "site-content-instruction") $("#site-content-instruction-count").textContent = String(event.target.value.length);
    const boardProperty = event.target.closest("[data-board-property], [data-board-edge-label]");
    if (boardProperty) return handleBoardPropertyInput(boardProperty);
    const editor = event.target.closest(".rich-editor-canvas");
    if (editor) {
      rememberRichSelection(editor);
      const stateLabel = editor.closest("[data-rich-editor-shell]")?.querySelector(".editor-save-state");
      if (stateLabel) stateLabel.textContent = "有未保存修改";
    }
  });
  document.addEventListener("click", (event) => { const zoomStep = event.target.closest("[data-pdf-zoom-step]"); if (zoomStep) return syncPdfZoom(state.pdfZoom + Number(zoomStep.dataset.pdfZoomStep) / 100); const zoomReset = event.target.closest("[data-pdf-zoom-reset]"); if (zoomReset) return syncPdfZoom(1); });
  $("#release-form").addEventListener("submit", publish);
  $("#generate-site-content").addEventListener("click", generateSiteContentDraft);
  $("#site-generation-modes").addEventListener("click", (event) => { const button = event.target.closest("[data-site-generation-mode]"); if (!button) return; state.siteGenerationMode = button.dataset.siteGenerationMode; renderSiteGenerationModes(); });
  $("#add-site-section").addEventListener("click", () => $("#site-section-dialog").showModal());
  $("#site-section-create-form").addEventListener("submit", createSiteSection);
  $("#release-description").addEventListener("input", (event) => { $("#release-description-count").textContent = String(event.target.value.length); });
  $("#snapshot-history").addEventListener("click", (event) => { const action = event.target.closest("[data-snapshot-action]"); if (action) snapshotAction(action); });
  $("#model-state").addEventListener("click", testBailian);
  $("#logout-button").addEventListener("click", async () => {
    const button = $("#logout-button");
    button.disabled = true;
    try { await post("/api/research/logout"); } catch (_) { /* Continue to login even if the session already expired. */ }
    location.replace("/research/login.html");
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - state.lastSyncedAt > 30000) {
      refresh().catch((error) => toast(error.message, true));
    }
  });
}
async function init() {
  if (initialized) return;
  initialized = true;
  try {
    bind();
    const initial = location.hash.slice(1);
    if (workspaceSectionExists(initial)) setSection(initial);
    const session = await request("/api/research/session");
    state.deploymentMode = session.deploymentMode || "local";
    if (!session.authenticated) {
      initialized = false;
      const next = encodeURIComponent(`${location.pathname}${location.hash}`);
      location.replace(`/research/login.html?next=${next}`);
      return;
    }
    const accessMode = $("#access-mode");
    if (accessMode) accessMode.textContent = session.deploymentMode === "public_demo" ? "公网演示 · 授权访问" : "仅本机";
    const syncTask = refreshWithRetry();
    const healthTask = request("/api/health").then((health) => {
      const modelButton = $("#model-state");
      modelButton.textContent = health.mode === "qwen" ? `百炼已配置 · ${health.model}` : "本地生成";
      modelButton.title = health.mode === "qwen" ? "API Key 已配置；点击检测实际网络连接" : "未配置百炼，使用本地证据模板";
    });
    const [syncResult, healthResult] = await Promise.allSettled([syncTask, healthTask]);
    if (syncResult.status === "rejected") toast(syncResult.reason?.message || "研究工作台同步失败", true);
    else if (healthResult.status === "rejected") toast("数据已同步，但模型状态暂时无法读取", true);
  } catch (error) {
    initialized = false;
    toast(error.message || "研究工作台初始化失败", true);
  }
}
document.addEventListener("DOMContentLoaded", init);
window.addEventListener("load", init);
window.addEventListener("pageshow", (event) => {
  if (event.persisted && state.lastSyncedAt) refresh().catch((error) => toast(error.message, true));
});
