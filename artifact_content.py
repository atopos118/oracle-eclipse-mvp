from __future__ import annotations

import base64
import binascii
import hashlib
import html
import io
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


MAX_RICH_HTML_CHARS = 1_000_000
MAX_EDITOR_IMAGE_BYTES = 5 * 1024 * 1024
MAX_EDITOR_IMAGE_PIXELS = 40_000_000
MAX_TABLE_COLUMNS = 20
MAX_TABLE_ROWS = 500
MAX_TABLE_CELL_CHARS = 20_000
MAX_BOARD_NODES = 120
MAX_BOARD_EDGES = 240
MAX_BOARD_TITLE_CHARS = 160
MAX_BOARD_BODY_CHARS = 4_000
MAX_BOARD_REFERENCE_CHARS = 500

BOARD_NODE_TYPES = {"note", "evidence", "source", "artifact"}
BOARD_NODE_COLORS = {"gold", "blue", "green", "red", "gray"}
BOARD_REFERENCE_TYPES = {"", "source", "knowledge", "artifact"}

ALLOWED_RICH_TAGS = {
    "p",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "blockquote",
    "a",
    "img",
    "figure",
    "figcaption",
    "span",
    "br",
}
VOID_RICH_TAGS = {"img", "br"}
BLOCK_RICH_TAGS = {"p", "h2", "h3", "h4", "li", "blockquote", "figcaption"}
SUPPRESSED_RICH_TAGS = {"script", "style", "iframe", "object", "svg", "math"}
ASSET_NAME_PATTERN = re.compile(r"[0-9a-f]{64}\.(?:png|jpg|webp)")
RICH_ICON_NAMES = {
    "sun",
    "moon",
    "telescope",
    "book-open",
    "scale",
    "clock-3",
    "sparkles",
    "chart",
    "presentation",
}
SLIDE_LAYOUTS = {
    "statement",
    "image-right",
    "image-left",
    "process",
    "comparison",
    "chart",
    "quote",
}
SLIDE_TRANSITIONS = {"none", "fade", "push", "wipe", "split", "cover"}
SLIDE_MAX_SOURCE_PAGES = 20
SLIDE_MAX_NORMALIZED_PAGES = 36
SLIDE_TITLE_CHARS = 22
SLIDE_TAKEAWAY_CHARS = 72
SLIDE_RICH_PARAGRAPH_CHARS = 130
SLIDE_BULLET_CHARS = 90
SLIDE_BODY_CHARS = 320
SLIDE_VISUAL_BODY_CHARS = 230


def _artifact_id_pattern(artifact_id: str) -> str:
    return re.escape(str(artifact_id))


def research_asset_url(artifact_id: str, asset_name: str) -> str:
    return f"/api/research/artifacts/{artifact_id}/images/{asset_name}"


def public_asset_url(artifact_id: str, asset_name: str) -> str:
    return f"/api/public/artifacts/{artifact_id}/images/{asset_name}"


def _safe_link(value: str) -> str | None:
    candidate = str(value or "").strip()
    if candidate.startswith(("https://", "http://", "mailto:", "#")):
        return candidate
    return None


def _asset_name_from_url(value: str, artifact_id: str) -> str | None:
    candidate = str(value or "").strip()
    match = re.fullmatch(
        rf"/api/(?:research|public)/artifacts/{_artifact_id_pattern(artifact_id)}/images/"
        rf"({ASSET_NAME_PATTERN.pattern})",
        candidate,
    )
    return match.group(1) if match else None


class ArtifactHTMLSanitizer(HTMLParser):
    def __init__(self, artifact_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.artifact_id = artifact_id
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SUPPRESSED_RICH_TAGS:
            self.suppressed.append(tag)
            return
        if self.suppressed:
            return
        if tag not in ALLOWED_RICH_TAGS:
            return
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        safe_attrs: list[tuple[str, str]] = []
        if tag == "a":
            href = _safe_link(attr_map.get("href", ""))
            if href:
                safe_attrs.extend(
                    [("href", href), ("target", "_blank"), ("rel", "noopener noreferrer")]
                )
        elif tag == "img":
            asset_name = _asset_name_from_url(attr_map.get("src", ""), self.artifact_id)
            if not asset_name:
                return
            safe_attrs.append(("src", research_asset_url(self.artifact_id, asset_name)))
            for name in ("alt", "title"):
                if attr_map.get(name):
                    safe_attrs.append((name, attr_map[name][:300]))
            safe_attrs.append(("loading", "lazy"))
        elif tag == "span":
            icon_name = attr_map.get("data-icon", "")
            if icon_name in RICH_ICON_NAMES:
                safe_attrs.extend(
                    [
                        ("data-icon", icon_name),
                        ("class", f"artifact-icon artifact-icon-{icon_name}"),
                        ("aria-hidden", "true"),
                    ]
                )
        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_RICH_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag not in ALLOWED_RICH_TAGS or tag in VOID_RICH_TAGS or tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.suppressed:
            return
        self.parts.append(html.escape(data))

    def close_document(self) -> str:
        super().close()
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts).strip()


class ArtifactTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in BLOCK_RICH_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        normalized = "".join(self.parts).replace("\xa0", " ")
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()


def sanitize_rich_html(raw_html: str, artifact_id: str) -> tuple[str, str]:
    value = str(raw_html or "")
    if len(value) > MAX_RICH_HTML_CHARS:
        raise ValueError("图文正文超过长度限制")
    sanitizer = ArtifactHTMLSanitizer(str(artifact_id))
    sanitizer.feed(value)
    clean_html = sanitizer.close_document()
    extractor = ArtifactTextExtractor()
    extractor.feed(clean_html)
    extractor.close()
    return clean_html, extractor.text()


def normalize_record_table(content: dict[str, Any]) -> dict[str, Any]:
    columns_value = content.get("columns")
    rows_value = content.get("rows")
    if not isinstance(columns_value, list) or not isinstance(rows_value, list):
        raise ValueError("记录表必须包含列和行")
    if not 1 <= len(columns_value) <= MAX_TABLE_COLUMNS:
        raise ValueError(f"记录表列数应为1至{MAX_TABLE_COLUMNS}列")
    if len(rows_value) > MAX_TABLE_ROWS:
        raise ValueError(f"记录表最多支持{MAX_TABLE_ROWS}行")
    columns = [str(item or "").strip() for item in columns_value]
    if any(not item for item in columns):
        raise ValueError("记录表列名不能为空")
    if len(set(columns)) != len(columns):
        raise ValueError("记录表列名不能重复")
    rows: list[dict[str, str]] = []
    for row in rows_value:
        if not isinstance(row, dict):
            raise ValueError("记录表行格式无效")
        normalized_row: dict[str, str] = {}
        for column in columns:
            cell = str(row.get(column, ""))
            if len(cell) > MAX_TABLE_CELL_CHARS:
                raise ValueError(f"“{column}”单元格内容过长")
            normalized_row[column] = cell
        rows.append(normalized_row)
    return {**content, "columns": columns, "rows": rows}


def _bounded_number(
    value: Any, default: float, minimum: float, maximum: float
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number != number or number in {float("inf"), float("-inf")}:
        number = default
    return round(max(minimum, min(maximum, number)), 2)


def _board_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_board_content(content: dict[str, Any]) -> dict[str, Any]:
    nodes_value = content.get("nodes")
    edges_value = content.get("edges", [])
    if not isinstance(nodes_value, list) or not isinstance(edges_value, list):
        raise ValueError("白板必须包含节点和关系")
    if not 1 <= len(nodes_value) <= MAX_BOARD_NODES:
        raise ValueError(f"白板节点数应为1至{MAX_BOARD_NODES}个")
    if len(edges_value) > MAX_BOARD_EDGES:
        raise ValueError(f"白板最多支持{MAX_BOARD_EDGES}条关系")

    viewport_value = content.get("viewport")
    viewport_value = viewport_value if isinstance(viewport_value, dict) else {}
    viewport = {
        "width": _bounded_number(viewport_value.get("width"), 1200, 720, 4000),
        "height": _bounded_number(viewport_value.get("height"), 760, 480, 3000),
    }
    layout = str(content.get("layout") or "free")
    if layout not in {"free", "mind_map"}:
        layout = "free"

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, node_value in enumerate(nodes_value, 1):
        if not isinstance(node_value, dict):
            raise ValueError("白板节点格式无效")
        raw_id = re.sub(r"[^A-Za-z0-9_-]", "-", str(node_value.get("id") or ""))[:80]
        node_id = raw_id or f"node-{index}"
        suffix = 2
        base_id = node_id
        while node_id in node_ids:
            node_id = f"{base_id[:72]}-{suffix}"
            suffix += 1
        node_ids.add(node_id)

        node_type = str(node_value.get("type") or "note")
        if node_type not in BOARD_NODE_TYPES:
            node_type = "note"
        color = str(node_value.get("color") or "gold")
        if color not in BOARD_NODE_COLORS:
            color = "gold"
        reference_value = node_value.get("reference")
        reference_value = reference_value if isinstance(reference_value, dict) else {}
        reference_type = str(reference_value.get("type") or "")
        if reference_type not in BOARD_REFERENCE_TYPES:
            reference_type = ""
        reference = {
            "type": reference_type,
            "id": _board_text(reference_value.get("id"), MAX_BOARD_REFERENCE_CHARS),
            "label": _board_text(reference_value.get("label"), MAX_BOARD_REFERENCE_CHARS),
            "page": _board_text(reference_value.get("page"), 80),
        }
        if not any(reference.values()):
            reference = {"type": "", "id": "", "label": "", "page": ""}

        width = _bounded_number(node_value.get("width"), 230, 160, 520)
        height = _bounded_number(node_value.get("height"), 140, 96, 420)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "title": _board_text(node_value.get("title"), MAX_BOARD_TITLE_CHARS)
                or f"节点 {index}",
                "body": _board_text(node_value.get("body"), MAX_BOARD_BODY_CHARS),
                "x": _bounded_number(
                    node_value.get("x"), 60 + ((index - 1) % 4) * 270, 0, viewport["width"] - width
                ),
                "y": _bounded_number(
                    node_value.get("y"), 60 + ((index - 1) // 4) * 180, 0, viewport["height"] - height
                ),
                "width": width,
                "height": height,
                "color": color,
                "reference": reference,
            }
        )

    edges: list[dict[str, str]] = []
    edge_ids: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for index, edge_value in enumerate(edges_value, 1):
        if not isinstance(edge_value, dict):
            continue
        source = str(edge_value.get("from") or "")
        target = str(edge_value.get("to") or "")
        label = _board_text(edge_value.get("label"), MAX_BOARD_TITLE_CHARS)
        if source not in node_ids or target not in node_ids or source == target:
            continue
        pair = (source, target, label)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        raw_id = re.sub(r"[^A-Za-z0-9_-]", "-", str(edge_value.get("id") or ""))[:80]
        edge_id = raw_id or f"edge-{index}"
        suffix = 2
        base_id = edge_id
        while edge_id in edge_ids:
            edge_id = f"{base_id[:72]}-{suffix}"
            suffix += 1
        edge_ids.add(edge_id)
        edges.append(
            {"id": edge_id, "from": source, "to": target, "label": label}
        )

    return {**content, "layout": layout, "nodes": nodes, "edges": edges, "viewport": viewport}


def _short_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_slide_text(value: Any, limit: int | None = None) -> str:
    """Convert model/PDF fragments to compact plain text for slide surfaces."""
    raw = html.unescape(str(value or ""))
    raw = re.sub(
        r"<(script|style|iframe|object|svg|math)\b[^>]*>.*?</\1\s*>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    extractor = ArtifactTextExtractor()
    try:
        extractor.feed(raw)
        extractor.close()
        text = extractor.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?<!\\)(?:\*\*|__|~~|`{1,3})", "", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|>\s*)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-—")
    if limit is not None and len(text) > limit:
        return text[: max(1, limit - 1)].rstrip("，,；;：:。.!！？?") + "…"
    return text


def _split_slide_text(value: str, limit: int) -> list[str]:
    text = clean_slide_text(value)
    if not text:
        return []
    parts: list[str] = []
    while len(text) > limit:
        window = text[: limit + 1]
        cut = max(window.rfind(mark) + 1 for mark in "。！？；.!?;")
        if cut < max(24, limit // 2):
            cut = max(window.rfind(mark) + 1 for mark in "，、,:：")
        if cut < max(18, limit // 3):
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def _pack_slide_rich_text(
    paragraphs: list[dict[str, str]], budget: int
) -> list[list[dict[str, str]]]:
    expanded: list[dict[str, str]] = []
    for paragraph in paragraphs:
        lead = clean_slide_text(paragraph.get("lead"), 24)
        text = clean_slide_text(paragraph.get("text"))
        if lead and text.startswith(lead):
            text = text[len(lead) :].lstrip("：:，,。 ")
        segments = _split_slide_text(text, SLIDE_RICH_PARAGRAPH_CHARS) or ([""] if lead else [])
        for index, segment in enumerate(segments):
            expanded.append({"lead": lead if index == 0 else "", "text": segment})
    if not expanded:
        return [[]]
    pages: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    used = 0
    for paragraph in expanded:
        size = len(paragraph["lead"]) + len(paragraph["text"])
        if current and (len(current) >= 4 or used + size > budget):
            pages.append(current)
            current = []
            used = 0
        current.append(paragraph)
        used += size
    if current:
        pages.append(current)
    return pages


def _pack_slide_bullets(values: list[str], budget: int) -> list[list[str]]:
    expanded = [
        segment
        for value in values
        for segment in _split_slide_text(value, SLIDE_BULLET_CHARS)
        if segment
    ]
    if not expanded:
        return [[]]
    pages: list[list[str]] = []
    current: list[str] = []
    used = 0
    for bullet in expanded:
        if current and (len(current) >= 5 or used + len(bullet) > budget):
            pages.append(current)
            current = []
            used = 0
        current.append(bullet)
        used += len(bullet)
    if current:
        pages.append(current)
    return pages


def normalize_rich_visuals(content: dict[str, Any]) -> dict[str, Any]:
    visuals_value = content.get("visuals")
    visuals: list[dict[str, str]] = []
    if isinstance(visuals_value, list):
        for index, item in enumerate(visuals_value[:4], 1):
            if not isinstance(item, dict):
                continue
            prompt = _short_text(item.get("prompt"), 1200)
            if not prompt:
                continue
            visuals.append(
                {
                    "id": re.sub(r"[^A-Za-z0-9_-]", "-", _short_text(item.get("id"), 80))
                    or f"visual-{index}",
                    "afterHeading": _short_text(item.get("afterHeading"), 160),
                    "prompt": prompt,
                    "alt": _short_text(item.get("alt"), 300) or "科普内容配图",
                    "caption": _short_text(item.get("caption"), 500),
                }
            )
    return {**content, "visuals": visuals}


def normalize_slide_deck_content(content: dict[str, Any]) -> dict[str, Any]:
    slides_value = content.get("slides")
    if not isinstance(slides_value, list) or not slides_value:
        raise ValueError("幻灯片必须包含至少一页正文")
    if len(slides_value) > SLIDE_MAX_SOURCE_PAGES:
        raise ValueError(f"幻灯片原始正文最多{SLIDE_MAX_SOURCE_PAGES}页")

    playback_value = content.get("playback")
    playback_value = playback_value if isinstance(playback_value, dict) else {}
    default_transition = str(playback_value.get("transition") or "fade")
    if default_transition not in SLIDE_TRANSITIONS:
        default_transition = "fade"
    playback = {
        "autoAdvance": bool(playback_value.get("autoAdvance", False)),
        "seconds": _bounded_number(playback_value.get("seconds"), 8, 3, 60),
        "loop": bool(playback_value.get("loop", False)),
        "transition": default_transition,
    }

    slides: list[dict[str, Any]] = []
    for index, raw_slide in enumerate(slides_value, 1):
        value = raw_slide if isinstance(raw_slide, dict) else {}
        layout = str(value.get("layout") or "statement")
        if layout not in SLIDE_LAYOUTS:
            layout = "statement"
        icon = str(value.get("icon") or "book-open")
        if icon not in RICH_ICON_NAMES:
            icon = "book-open"
        bullets_value = value.get("bullets") or value.get("points") or []
        if isinstance(bullets_value, str):
            bullets_value = [bullets_value]
        bullets = [
            clean_slide_text(item)
            for item in (bullets_value if isinstance(bullets_value, list) else [])
            if clean_slide_text(item)
        ]

        rich_text: list[dict[str, str]] = []
        if isinstance(value.get("richText"), list):
            for paragraph in value["richText"]:
                if not isinstance(paragraph, dict):
                    continue
                text = clean_slide_text(paragraph.get("text"))
                lead = clean_slide_text(paragraph.get("lead"), 24)
                if lead or text:
                    rich_text.append({"lead": lead, "text": text})

        visual_value = value.get("visual")
        visual_value = visual_value if isinstance(visual_value, dict) else {}
        visual_asset = str(visual_value.get("asset") or "")
        if visual_asset and not ASSET_NAME_PATTERN.fullmatch(visual_asset):
            visual_asset = ""
        visual = {
            "prompt": clean_slide_text(visual_value.get("prompt"), 800),
            "alt": clean_slide_text(visual_value.get("alt"), 80),
            "caption": clean_slide_text(visual_value.get("caption"), 80),
            "asset": visual_asset,
        }

        diagram_value = value.get("diagram")
        diagram_value = diagram_value if isinstance(diagram_value, dict) else {}
        diagram_nodes: list[dict[str, str]] = []
        if isinstance(diagram_value.get("nodes"), list):
            for node in diagram_value["nodes"][:6]:
                if isinstance(node, dict):
                    label = clean_slide_text(node.get("label"), 24)
                    if label:
                        diagram_nodes.append(
                            {
                                "label": label,
                                "detail": clean_slide_text(node.get("detail"), 48),
                            }
                        )
        diagram = {
            "type": "process" if str(diagram_value.get("type")) == "process" else "",
            "nodes": diagram_nodes,
        }

        chart_value = value.get("chart")
        chart_value = chart_value if isinstance(chart_value, dict) else {}
        chart_type = str(chart_value.get("type") or "")
        if chart_type not in {"bar", "line", "pie", "doughnut"}:
            chart_type = ""
        categories = [
            clean_slide_text(item, 20)
            for item in (chart_value.get("categories") if isinstance(chart_value.get("categories"), list) else [])[:8]
        ]
        series: list[dict[str, Any]] = []
        if chart_type and len(categories) >= 2 and isinstance(chart_value.get("series"), list):
            for series_value in chart_value["series"][:3]:
                if not isinstance(series_value, dict) or not isinstance(series_value.get("values"), list):
                    continue
                values: list[float] = []
                for number in series_value["values"][: len(categories)]:
                    try:
                        parsed = float(number)
                    except (TypeError, ValueError):
                        parsed = 0
                    values.append(0 if parsed != parsed or parsed in {float("inf"), float("-inf")} else parsed)
                if len(values) == len(categories):
                    series.append({"name": clean_slide_text(series_value.get("name"), 24) or "数值", "values": values})
        chart = {
            "type": chart_type if series else "",
            "title": clean_slide_text(chart_value.get("title"), 40),
            "categories": categories if series else [],
            "series": series,
        }

        transition_value = value.get("transition")
        transition_value = transition_value if isinstance(transition_value, dict) else {}
        transition_type = str(transition_value.get("type") or default_transition)
        if transition_type not in SLIDE_TRANSITIONS:
            transition_type = default_transition
        transition = {
            "type": transition_type,
            "duration": _bounded_number(transition_value.get("duration"), 0.7, 0.2, 3),
            "advanceAfter": _bounded_number(
                transition_value.get("advanceAfter"), playback["seconds"], 3, 60
            ),
        }
        citations_value = value.get("citations") or value.get("evidence") or []
        if isinstance(citations_value, str):
            citations_value = [citations_value]
        citations = [
            clean_slide_text(item, 110)
            for item in (citations_value if isinstance(citations_value, list) else [])[:3]
            if clean_slide_text(item)
        ]
        title = clean_slide_text(value.get("title"), SLIDE_TITLE_CHARS) or f"第{index}页"
        takeaway = clean_slide_text(value.get("takeaway"), SLIDE_TAKEAWAY_CHARS)
        has_visual_surface = bool(
            visual["asset"] or chart["type"] or diagram["nodes"]
        )
        body_budget = SLIDE_VISUAL_BODY_CHARS if has_visual_surface else SLIDE_BODY_CHARS
        if rich_text:
            body_pages = [
                {"richText": page, "bullets": []}
                for page in _pack_slide_rich_text(rich_text, body_budget)
            ]
        else:
            body_pages = [
                {"richText": [], "bullets": page}
                for page in _pack_slide_bullets(bullets, body_budget)
            ]
        for page_index, body in enumerate(body_pages):
            continuation = page_index > 0
            page_title = title
            if continuation:
                page_title = clean_slide_text(title, SLIDE_TITLE_CHARS - 3) + "（续）"
            slides.append(
                {
                "title": page_title,
                "takeaway": takeaway if not continuation else "",
                "layout": layout,
                "icon": icon,
                "bullets": body["bullets"],
                "richText": body["richText"],
                "visual": visual if not continuation else {"prompt": "", "alt": "", "caption": "", "asset": ""},
                "diagram": diagram if not continuation else {"type": "", "nodes": []},
                "chart": chart if not continuation else {"type": "", "title": "", "categories": [], "series": []},
                "speakerNotes": clean_slide_text(value.get("speakerNotes"), 4000),
                "citations": citations,
                "transition": transition,
                }
            )
    if len(slides) > SLIDE_MAX_NORMALIZED_PAGES:
        raise ValueError(
            f"幻灯片拆分后超过{SLIDE_MAX_NORMALIZED_PAGES}页，请精简正文或减少原始页面"
        )
    return {
        **content,
        "subtitle": clean_slide_text(content.get("subtitle"), 72),
        "theme": "museum-observatory",
        "playback": playback,
        "slides": slides,
    }


def normalize_artifact_content(
    kind: str, content: dict[str, Any], artifact_id: str
) -> dict[str, Any]:
    normalized = dict(content or {})
    if kind == "record_table":
        return normalize_record_table(normalized)
    if kind == "slide_deck":
        return normalize_slide_deck_content(normalized)
    if kind in {"whiteboard", "mind_map"}:
        normalized["layout"] = "mind_map" if kind == "mind_map" else normalized.get("layout", "free")
        return normalize_board_content(normalized)
    if isinstance(normalized.get("html"), str):
        clean_html, plain_text = sanitize_rich_html(normalized["html"], artifact_id)
        normalized["html"] = clean_html
        normalized["text"] = plain_text
    elif isinstance(normalized.get("text"), str):
        normalized["text"] = str(normalized["text"])
    return normalize_rich_visuals(normalized)


def store_editor_image(
    root: Path,
    artifact_id: str,
    filename: str,
    content_base64: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(artifact_id)):
        raise ValueError("作品编号无效")
    try:
        raw = base64.b64decode(str(content_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片数据无效") from exc
    if not raw:
        raise ValueError("图片内容为空")
    if len(raw) > MAX_EDITOR_IMAGE_BYTES:
        raise ValueError("图片超过5MB限制")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("文件不是有效图片") from exc
    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(image_format)
    if not extension:
        raise ValueError("仅支持PNG、JPEG和WebP图片")
    if width <= 0 or height <= 0 or width * height > MAX_EDITOR_IMAGE_PIXELS:
        raise ValueError("图片像素尺寸过大")
    digest = hashlib.sha256(raw).hexdigest()
    asset_name = f"{digest}.{extension}"
    target_dir = Path(root) / str(artifact_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset_name
    if not target.exists():
        target.write_bytes(raw)
    return {
        "asset": asset_name,
        "filename": Path(str(filename or "图片")).name,
        "contentType": {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[
            extension
        ],
        "width": width,
        "height": height,
        "size": len(raw),
        "url": research_asset_url(str(artifact_id), asset_name),
    }


def editor_image_path(root: Path, artifact_id: str, asset_name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(artifact_id)):
        raise ValueError("作品编号无效")
    if not ASSET_NAME_PATTERN.fullmatch(str(asset_name)):
        raise ValueError("图片资源编号无效")
    base = (Path(root) / str(artifact_id)).resolve()
    target = (base / str(asset_name)).resolve()
    if target.parent != base:
        raise ValueError("图片资源路径无效")
    if not target.is_file():
        raise KeyError("图片资源不存在")
    return target


def artifact_references_asset(content: dict[str, Any], artifact_id: str, asset_name: str) -> bool:
    raw_html = content.get("html") if isinstance(content, dict) else None
    if not ASSET_NAME_PATTERN.fullmatch(str(asset_name)):
        return False
    urls = {
        research_asset_url(str(artifact_id), str(asset_name)),
        public_asset_url(str(artifact_id), str(asset_name)),
    }
    if isinstance(raw_html, str) and any(url in raw_html for url in urls):
        return True

    def references(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                (key in {"asset", "imageAsset"} and str(item) == asset_name)
                or references(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(references(item) for item in value)
        return False

    return references(content)
