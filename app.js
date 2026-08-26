const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  snapshot: null,
  knowledge: null,
  recordsMeta: null,
  records: [],
  literature: [],
  works: [],
  siteContent: {},
  heroIndex: 0,
  heroPaused: false,
  heroTimer: null,
  navObserver: null,
  activeWorkId: null,
  activeWorkKind: null,
  workPages: {},
  workSlideTimers: {},
  workSlidesPlaying: new Set(),
  query: ""
};

const workTypes = {
  public_explainer: { label: "大众讲解", kicker: "先读懂", description: "把已审核研究转写为面向普通读者的完整讲解。" },
  record_table: { label: "记录表", kicker: "逐项查找", description: "集中查看卜辞、著录、年代边界和主要争议。" },
  viewpoint_comparison: { label: "观点对照", kicker: "保留分歧", description: "把不同解释和待核问题并列呈现，不替争议下结论。" },
  audio_guide: { label: "音频导览", kicker: "听见日光", description: "用百炼中文语音把科学原理与甲骨记录串成正式WAV导览。" },
  research_qa: { label: "研究问答", kicker: "从问题开始", description: "保存一次基于资料的问答结果，保留问题、回答和引用。" },
  literature_summary: { label: "文献摘要", kicker: "抓住主线", description: "提炼文献论点、证据和需要继续核对的地方。" },
  source_guide: { label: "资料导读", kicker: "怎么读", description: "为一篇或一组资料建立阅读路线。" },
  dating_timeline: { label: "断代时间线", kicker: "排出年代", description: "将材料分期和天文学对应放在同一条时间线上。" },
  evidence_card: { label: "证据卡片", kicker: "一张卡片", description: "把主张、原文和争议集中展示。" },
  student_explainer: { label: "学生讲解", kicker: "讲给学生", description: "适合课堂和自主学习的版本。" },
  researcher_brief: { label: "研究者简报", kicker: "快速掌握", description: "面向研究者的材料、方法与争议摘要。" },
  infographic: { label: "科普图卡", kicker: "一眼看懂", description: "用于图卡排版的标题和要点文案。" },
  lesson_material: { label: "课堂材料", kicker: "带进课堂", description: "包括教学目标、活动和讨论问题。" },
  short_video_script: { label: "短视频脚本", kicker: "三分钟讲清", description: "按镜头、口播和证据提示组织。" },
  captions: { label: "视频字幕", kicker: "逐句呈现", description: "适合短视频剪辑的字幕草稿。" },
  visual_card_set: { label: "科普图卡组", kicker: "一组看懂", description: "用经过审核的文字和视觉层级组织成系列图卡。" },
  slide_deck: { label: "讲解幻灯片", kicker: "带进课堂", description: "按演示节奏组织标题、要点和讲者提示。" },
  video_package: { label: "可播放视频", kicker: "直接成片", description: "由分镜生成可直接播放的短片，并保留镜头信息。" },
  whiteboard: { label: "研究白板", kicker: "看见关系", description: "以可追溯节点整理资料、证据、观点和待核问题。" },
  mind_map: { label: "思维导图", kicker: "梳理脉络", description: "从中心主题展开资料证据、学者观点与研究边界。" }
};

const workOrder = ["public_explainer", "record_table", "viewpoint_comparison", "audio_guide", "visual_card_set", "slide_deck", "whiteboard", "mind_map", "video_package", "research_qa", "literature_summary", "source_guide", "dating_timeline", "evidence_card", "student_explainer", "researcher_brief", "infographic", "lesson_material", "short_video_script", "captions"];

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;"
  })[character]);
}
function slidePlainText(value) {
  const template = document.createElement("template");
  template.innerHTML = String(value ?? "");
  template.content.querySelectorAll("script,style,iframe,object,svg,math").forEach((node) => node.remove());
  return String(template.content.textContent || "").replace(/(?:\*\*|__|~~|`{1,3})/g, "").replace(/\s+/g, " ").trim();
}
function publicMediaText(value) {
  return slidePlainText(value)
    .replace(/《[^》]+》(?=\s*PDF第)/g, "")
    .replace(/《[^》]+》\s*PDF第[^，。；]*页表[^，。；]*截图/g, "")
    .replace(/《[^》]+》\s*PDF第[^，。；]*页/g, "")
    .replace(/PDF第[0-9、\-~]+页(?:表[^，。；]*截图)?/g, "")
    .replace(/(?:《[^》]+》|[^。；\n]{2,50}(?:研究|日食|行星历表)[^。；\n]{0,30})\s*[·•]\s*(?:PDF\s*)?第\s*\d+页/g, "")
    .replace(/\s*[·•]\s*(?:PDF\s*)?第\s*\d+页/g, "")
    .replace(/(?:《(?:癸酉日食说|说“癸酉日食”)》?|故宫博物院藏甲骨卜辞中记载的祖庚时期日食|殷卜辞乙巳日食的初步研究|基于JPL行星历表的殷卜辞乙巳日食观测的研究)\s*/g, "")
    .replace(/所有(?:画面、文字与旁白|结论)均[^。]*?(?:出处|页码)[^。]*。?/g, "")
    .replace(/本制作包依据给定资料生成[^。]*。?/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/[：:，,]\s*([，,。；])/g, "$1")
    .trim();
}
function slideDensityClass(page = {}) {
  const rich = Array.isArray(page.richText) ? page.richText : [];
  const bullets = Array.isArray(page.bullets) ? page.bullets : [];
  const size = [page.title, page.takeaway, ...bullets, ...rich.flatMap((item) => [item?.lead, item?.text])].map(slidePlainText).join("").length;
  return size > 280 ? "density-condensed" : size > 190 ? "density-compact" : "";
}

function preferredStaticImageUrl(url) {
  const value = String(url || "");
  const optimized = new Map([
    ["assets/hero-eclipse.png", "assets/hero-eclipse.webp"],
    ["assets/evidence-oracle.png", "assets/evidence-oracle.webp"],
    ["assets/eclipse-mechanism.png", "assets/eclipse-mechanism.webp"],
  ]);
  return optimized.get(value) || value;
}

async function getJSON(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function publishedSiteContent(key) {
  const shortcodeByRenderer = { science: "[日食科学互动]", history: "[甲骨时代导读]", records: "[甲骨日食记录]", works: "[研究成果]", ask: "[公众问答]", sources: "[研究依据与进度]" };
  const entry = state.siteContent?.[key] || Object.values(state.siteContent || {}).find((item) => String(item?.bodyHtml || "").includes(shortcodeByRenderer[key] || "\u0000"));
  return entry && typeof entry.content === "object" ? entry.content : null;
}
function publishedSiteEntry(key) {
  const shortcodeByRenderer = { science: "[日食科学互动]", history: "[甲骨时代导读]", records: "[甲骨日食记录]", works: "[研究成果]", ask: "[公众问答]", sources: "[研究依据与进度]" };
  return state.siteContent?.[key] || Object.values(state.siteContent || {}).find((item) => String(item?.bodyHtml || "").includes(shortcodeByRenderer[key] || "\u0000")) || null;
}

const publicShortcodes = {
  "[日食科学互动]": "science",
  "[甲骨时代导读]": "history",
  "[甲骨日食记录]": "records",
  "[研究成果]": "works",
  "[公众问答]": "ask",
  "[研究依据与进度]": "sources"
};

function sanitizeManagedHTML(rawHTML) {
  const allowed = new Set(["P", "H2", "H3", "H4", "UL", "OL", "LI", "STRONG", "EM", "BLOCKQUOTE", "A", "IMG", "FIGURE", "FIGCAPTION", "BR", "HR", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DIV", "SPAN"]);
  const template = document.createElement("template");
  template.innerHTML = String(rawHTML || "");
  [...template.content.querySelectorAll("*")].forEach((element) => {
    if (!allowed.has(element.tagName)) {
      if (["SCRIPT", "STYLE", "IFRAME", "OBJECT", "SVG", "MATH"].includes(element.tagName)) element.remove();
      else element.replaceWith(...element.childNodes);
      return;
    }
    const attributes = [...element.attributes];
    attributes.forEach((attribute) => element.removeAttribute(attribute.name));
    if (element.tagName === "A") {
      const href = attributes.find((attribute) => attribute.name.toLowerCase() === "href")?.value || "";
      if (/^(?:https?:\/\/|mailto:|#)/i.test(href)) { element.setAttribute("href", href); element.setAttribute("target", "_blank"); element.setAttribute("rel", "noopener noreferrer"); }
    }
    if (element.tagName === "IMG") {
      const src = attributes.find((attribute) => attribute.name.toLowerCase() === "src")?.value || "";
      if (!/^(?:\/?assets\/|\/api\/public\/site-media\/)/i.test(src)) { element.remove(); return; }
      element.setAttribute("src", src); element.setAttribute("loading", "lazy");
      ["alt", "title"].forEach((name) => { const value = attributes.find((attribute) => attribute.name.toLowerCase() === name)?.value; if (value) element.setAttribute(name, value.slice(0, 300)); });
    }
    if (element.tagName === "FIGURE" && attributes.some((attribute) => attribute.name.toLowerCase() === "class" && attribute.value === "site-generated-visual")) element.setAttribute("class", "site-generated-visual");
    if (["TH", "TD"].includes(element.tagName)) ["colspan", "rowspan"].forEach((name) => { const value = attributes.find((attribute) => attribute.name.toLowerCase() === name)?.value; if (/^\d{1,2}$/.test(value || "")) element.setAttribute(name, value); });
  });
  return template.innerHTML;
}

function managedRenderer(entry, contentKey) {
  if (entry.sectionType === "hero" || contentKey === "hero") return "hero";
  const body = String(entry.bodyHtml || "");
  return Object.entries(publicShortcodes).find(([code]) => body.includes(code))?.[1] || (document.querySelector(`[data-public-renderer="${contentKey}"]`) ? contentKey : "");
}

function managedExtraHTML(entry) {
  const template = document.createElement("template");
  template.innerHTML = sanitizeManagedHTML(entry.bodyHtml || "");
  const codes = Object.keys(publicShortcodes);
  const pattern = new RegExp(`(${codes.map((code) => code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => { node.data = node.data.replace(pattern, ""); });
  [...template.content.querySelectorAll("p")].forEach((node) => { if (!node.textContent.trim() && !node.querySelector("img")) node.remove(); });
  return template.innerHTML.trim();
}

function applyManagedHeadings(renderer, entry) {
  const selectors = {
    science: ["#science-kicker", "#science-title", "#science-summary"],
    history: ["#history-kicker", "#history-title", "#history-summary"],
    records: ["#records-kicker", "#records-title", "#records-summary"],
    works: ["#works-kicker", "#works-title", "#works-summary"],
    ask: ["#ask-kicker", "#ask-title", "#ask-summary"],
    sources: ["#sources-kicker", "#sources-title", "#sources-summary"]
  }[renderer];
  if (!selectors) return;
  setTextContent(selectors[0], entry.kicker); setTextContent(selectors[1], entry.title); setTextContent(selectors[2], entry.summary);
}

function publicNavigationLabel(entry) {
  const label = String(entry.navLabel || entry.nav_label || entry.title || "栏目").trim();
  return label.replace(/^栏目(?:[一二三四五六七八九十百]+|\d+)\s*[·•、.:：—-]?\s*/, "") || "栏目";
}

function observePublicSections() {
  state.navObserver?.disconnect();
  const links = $$('.site-nav a[href^="#"]');
  const sections = links.map((link) => {
    const id = decodeURIComponent(link.getAttribute("href").slice(1));
    return { link, section: document.getElementById(id) };
  }).filter(({ section }) => section && !section.hidden);
  const activate = (activeLink) => {
    sections.forEach(({ link }) => {
      const isActive = link === activeLink;
      link.classList.toggle("is-active", isActive);
      if (isActive) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  };
  if (!sections.length) return;
  activate(sections[0].link);
  if (!("IntersectionObserver" in window)) return;
  state.navObserver = new IntersectionObserver((entries) => {
    const current = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!current) return;
    activate(sections.find(({ section }) => section === current.target)?.link);
  }, { rootMargin: "-18% 0px -68%", threshold: [0, 0.2, 0.6] });
  sections.forEach(({ section }) => state.navObserver.observe(section));
}

function renderManagedSiteSections() {
  const main = $("#main");
  if (!main) return;
  $$('[data-managed-generated]', main).forEach((node) => node.remove());
  $$('[data-public-renderer]', main).forEach((node) => { node.hidden = true; node.removeAttribute("data-managed-key"); node.querySelector("[data-managed-extra]")?.remove(); });
  const managed = { ...(state.siteContent || {}) };
  if (String(state.snapshot?.schemaVersion || "0") < "0.6") {
    if (!managed.works) managed.works = { title: "已经可以公开阅读的研究成果", navLabel: "看公开成果", kicker: "从研究工作台审核发布", summary: "这里呈现的是研究工作台审核后正式发布的作品。未确认资料、未批准内容和原始论文不会在公众站显示。", bodyHtml: "<p>[研究成果]</p>", enabled: true, sortOrder: 4, content: {} };
    if (!managed.ask) managed.ask = { title: "从一句卜辞问起，也可以先问一个大问题", navLabel: "问一问", kicker: "问问古人的天空", summary: "回答只调用页面中的日食常识、甲骨记录和文献来源。没有证据的部分会直接说“尚不清楚”。", bodyHtml: "<p>[公众问答]</p>", enabled: true, sortOrder: 5, content: {} };
  }
  const entries = Object.entries(managed)
    .filter(([, entry]) => entry && entry.enabled !== false)
    .sort(([, a], [, b]) => Number(a.sortOrder || 0) - Number(b.sortOrder || 0));
  const navigation = [];
  const usedRenderers = new Set();
  const chapterLabels = {
    science: "天象",
    history: "殷商",
    records: "卜辞",
    works: "成果",
    ask: "问答",
    sources: "来源"
  };
  let chapter = 0;
  entries.forEach(([contentKey, entry]) => {
    const renderer = managedRenderer(entry, contentKey);
    if (renderer === "sources") return;
    let section = renderer && !usedRenderers.has(renderer) ? document.querySelector(`[data-public-renderer="${renderer}"]`) : null;
    if (section) {
      usedRenderers.add(renderer); section.hidden = false; section.dataset.managedKey = contentKey; applyManagedHeadings(renderer, entry);
      const extraHTML = managedExtraHTML(entry);
      if (extraHTML && renderer !== "hero") {
        const extra = document.createElement("div"); extra.className = "managed-section-html"; extra.dataset.managedExtra = ""; extra.innerHTML = extraHTML;
        const anchor = section.querySelector(".chapter-heading, .history-copy, .ask-copy, .sources-heading");
        if (["history", "ask"].includes(renderer) && anchor) anchor.append(extra);
        else if (anchor?.parentNode) anchor.parentNode.insertBefore(extra, anchor.nextSibling);
        else section.append(extra);
      }
    } else {
      section = document.createElement("section"); section.className = "managed-content-section"; section.dataset.managedGenerated = ""; section.dataset.managedKey = contentKey;
      section.innerHTML = `<div class="section-inner"><div class="chapter-heading reveal"><span class="chapter-number"></span><div><p class="kicker">${escapeHTML(entry.kicker || "")}</p><h2>${escapeHTML(entry.title || "未命名栏目")}</h2><p>${escapeHTML(entry.summary || "")}</p></div></div><div class="managed-section-html">${managedExtraHTML(entry)}</div></div>`;
    }
    if (renderer !== "hero") chapter += 1;
    const chapterNode = section.querySelector(".chapter-number");
    if (chapterNode && renderer !== "hero") chapterNode.textContent = chapterLabels[renderer] || "栏目";
    const anchorId = renderer === "records" ? "oracle" : (renderer || contentKey);
    if (!section.id) section.id = anchorId;
    main.append(section);
    if (renderer !== "hero") navigation.push(`<a href="#${escapeHTML(section.id)}">${escapeHTML(publicNavigationLabel(entry))}</a>`);
  });
  const nav = $(".site-nav");
  if (nav) {
    nav.innerHTML = navigation.join("");
    requestAnimationFrame(observePublicSections);
  }
}

function setTextContent(selector, value) {
  const node = $(selector);
  if (node && value) node.textContent = value;
}

function activeHeroSlides() {
  const content = publishedSiteContent("hero") || {};
  return (Array.isArray(content.slides) ? content.slides : []).filter((slide) => slide && slide.enabled !== false);
}

function stopHeroTimer() {
  clearTimeout(state.heroTimer);
  state.heroTimer = null;
}

function scheduleHeroTimer() {
  stopHeroTimer();
  const content = publishedSiteContent("hero") || {};
  const slides = activeHeroSlides();
  if (slides.length < 2 || !content.autoplay || state.heroPaused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const delay = Math.max(3, Math.min(30, Number(slides[state.heroIndex]?.durationSeconds || content.intervalSeconds || 6))) * 1000;
  state.heroTimer = setTimeout(() => showHeroSlide(state.heroIndex + 1), delay);
}

function showHeroSlide(index) {
  const slides = activeHeroSlides();
  if (!slides.length) return;
  state.heroIndex = (Number(index) + slides.length) % slides.length;
  const slide = slides[state.heroIndex];
  const mediaUrl = preferredStaticImageUrl(slide.mediaUrl || "assets/hero-eclipse.webp");
  const posterUrl = preferredStaticImageUrl(slide.posterUrl || "");
  const media = slide.mediaType === "video"
    ? `<video src="${escapeHTML(slide.mediaUrl || "")}" ${posterUrl ? `poster="${escapeHTML(posterUrl)}"` : ""} muted loop autoplay playsinline preload="metadata"></video>`
    : `<img src="${escapeHTML(mediaUrl)}" alt="" width="1920" height="1080" fetchpriority="high" decoding="async">`;
  $("#hero-media").innerHTML = `<div class="hero-slide is-active">${media}</div>`;
  setTextContent("#hero-overline", slide.overline);
  setTextContent("#hero-title", slide.title);
  setTextContent("#hero-lede", slide.lede);
  setTextContent("#hero-caption", slide.caption);
  const primary = $("#hero-primary-action");
  const secondary = $("#hero-secondary-action");
  if (primary) { primary.firstChild.textContent = `${slide.primaryAction?.label || "先看懂日食"} `; primary.href = slide.primaryAction?.href || "#science"; }
  if (secondary) { secondary.textContent = slide.secondaryAction?.label || "直接读记录"; secondary.href = slide.secondaryAction?.href || "#oracle"; }
  $$("[data-hero-index]", $("#hero-controls")).forEach((button) => {
    const active = Number(button.dataset.heroIndex) === state.heroIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "true" : "false");
  });
  const pause = $("[data-hero-action=pause]", $("#hero-controls"));
  if (pause) { pause.textContent = state.heroPaused ? "▶" : "Ⅱ"; pause.title = state.heroPaused ? "继续轮播" : "暂停轮播"; pause.setAttribute("aria-label", pause.title); }
  scheduleHeroTimer();
}

function renderHero() {
  const content = publishedSiteContent("hero");
  const slides = activeHeroSlides();
  if (!content || !slides.length) return;
  state.heroIndex = Math.min(state.heroIndex, slides.length - 1);
  state.heroPaused = window.matchMedia("(prefers-reduced-motion: reduce)").matches || !content.autoplay;
  const controls = $("#hero-controls");
  controls.hidden = slides.length < 2;
  controls.innerHTML = slides.length < 2 ? "" : `<button type="button" data-hero-action="previous" title="上一张" aria-label="上一张">←</button><div class="hero-dots">${slides.map((_, index) => `<button type="button" class="hero-dot ${index === state.heroIndex ? "is-active" : ""}" data-hero-index="${index}" title="第 ${index + 1} 张" aria-label="显示第 ${index + 1} 张"></button>`).join("")}</div><button type="button" data-hero-action="pause" title="${state.heroPaused ? "继续轮播" : "暂停轮播"}" aria-label="${state.heroPaused ? "继续轮播" : "暂停轮播"}">${state.heroPaused ? "▶" : "Ⅱ"}</button><button type="button" data-hero-action="next" title="下一张" aria-label="下一张">→</button>`;
  showHeroSlide(state.heroIndex);
}

function renderPublishedSiteContent() {
  renderHero();
  const science = publishedSiteContent("science");
  if (science) {
    if (!publishedSiteEntry("science")?.bodyHtml) { setTextContent("#science-kicker", science.kicker); setTextContent("#science-title", science.heading); setTextContent("#science-summary", science.summary); }
    setTextContent("#orbit-question", science.orbitQuestion);
    setTextContent("#orbit-explanation", science.orbitExplanation);
    setTextContent("#type-kicker", science.typeKicker);
    setTextContent("#type-heading", science.typeHeading);
    setTextContent("#safety-note", science.safetyNote);
  }
  const history = publishedSiteContent("history");
  if (history) {
    if (!publishedSiteEntry("history")?.bodyHtml) { setTextContent("#history-kicker", history.kicker); setTextContent("#history-title", history.heading); setTextContent("#history-summary", history.summary); }
    setTextContent("#history-quote", history.quote);
    if (history.image) {
      const image = $("#history-image");
      if (image && history.image.url) image.src = preferredStaticImageUrl(history.image.url);
      if (image && history.image.alt) image.alt = history.image.alt;
      setTextContent("#history-image-caption", history.image.caption);
    }
  }
  const records = publishedSiteContent("records");
  if (records) {
    if (!publishedSiteEntry("records")?.bodyHtml) { setTextContent("#records-kicker", records.kicker); setTextContent("#records-title", records.heading); setTextContent("#records-summary", records.summary); }
    setTextContent("#records-scope-title", records.scopeTitle);
    setTextContent("#records-scope-note", records.scopeNote);
    if (records.searchPlaceholder) $("#record-search").placeholder = records.searchPlaceholder;
  }
}

function renderScience() {
  if (!state.knowledge) return;
  const astronomy = state.knowledge.astronomy || {};
  if (!publishedSiteContent("science") && astronomy.plainExplanation) {
    $("#science-summary").textContent = astronomy.plainExplanation;
  }
  const historyContent = publishedSiteContent("history");
  const historyPoints = historyContent?.points || state.knowledge.history?.interpretation;
  if (historyPoints?.length) {
    $("#belief-points").innerHTML = historyPoints
      .map((item) => `<p>${escapeHTML(item)}</p>`)
      .join("");
  }
  updateEclipseType("total");
}

function updateEclipseType(typeId) {
  const types = publishedSiteContent("science")?.eclipseTypes || state.knowledge?.astronomy?.types || [];
  const type = types.find((item) => item.id === typeId) || types[0];
  if (!type) return;
  $("#type-name").textContent = type.name;
  $("#type-short").textContent = type.short;
  $("#type-explanation").textContent = type.explanation;
  $("#type-fact").textContent = type.fact;
  $("#eclipse-view").className = `eclipse-view ${type.id}`;
  $$(".type-tab").forEach((button) => {
    const active = button.dataset.type === type.id;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  window.dispatchEvent(new CustomEvent("eclipse:typechange", { detail: { type: type.id } }));
}

function sourceFor(id) {
  return state.literature.find((item) => String(item.id) === String(id));
}

function publicSourceUrl(source) {
  if (!source) return "#sources";
  return source.detailUrl || `/source.html?id=${encodeURIComponent(source.id)}`;
}

function recordsFromPublishedTables(works, literature) {
  const literatureByTitle = new Map(literature.map((item) => [String(item.title || "").trim(), String(item.id || "")]));
  const seen = new Set();
  return works
    .filter((work) => work.kind === "record_table")
    .flatMap((work) => {
      const sourceIds = (work.provenance?.sources || [])
        .map((source) => literatureByTitle.get(String(source.title || "").trim()))
        .filter(Boolean);
      return (work.content?.rows || []).map((row, index) => {
        const inscription = String(row["卜辞"] || "").trim();
        const catalogNumber = String(row["著录"] || "").trim();
        const key = `${inscription}\u0000${catalogNumber}`;
        if (!inscription || seen.has(key)) return null;
        seen.add(key);
        const status = String(row["状态"] || "研究线索");
        return {
          id: `${work.id}-row-${index + 1}`,
          headline: catalogNumber || "已发布记录表条目",
          inscription,
          status,
          reviewed: !["待核", "尚未", "未确认"].some((token) => status.includes(token)),
          translation: String(row["释义"] || "当前已公开卜辞、著录、年代与争议；基本释义尚待古文字学复核后补充。"),
          dating: String(row["年代"] || "尚不清楚"),
          catalogNumber: catalogNumber || "尚待核对",
          scholarViews: [],
          disputes: String(row["争议"] || "").split(/[；\n]+/).map((item) => item.trim()).filter(Boolean),
          sourceIds,
          sourceEvidence: [],
          reviewLevel: "来自已审核发布的记录表"
        };
      }).filter(Boolean);
    });
}

function searchableRecord(record) {
  const sources = (record.sourceIds || []).map(sourceFor).filter(Boolean);
  return [
    record.headline,
    record.inscription,
    record.status,
    record.translation,
    record.dating,
    record.catalogNumber,
    record.reviewLevel,
    ...(record.scholarViews || []),
    ...(record.disputes || []),
    ...(record.sourceEvidence || []).map((item) => item.purpose),
    ...sources.flatMap((source) => [source.title, ...(source.authors || [])])
  ].join(" ").toLocaleLowerCase("zh-CN");
}

function evidenceLabel(item) {
  const source = sourceFor(item.sourceId);
  return source?.title || "来源文献";
}

function renderRecords() {
  const query = state.query.trim().toLocaleLowerCase("zh-CN");
  const records = state.records.filter((record) => !query || searchableRecord(record).includes(query));
  $("#record-count").textContent = `显示 ${records.length} / ${state.records.length} 条`;
  $("#record-empty").hidden = records.length > 0;
  $("#record-list").innerHTML = records.map((record, index) => {
    const statusClass = record.reviewed ? "verified" : "pending";
    const views = (record.scholarViews || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("");
    const disputes = (record.disputes || []).map((item) => `<li>${escapeHTML(item)}</li>`).join("");
    return `
      <details class="record-item" data-record-id="${escapeHTML(record.id)}">
        <summary>
          <span class="record-index">${String(index + 1).padStart(2, "0")}</span>
          <span class="record-inscription">
            <strong>${escapeHTML(record.inscription)}</strong>
            <span>${escapeHTML(record.headline)}</span>
          </span>
          <span class="status-chip ${statusClass}">${escapeHTML(record.status)}</span>
          <span class="record-toggle" aria-hidden="true"></span>
        </summary>
        <div class="record-detail">
          <p class="detail-lead">${escapeHTML(record.translation)}</p>
          <div class="evidence-strip">
            <div>
              <span>著录</span>
              <strong>${escapeHTML(record.catalogNumber || "尚待核对")}</strong>
            </div>
          </div>
          <div class="detail-grid">
            <section class="detail-block">
              <h4>年代</h4>
              <p>${escapeHTML(record.dating || "尚不清楚")}</p>
            </section>
            <section class="detail-block">
              <h4>学者观点</h4>
              <ul>${views}</ul>
            </section>
            <section class="detail-block">
              <h4>争议与待核</h4>
              <ul>${disputes}</ul>
            </section>
          </div>
        </div>
      </details>
    `;
  }).join("");
}

function renderTextWork(text = "") {
  const publicText = String(text)
    .replaceAll("**", "")
    .replaceAll("已审核知识快照", "已审核并发布的内容")
    .replaceAll("稳定知识快照", "当前发布内容")
    .replaceAll("审核快照", "已审核发布内容")
    .replaceAll("候选知识", "待整理内容");
  return publicText.trim().split(/\n\s*\n/).filter(Boolean).map((block) => {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length && lines.every((line) => line.startsWith("- "))) {
      return `<ul>${lines.map((line) => `<li>${escapeHTML(line.slice(2))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(escapeHTML).join("<br>")}</p>`;
  }).join("");
}

function cleanAnswerText(text = "") {
  return String(text || "").replace(/\*{2,}/g, "").trim();
}

const publicRichTags = new Set(["P", "H2", "H3", "H4", "UL", "OL", "LI", "STRONG", "EM", "BLOCKQUOTE", "A", "IMG", "FIGURE", "FIGCAPTION", "SPAN", "BR"]);
const publicArtifactIcons = new Set(["sun", "moon", "telescope", "book-open", "scale", "clock-3", "sparkles", "chart", "presentation"]);
function publicArtifactIcon(name) {
  const icon = publicArtifactIcons.has(name) ? name : "book-open";
  return `<span data-icon="${icon}" class="artifact-icon artifact-icon-${icon}" aria-hidden="true"></span>`;
}
function sanitizePublicRichHTML(rawHTML, artifactId) {
  const template = document.createElement("template");
  template.innerHTML = String(rawHTML || "");
  [...template.content.querySelectorAll("*")].forEach((element) => {
    if (!publicRichTags.has(element.tagName)) {
      if (["SCRIPT", "STYLE", "IFRAME", "OBJECT"].includes(element.tagName)) element.remove();
      else element.replaceWith(...element.childNodes);
      return;
    }
    const attributes = [...element.attributes];
    attributes.forEach((attribute) => element.removeAttribute(attribute.name));
    if (element.tagName === "SPAN") {
      const icon = attributes.find((item) => item.name.toLowerCase() === "data-icon")?.value || "";
      if (!publicArtifactIcons.has(icon)) { element.replaceWith(...element.childNodes); return; }
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
      element.setAttribute("src", `/api/public/artifacts/${artifactId}/images/${match[1]}`);
      ["alt", "title"].forEach((name) => {
        const value = attributes.find((item) => item.name.toLowerCase() === name)?.value;
        if (value) element.setAttribute(name, value.slice(0, 300));
      });
      element.setAttribute("loading", "lazy");
    }
  });
  return template.innerHTML;
}
function renderTextualWork(work, extraClass = "") {
  const richHTML = work.content?.html;
  const classes = `work-prose rich-work-prose ${extraClass}`.trim();
  if (typeof richHTML === "string" && richHTML.trim()) return `<div class="${classes}">${sanitizePublicRichHTML(richHTML, work.id)}</div>`;
  return `<div class="${classes}">${renderTextWork(work.content?.text || "")}</div>`;
}

function workPage(work, total) {
  const current = Number(state.workPages[work.id] || 0);
  return Math.max(0, Math.min(Math.max(0, total - 1), current));
}

function workPager(work, total, current) {
  return `<div class="public-reader-controls"><button type="button" data-work-page-step="-1" data-id="${escapeHTML(work.id)}" ${current === 0 ? "disabled" : ""} title="上一页" aria-label="上一页">←</button><div class="public-reader-pages" aria-label="选择页面">${Array.from({ length: total }, (_, index) => `<button type="button" data-work-page-index="${index}" data-id="${escapeHTML(work.id)}" class="${index === current ? "is-active" : ""}" aria-label="第${index + 1}页" aria-current="${index === current ? "page" : "false"}">${index + 1}</button>`).join("")}</div><span>${current + 1} / ${total}</span><button type="button" data-work-page-step="1" data-id="${escapeHTML(work.id)}" ${current === total - 1 ? "disabled" : ""} title="下一页" aria-label="下一页">→</button></div>`;
}

function renderRecordTable(work) {
  const columns = work.content?.columns || [];
  const rows = work.content?.rows || [];
  return `
    <div class="work-table-wrap">
      <table class="public-record-table">
        <thead><tr>${columns.map((column) => `<th scope="col">${escapeHTML(column)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((row) => `
          <tr>${columns.map((column) => `<td>${escapeHTML(row[column] ?? "")}</td>`).join("")}</tr>
        `).join("")}</tbody>
      </table>
    </div>
  `;
}

function renderViewpointComparison(work) {
  const items = work.content?.items || [];
  return `<div class="viewpoint-list">${items.map((item, index) => `
    <details class="viewpoint-item">
      <summary>
        <span>${String(index + 1).padStart(2, "0")}</span>
        <strong>第${String(index + 1).padStart(2, "0")}条观点对照</strong>
        <span class="viewpoint-toggle" aria-hidden="true"></span>
      </summary>
      <div class="viewpoint-body">
        <section>
          <h4>学者观点</h4>
          <ul>${(item.views || []).map((view) => `<li>${escapeHTML(view)}</li>`).join("") || "<li>尚待补录</li>"}</ul>
        </section>
        <section>
          <h4>争议与待核</h4>
          <ul>${(item.disputes || []).map((dispute) => `<li>${escapeHTML(dispute)}</li>`).join("") || "<li>尚待补录</li>"}</ul>
        </section>
      </div>
    </details>
  `).join("")}</div>`;
}

function renderAudioGuide(work) {
  const configuredUrl = work.media?.url || `/api/public/artifacts/${encodeURIComponent(work.id)}/audio`;
  const publicAudioBase = configuredUrl.replace(/\/audio(?:\.(?:mp3|wav))?$/, "/audio");
  const playbackUrl = publicAudioBase.startsWith("/api/public/artifacts/") ? `${publicAudioBase}.mp3` : configuredUrl;
  const downloadUrl = publicAudioBase.startsWith("/api/public/artifacts/") ? `${publicAudioBase}.wav` : configuredUrl;
  return `
    <div class="audio-guide">
      <div class="audio-actions" aria-label="正式音频导览">
        <div><span>在线导览</span><strong>百炼语音 · 轻量播放</strong></div>
        <audio controls preload="metadata" src="${escapeHTML(playbackUrl)}">当前浏览器不支持音频播放。</audio>
        <a class="audio-download" href="${escapeHTML(downloadUrl)}" download>下载高质量 WAV</a>
      </div>
      ${renderTextualWork(work, "audio-transcript")}
    </div>
  `;
}

function renderVisualCardSet(work) {
  const cards = Array.isArray(work.content?.cards) ? work.content.cards : [];
  if (!cards.length) return '<p class="loading-row">图卡内容待补充。</p>';
  const current = workPage(work, cards.length);
  const card = cards[current] || {};
  const body = Array.isArray(card.body) ? card.body : [card.body || "内容待补充"];
  const version = encodeURIComponent(state.snapshot?.snapshotId || work.updated_at || "published");
  const cardUrl = `/api/public/artifacts/${encodeURIComponent(work.id)}/cards/${current + 1}`;
  const title = card.title || `科普图卡 ${current + 1}`;
  return `<div class="public-artifact-reader"><figure class="public-card-page"><picture hidden><source srcset="${cardUrl}.webp?v=${version}" type="image/webp"><img data-public-card-image src="${cardUrl}.png?v=${version}" alt="${escapeHTML(title)}" width="1080" height="1350" loading="lazy" decoding="async"></picture><article class="public-card-fallback"><span>${String(current + 1).padStart(2, "0")}</span><h4>${escapeHTML(title)}</h4><ul>${body.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></article><figcaption>${escapeHTML(title)}</figcaption></figure>${workPager(work, cards.length, current)}</div>`;
}

function bindPublicCardFallbacks() {
  $$('[data-public-card-image]').forEach((image) => {
    const showFallback = () => { const picture = image.closest("picture"); if (picture) picture.hidden = true; else image.hidden = true; const fallback = picture?.nextElementSibling || image.nextElementSibling; if (fallback) fallback.hidden = false; };
    image.addEventListener("error", showFallback, { once: true });
    if (image.complete && !image.naturalWidth) showFallback();
  });
}

function publicSlideChartHTML(chart = {}) {
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

function publicSlideDiagramHTML(diagram = {}) {
  const nodes = Array.isArray(diagram.nodes) ? diagram.nodes : [];
  if (!nodes.length) return "";
  return `<div class="slide-process-preview">${nodes.map((node, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHTML(node.label || "节点")}</strong><small>${escapeHTML(node.detail || "")}</small></article>`).join('<i aria-hidden="true">→</i>')}</div>`;
}

function publicSlidePageHTML(work, page, current) {
  if (page.cover) return `<div class="public-slide-cover"><span>甲骨里的日光缺口</span><h4>${escapeHTML(slidePlainText(page.title) || "讲解幻灯片")}</h4><p>${escapeHTML(slidePlainText(page.subtitle) || "基于已确认资料形成的公开讲解幻灯片")}</p></div>`;
  const rich = Array.isArray(page.richText) ? page.richText : [];
  const bullets = (Array.isArray(page.bullets) ? page.bullets : []).map(publicMediaText).filter(Boolean);
  const visual = page.visual || {};
  const citations = (Array.isArray(page.citations) ? page.citations : [page.citations]).map(slidePlainText).filter(Boolean).slice(0, 3);
  const image = visual.asset ? `<figure class="slide-page-image"><img src="/api/public/artifacts/${encodeURIComponent(work.id)}/images/${escapeHTML(visual.asset)}" alt="${escapeHTML(publicMediaText(visual.alt) || "页面配图")}" loading="lazy"><figcaption>${escapeHTML(publicMediaText(visual.caption))}</figcaption></figure>` : "";
  const visualHTML = image || publicSlideChartHTML(page.chart) || publicSlideDiagramHTML(page.diagram);
  const title = publicMediaText(page.title) || `第${current}页`;
  const takeaway = publicMediaText(page.takeaway);
  const textHTML = `<div class="slide-copy-column"><div class="slide-title-row">${publicArtifactIcon(page.icon)}<span>${String(current).padStart(2, "0")}</span></div><h4>${escapeHTML(title)}</h4>${takeaway ? `<p class="slide-takeaway">${escapeHTML(takeaway)}</p>` : ""}${rich.length ? `<div class="slide-rich-lines">${rich.map((item) => { const lead = publicMediaText(item?.lead); const text = publicMediaText(item?.text); return `<p>${lead ? `<strong>${escapeHTML(lead)}</strong>` : ""}${escapeHTML(text)}</p>`; }).join("")}</div>` : `<ul>${bullets.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>`}</div>`;
  return `<div class="public-slide-page layout-${escapeHTML(page.layout || "statement")} ${slideDensityClass(page)}">${textHTML}${visualHTML ? `<div class="slide-visual-column">${visualHTML}</div>` : ""}</div>`;
}

function renderSlideDeck(work) {
  const slides = Array.isArray(work.content?.slides) ? work.content.slides : [];
  if (!slides.length) return '<p class="loading-row">幻灯片内容待补充。</p>';
  const pages = [{ cover: true, title: work.title, subtitle: work.content?.subtitle }, ...slides];
  const current = workPage(work, pages.length);
  const page = pages[current] || {};
  const transition = page.transition?.type || work.content?.playback?.transition || "fade";
  const playing = state.workSlidesPlaying.has(work.id);
  return `<div class="public-artifact-reader"><article class="public-slide-frame ${page.cover ? "is-cover" : ""} transition-${escapeHTML(transition)}">${publicSlidePageHTML(work, page, current)}</article><div class="public-slide-controls">${workPager(work, pages.length, current)}<button type="button" data-work-slide-play data-id="${escapeHTML(work.id)}" aria-pressed="${playing}">${playing ? "暂停" : "播放"}</button></div></div>`;
}

function renderVideoPackage(work) {
  const scenes = Array.isArray(work.content?.scenes) ? work.content.scenes : [];
  const video = work.content?.video || {};
  const player = video.status === "ready"
    ? `<video class="public-artifact-video" controls preload="metadata" playsinline src="/api/public/artifacts/${encodeURIComponent(work.id)}/video">当前浏览器不支持视频播放。</video>`
    : "";
  return `${player}<div class="public-video-timeline">${scenes.map((scene, index) => `<article><time>${escapeHTML(`${scene.start ?? scene.startSeconds ?? 0}–${scene.end ?? scene.endSeconds ?? ""} 秒`)}</time><div><span>镜头 ${String(index + 1).padStart(2, "0")}</span><h4>${escapeHTML(publicMediaText(scene.onScreenText) || "屏幕文字待补充")}</h4><p><strong>画面</strong>${escapeHTML(publicMediaText(scene.visual) || "待设计")}</p><p><strong>旁白</strong>${escapeHTML(publicMediaText(scene.narration) || "待补充")}</p></div></article>`).join("")}</div>`;
}

function renderResearchBoard(work) {
  const content = work.content || {};
  const nodes = Array.isArray(content.nodes) ? content.nodes : [];
  const edges = Array.isArray(content.edges) ? content.edges : [];
  if (!nodes.length) return '<p class="loading-row">白板内容待补充。</p>';
  const viewport = content.viewport || {};
  const width = Math.max(720, Number(viewport.width) || 1200);
  const height = Math.max(480, Number(viewport.height) || 760);
  const markerId = `public-board-arrow-${String(work.id).replace(/[^A-Za-z0-9_-]/g, "-")}`;
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edgeSVG = edges.map((edge) => {
    const source = nodeMap.get(edge.from);
    const target = nodeMap.get(edge.to);
    if (!source || !target) return "";
    const sourceX = Number(source.x) + Number(source.width) / 2;
    const sourceY = Number(source.y) + Number(source.height) / 2;
    const targetX = Number(target.x) + Number(target.width) / 2;
    const targetY = Number(target.y) + Number(target.height) / 2;
    const dx = targetX - sourceX;
    const dy = targetY - sourceY;
    let x1; let y1; let x2; let y2; let path;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const direction = dx >= 0 ? 1 : -1;
      x1 = sourceX + direction * Number(source.width) / 2;
      y1 = sourceY;
      x2 = targetX - direction * Number(target.width) / 2;
      y2 = targetY;
      const bend = Math.max(48, Math.abs(x2 - x1) * 0.48);
      path = `M ${x1} ${y1} C ${x1 + direction * bend} ${y1}, ${x2 - direction * bend} ${y2}, ${x2} ${y2}`;
    } else {
      const direction = dy >= 0 ? 1 : -1;
      x1 = sourceX;
      y1 = sourceY + direction * Number(source.height) / 2;
      x2 = targetX;
      y2 = targetY - direction * Number(target.height) / 2;
      const bend = Math.max(42, Math.abs(y2 - y1) * 0.48);
      path = `M ${x1} ${y1} C ${x1} ${y1 + direction * bend}, ${x2} ${y2 - direction * bend}, ${x2} ${y2}`;
    }
    return `<g><path d="${path}" marker-end="url(#${markerId})"></path>${edge.label ? `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 9}">${escapeHTML(edge.label)}</text>` : ""}</g>`;
  }).join("");
  const nodeHTML = nodes.map((node, index) => {
    const left = Math.max(0, Math.min(100, Number(node.x) / width * 100));
    const top = Math.max(0, Math.min(100, Number(node.y) / height * 100));
    const nodeWidth = Math.max(10, Math.min(50, Number(node.width) / width * 100));
    const nodeHeight = Math.max(10, Math.min(55, Number(node.height) / height * 100));
    const nodeType = ["note", "evidence", "source", "artifact"].includes(node.type) ? node.type : "note";
    const type = ({ note: "研究笔记", evidence: "证据", source: "资料", artifact: "作品" })[nodeType];
    return `<article class="public-board-node board-type-${escapeHTML(nodeType)} board-color-${escapeHTML(node.color || "gold")} ${work.kind === "mind_map" && index === 0 ? "is-root" : ""}" style="left:${left}%;top:${top}%;width:${nodeWidth}%;height:${nodeHeight}%"><span>${escapeHTML(type)}</span><strong>${escapeHTML(publicMediaText(node.title || "未命名节点"))}</strong><p>${escapeHTML(publicMediaText(node.body || ""))}</p></article>`;
  }).join("");
  return `<div class="public-board-reader"><div class="public-board-meta"><span>${work.kind === "mind_map" ? "思维导图" : "研究白板"}</span><strong>${nodes.length} 个节点 · ${edges.length} 条关系</strong><small>审核发布版</small></div><div class="public-board-scroll"><div class="public-board-stage ${work.kind === "mind_map" ? "is-mind-map" : ""}" style="aspect-ratio:${width} / ${height}"><svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><marker id="${markerId}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${edgeSVG}</svg>${nodeHTML}</div></div></div>`;
}

function renderWorkContent(work) {
  if (work.kind === "record_table") return renderRecordTable(work);
  if (work.kind === "viewpoint_comparison") return renderViewpointComparison(work);
  if (work.kind === "audio_guide") return renderAudioGuide(work);
  if (work.kind === "visual_card_set") return renderVisualCardSet(work);
  if (work.kind === "slide_deck") return renderSlideDeck(work);
  if (work.kind === "video_package") return renderVideoPackage(work);
  if (["whiteboard", "mind_map"].includes(work.kind)) return renderResearchBoard(work);
  return renderTextualWork(work);
}

function renderWorks() {
  const works = [...state.works].sort((a, b) => workOrder.indexOf(a.kind) - workOrder.indexOf(b.kind));
  $("#work-count").textContent = String(works.length);
  $("#work-source-count").textContent = `${state.snapshot?.audit?.reviewedSources || 0} / 7`;

  if (!works.length) {
    $("#work-tabs").innerHTML = "";
    $("#work-stage").innerHTML = '<p class="loading-row">尚无作品通过审核发布。</p>';
    return;
  }

  const groups = [...new Set(works.map((work) => work.kind))].map((kind) => ({ kind, works: works.filter((work) => work.kind === kind) }));
  if (!state.activeWorkKind || !groups.some((group) => group.kind === state.activeWorkKind)) state.activeWorkKind = groups.find((group) => group.kind === "public_explainer")?.kind || groups[0].kind;
  const activeGroup = groups.find((group) => group.kind === state.activeWorkKind) || groups[0];
  if (!state.activeWorkId || !activeGroup.works.some((work) => work.id === state.activeWorkId)) state.activeWorkId = activeGroup.works[0].id;
  const active = activeGroup.works.find((work) => work.id === state.activeWorkId) || activeGroup.works[0];
  const activeIndex = groups.indexOf(activeGroup);
  const meta = workTypes[active.kind] || { label: active.title, kicker: "审核发布", description: "经研究工作台审核并正式发布的作品。" };

  $("#work-tabs").innerHTML = groups.map((group, index) => {
    const itemMeta = workTypes[group.kind] || { label: group.kind };
    const selected = group.kind === activeGroup.kind;
    return `<button id="work-tab-${index}" type="button" role="tab" aria-selected="${selected}" aria-controls="work-panel" data-work-kind="${escapeHTML(group.kind)}" class="${selected ? "is-active" : ""}">${escapeHTML(itemMeta.label)}${group.works.length > 1 ? ` <span class="work-count-badge">${group.works.length}</span>` : ""}</button>`;
  }).join("");
  const variants = activeGroup.works.length > 1 ? `<div class="work-variants" aria-label="同类型作品"><span>同类型作品</span>${activeGroup.works.map((work, index) => `<button type="button" data-work-id="${escapeHTML(work.id)}" class="${work.id === active.id ? "is-active" : ""}">${escapeHTML(work.title || `版本 ${index + 1}`)}</button>`).join("")}</div>` : "";

  $("#work-stage").innerHTML = `
    <article id="work-panel" class="work-panel" role="tabpanel" aria-labelledby="work-tab-${activeIndex}">
      <header class="work-panel-heading">
        <div>
          <p class="kicker">${escapeHTML(meta.kicker)}</p>
          <h3>${escapeHTML(active.title)}</h3>
          <p>${escapeHTML(meta.description)}</p>
        </div>
        <div class="work-panel-meta">
          <span>经审核发布</span>
          <span>${escapeHTML(active.provenance?.sourceCount || 0)} 篇来源资料</span>
        </div>
      </header>
      ${variants}
      <div class="work-output">${renderWorkContent(active)}</div>
    </article>
  `;
  bindPublicCardFallbacks();
}

async function loadData() {
  try {
    const snapshot = await getJSON("/api/public/snapshot").catch(() =>
      getJSON("data/published-snapshot.json")
    );
    const knowledge = snapshot.knowledge;
    const recordsMeta = snapshot.recordsMeta;
    const literatureMeta = snapshot.literatureMeta;
    state.snapshot = snapshot;
    state.knowledge = knowledge;
    state.recordsMeta = recordsMeta;
    state.literature = literatureMeta.items || [];
    state.works = snapshot.works || [];
    state.siteContent = snapshot.siteContent || {};
    state.records = recordsMeta.records?.length
      ? recordsMeta.records
      : recordsFromPublishedTables(state.works, state.literature);
    renderManagedSiteSections();
    renderPublishedSiteContent();
    if ($("#public-snapshot")) $("#public-snapshot").textContent = "当前内容来自已发布版本";
    renderScience();
    renderRecords();
    renderWorks();
  } catch (error) {
    $("#record-list").innerHTML = '<p class="loading-row">资料读取失败，请通过本地服务打开页面。</p>';
    $("#work-stage").innerHTML = '<p class="loading-row">公开成果读取失败。</p>';
    console.error(error);
  }
}

async function healthCheck() {
  const indicator = $("#service-state");
  try {
    const result = await getJSON("/api/health");
    indicator.textContent = result.mode === "qwen" ? `百炼 · ${result.model}` : "本地知识库";
    indicator.classList.add("is-online");
    $("#chat-mode").textContent = result.mode === "qwen" ? `百炼 · ${result.model}` : "本地知识库";
  } catch (_) {
    indicator.textContent = "静态浏览";
    $("#chat-mode").textContent = "静态知识库";
  }
}

function drawEclipse() {
  const input = $("#orbit-offset");
  if (!input) return;
  const offset = Number(input.value);
  const absolute = Math.abs(offset);
  const status = absolute <= 1.1
    ? "影子正落向地球"
    : absolute <= 2.8
      ? "影子擦过地球，部分地区可见"
      : "影子从地球旁边掠过";
  const detail = absolute <= 1.1
    ? "本影与地表相交"
    : absolute <= 2.8
      ? "仅半影或本影边缘经过"
      : "这次朔月不会形成日食";
  $("#alignment-status").textContent = status;
  $("#alignment-detail").textContent = detail;
  $("#alignment-value").textContent = `${offset.toFixed(1)}°`;
  window.dispatchEvent(new CustomEvent("eclipse:alignmentchange", { detail: { offset } }));
}

function localAnswer(question) {
  const normalized = question.toLocaleLowerCase("zh-CN");
  const matchedRecords = state.records.filter((record) => searchableRecord(record).includes(normalized));
  if (/凶|吉|预兆|怎么看|认为/.test(normalized)) {
    const source = sourceFor("52172");
    return {
      answer: "有学者认为，日月食被视作严重异象或不吉之象：人们会向祖先报告、反复询问祭牲，并担心它是否给商王带来忧祸。但一条卜辞提出问题，并不等于它已经给出固定的凶吉占断；具体仍要看上下辞和材料分期。",
      citations: [{ label: "甲骨文日月食与商代社会", url: publicSourceUrl(source) }]
    };
  }
  if (/记录|表|哪些|几条|列出/.test(normalized)) {
    const verified = state.records.filter((record) => record.reviewed).length;
    return {
      answer: `当前公开内容展示 ${state.records.length} 条记录：其中 ${verified} 条来源已确认，其余条目仍标为研究线索。\n\n${state.records.map((record, index) => `${index + 1}. ${record.inscription}｜${record.catalogNumber || "著录待核"}｜${record.status}`).join("\n")}\n\n页面只展示已审核发布的内容，不代表已经穷尽全部甲骨日食记录。`,
      citations: [{ label: "页面 · 记录列表", url: "#oracle" }]
    };
  }
  if (/21298|宫藏谢|乙丑/.test(normalized)) {
    return recordAnswer(state.records.find((record) => record.id === "gongcangxie-17"));
  }
  if (/33696|乙巳/.test(normalized)) {
    return recordAnswer(state.records.find((record) => record.id === "hj-33696") || state.records.find((record) => record.id === "yisi-eclipse"));
  }
  if (/11480/.test(normalized)) {
    return recordAnswer(state.records.find((record) => record.id === "hj-11480"));
  }
  if (/癸酉/.test(normalized)) {
    return recordAnswer(state.records.find((record) => record.id === "guiyou-eclipse"));
  }
  if (/祖庚|故宫/.test(normalized)) {
    return recordAnswer(state.records.find((record) => record.id === "gongcangxie-17"));
  }
  if (matchedRecords.length) return recordAnswer(matchedRecords[0]);
  return {
    answer: "现有资料还不足以对这个问题给出可靠结论。你可以换一种问法，指定“《合集》11480”“《合集》21298”“《合集》33696”或“癸酉”线索；也可以询问日全食、日环食、日偏食的科学原理。",
    citations: [{ label: "页面 · 资料边界", url: "#sources" }]
  };
}

function recordAnswer(record) {
  if (!record) return localAnswer("");
  const citations = (record.sourceEvidence || []).map((item) => {
    const source = sourceFor(item.sourceId);
    return { label: evidenceLabel(item), url: publicSourceUrl(source) };
  });
  if (!citations.length) {
    (record.sourceIds || []).map(sourceFor).filter(Boolean).forEach((source) => citations.push({
      label: source.title || "来源文献",
      url: publicSourceUrl(source)
    }));
  }
  const disputes = (record.disputes || []).map((item) => item.replace(/[。；]+$/g, "")).join("；");
  return {
    answer: `${record.translation}\n\n著录：${record.catalogNumber || "尚待核对"}\n年代：${record.dating}。\n主要争议：${disputes}。`,
    citations
  };
}

function appendMessage(role, text, citations = []) {
  text = cleanAnswerText(text).replaceAll("韩宇娇", "有学者").replaceAll("韩语娇", "有学者");
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  const label = document.createElement("span");
  label.textContent = role === "user" ? "你" : "日光问答";
  const body = document.createElement("p");
  body.textContent = text;
  article.append(label, body);
  if (citations.length) {
    const citationRow = document.createElement("div");
    citationRow.className = "message-citations";
    citations.forEach((citation) => {
      const link = document.createElement("a");
      link.href = citation.url;
      link.textContent = citation.label;
      if (citation.url.startsWith("http")) {
        link.target = "_blank";
        link.rel = "noreferrer";
      }
      citationRow.append(link);
    });
    article.append(citationRow);
  }
  $("#chat-log").append(article);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return article;
}

async function askQuestion(question) {
  const button = $("#send-button");
  appendMessage("user", question);
  button.disabled = true;
  button.textContent = "思考中";
  const waiting = appendMessage("assistant", "正在查找相关记录和来源……");
  try {
    const result = await postJSON("/api/chat", { message: question });
    waiting.remove();
    appendMessage("assistant", result.answer, result.citations || []);
    if (result.mode === "qwen") $("#chat-mode").textContent = `百炼 · ${result.model}`;
  } catch (_) {
    waiting.remove();
    const fallback = localAnswer(question);
    appendMessage("assistant", fallback.answer, fallback.citations);
  } finally {
    button.disabled = false;
    button.textContent = "发送";
  }
}

function stopPublicSlidePlayback(workId) {
  clearTimeout(state.workSlideTimers[workId]);
  delete state.workSlideTimers[workId];
  state.workSlidesPlaying.delete(workId);
}

function schedulePublicSlidePlayback(work) {
  clearTimeout(state.workSlideTimers[work.id]);
  if (!state.workSlidesPlaying.has(work.id)) return;
  const slides = work.content?.slides || [];
  const total = slides.length + 1;
  const current = workPage(work, total);
  const page = current > 0 ? slides[current - 1] || {} : {};
  const seconds = Number(page.transition?.advanceAfter || work.content?.playback?.seconds || 8);
  state.workSlideTimers[work.id] = setTimeout(() => {
    let next = current + 1;
    if (next >= total) {
      if (work.content?.playback?.loop) next = 0;
      else { stopPublicSlidePlayback(work.id); renderWorks(); return; }
    }
    state.workPages[work.id] = next;
    renderWorks();
    schedulePublicSlidePlayback(work);
  }, Math.max(3, seconds) * 1000);
}

function togglePublicSlidePlayback(workId) {
  const work = state.works.find((item) => item.id === workId);
  if (!work) return;
  if (state.workSlidesPlaying.has(work.id)) stopPublicSlidePlayback(work.id);
  else { state.workSlidesPlaying.add(work.id); schedulePublicSlidePlayback(work); }
  renderWorks();
}

function bindInteractions() {
  const navToggle = $("#nav-toggle");
  const siteNav = $("#site-nav");
  const closeNavigation = () => {
    if (!navToggle || !siteNav) return;
    navToggle.setAttribute("aria-expanded", "false");
    navToggle.setAttribute("title", "打开导航");
    navToggle.querySelector('[aria-hidden="true"]').textContent = "☰";
    navToggle.querySelector(".sr-only").textContent = "打开导航";
    siteNav.classList.remove("is-open");
  };
  if (navToggle && siteNav) {
    navToggle.addEventListener("click", () => {
      const isOpen = navToggle.getAttribute("aria-expanded") !== "true";
      navToggle.setAttribute("aria-expanded", String(isOpen));
      navToggle.setAttribute("title", isOpen ? "关闭导航" : "打开导航");
      navToggle.querySelector('[aria-hidden="true"]').textContent = isOpen ? "×" : "☰";
      navToggle.querySelector(".sr-only").textContent = isOpen ? "关闭导航" : "打开导航";
      siteNav.classList.toggle("is-open", isOpen);
    });
    siteNav.addEventListener("click", (event) => {
      if (event.target.closest("a")) closeNavigation();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeNavigation();
    });
    window.addEventListener("resize", () => {
      if (window.innerWidth > 980) closeNavigation();
    });
  }
  const backToTop = $("#back-to-top");
  if (backToTop) {
    backToTop.addEventListener("click", (event) => {
      event.preventDefault();
      window.scrollTo({ top: 0, left: 0, behavior: "smooth" });
      history.replaceState(null, "", `${location.pathname}${location.search}`);
    });
  }
  $("#hero-controls").addEventListener("click", (event) => {
    const dot = event.target.closest("[data-hero-index]");
    if (dot) return showHeroSlide(Number(dot.dataset.heroIndex));
    const action = event.target.closest("[data-hero-action]")?.dataset.heroAction;
    if (action === "previous") return showHeroSlide(state.heroIndex - 1);
    if (action === "next") return showHeroSlide(state.heroIndex + 1);
    if (action === "pause") { state.heroPaused = !state.heroPaused; showHeroSlide(state.heroIndex); }
  });
  $$(".type-tab").forEach((button) => {
    button.addEventListener("click", () => updateEclipseType(button.dataset.type));
  });
  $("#orbit-offset").addEventListener("input", drawEclipse);
  $("#record-search").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderRecords();
  });
  $("#work-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-work-kind]");
    if (!button) return;
    state.activeWorkKind = button.dataset.workKind;
    state.activeWorkId = null;
    renderWorks();
  });
  $("#work-stage").addEventListener("click", (event) => {
    const slidePlay = event.target.closest("[data-work-slide-play]");
    if (slidePlay) return togglePublicSlidePlayback(slidePlay.dataset.id);
    const pageStep = event.target.closest("[data-work-page-step]");
    if (pageStep) {
      const work = state.works.find((item) => item.id === pageStep.dataset.id);
      if (!work) return;
      const total = work.kind === "slide_deck" ? (work.content?.slides || []).length + 1 : (work.content?.cards || []).length;
      state.workPages[work.id] = Math.max(0, Math.min(total - 1, workPage(work, total) + Number(pageStep.dataset.workPageStep)));
      renderWorks();
      return;
    }
    const pageIndex = event.target.closest("[data-work-page-index]");
    if (pageIndex) {
      state.workPages[pageIndex.dataset.id] = Number(pageIndex.dataset.workPageIndex);
      renderWorks();
      return;
    }
    const variant = event.target.closest("[data-work-id]");
    if (variant) {
      state.activeWorkId = variant.dataset.workId;
      renderWorks();
      return;
    }
  });
  $("#chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#chat-input");
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    await askQuestion(question);
  });
  $$("[data-prompt]").forEach((button) => {
    button.addEventListener("click", async () => {
      $("#chat-input").value = button.dataset.prompt;
      await askQuestion(button.dataset.prompt);
      $("#chat-input").value = "";
    });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopHeroTimer();
    else scheduleHeroTimer();
  });
}

function revealOnScroll() {
  if (!("IntersectionObserver" in window)) {
    $$(".reveal").forEach((node) => node.classList.add("is-visible"));
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.1 });
  $$(".reveal").forEach((node) => observer.observe(node));
}

async function init() {
  bindInteractions();
  drawEclipse();
  revealOnScroll();
  await Promise.all([loadData(), healthCheck()]);
}

document.addEventListener("DOMContentLoaded", init);
