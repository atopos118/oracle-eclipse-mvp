import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [inputPath, outputPath, assetRoot] = process.argv.slice(2);
if (!inputPath || !outputPath || !assetRoot) {
  throw new Error("usage: export_presentation.mjs input.json output.pptx asset-root");
}

const runtimeHome = process.env.USERPROFILE || process.env.HOME || "C:/Users/dhtbo";
const defaultModule = path.join(runtimeHome, ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "@oai", "artifact-tool", "dist", "artifact_tool.mjs");
const modulePath = process.env.ORACLE_ARTIFACT_TOOL_MODULE || defaultModule;
const { Presentation, PresentationFile } = await import(pathToFileURL(modulePath).href);
const artifact = JSON.parse(await fs.readFile(inputPath, "utf8"));
const content = artifact.content || {};
const slides = Array.isArray(content.slides) ? content.slides : [];
if (!slides.length) throw new Error("幻灯片作品没有可导出的页面");

function plainText(value) {
  return String(value || "")
    .replace(/<(script|style|iframe|object|svg|math)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&")
    .replace(/(?:\*\*|__|~~|`{1,3})/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

const W = 1280;
const H = 720;
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const C = {
  ink: "#17212b",
  bone: "#f5f1e8",
  paper: "#fffdf8",
  green: "#2f6e63",
  red: "#a94235",
  gold: "#c7993d",
  mist: "#e4ebe7",
  muted: "#5e6a75",
  line: "#c9d2ce",
  white: "#ffffff",
};

const iconFiles = {
  sun: "sun.svg",
  moon: "moon.svg",
  telescope: "telescope.svg",
  "book-open": "book-open.svg",
  scale: "scale.svg",
  "clock-3": "clock-3.svg",
  sparkles: "sparkles.svg",
  chart: "chart.svg",
  presentation: "presentation.svg",
};

const deck = Presentation.create({ slideSize: { width: W, height: H } });

function addShape(slide, geometry, position, fill = "none", line = { style: "solid", fill: "none", width: 0 }, name = "") {
  return slide.shapes.add({ geometry, name, position, fill, line });
}

function addText(slide, text, position, style = {}, name = "") {
  const shape = addShape(slide, "textbox", position, "none", { style: "solid", fill: "none", width: 0 }, name);
  shape.text = plainText(text);
  shape.text.style = {
    fontSize: style.fontSize || 23,
    bold: Boolean(style.bold),
    color: style.color || C.ink,
    alignment: style.alignment || "left",
    verticalAlignment: style.verticalAlignment || "top",
    autoFit: "shrinkText",
    typeface: style.typeface || "Microsoft YaHei",
    insets: style.insets || { top: 0, right: 0, bottom: 0, left: 0 },
    lineSpacing: style.lineSpacing || 1.12,
  };
  return shape;
}

async function addIcon(slide, name, position, color = C.gold) {
  const filename = iconFiles[name] || iconFiles["book-open"];
  const iconPath = path.resolve(scriptDir, "..", "assets", "icons", filename);
  const svg = (await fs.readFile(iconPath, "utf8")).replaceAll("currentColor", color);
  slide.images.add({
    blob: new TextEncoder().encode(svg),
    contentType: "image/svg+xml",
    alt: name,
    fit: "contain",
    position,
  });
}

async function readArtworkImage(asset) {
  if (!/^[0-9a-f]{64}\.(?:png|jpg|webp)$/.test(String(asset || ""))) return null;
  const fullPath = path.resolve(assetRoot, String(artifact.id || ""), asset);
  const expectedDir = path.resolve(assetRoot, String(artifact.id || ""));
  if (path.dirname(fullPath) !== expectedDir) return null;
  try {
    const bytes = await fs.readFile(fullPath);
    const extension = path.extname(fullPath).toLowerCase();
    return {
      bytes,
      contentType: extension === ".png" ? "image/png" : extension === ".webp" ? "image/webp" : "image/jpeg",
    };
  } catch {
    return null;
  }
}

function addCitation(slide, citations, pageNumber) {
  const text = Array.isArray(citations) && citations.length ? citations.slice(0, 3).map(plainText).join("；") : "页码待补充";
  addText(slide, `资料依据：${text}`, { left: 74, top: 654, width: 1050, height: 30 }, { fontSize: 14, color: C.muted }, `citation-${pageNumber}`);
  addText(slide, String(pageNumber).padStart(2, "0"), { left: 1168, top: 650, width: 42, height: 28 }, { fontSize: 16, color: C.red, bold: true, alignment: "right", typeface: "Georgia" }, `page-${pageNumber}`);
}

function addRichBody(slide, item, position) {
  const rich = Array.isArray(item.richText) ? item.richText : [];
  const bullets = Array.isArray(item.bullets) ? item.bullets : [];
  const shape = addShape(slide, "textbox", position, "none", { style: "solid", fill: "none", width: 0 }, "body");
  if (rich.length) {
    shape.text.set(rich.slice(0, 6).map((paragraph) => ({
      spaceAfter: 12,
      runs: [
        ...(paragraph.lead ? [{ run: `${paragraph.lead} `, textStyle: { bold: true, color: C.red } }] : []),
        { run: plainText(paragraph.text), textStyle: { color: C.ink } },
      ],
    })));
  } else {
    shape.text.set(bullets.slice(0, 6).map((bullet) => ({
      bulletCharacter: "•",
      marginLeft: 24,
      indent: -13,
      spaceAfter: 11,
      runs: [{ run: plainText(bullet), textStyle: { color: C.ink } }],
    })));
  }
  shape.text.style = {
    fontSize: position.width < 600 ? 19 : 22,
    color: C.ink,
    autoFit: "shrinkText",
    typeface: "Microsoft YaHei",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
    lineSpacing: 1.15,
  };
  return shape;
}

function addProcess(slide, diagram, frame) {
  const nodes = Array.isArray(diagram?.nodes) ? diagram.nodes.slice(0, 6) : [];
  if (!nodes.length) return false;
  const gap = 18;
  const nodeWidth = (frame.width - gap * (nodes.length - 1)) / nodes.length;
  const nodeTop = frame.top + 56;
  for (let index = 0; index < nodes.length - 1; index += 1) {
    addShape(slide, "rightArrow", { left: frame.left + (index + 1) * nodeWidth + index * gap + 2, top: nodeTop + 72, width: gap - 4, height: 26 }, C.gold, { style: "solid", fill: "none", width: 0 }, `process-arrow-${index + 1}`);
  }
  nodes.forEach((node, index) => {
    const left = frame.left + index * (nodeWidth + gap);
    const box = addShape(slide, "roundRect", { left, top: nodeTop, width: nodeWidth, height: 176 }, index % 2 ? C.paper : C.mist, { style: "solid", fill: C.line, width: 1.2 }, `process-node-${index + 1}`);
    box.borderRadius = 7;
    addText(slide, String(index + 1).padStart(2, "0"), { left: left + 16, top: nodeTop + 15, width: 45, height: 28 }, { fontSize: 17, color: C.red, bold: true, typeface: "Georgia" });
    addText(slide, node.label || "节点", { left: left + 16, top: nodeTop + 52, width: nodeWidth - 32, height: 50 }, { fontSize: 22, color: C.ink, bold: true });
    addText(slide, node.detail || "", { left: left + 16, top: nodeTop + 108, width: nodeWidth - 32, height: 54 }, { fontSize: 17, color: C.muted });
  });
  return true;
}

function addChart(slide, chart, frame) {
  const categories = Array.isArray(chart?.categories) ? chart.categories : [];
  const series = Array.isArray(chart?.series) ? chart.series : [];
  if (!chart?.type || categories.length < 2 || !series.length) return false;
  const type = ["bar", "line", "pie", "doughnut"].includes(chart.type) ? chart.type : "bar";
  slide.charts.add(type, {
    position: frame,
    title: chart.title || "资料数据",
    titleTextStyle: { fontSize: 20, bold: true, fill: C.ink },
    categories,
    series: series.map((item, index) => ({
      name: item.name || `系列${index + 1}`,
      values: item.values,
      fill: [C.green, C.gold, C.red][index % 3],
      line: { style: "solid", fill: [C.green, C.gold, C.red][index % 3], width: 3 },
    })),
    hasLegend: series.length > 1 || ["pie", "doughnut"].includes(type),
    legend: { position: "bottom", overlay: false, textStyle: { fontSize: 13, fill: C.muted } },
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 48 },
    lineOptions: { smooth: true },
    doughnutOptions: { holeSize: 52 },
    xAxis: { textStyle: { fontSize: 13, fill: C.muted }, line: { style: "solid", fill: C.line, width: 1 } },
    yAxis: { textStyle: { fontSize: 13, fill: C.muted }, majorGridlines: { style: "solid", fill: C.line, width: 1 } },
    dataLabels: ["pie", "doughnut"].includes(type) ? { showPercent: true, showCategoryName: true, position: "outEnd", textStyle: { fontSize: 12, fill: C.ink } } : { showValue: true, position: "outEnd", textStyle: { fontSize: 12, fill: C.ink } },
    chartFill: "none",
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaFill: "none",
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  return true;
}

async function addCover() {
  const slide = deck.slides.add();
  slide.background.fill = C.ink;
  addShape(slide, "rect", { left: 62, top: 64, width: 8, height: 572 }, C.gold, { style: "solid", fill: "none", width: 0 }, "sun-line");
  await addIcon(slide, "sun", { left: 102, top: 88, width: 72, height: 72 }, C.gold);
  addText(slide, artifact.title || "甲骨里的日光缺口", { left: 102, top: 202, width: 1040, height: 178 }, { fontSize: 64, bold: true, color: C.white, typeface: "STSong" }, "cover-title");
  addText(slide, content.subtitle || "从日食科学原理到甲骨卜辞记录", { left: 106, top: 434, width: 880, height: 76 }, { fontSize: 28, color: "#d2dbd6" }, "cover-subtitle");
  addText(slide, "基于已确认资料形成的可审核讲解", { left: 106, top: 584, width: 520, height: 32 }, { fontSize: 16, color: C.gold }, "cover-note");
}

async function addContentSlide(item, pageNumber) {
  const slide = deck.slides.add();
  slide.background.fill = C.paper;
  addShape(slide, "rect", { left: 0, top: 0, width: W, height: 10 }, C.green, { style: "solid", fill: "none", width: 0 }, "top-rule");
  await addIcon(slide, item.icon || "book-open", { left: 74, top: 50, width: 46, height: 46 }, C.gold);
  addText(slide, item.title || `第${pageNumber}页`, { left: 140, top: 43, width: 1040, height: 90 }, { fontSize: 48, bold: true, color: C.ink, typeface: "STSong" }, "slide-title");
  if (item.takeaway) addText(slide, item.takeaway, { left: 76, top: 139, width: 1120, height: 52 }, { fontSize: 22, bold: true, color: C.green }, "takeaway");

  const layout = item.layout || "statement";
  const imageData = await readArtworkImage(item.visual?.asset);
  const hasChart = Boolean(item.chart?.type && item.chart?.series?.length);
  const hasProcess = Boolean(item.diagram?.nodes?.length);
  const shouldSplit = Boolean(imageData || hasChart) && !["statement", "quote", "process"].includes(layout);
  if (layout === "process" && addProcess(slide, item.diagram, { left: 76, top: 205, width: 1128, height: 340 })) {
    // The process itself carries the page narrative.
  } else if (hasChart && (layout === "chart" || !imageData)) {
    addRichBody(slide, item, { left: 76, top: 214, width: 360, height: 386 });
    addChart(slide, item.chart, { left: 470, top: 200, width: 730, height: 410 });
  } else if (shouldSplit) {
    const imageLeft = layout === "image-left";
    const textFrame = { left: imageLeft ? 672 : 76, top: 210, width: 528, height: 390 };
    const imageFrame = { left: imageLeft ? 76 : 672, top: 210, width: 528, height: 352 };
    addRichBody(slide, item, textFrame);
    slide.images.add({
      blob: imageData.bytes,
      contentType: imageData.contentType,
      alt: item.visual?.alt || "幻灯片配图",
      fit: "cover",
      geometry: "roundRect",
      borderRadius: 7,
      position: imageFrame,
    });
    if (item.visual?.caption) addText(slide, item.visual.caption, { left: imageFrame.left, top: 574, width: imageFrame.width, height: 30 }, { fontSize: 14, color: C.muted, alignment: "center" });
  } else if (layout === "comparison") {
    const bullets = Array.isArray(item.bullets) && item.bullets.length
      ? item.bullets.map(plainText)
      : (Array.isArray(item.richText) ? item.richText : []).map((paragraph) =>
          plainText(`${paragraph.lead ? `${paragraph.lead} ` : ""}${paragraph.text || ""}`),
        ).filter(Boolean);
    const middle = Math.ceil(bullets.length / 2);
    [{ title: "主要材料", values: bullets.slice(0, middle), left: 76 }, { title: "比较与边界", values: bullets.slice(middle), left: 654 }].forEach((group, index) => {
      addShape(slide, "roundRect", { left: group.left, top: 214, width: 550, height: 352 }, index ? C.mist : C.bone, { style: "solid", fill: C.line, width: 1 }, `comparison-${index + 1}`);
      addText(slide, group.title, { left: group.left + 28, top: 242, width: 490, height: 38 }, { fontSize: 24, bold: true, color: index ? C.green : C.red });
      const proxy = { ...item, richText: [], bullets: group.values };
      addRichBody(slide, proxy, { left: group.left + 28, top: 294, width: 490, height: 238 });
    });
  } else {
    addRichBody(slide, item, { left: 112, top: 220, width: 1020, height: 370 });
  }
  addCitation(slide, item.citations, pageNumber);
  const notes = [item.speakerNotes || "", ...(item.citations || []).map((value) => `来源：${value}`)].filter(Boolean).join("\n\n");
  if (notes) slide.speakerNotes.textFrame.setText(notes);
}

await addCover();
for (let index = 0; index < slides.length; index += 1) {
  await addContentSlide(slides[index] || {}, index + 1);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(outputPath);
