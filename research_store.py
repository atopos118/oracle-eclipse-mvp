from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sqlite3
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from artifact_content import normalize_artifact_content
from text_quality import aggregate_quality, assess_text_quality


ROOT = Path(__file__).resolve().parent
PRIVATE_DIR = ROOT / "source-materials"
IMPORT_DIR = PRIVATE_DIR / "imports"
# Cloud deployments can place the mutable SQLite file on a persistent volume
# without exposing or committing it to the source repository. Local runs keep
# the historical source-materials/research.db location by default.
DB_PATH = Path(os.environ.get("ORACLE_RESEARCH_DB_PATH", str(PRIVATE_DIR / "research.db"))).expanduser()
MAX_IMPORT_BYTES = 25 * 1024 * 1024
MAX_SITE_ASSET_BYTES = 24 * 1024 * 1024
RESEARCH_READY_RECOGNITION = {"text_ready", "ocr_needs_review", "ocr_ready"}
PUBLISH_READY_RECOGNITION = {"text_ready", "ocr_ready"}
ARTIFACT_KINDS = {
    "record_table",
    "viewpoint_comparison",
    "public_explainer",
    "audio_guide",
    "research_qa",
    "literature_summary",
    "source_guide",
    "dating_timeline",
    "evidence_card",
    "student_explainer",
    "researcher_brief",
    "infographic",
    "lesson_material",
    "short_video_script",
    "captions",
    "visual_card_set",
    "slide_deck",
    "video_package",
    "whiteboard",
    "mind_map",
}

SITE_CONTENT_KEYS = ("hero", "science", "history", "records")
SITE_SHORTCODES = {
    "[日食科学互动]": "science",
    "[甲骨时代导读]": "history",
    "[甲骨日食记录]": "records",
    "[研究成果]": "works",
    "[公众问答]": "ask",
    "[研究依据与进度]": "sources",
}
SITE_SYSTEM_DEFAULTS: dict[str, dict[str, Any]] = {
    "works": {
        "title": "公开研究成果",
        "nav_label": "公开成果",
        "section_type": "data",
        "kicker": "从研究工作台审核发布",
        "summary": "这里呈现研究工作台审核后正式发布的作品。",
        "body_html": "<p>[研究成果]</p>",
        "content": {},
        "sort_order": 4,
    },
    "ask": {
        "title": "日光问答",
        "nav_label": "问一问",
        "section_type": "data",
        "kicker": "问问古人的天空",
        "summary": "回答只调用页面中的日食常识、甲骨记录和文献来源。没有证据的部分会直接说“尚不清楚”。",
        "body_html": "<p>[公众问答]</p>",
        "content": {},
        "sort_order": 5,
    },
    "sources": {
        "title": "研究依据与进度",
        "nav_label": "研究依据",
        "section_type": "data",
        "kicker": "结论和作品从哪里来",
        "summary": "只列出已经完成资料确认并进入公开内容的研究依据。",
        "body_html": "<p>[研究依据与进度]</p>",
        "content": {},
        "sort_order": 6,
    },
}
SITE_CONTENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "hero": {
        "title": "Banner 横幅",
        "content": {
            "autoplay": True,
            "intervalSeconds": 6,
            "slides": [
                {
                    "id": "hero-slide-1",
                    "enabled": True,
                    "mediaType": "image",
                    "mediaUrl": "assets/hero-eclipse.webp",
                    "assetId": "",
                    "posterUrl": "",
                    "posterAssetId": "",
                    "overline": "太阳被遮住的那一刻，古人看见了什么？",
                    "title": "甲骨里的日光缺口",
                    "lede": "从月球投下的一片影子，走进三千多年前的贞问与记录。",
                    "primaryAction": {"label": "先看懂日食", "href": "#science"},
                    "secondaryAction": {"label": "直接读记录", "href": "#oracle"},
                    "caption": "主视觉为传播插图，不是甲骨原片或拓片",
                    "durationSeconds": 6,
                }
            ],
        },
    },
    "science": {
        "title": "栏目一 · 科学原理",
        "content": {
            "kicker": "先看懂今天的天空",
            "heading": "日食，是月亮投下的一片影子",
            "summary": "当月球运行到太阳和地球之间，它的影子可能落到地球上。站在影子经过的地方，人们会看到太阳被遮住一部分或全部，这就是日食。",
            "orbitQuestion": "为什么不是每个月都有日食？",
            "orbitExplanation": "月球轨道与地球绕太阳运行的平面约有 5° 倾角。只有朔月靠近轨道交点时，月影才可能扫过地球。",
            "typeKicker": "同一场天象，不同地点会看见不同模样",
            "typeHeading": "太阳会被遮住多少？",
            "safetyNote": "除全食阶段外，不能用肉眼或普通墨镜直接观看太阳，应使用合格的太阳观测镜。",
            "eclipseTypes": [
                {"id": "total", "name": "日全食", "short": "太阳被完全遮住", "explanation": "观测者位于月球本影扫过的狭窄区域内。短暂的全食阶段里，明亮的日面被遮住，日冕才更容易被看见。", "fact": "全食带很窄，同一时刻并不是整颗地球都能看到日全食。"},
                {"id": "annular", "name": "日环食", "short": "太阳边缘留下一圈光环", "explanation": "月球距离地球较远，视直径比太阳小，遮住日面中央后仍会留下明亮的环。", "fact": "日环食也不能直接用肉眼观看，整个过程都需要合格的太阳观测镜。"},
                {"id": "partial", "name": "日偏食", "short": "太阳只被遮住一部分", "explanation": "观测者位于月球半影覆盖的区域，只能看到月球遮住部分日面。", "fact": "同一场日食中，全食带或环食带之外的大片区域通常会看到偏食。"},
            ],
        },
    },
    "history": {
        "title": "栏目二 · 甲骨时代",
        "content": {
            "kicker": "再回到三千多年前",
            "heading": "天空出现缺口，问题被留在甲骨上",
            "summary": "这种天象早在使用甲骨文的时代就已进入先人的观察与贞问。今天能看到的，不只是一条“古人见过日食”的结论，更是他们怎样面对一次异常天象。",
            "quote": "卜辞提出的是问题，不一定已经给出“凶”或“吉”的答案。",
            "points": [
                "商代卜辞把天象放进占卜、祭祀与政治生活的语境中。",
                "不能把所有日食记录简单概括为同一种固定预兆。",
                "具体一辞怎样解释，要看字形、上下辞、分期和同类辞例。",
            ],
            "image": {"assetId": "", "url": "assets/evidence-oracle.webp", "alt": "甲骨材料主题传播插图，非甲骨原片或拓片", "caption": "传播情境图 / 非原片"},
        },
    },
    "records": {
        "title": "栏目三 · 日食记录",
        "content": {
            "kicker": "逐条打开，不替争议下结论",
            "heading": "甲骨日食记录与研究线索",
            "summary": "点击句子即可展开释义、年代、学者观点和争议；不同条目可以同时保持展开。这里的逐条记录来自已经审核发布的记录整理；尚未形成独立条目时，会从已经发布的记录表同步展示。",
            "searchPlaceholder": "搜索乙丑、21298、33696或学者姓名",
            "scopeTitle": "这里展示的是研究工作台已审核并发布的甲骨日食记录与研究线索。",
            "scopeNote": "释文、著录、年代或日食对应仍有不确定时，条目会明确标为“研究线索”或“待核”，不会作为定论。",
        },
    },
}

SITE_SECTION_META: dict[str, dict[str, Any]] = {
    "hero": {
        "nav_label": "首页",
        "section_type": "hero",
        "kicker": "",
        "summary": "",
        "body_html": "",
        "sort_order": 0,
    },
    "science": {
        "nav_label": "看懂日食",
        "section_type": "data",
        "kicker": SITE_CONTENT_DEFAULTS["science"]["content"]["kicker"],
        "summary": SITE_CONTENT_DEFAULTS["science"]["content"]["summary"],
        "body_html": "<p>[日食科学互动]</p>",
        "sort_order": 1,
    },
    "history": {
        "nav_label": "甲骨时代",
        "section_type": "data",
        "kicker": SITE_CONTENT_DEFAULTS["history"]["content"]["kicker"],
        "summary": SITE_CONTENT_DEFAULTS["history"]["content"]["summary"],
        "body_html": "<p>[甲骨时代导读]</p>",
        "sort_order": 2,
    },
    "records": {
        "nav_label": "读甲骨记录",
        "section_type": "data",
        "kicker": SITE_CONTENT_DEFAULTS["records"]["content"]["kicker"],
        "summary": SITE_CONTENT_DEFAULTS["records"]["content"]["summary"],
        "body_html": "<p>[甲骨日食记录]</p>",
        "sort_order": 3,
    },
}

SITE_HTML_TAGS = {
    "p", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em",
    "blockquote", "a", "img", "figure", "figcaption", "br", "hr",
    "table", "thead", "tbody", "tr", "th", "td", "div", "span",
}
SITE_HTML_VOID_TAGS = {"img", "br", "hr"}
SITE_HTML_SUPPRESSED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}
SITE_HTML_MAX_CHARS = 200_000


class SiteHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SITE_HTML_SUPPRESSED_TAGS:
            self.suppressed.append(tag)
            return
        if self.suppressed or tag not in SITE_HTML_TAGS:
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        safe_attrs: list[tuple[str, str]] = []
        if tag == "a":
            href = values.get("href", "").strip()
            if href.startswith(("https://", "http://", "mailto:", "#")):
                safe_attrs.extend((('href', href), ('target', '_blank'), ('rel', 'noopener noreferrer')))
        elif tag == "img":
            source = values.get("src", "").strip().replace("\\", "/")
            if source.startswith(("assets/", "/assets/", "/api/research/site-content/assets/", "/api/public/site-media/")):
                safe_attrs.append(("src", source))
                for name in ("alt", "title"):
                    if values.get(name):
                        safe_attrs.append((name, values[name][:300]))
                safe_attrs.append(("loading", "lazy"))
            else:
                return
        elif tag == "figure" and values.get("class") == "site-generated-visual":
            safe_attrs.append(("class", "site-generated-visual"))
        if tag in {"th", "td"}:
            for name in ("colspan", "rowspan"):
                if values.get(name, "").isdigit():
                    safe_attrs.append((name, str(max(1, min(20, int(values[name]))))))
        rendered = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<{tag}{rendered}>")
        if tag not in SITE_HTML_VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag not in SITE_HTML_TAGS or tag in SITE_HTML_VOID_TAGS or tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            self.parts.append(html.escape(data))

    def result(self) -> str:
        super().close()
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts).strip()


def sanitize_site_html(raw_html: Any) -> str:
    value = str(raw_html or "")
    if len(value) > SITE_HTML_MAX_CHARS:
        raise ValueError("栏目HTML正文超过长度限制")
    sanitizer = SiteHTMLSanitizer()
    sanitizer.feed(value)
    return sanitizer.result()


def site_section_default(content_key: str) -> dict[str, Any] | None:
    if content_key in SITE_CONTENT_DEFAULTS:
        default = SITE_CONTENT_DEFAULTS[content_key]
        meta = SITE_SECTION_META[content_key]
        content = json.loads(json.dumps(default["content"], ensure_ascii=False))
        return {
            "content_key": content_key,
            "title": default["title"] if content_key == "hero" else str(content.get("heading") or default["title"]),
            "content": content,
            **meta,
            "enabled": True,
        }
    if content_key in SITE_SYSTEM_DEFAULTS:
        default = SITE_SYSTEM_DEFAULTS[content_key]
        return {
            "content_key": content_key,
            "title": default["title"],
            "content": json.loads(json.dumps(default["content"], ensure_ascii=False)),
            "nav_label": default["nav_label"],
            "section_type": default["section_type"],
            "kicker": default["kicker"],
            "summary": default["summary"],
            "body_html": default["body_html"],
            "sort_order": default["sort_order"],
            "enabled": True,
        }
    return None


def _site_text(value: Any, limit: int, fallback: str = "") -> str:
    cleaned = re.sub(r"\*{2,}", "", str(value or "")).strip()
    return cleaned[:limit] or fallback


def _site_action(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    item = value if isinstance(value, dict) else {}
    href = str(item.get("href") or fallback["href"]).strip()
    if not re.fullmatch(r"#[A-Za-z][A-Za-z0-9_-]*", href):
        href = fallback["href"]
    return {
        "label": _site_text(item.get("label"), 30, fallback["label"]),
        "href": href,
    }


def _site_media_url(value: Any, fallback: str = "") -> str:
    url = str(value or "").strip().replace("\\", "/")
    if url.startswith("assets/") or url.startswith("/api/public/site-media/"):
        return url
    return fallback


def normalize_site_content(content_key: str, value: Any) -> dict[str, Any]:
    incoming = value if isinstance(value, dict) else {}
    if content_key not in SITE_CONTENT_DEFAULTS:
        encoded = json.dumps(incoming, ensure_ascii=False)
        if len(encoded) > 200_000:
            raise ValueError("栏目结构化配置超过长度限制")
        return incoming
    default = SITE_CONTENT_DEFAULTS[content_key]["content"]
    if content_key == "hero":
        raw_slides = incoming.get("slides") if isinstance(incoming.get("slides"), list) else []
        slides = []
        for index, raw in enumerate(raw_slides[:8], 1):
            item = raw if isinstance(raw, dict) else {}
            default_slide = default["slides"][0]
            asset_id = str(item.get("assetId") or "").strip()
            poster_asset_id = str(item.get("posterAssetId") or "").strip()
            if asset_id and not re.fullmatch(r"siteasset-[0-9a-f]{12}", asset_id):
                asset_id = ""
            if poster_asset_id and not re.fullmatch(r"siteasset-[0-9a-f]{12}", poster_asset_id):
                poster_asset_id = ""
            slides.append(
                {
                    "id": _site_text(item.get("id"), 80, f"hero-slide-{index}"),
                    "enabled": bool(item.get("enabled", True)),
                    "mediaType": "video" if item.get("mediaType") == "video" else "image",
                    "mediaUrl": _site_media_url(item.get("mediaUrl"), default_slide["mediaUrl"]),
                    "assetId": asset_id,
                    "posterUrl": _site_media_url(item.get("posterUrl")),
                    "posterAssetId": poster_asset_id,
                    "overline": _site_text(item.get("overline"), 100, default_slide["overline"]),
                    "title": _site_text(item.get("title"), 120, default_slide["title"]),
                    "lede": _site_text(item.get("lede"), 240, default_slide["lede"]),
                    "primaryAction": _site_action(item.get("primaryAction"), default_slide["primaryAction"]),
                    "secondaryAction": _site_action(item.get("secondaryAction"), default_slide["secondaryAction"]),
                    "caption": _site_text(item.get("caption"), 120, default_slide["caption"]),
                    "durationSeconds": max(3, min(30, int(item.get("durationSeconds") or 6))),
                }
            )
        if not slides:
            slides = json.loads(json.dumps(default["slides"], ensure_ascii=False))
        return {
            "autoplay": bool(incoming.get("autoplay", True)),
            "intervalSeconds": max(3, min(30, int(incoming.get("intervalSeconds") or 6))),
            "slides": slides,
        }
    if content_key == "science":
        raw_types = incoming.get("eclipseTypes") if isinstance(incoming.get("eclipseTypes"), list) else []
        types_by_id = {
            str(item.get("id")): item
            for item in raw_types
            if isinstance(item, dict) and item.get("id") in {"total", "annular", "partial"}
        }
        eclipse_types = []
        for fallback in default["eclipseTypes"]:
            item = types_by_id.get(fallback["id"], {})
            eclipse_types.append(
                {
                    "id": fallback["id"],
                    "name": _site_text(item.get("name"), 30, fallback["name"]),
                    "short": _site_text(item.get("short"), 80, fallback["short"]),
                    "explanation": _site_text(item.get("explanation"), 400, fallback["explanation"]),
                    "fact": _site_text(item.get("fact"), 300, fallback["fact"]),
                }
            )
        return {
            key: _site_text(incoming.get(key), limit, default[key])
            for key, limit in (
                ("kicker", 80), ("heading", 120), ("summary", 600),
                ("orbitQuestion", 100), ("orbitExplanation", 500),
                ("typeKicker", 100), ("typeHeading", 100), ("safetyNote", 400),
            )
        } | {"eclipseTypes": eclipse_types}
    if content_key == "history":
        image = incoming.get("image") if isinstance(incoming.get("image"), dict) else {}
        fallback_image = default["image"]
        asset_id = str(image.get("assetId") or "").strip()
        if asset_id and not re.fullmatch(r"siteasset-[0-9a-f]{12}", asset_id):
            asset_id = ""
        points = incoming.get("points") if isinstance(incoming.get("points"), list) else []
        cleaned_points = [_site_text(item, 260) for item in points[:8] if _site_text(item, 260)]
        return {
            "kicker": _site_text(incoming.get("kicker"), 80, default["kicker"]),
            "heading": _site_text(incoming.get("heading"), 120, default["heading"]),
            "summary": _site_text(incoming.get("summary"), 700, default["summary"]),
            "quote": _site_text(incoming.get("quote"), 400, default["quote"]),
            "points": cleaned_points or list(default["points"]),
            "image": {
                "assetId": asset_id,
                "url": _site_media_url(image.get("url"), fallback_image["url"]),
                "alt": _site_text(image.get("alt"), 160, fallback_image["alt"]),
                "caption": _site_text(image.get("caption"), 100, fallback_image["caption"]),
            },
        }
    return {
        key: _site_text(incoming.get(key), limit, default[key])
        for key, limit in (
            ("kicker", 80), ("heading", 140), ("summary", 800),
            ("searchPlaceholder", 100), ("scopeTitle", 240), ("scopeNote", 400),
        )
    }


def validate_site_shortcodes(body_html: str) -> str:
    clean = sanitize_site_html(body_html)
    tokens = set(re.findall(r"\[[\u4e00-\u9fff]{4,12}\]", clean))
    unknown = sorted(tokens.difference(SITE_SHORTCODES))
    if unknown:
        raise ValueError(f"未知栏目简码：{'、'.join(unknown)}")
    return clean


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_site_content_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'site_content_entries'"
    ).fetchone()
    columns = {
        item[1] for item in connection.execute("PRAGMA table_info(site_content_entries)").fetchall()
    }
    required = {
        "section_type", "nav_label", "kicker", "summary", "body_html",
        "enabled", "sort_order",
    }
    constrained = bool(row and "CHECK(content_key IN" in str(row[0] or ""))
    if required.issubset(columns) and not constrained:
        return
    connection.execute("DROP TABLE IF EXISTS site_content_entries_v2")
    connection.execute(
        """
        CREATE TABLE site_content_entries_v2 (
            id TEXT PRIMARY KEY,
            content_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            section_type TEXT NOT NULL DEFAULT 'standard' CHECK(section_type IN ('hero','standard','data')),
            nav_label TEXT NOT NULL DEFAULT '',
            kicker TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            content_json TEXT NOT NULL,
            published_content_json TEXT,
            status TEXT NOT NULL CHECK(status IN ('draft','approved')),
            publication_state TEXT NOT NULL DEFAULT 'private' CHECK(publication_state IN ('private','public','outdated')),
            model TEXT NOT NULL DEFAULT 'manual',
            prompt_version TEXT NOT NULL DEFAULT 'manual:v1',
            generation_instruction TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            approved_at TEXT,
            published_at TEXT
        )
        """
    )
    existing = [
        "id", "content_key", "title", "content_json", "published_content_json",
        "status", "publication_state", "model", "prompt_version",
        "generation_instruction", "created_at", "updated_at", "approved_at", "published_at",
    ]
    select_parts = []
    for name in existing:
        if name in columns:
            select_parts.append(name)
        elif name == "generation_instruction":
            select_parts.append("''")
        else:
            select_parts.append("NULL")
    connection.execute(
        f"""
        INSERT INTO site_content_entries_v2
        (id, content_key, title, content_json, published_content_json, status,
         publication_state, model, prompt_version, generation_instruction,
         created_at, updated_at, approved_at, published_at)
        SELECT {', '.join(select_parts)} FROM site_content_entries
        """
    )
    connection.execute("DROP TABLE site_content_entries")
    connection.execute("ALTER TABLE site_content_entries_v2 RENAME TO site_content_entries")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_site_content_status ON site_content_entries(status, publication_state)"
    )


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return sha256_bytes(content.encode("utf-8"))


def compact_locator_values(values: Iterable[str]) -> str:
    unique = sorted(
        {str(value).strip() for value in values if str(value).strip()},
        key=lambda value: (0, int(value)) if value.isdigit() else (1, value),
    )
    numeric = [int(value) for value in unique if value.isdigit()]
    labels: list[str] = []
    if numeric:
        start = previous = numeric[0]
        for value in numeric[1:]:
            if value == previous + 1:
                previous = value
                continue
            labels.append(str(start) if start == previous else f"{start}~{previous}")
            start = previous = value
        labels.append(str(start) if start == previous else f"{start}~{previous}")
    labels.extend(value for value in unique if not value.isdigit())
    return "、".join(labels)


def group_lineage_edges(edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (
            str(edge.get("source_id") or ""),
            str(edge.get("source_title") or "来源资料"),
            str(edge.get("source_status") or ""),
            str(edge.get("source_recognition_status") or ""),
        )
        item = grouped.setdefault(
            key,
            {
                "source_id": key[0],
                "source_title": key[1],
                "source_status": key[2],
                "source_recognition_status": key[3],
                "locator_type": str(edge.get("locator_type") or ""),
                "locator_types": [],
                "locator_values": [],
                "pdf_page_values": [],
            },
        )
        locator_type = str(edge.get("locator_type") or "")
        if locator_type and locator_type not in item["locator_types"]:
            item["locator_types"].append(locator_type)
        if len(item["locator_types"]) > 1:
            item["locator_type"] = "mixed"
        locator = str(edge.get("locator_value") or "").strip()
        if locator and locator not in item["locator_values"]:
            item["locator_values"].append(locator)
        if locator_type == "pdf_page" and locator and locator not in item["pdf_page_values"]:
            item["pdf_page_values"].append(locator)
    result = list(grouped.values())
    for item in result:
        item["locator_range"] = compact_locator_values(item["locator_values"])
    return result


def clean_filename(name: str, suffix: str = "") -> str:
    base = Path(name or "source").name
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", base).strip("._")
    if not base:
        base = "source"
    if suffix and not base.lower().endswith(suffix.lower()):
        base += suffix
    return base[:140]


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\s+", " ", "\n".join(self.parts)).strip()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    external_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('pdf','url','manual')),
    source_role TEXT NOT NULL DEFAULT 'evidence',
    title TEXT NOT NULL,
    filename TEXT,
    source_url TEXT,
    private_path TEXT,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('imported','parsed','reviewed','parse_failed','deleted')),
    parse_version INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER,
    recognition_status TEXT NOT NULL DEFAULT 'unverified',
    recognition_method TEXT NOT NULL DEFAULT 'legacy_text',
    recognition_version INTEGER NOT NULL DEFAULT 0,
    quality_score REAL,
    quality_report_json TEXT,
    provenance_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_hash ON source_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_sources_status ON source_documents(status);

CREATE TABLE IF NOT EXISTS source_units (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(id),
    parse_version INTEGER NOT NULL,
    unit_index INTEGER NOT NULL,
    locator_type TEXT NOT NULL,
    locator_value TEXT NOT NULL,
    text_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_method TEXT NOT NULL DEFAULT 'legacy_text',
    quality_score REAL,
    quality_status TEXT NOT NULL DEFAULT 'unverified',
    ocr_model TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, parse_version, unit_index)
);
CREATE INDEX IF NOT EXISTS idx_units_source ON source_units(source_id, parse_version);

CREATE TABLE IF NOT EXISTS ocr_runs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_documents(id),
    status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed')),
    engine TEXT NOT NULL,
    model TEXT NOT NULL,
    total_pages INTEGER NOT NULL DEFAULT 0,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    quality_score REAL,
    quality_report_json TEXT,
    page_dir TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ocr_runs_source ON ocr_runs(source_id, created_at);

CREATE TABLE IF NOT EXISTS ocr_page_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES ocr_runs(id),
    source_id TEXT NOT NULL REFERENCES source_documents(id),
    page_number INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    quality_score REAL NOT NULL,
    quality_status TEXT NOT NULL,
    quality_report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, page_number)
);
CREATE INDEX IF NOT EXISTS idx_ocr_pages_run ON ocr_page_results(run_id, page_number);

CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id TEXT PRIMARY KEY,
    candidate_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected','stale')),
    source_id TEXT NOT NULL REFERENCES source_documents(id),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON knowledge_candidates(status);

CREATE TABLE IF NOT EXISTS published_knowledge (
    id TEXT PRIMARY KEY,
    candidate_id TEXT REFERENCES knowledge_candidates(id),
    knowledge_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('approved','stale','retired')),
    source_revision_sig TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_status ON published_knowledge(status);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id TEXT PRIMARY KEY,
    artifact_kind TEXT NOT NULL,
    version TEXT NOT NULL,
    template TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','approved','published','rejected','stale')),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    generation_instruction TEXT NOT NULL DEFAULT '',
    source_revision_sig TEXT NOT NULL,
    publication_state TEXT NOT NULL DEFAULT 'private',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);

CREATE TABLE IF NOT EXISTS lineage_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upstream_type TEXT NOT NULL CHECK(upstream_type IN ('source','unit','knowledge')),
    upstream_id TEXT NOT NULL,
    downstream_type TEXT NOT NULL CHECK(downstream_type IN ('candidate','knowledge','artifact')),
    downstream_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source_id TEXT REFERENCES source_documents(id),
    unit_id TEXT REFERENCES source_units(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage_source ON lineage_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_lineage_downstream ON lineage_edges(downstream_type, downstream_id);

CREATE TABLE IF NOT EXISTS review_events (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK(target_type IN ('source','candidate','knowledge','artifact','snapshot')),
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_target ON review_events(target_type, target_id);

CREATE TABLE IF NOT EXISTS publish_snapshots (
    id TEXT PRIMARY KEY,
    snapshot_hash TEXT NOT NULL,
    path TEXT NOT NULL,
    item_counts_json TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('published','failed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_content_entries (
    id TEXT PRIMARY KEY,
    content_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    section_type TEXT NOT NULL DEFAULT 'standard' CHECK(section_type IN ('hero','standard','data')),
    nav_label TEXT NOT NULL DEFAULT '',
    kicker TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    content_json TEXT NOT NULL,
    published_content_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('draft','approved')),
    publication_state TEXT NOT NULL DEFAULT 'private' CHECK(publication_state IN ('private','public','outdated')),
    model TEXT NOT NULL DEFAULT 'manual',
    prompt_version TEXT NOT NULL DEFAULT 'manual:v1',
    generation_instruction TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_site_content_status ON site_content_entries(status, publication_state);

CREATE TABLE IF NOT EXISTS site_assets (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('image','video')),
    mime_type TEXT NOT NULL,
    private_path TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_content_review_events (
    id TEXT PRIMARY KEY,
    content_key TEXT NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_site_content_reviews ON site_content_review_events(content_key, created_at);
"""


PROMPTS = {
    "record_table": (
        "v1",
        "仅依据所选资料和已批准知识生成甲骨日食记录表。保留著录、释文、年代、争议和页码，不补写残字。",
    ),
    "viewpoint_comparison": (
        "v1",
        "仅依据所选资料比较学者观点与争议。区分共识、分歧、作者推测和待核事项。",
    ),
    "public_explainer": (
        "v3",
        "面向普通公众生成可编辑富文本图文讲解。先说结论，再说明证据与争议；用受控图标建立阅读层级，并只在有助理解机制、时间线或证据关系的位置规划配图。不得把AI插图当作甲骨原片。",
    ),
    "audio_guide": (
        "v2",
        "直接生成面向听众的中文音频导览正文，句子适合朗读，并在口播中自然说明不确定性。开头直接进入主题或听众称呼；禁止输出生成说明、资料使用声明、篇幅说明、审核状态、发布状态、免责声明或独立分隔线。",
    ),
    "research_qa": ("v2", "整理资料问答结果为可编辑富文本研究笔记，保留问题、回答、引用页码和必要配图计划。"),
    "literature_summary": ("v2", "生成富文本文献摘要，区分摘要事实、作者观点和待核问题，并用受控图标辅助阅读。"),
    "source_guide": ("v2", "生成富文本资料导读，说明资料主题、结构、可用页码和阅读边界。"),
    "dating_timeline": ("v2", "生成富文本断代时间线，只列出资料支持的时间和不确定性。"),
    "evidence_card": ("v2", "生成富文本证据卡片，包含主张、原文、页码、观点和争议。"),
    "student_explainer": ("v2", "生成学生版富文本讲解，语言清楚，保留证据边界并规划必要配图。"),
    "researcher_brief": ("v2", "生成富文本研究者简报，突出材料、方法、观点和争议。"),
    "infographic": ("v2", "生成可编辑富文本科普图卡文案，按标题、要点、证据提示与配图计划组织。"),
    "lesson_material": ("v2", "生成富文本课堂材料，包括目标、讲解、问题、活动和必要图示。"),
    "short_video_script": ("v2", "生成富文本短视频脚本，包含镜头、口播、证据提示和免责声明。"),
    "captions": ("v1", "生成短视频字幕，按短句分行并保留资料边界。"),
    "visual_card_set": (
        "v1",
        "生成一组可直接排版为科普图片的图卡。每张卡只表达一个主题，正文简短，并保留资料名称与页码。不得把AI绘图当作甲骨原片。",
    ),
    "slide_deck": (
        "v2",
        "生成面向公众或课堂的增强讲解幻灯片。每页只有一个叙事任务，包含结论式标题、富文本、受控图标、必要图片、原生智能图形或基于真实数据的图表、讲者备注、资料页码、播放和转场设置。",
    ),
    "video_package": (
        "v1",
        "生成约三分钟的可编辑视频制作包。按时间给出分镜、画面说明、屏幕文字、旁白和资料页码；不得生成无依据的历史复原画面。",
    ),
    "whiteboard": (
        "v1",
        "生成可编辑研究白板，把资料、证据、观点和待核问题拆成节点并建立关系。节点只引用既有资料页、知识或作品，不改写为新的证据。",
    ),
    "mind_map": (
        "v1",
        "生成可编辑思维导图，以一个中心主题组织资料分支、证据分支、观点分歧和待核问题，并保留真实资料页码。",
    ),
}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


class ResearchStore:
    def __init__(self, path: Path = DB_PATH, private_dir: Path = PRIVATE_DIR) -> None:
        self.path = path
        self.private_dir = private_dir
        self.import_dir = private_dir / "imports"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _stored_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(ROOT).as_posix()
        except ValueError:
            return str(resolved)

    def _resolved_private_path(self, value: str) -> Path:
        # SQLite files can move between Windows research machines and Linux
        # deployment hosts. Normalize legacy Windows separators before resolve.
        path = Path(value.replace("\\", "/"))
        return path if path.is_absolute() else ROOT / path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            migrate_site_content_schema(connection)
            publication_state_added = False
            try:
                connection.execute(
                    "ALTER TABLE artifacts ADD COLUMN publication_state TEXT NOT NULL DEFAULT 'private'"
                )
                publication_state_added = True
            except sqlite3.OperationalError:
                pass
            if publication_state_added:
                connection.execute(
                    "UPDATE artifacts SET publication_state = 'public' WHERE status = 'published'"
                )
            # `published` was a legacy review status. Publication now lives only in
            # publication_state so the two workflow axes cannot contradict each other.
            connection.execute(
                "UPDATE artifacts SET publication_state = 'public' WHERE status = 'published' AND publication_state = 'private'"
            )
            connection.execute(
                "UPDATE artifacts SET status = 'approved' WHERE status = 'published'"
            )
            source_migrations = (
                "ALTER TABLE source_documents ADD COLUMN recognition_status TEXT NOT NULL DEFAULT 'unverified'",
                "ALTER TABLE source_documents ADD COLUMN recognition_method TEXT NOT NULL DEFAULT 'legacy_text'",
                "ALTER TABLE source_documents ADD COLUMN recognition_version INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE source_documents ADD COLUMN quality_score REAL",
                "ALTER TABLE source_documents ADD COLUMN quality_report_json TEXT",
                "ALTER TABLE source_documents ADD COLUMN source_role TEXT NOT NULL DEFAULT 'evidence'",
                "ALTER TABLE source_documents ADD COLUMN provenance_json TEXT",
            )
            unit_migrations = (
                "ALTER TABLE source_units ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'legacy_text'",
                "ALTER TABLE source_units ADD COLUMN quality_score REAL",
                "ALTER TABLE source_units ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'unverified'",
                "ALTER TABLE source_units ADD COLUMN ocr_model TEXT",
            )
            artifact_migrations = (
                "ALTER TABLE artifacts ADD COLUMN generation_instruction TEXT NOT NULL DEFAULT ''",
            )
            snapshot_migrations = (
                "ALTER TABLE publish_snapshots ADD COLUMN title TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE publish_snapshots ADD COLUMN description TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE publish_snapshots ADD COLUMN created_by TEXT NOT NULL DEFAULT ''",
            )
            for statement in (*source_migrations, *unit_migrations, *artifact_migrations, *snapshot_migrations):
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'reviewed'
                WHERE kind = 'pdf'
                  AND source_role = 'evidence'
                  AND status = 'parsed'
                  AND recognition_status = 'ocr_ready'
                """
            )
            for kind, (version, template) in PROMPTS.items():
                prompt_id = f"{kind}:{version}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO prompt_versions
                    (id, artifact_kind, version, template, active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (prompt_id, kind, version, template, now_iso()),
                )
            timestamp = now_iso()
            for content_key, default in SITE_CONTENT_DEFAULTS.items():
                encoded = json.dumps(default["content"], ensure_ascii=False)
                section = site_section_default(content_key) or {}
                connection.execute(
                    """
                    INSERT OR IGNORE INTO site_content_entries
                    (id, content_key, title, section_type, nav_label, kicker,
                     summary, body_html, enabled, sort_order,
                     content_json, published_content_json,
                     status, publication_state, model, prompt_version,
                     generation_instruction, created_at, updated_at, approved_at, published_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'approved', 'public', 'manual',
                            'site-content:seed-v1', '', ?, ?, ?, ?)
                    """,
                    (
                        f"site-{content_key}",
                        content_key,
                        section.get("title", default["title"]),
                        section.get("section_type", "standard"),
                        section.get("nav_label", ""),
                        section.get("kicker", ""),
                        section.get("summary", ""),
                        section.get("body_html", ""),
                        section.get("sort_order", 0),
                        encoded,
                        encoded,
                        timestamp,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                current = connection.execute(
                    "SELECT * FROM site_content_entries WHERE content_key = ?", (content_key,)
                ).fetchone()
                current_content = json.loads(current["content_json"]) if current else {}
                heading = str(current_content.get("heading") or section.get("title") or default["title"])
                kicker = str(current_content.get("kicker") or section.get("kicker") or "")
                summary = str(current_content.get("summary") or section.get("summary") or "")
                connection.execute(
                    """
                    UPDATE site_content_entries
                    SET title = CASE WHEN title = '' OR title LIKE '栏目%·%' THEN ? ELSE title END,
                        section_type = CASE WHEN section_type = 'standard' THEN ? ELSE section_type END,
                        nav_label = CASE WHEN nav_label = '' THEN ? ELSE nav_label END,
                        kicker = CASE WHEN kicker = '' THEN ? ELSE kicker END,
                        summary = CASE WHEN summary = '' THEN ? ELSE summary END,
                        body_html = CASE WHEN body_html = '' THEN ? ELSE body_html END,
                        sort_order = CASE WHEN sort_order = 0 AND content_key != 'hero' THEN ? ELSE sort_order END
                    WHERE content_key = ?
                    """,
                    (
                        heading,
                        section.get("section_type", "standard"),
                        section.get("nav_label", ""),
                        kicker,
                        summary,
                        section.get("body_html", ""),
                        section.get("sort_order", 0),
                        content_key,
                    ),
                )

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def _json_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in (
            "content_json",
            "published_content_json",
            "item_counts_json",
            "quality_report_json",
            "provenance_json",
        ):
            if key in item and item[key]:
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
        if item.get("kind") == "slide_deck" and isinstance(item.get("content"), dict):
            # Older generated decks are normalized on read so their previews and
            # exports gain current text cleaning and page-capacity safeguards.
            try:
                item["content"] = normalize_artifact_content(
                    "slide_deck", item["content"], str(item.get("id") or "artifact")
                )
            except ValueError:
                pass
        return item

    def _source_public(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item.pop("private_path", None)
        if item.get("quality_report_json"):
            item["quality_report"] = json.loads(item.pop("quality_report_json"))
        else:
            item.pop("quality_report_json", None)
        if item.get("provenance_json"):
            item["provenance"] = json.loads(item.pop("provenance_json"))
        else:
            item.pop("provenance_json", None)
        return item

    def list_sources(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE status != 'deleted'"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM source_documents {where} ORDER BY updated_at DESC"
            ).fetchall()
        return [self._source_public(row) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_documents WHERE id = ?", (source_id,)
            ).fetchone()
        return self._row(row)

    def source_file(self, source_id: str) -> tuple[Path, str]:
        source = self.get_source(source_id)
        if not source or source.get("kind") != "pdf" or not source.get("private_path"):
            raise KeyError("该资料没有可预览的PDF")
        path = self._resolved_private_path(str(source["private_path"])).resolve()
        private_root = self.private_dir.resolve()
        if not path.is_relative_to(private_root) or not path.exists():
            raise KeyError("PDF文件不存在")
        return path, str(source.get("filename") or "source.pdf")

    def source_page_image(self, source_id: str, page_number: int) -> Path:
        if page_number < 1:
            raise ValueError("PDF页码必须大于0")
        pdf_path, _ = self.source_file(source_id)
        private_root = self.private_dir.resolve()

        for run in self.list_ocr_runs(source_id):
            page_dir_value = str(run.get("page_dir") or "")
            if not page_dir_value:
                continue
            page_dir = self._resolved_private_path(page_dir_value).resolve()
            image_path = page_dir / f"page-{page_number:04d}.png"
            if page_dir.is_relative_to(private_root) and image_path.is_file():
                return image_path

        cache_dir = self.private_dir / "page-previews" / source_id
        image_path = cache_dir / f"page-{page_number:04d}.png"
        if image_path.is_file():
            return image_path

        try:
            import pypdfium2
        except ImportError as exc:
            raise RuntimeError("缺少PDF页面渲染组件") from exc

        document = pypdfium2.PdfDocument(str(pdf_path))
        try:
            if page_number > len(document):
                raise KeyError("PDF页码不存在")
            image = document[page_number - 1].render(scale=1.8).to_pil()
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = image_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            image.save(temporary, format="PNG", optimize=True)
            temporary.replace(image_path)
        finally:
            document.close()
        return image_path

    def list_review_events(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        if target_type not in {"source", "candidate", "knowledge", "artifact", "snapshot"}:
            raise ValueError("审核对象类型无效")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, target_type, target_id, action, reviewer, note, created_at
                FROM review_events
                WHERE target_type = ? AND target_id = ?
                ORDER BY created_at DESC
                """,
                (target_type, target_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _find_duplicate(self, content_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM source_documents
                WHERE content_hash = ? AND status != 'deleted'
                ORDER BY created_at LIMIT 1
                """,
                (content_hash,),
            ).fetchone()
        return self._row(row)

    def _insert_source(
        self,
        *,
        kind: str,
        title: str,
        content_hash: str,
        filename: str | None = None,
        source_url: str | None = None,
        private_path: str | None = None,
        external_id: str | None = None,
        source_role: str = "evidence",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        duplicate = self._find_duplicate(content_hash)
        if duplicate:
            public = next(item for item in self.list_sources() if item["id"] == duplicate["id"])
            public["duplicate"] = True
            return public
        source_id = make_id("src")
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_documents
                (id, external_id, kind, source_role, title, filename, source_url, private_path,
                 content_hash, status, parse_version, provenance_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported', 0, ?, ?, ?)
                """,
                (
                    source_id,
                    external_id,
                    kind,
                    source_role,
                    title.strip() or filename or "未命名资料",
                    filename,
                    source_url,
                    private_path,
                    content_hash,
                    json.dumps(provenance, ensure_ascii=False) if provenance else None,
                    timestamp,
                    timestamp,
                ),
            )
        result = self.get_source(source_id) or {}
        result.pop("private_path", None)
        result["duplicate"] = False
        return result

    def import_pdf_bytes(self, filename: str, content: bytes, title: str = "") -> dict[str, Any]:
        if not content or len(content) > MAX_IMPORT_BYTES:
            raise ValueError("PDF为空或超过25MB限制")
        if not content.startswith(b"%PDF"):
            raise ValueError("文件不是有效PDF")
        content_hash = sha256_bytes(content)
        duplicate = self._find_duplicate(content_hash)
        if duplicate:
            public = next(item for item in self.list_sources() if item["id"] == duplicate["id"])
            public["duplicate"] = True
            return public
        self.import_dir.mkdir(parents=True, exist_ok=True)
        safe_name = clean_filename(filename, ".pdf")
        target = self.import_dir / f"{content_hash[:12]}_{safe_name}"
        target.write_bytes(content)
        return self._insert_source(
            kind="pdf",
            title=title or Path(safe_name).stem,
            filename=safe_name,
            private_path=self._stored_path(target),
            content_hash=content_hash,
        )

    def register_existing_pdf(
        self,
        path: Path,
        *,
        title: str,
        external_id: str | None = None,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        resolved = path.resolve()
        private_root = self.private_dir.resolve()
        if private_root not in resolved.parents:
            raise ValueError("PDF必须位于私有资料目录")
        content = resolved.read_bytes()
        return self._insert_source(
            kind="pdf",
            title=title,
            filename=resolved.name,
            source_url=source_url,
            private_path=self._stored_path(resolved),
            content_hash=sha256_bytes(content),
            external_id=external_id,
        )

    def import_manual_text(self, title: str, text: str) -> dict[str, Any]:
        normalized = text.strip()
        if not normalized:
            raise ValueError("手动文本不能为空")
        content = normalized.encode("utf-8")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("文本超过25MB限制")
        content_hash = sha256_bytes(content)
        duplicate = self._find_duplicate(content_hash)
        if duplicate:
            duplicate["duplicate"] = True
            duplicate.pop("private_path", None)
            return duplicate
        self.import_dir.mkdir(parents=True, exist_ok=True)
        target = self.import_dir / f"{content_hash[:12]}_{clean_filename(title or 'manual', '.txt')}"
        target.write_text(normalized, encoding="utf-8")
        return self._insert_source(
            kind="manual",
            title=title or "手动文本",
            filename=target.name,
            private_path=self._stored_path(target),
            content_hash=content_hash,
        )

    def import_generated_note(
        self,
        *,
        title: str,
        question: str,
        answer: str,
        source_ids: list[str],
        citations: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        normalized = answer.strip()
        if not normalized:
            raise ValueError("问答结果为空")
        evidence_sources = [self.get_source(source_id) for source_id in sorted(set(source_ids))]
        if any(not source or source.get("source_role", "evidence") != "evidence" for source in evidence_sources):
            raise ValueError("研究笔记只能关联原始资料")
        body = f"问题：{question.strip()}\n\n回答：\n{normalized}"
        content_hash = sha256_text(f"generated_note\0{body}")
        duplicate = self._find_duplicate(content_hash)
        if duplicate:
            public = next(item for item in self.list_sources() if item["id"] == duplicate["id"])
            public["duplicate"] = True
            return public
        self.import_dir.mkdir(parents=True, exist_ok=True)
        target = self.import_dir / f"{content_hash[:12]}_{clean_filename(title or 'research-note', '.txt')}"
        target.write_text(body, encoding="utf-8")
        result = self._insert_source(
            kind="manual",
            source_role="generated_note",
            title=title or "AI研究笔记",
            filename=target.name,
            private_path=self._stored_path(target),
            content_hash=content_hash,
            provenance={
                "origin": "research_answer",
                "model": model,
                "question": question.strip(),
                "sourceIds": sorted(set(source_ids)),
                "citations": citations,
                "evidenceEligible": False,
            },
        )
        parsed = self.parse_source(str(result["id"]))
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'source', ?, 'save_generated_note', 'system',
                        '问答结果保存为AI研究笔记；不作为证据，不参与模型检索或公众发布', ?)
                """,
                (make_id("review"), result["id"], now_iso()),
            )
        public = next(item for item in self.list_sources() if item["id"] == result["id"])
        public["duplicate"] = False
        public["autoParse"] = parsed
        return public

    def _validate_remote_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("仅支持HTTP或HTTPS网页链接")
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("不允许导入本机或私有网络地址")
        return urllib.parse.urlunparse(parsed._replace(fragment=""))

    def import_url(self, url: str, title: str = "") -> dict[str, Any]:
        safe_url = self._validate_remote_url(url)
        request = urllib.request.Request(
            safe_url,
            headers={"User-Agent": "OracleEclipseResearch/0.4"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError("网页内容超过25MB限制")
        if content_type not in {"text/html", "text/plain"}:
            raise ValueError("网页不是HTML或纯文本")
        decoded = raw.decode(charset, errors="replace")
        if content_type == "text/html":
            parser = TextHTMLParser()
            parser.feed(decoded)
            decoded = parser.text()
        if not decoded.strip():
            raise ValueError("网页没有可用正文")
        content_hash = sha256_text(decoded)
        duplicate = self._find_duplicate(content_hash)
        if duplicate:
            duplicate["duplicate"] = True
            duplicate.pop("private_path", None)
            return duplicate
        self.import_dir.mkdir(parents=True, exist_ok=True)
        target = self.import_dir / f"{content_hash[:12]}_web.txt"
        target.write_text(decoded, encoding="utf-8")
        return self._insert_source(
            kind="url",
            title=title or urllib.parse.urlparse(safe_url).hostname or "网页资料",
            source_url=safe_url,
            filename=target.name,
            private_path=self._stored_path(target),
            content_hash=content_hash,
        )

    def _extract_pdf_units(self, path: Path) -> list[tuple[str, str]]:
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore[no-redef]
            except ImportError as exc:
                raise RuntimeError("缺少pypdf，无法解析PDF") from exc
        try:
            reader = PdfReader(str(path))
            return [
                (str(index), (page.extract_text() or "").strip())
                for index, page in enumerate(reader.pages, 1)
            ]
        except Exception:
            try:
                import pypdfium2
            except ImportError as exc:
                raise RuntimeError("PDF文本层损坏，且缺少pypdfium2获取页数") from exc
            document = pypdfium2.PdfDocument(str(path))
            return [(str(index), "") for index in range(1, len(document) + 1)]

    def parse_source(self, source_id: str, force: bool = False) -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or source["status"] == "deleted":
            raise KeyError("资料不存在")
        if source["status"] in {"parsed", "reviewed"} and not force:
            return {"sourceId": source_id, "status": source["status"], "unchanged": True}
        path = self._resolved_private_path(str(source.get("private_path") or ""))
        next_version = int(source["parse_version"]) + 1
        try:
            if source["kind"] == "pdf":
                extracted = self._extract_pdf_units(path)
                locator_type = "pdf_page"
            else:
                extracted = [("1", path.read_text(encoding="utf-8"))]
                locator_type = "text_unit"
            quality_reports = [assess_text_quality(text) for _, text in extracted]
            aggregate = aggregate_quality(quality_reports)
            if source["kind"] == "pdf":
                recognition_status = "text_ready" if aggregate["status"] == "passed" else "ocr_pending"
                recognition_method = "pdf_text"
            else:
                recognition_status = "text_ready"
                recognition_method = "trusted_text"
            timestamp = now_iso()
            with self.connect() as connection:
                for index, ((locator, text), quality) in enumerate(
                    zip(extracted, quality_reports), 1
                ):
                    connection.execute(
                        """
                        INSERT INTO source_units
                        (id, source_id, parse_version, unit_index, locator_type,
                         locator_value, text_content, content_hash, extraction_method,
                         quality_score, quality_status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            make_id("unit"),
                            source_id,
                            next_version,
                            index,
                            locator_type,
                            locator,
                            text,
                            sha256_text(text),
                            recognition_method,
                            quality["score"],
                            quality["status"],
                            timestamp,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE source_documents
                    SET status = 'parsed', parse_version = ?, page_count = ?,
                        recognition_status = ?, recognition_method = ?,
                        quality_score = ?, quality_report_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_version,
                        len(extracted),
                        recognition_status,
                        recognition_method,
                        aggregate["score"],
                        json.dumps(aggregate, ensure_ascii=False),
                        timestamp,
                        source_id,
                    ),
                )
            if force:
                self.invalidate_source(source_id, "资料已重新解析")
            return {
                "sourceId": source_id,
                "status": "parsed",
                "parseVersion": next_version,
                "units": len(extracted),
                "recognitionStatus": recognition_status,
                "quality": aggregate,
            }
        except Exception:
            with self.connect() as connection:
                connection.execute(
                    "UPDATE source_documents SET status = 'parse_failed', updated_at = ? WHERE id = ?",
                    (now_iso(), source_id),
                )
            raise

    def list_units(self, source_id: str) -> list[dict[str, Any]]:
        source = self.get_source(source_id)
        if not source:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, parse_version, unit_index, locator_type,
                       locator_value, text_content, content_hash, extraction_method,
                       quality_score, quality_status, ocr_model
                FROM source_units
                WHERE source_id = ? AND parse_version = ?
                ORDER BY unit_index
                """,
                (source_id, source["parse_version"]),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ocr_runs(self, source_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE source_id = ?" if source_id else ""
        params: tuple[Any, ...] = (source_id,) if source_id else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM ocr_runs {where} ORDER BY created_at DESC", params
            ).fetchall()
        return [self._json_row(row) for row in rows]

    def start_ocr_run(self, source_id: str, model: str) -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or source.get("kind") != "pdf" or source.get("status") == "deleted":
            raise ValueError("只有有效PDF资料可以执行OCR")
        with self.connect() as connection:
            active = connection.execute(
                "SELECT * FROM ocr_runs WHERE source_id = ? AND status IN ('queued','processing') ORDER BY created_at DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if active:
                return self._json_row(active)
            run_id = make_id("ocr")
            timestamp = now_iso()
            page_dir = self.private_dir / "ocr-pages" / source_id / run_id
            connection.execute(
                """
                INSERT INTO ocr_runs
                (id, source_id, status, engine, model, total_pages, processed_pages,
                 page_dir, created_at, updated_at)
                VALUES (?, ?, 'queued', 'bailian-vision', ?, ?, 0, ?, ?, ?)
                """,
                (
                    run_id,
                    source_id,
                    model,
                    int(source.get("page_count") or 0),
                    self._stored_path(page_dir),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'parsed', recognition_status = 'ocr_processing', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, source_id),
            )
        return self.list_ocr_runs(source_id)[0]

    def begin_ocr_run(self, run_id: str, total_pages: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE ocr_runs SET status = 'processing', total_pages = ?, updated_at = ? WHERE id = ?",
                (total_pages, now_iso(), run_id),
            )

    def save_ocr_page_result(
        self, run_id: str, source_id: str, page_number: int, text: str
    ) -> dict[str, Any]:
        report = assess_text_quality(text)
        report["pageNumber"] = page_number
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO ocr_page_results
                (id, run_id, source_id, page_number, text_content, content_hash,
                 quality_score, quality_status, quality_report_json, created_at)
                VALUES (
                    COALESCE((SELECT id FROM ocr_page_results WHERE run_id = ? AND page_number = ?), ?),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    page_number,
                    make_id("ocrpage"),
                    run_id,
                    source_id,
                    page_number,
                    text.strip(),
                    sha256_text(text.strip()),
                    report["score"],
                    report["status"],
                    json.dumps(report, ensure_ascii=False),
                    timestamp,
                ),
            )
            processed = connection.execute(
                "SELECT COUNT(*) FROM ocr_page_results WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            connection.execute(
                "UPDATE ocr_runs SET processed_pages = ?, updated_at = ? WHERE id = ?",
                (processed, timestamp, run_id),
            )
        return report

    def complete_ocr_run(
        self,
        run_id: str,
        source_id: str,
        model: str,
        *,
        completion_note: str = "OCR文本重建完成，来源版本已更新",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            run = connection.execute("SELECT * FROM ocr_runs WHERE id = ?", (run_id,)).fetchone()
            pages = connection.execute(
                "SELECT * FROM ocr_page_results WHERE run_id = ? ORDER BY page_number",
                (run_id,),
            ).fetchall()
        if not run or not pages or len(pages) != int(run["total_pages"]):
            raise ValueError("OCR页面结果不完整")
        reports = []
        for page in pages:
            report = json.loads(page["quality_report_json"])
            report.setdefault("pageNumber", int(page["page_number"]))
            reports.append(report)
        aggregate = aggregate_quality(reports)
        timestamp = now_iso()
        if aggregate["status"] == "failed":
            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE ocr_runs
                    SET status = 'failed', quality_score = ?, quality_report_json = ?,
                        error = 'OCR文本质量未通过', updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (
                        aggregate["score"],
                        json.dumps(aggregate, ensure_ascii=False),
                        timestamp,
                        timestamp,
                        run_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE source_documents
                    SET status = 'parsed', recognition_status = 'ocr_failed',
                        quality_score = ?, quality_report_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        aggregate["score"],
                        json.dumps(aggregate, ensure_ascii=False),
                        timestamp,
                        source_id,
                    ),
                )
            return {"runId": run_id, "status": "failed", "quality": aggregate}

        source = self.get_source(source_id) or {}
        next_version = int(source.get("parse_version") or 0) + 1
        with self.connect() as connection:
            for index, page in enumerate(pages, 1):
                connection.execute(
                    """
                    INSERT INTO source_units
                    (id, source_id, parse_version, unit_index, locator_type,
                     locator_value, text_content, content_hash, extraction_method,
                     quality_score, quality_status, ocr_model, created_at)
                    VALUES (?, ?, ?, ?, 'pdf_page', ?, ?, ?, 'bailian_ocr', ?, ?, ?, ?)
                    """,
                    (
                        make_id("unit"),
                        source_id,
                        next_version,
                        index,
                        str(page["page_number"]),
                        page["text_content"],
                        page["content_hash"],
                        page["quality_score"],
                        page["quality_status"],
                        model,
                        timestamp,
                    ),
                )
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'parsed', parse_version = ?, page_count = ?,
                    recognition_status = 'ocr_needs_review', recognition_method = 'bailian_ocr',
                    recognition_version = recognition_version + 1,
                    quality_score = ?, quality_report_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_version,
                    len(pages),
                    aggregate["score"],
                    json.dumps(aggregate, ensure_ascii=False),
                    timestamp,
                    source_id,
                ),
            )
            connection.execute(
                """
                UPDATE ocr_runs
                SET status = 'completed', quality_score = ?, quality_report_json = ?,
                    error = NULL, updated_at = ?, completed_at = ? WHERE id = ?
                """,
                (
                    aggregate["score"],
                    json.dumps(aggregate, ensure_ascii=False),
                    timestamp,
                    timestamp,
                    run_id,
                ),
            )
        invalidated = self.invalidate_source(source_id, completion_note)
        return {
            "runId": run_id,
            "status": "completed",
            "parseVersion": next_version,
            "quality": aggregate,
            "invalidated": invalidated,
        }

    def reassess_ocr_results(self, source_id: str) -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or source.get("kind") != "pdf" or source.get("status") == "deleted":
            raise ValueError("只有有效PDF资料可以重新评估OCR结果")
        if source.get("recognition_status") != "ocr_failed":
            raise ValueError("只有OCR失败的资料需要重新评估已有结果")

        with self.connect() as connection:
            run = connection.execute(
                """
                SELECT * FROM ocr_runs
                WHERE source_id = ? AND total_pages > 0
                  AND processed_pages = total_pages
                ORDER BY created_at DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if not run:
                raise ValueError("没有完整的已有OCR结果，请重新启动百炼OCR")
            pages = connection.execute(
                "SELECT * FROM ocr_page_results WHERE run_id = ? ORDER BY page_number",
                (run["id"],),
            ).fetchall()
            if len(pages) != int(run["total_pages"]):
                raise ValueError("已有OCR页面不完整，请重新启动百炼OCR")

            timestamp = now_iso()
            for page in pages:
                report = assess_text_quality(str(page["text_content"] or ""))
                report["pageNumber"] = int(page["page_number"])
                connection.execute(
                    """
                    UPDATE ocr_page_results
                    SET quality_score = ?, quality_status = ?, quality_report_json = ?
                    WHERE id = ?
                    """,
                    (
                        report["score"],
                        report["status"],
                        json.dumps(report, ensure_ascii=False),
                        page["id"],
                    ),
                )
            connection.execute(
                "UPDATE ocr_runs SET updated_at = ? WHERE id = ?",
                (timestamp, run["id"]),
            )

        result = self.complete_ocr_run(
            str(run["id"]),
            source_id,
            str(run["model"]),
            completion_note="已有OCR文本按新版质量规则重新评估，来源版本已更新",
        )
        return {**result, "reassessed": True, "reusedStoredText": True}

    def fail_ocr_run(self, run_id: str, source_id: str, error: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE ocr_runs SET status = 'failed', error = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (error[:1000], timestamp, timestamp, run_id),
            )
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'parsed', recognition_status = 'ocr_failed', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, source_id),
            )

    def mark_ocr_pending(self, source_id: str, reason: str = "文本层质量异常") -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or source.get("kind") != "pdf" or source.get("status") == "deleted":
            raise ValueError("只有有效PDF资料可以标记OCR重建")
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'parsed', recognition_status = 'ocr_pending', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, source_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'source', ?, 'ocr_pending', 'system', ?, ?)
                """,
                (make_id("review"), source_id, reason, timestamp),
            )
        invalidated = self.invalidate_source(source_id, reason)
        return {"sourceId": source_id, "recognitionStatus": "ocr_pending", "invalidated": invalidated}

    def mark_all_pdfs_ocr_pending(self, reason: str) -> list[dict[str, Any]]:
        return [
            self.mark_ocr_pending(source["id"], reason)
            for source in self.list_sources()
            if source.get("kind") == "pdf"
            and source.get("recognition_status") not in {"ocr_processing", "ocr_pending"}
        ]

    def review_ocr(
        self, source_id: str, action: str, reviewer: str = "本地审核人"
    ) -> dict[str, Any]:
        if action not in {"approve", "reject"}:
            raise ValueError("OCR确认动作无效")
        source = self.get_source(source_id)
        if not source or source.get("recognition_status") != "ocr_needs_review":
            raise ValueError("该资料没有待确认的OCR文本")
        recognition_status = "ocr_ready" if action == "approve" else "ocr_pending"
        source_status = "reviewed" if action == "approve" else "parsed"
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE source_documents SET recognition_status = ?, status = ?, updated_at = ? WHERE id = ?",
                (recognition_status, source_status, timestamp, source_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'source', ?, ?, ?, ?, ?)
                """,
                (
                    make_id("review"),
                    source_id,
                    f"ocr_{action}",
                    reviewer,
                    "OCR逐页文本已确认，来源同步进入可发布状态"
                    if action == "approve"
                    else "OCR文本退回重新识别",
                    timestamp,
                ),
            )
        if action == "reject":
            self.invalidate_source(source_id, "OCR文本被退回确认")
        return {
            "sourceId": source_id,
            "recognitionStatus": recognition_status,
            "status": source_status,
        }

    def _candidate_payload(self, source: dict[str, Any], unit: dict[str, Any], snippet: str) -> dict[str, Any]:
        locator = unit["locator_value"]
        return {
            "id": make_id("record"),
            "headline": f"{source['title']} · 候选记录",
            "inscription": snippet,
            "status": "候选知识，待人工审核",
            "confidence": "待核验",
            "translation": "待审核人员依据上下文补充释义。",
            "dating": "尚不清楚",
            "catalogNumber": "待核",
            "sourceEvidence": [
                {
                    "sourceId": source.get("external_id") or source["id"],
                    "pdfPage": int(locator) if locator.isdigit() and source["kind"] == "pdf" else None,
                    "publicationPage": None,
                    "purpose": "自动定位的候选文本，尚未审核",
                }
            ],
            "scholarViews": [],
            "disputes": ["该条由规则自动定位，必须对照原文页面人工审核。"],
            "sourceIds": [source.get("external_id") or source["id"]],
            "reviewed": False,
            "reviewLevel": "候选知识",
        }

    def extract_candidates(self, source_id: str) -> list[dict[str, Any]]:
        source = self.get_source(source_id)
        if not source or source["status"] not in {"parsed", "reviewed"}:
            raise ValueError("资料必须先完成解析")
        if source.get("recognition_status") not in RESEARCH_READY_RECOGNITION:
            raise ValueError("资料文本质量未通过，必须先完成OCR重建")
        patterns = re.compile(r"日有食|日有戠|日食|忧祸|祖庚|乙巳|乙丑|癸酉")
        created: list[dict[str, Any]] = []
        for unit in self.list_units(source_id):
            text = unit["text_content"]
            for match in patterns.finditer(text):
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 140)
                snippet = re.sub(r"\s+", " ", text[start:end]).strip()
                content_hash = sha256_text(f"{source_id}:{unit['id']}:{snippet}")
                with self.connect() as connection:
                    exists = connection.execute(
                        "SELECT id FROM knowledge_candidates WHERE content_hash = ?",
                        (content_hash,),
                    ).fetchone()
                    if exists:
                        continue
                    candidate_id = make_id("cand")
                    content = self._candidate_payload(source, unit, snippet)
                    timestamp = now_iso()
                    connection.execute(
                        """
                        INSERT INTO knowledge_candidates
                        (id, candidate_type, title, summary, content_json, content_hash,
                         status, source_id, created_by, created_at, updated_at)
                        VALUES (?, 'record', ?, ?, ?, ?, 'candidate', ?, 'local-rules:v1', ?, ?)
                        """,
                        (
                            candidate_id,
                            f"{source['title']} · {unit['locator_type']} {unit['locator_value']}",
                            snippet,
                            json.dumps(content, ensure_ascii=False),
                            content_hash,
                            source_id,
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO lineage_edges
                        (upstream_type, upstream_id, downstream_type, downstream_id,
                         relation, source_id, unit_id, created_at)
                        VALUES ('unit', ?, 'candidate', ?, 'supports', ?, ?, ?)
                        """,
                        (unit["id"], candidate_id, source_id, unit["id"], timestamp),
                    )
                created.append({"id": candidate_id, "summary": snippet})
                if len(created) >= 20:
                    return created
        return created

    def list_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE c.status = ?" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, s.title AS source_title
                FROM knowledge_candidates c
                JOIN source_documents s ON s.id = c.source_id
                {where}
                ORDER BY c.updated_at DESC
                """,
                params,
            ).fetchall()
        items = [self._json_row(row) for row in rows]
        for item in items:
            item["sources"] = self.lineage_for("candidate", item["id"])
        return items

    def review_candidate(
        self,
        candidate_id: str,
        action: str,
        *,
        reviewer: str = "本地审核人",
        note: str = "",
        content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action not in {"approve", "reject"}:
            raise ValueError("审核动作无效")
        with self.connect() as connection:
            candidate = connection.execute(
                "SELECT * FROM knowledge_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if not candidate:
                raise KeyError("候选知识不存在")
            if action == "approve":
                source = connection.execute(
                    "SELECT status, recognition_status FROM source_documents WHERE id = ?",
                    (candidate["source_id"],),
                ).fetchone()
                if (
                    not source
                    or source["status"] != "reviewed"
                    or source["recognition_status"] not in PUBLISH_READY_RECOGNITION
                ):
                    raise ValueError("候选知识的来源尚未完成确认")
            status = "approved" if action == "approve" else "rejected"
            payload = content or json.loads(candidate["content_json"])
            if action == "approve" and isinstance(payload, dict):
                payload = {
                    **payload,
                    "status": "已通过人工审核",
                    "confidence": payload.get("confidence", "人工审核"),
                    "reviewed": True,
                    "reviewLevel": "人工审核",
                }
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE knowledge_candidates
                SET status = ?, content_json = ?, updated_at = ? WHERE id = ?
                """,
                (status, json.dumps(payload, ensure_ascii=False), timestamp, candidate_id),
            )
            if action == "reject":
                connection.execute(
                    "UPDATE published_knowledge SET status = 'retired', updated_at = ? WHERE candidate_id = ?",
                    (timestamp, candidate_id),
                )
            review_id = make_id("review")
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'candidate', ?, ?, ?, ?, ?)
                """,
                (review_id, candidate_id, action, reviewer, note, timestamp),
            )
            if action == "approve":
                knowledge_id = payload.get("id") or make_id("knowledge")
                source = connection.execute(
                    "SELECT parse_version FROM source_documents WHERE id = ?",
                    (candidate["source_id"],),
                ).fetchone()
                signature = f"{candidate['source_id']}@{source['parse_version']}"
                connection.execute(
                    """
                    INSERT OR REPLACE INTO published_knowledge
                    (id, candidate_id, knowledge_type, title, content_json, status,
                     source_revision_sig, approved_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)
                    """,
                    (
                        knowledge_id,
                        candidate_id,
                        candidate["candidate_type"],
                        candidate["title"],
                        json.dumps(payload, ensure_ascii=False),
                        signature,
                        timestamp,
                        timestamp,
                    ),
                )
                units = connection.execute(
                    "SELECT unit_id FROM lineage_edges WHERE downstream_type = 'candidate' AND downstream_id = ?",
                    (candidate_id,),
                ).fetchall()
                for unit in units:
                    connection.execute(
                        """
                        INSERT INTO lineage_edges
                        (upstream_type, upstream_id, downstream_type, downstream_id,
                         relation, source_id, unit_id, created_at)
                        VALUES ('unit', ?, 'knowledge', ?, 'supports', ?, ?, ?)
                        """,
                        (unit["unit_id"], knowledge_id, candidate["source_id"], unit["unit_id"], timestamp),
                    )
        return {"id": candidate_id, "status": status}

    def add_published_knowledge(
        self,
        knowledge_id: str,
        knowledge_type: str,
        title: str,
        content: dict[str, Any],
        source_links: Iterable[tuple[str, str | None]],
        reviewer: str = "MVP 0.3迁移",
    ) -> None:
        links = list(source_links)
        signatures: list[str] = []
        timestamp = now_iso()
        with self.connect() as connection:
            for source_id, _ in links:
                source = connection.execute(
                    "SELECT parse_version FROM source_documents WHERE id = ?", (source_id,)
                ).fetchone()
                if source:
                    signatures.append(f"{source_id}@{source['parse_version']}")
            signature = ";".join(sorted(signatures)) or "legacy-seed"
            connection.execute(
                """
                INSERT OR REPLACE INTO published_knowledge
                (id, candidate_id, knowledge_type, title, content_json, status,
                 source_revision_sig, approved_at, updated_at)
                VALUES (?, NULL, ?, ?, ?, 'approved', ?, ?, ?)
                """,
                (
                    knowledge_id,
                    knowledge_type,
                    title,
                    json.dumps(content, ensure_ascii=False),
                    signature,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'knowledge', ?, 'approve', ?, '从已核验MVP 0.3迁移', ?)
                """,
                (f"review-seed-{knowledge_id}", knowledge_id, reviewer, timestamp),
            )
            for source_id, unit_id in links:
                connection.execute(
                    """
                    INSERT INTO lineage_edges
                    (upstream_type, upstream_id, downstream_type, downstream_id,
                     relation, source_id, unit_id, created_at)
                    VALUES (?, ?, 'knowledge', ?, 'supports', ?, ?, ?)
                    """,
                    (
                        "unit" if unit_id else "source",
                        unit_id or source_id,
                        knowledge_id,
                        source_id,
                        unit_id,
                        timestamp,
                    ),
                )

    def list_published_knowledge(self, include_stale: bool = False) -> list[dict[str, Any]]:
        where = "" if include_stale else "WHERE status = 'approved'"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM published_knowledge {where} ORDER BY approved_at"
            ).fetchall()
        items = [self._json_row(row) for row in rows]
        for item in items:
            item["sources"] = self.lineage_for("knowledge", item["id"])
        return items

    def get_knowledge(self, knowledge_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM published_knowledge WHERE id = ?", (knowledge_id,)
            ).fetchone()
        if not row:
            return None
        item = self._json_row(row)
        item["sources"] = self.lineage_for("knowledge", knowledge_id)
        return item

    def edit_candidate(
        self,
        candidate_id: str,
        *,
        title: str,
        summary: str,
        content: dict[str, Any],
        reviewer: str = "本地审核人",
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            candidate = connection.execute(
                "SELECT id FROM knowledge_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if not candidate:
                raise KeyError("候选知识不存在")
            connection.execute(
                """
                UPDATE knowledge_candidates
                SET title = ?, summary = ?, content_json = ?, status = 'candidate', updated_at = ?
                WHERE id = ?
                """,
                (
                    title.strip() or "未命名候选",
                    summary.strip(),
                    json.dumps(content, ensure_ascii=False),
                    timestamp,
                    candidate_id,
                ),
            )
            connection.execute(
                """
                UPDATE published_knowledge
                SET status = 'stale', updated_at = ?
                WHERE candidate_id = ? AND status = 'approved'
                """,
                (timestamp, candidate_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'candidate', ?, 'edit', ?, '编辑后退回待审核', ?)
                """,
                (make_id("review"), candidate_id, reviewer, timestamp),
            )
        return next(item for item in self.list_candidates() if item["id"] == candidate_id)

    def edit_knowledge(
        self,
        knowledge_id: str,
        *,
        title: str,
        content: dict[str, Any],
        reviewer: str = "本地审核人",
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            if not connection.execute(
                "SELECT id FROM published_knowledge WHERE id = ?", (knowledge_id,)
            ).fetchone():
                raise KeyError("知识不存在")
            connection.execute(
                """
                UPDATE published_knowledge
                SET title = ?, content_json = ?, status = 'stale', updated_at = ?
                WHERE id = ?
                """,
                (
                    title.strip() or "未命名知识",
                    json.dumps(content, ensure_ascii=False),
                    timestamp,
                    knowledge_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'knowledge', ?, 'edit', ?, '编辑后等待重新审核', ?)
                """,
                (make_id("review"), knowledge_id, reviewer, timestamp),
            )
        return self.get_knowledge(knowledge_id) or {}

    def review_knowledge(
        self,
        knowledge_id: str,
        action: str,
        reviewer: str = "本地审核人",
        note: str = "",
    ) -> dict[str, Any]:
        if action not in {"approve", "retire"}:
            raise ValueError("知识审核动作无效")
        status = "approved" if action == "approve" else "retired"
        timestamp = now_iso()
        with self.connect() as connection:
            if not connection.execute(
                "SELECT id FROM published_knowledge WHERE id = ?", (knowledge_id,)
            ).fetchone():
                raise KeyError("知识不存在")
            connection.execute(
                "UPDATE published_knowledge SET status = ?, updated_at = ? WHERE id = ?",
                (status, timestamp, knowledge_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'knowledge', ?, ?, ?, ?, ?)
                """,
                (make_id("review"), knowledge_id, action, reviewer, note, timestamp),
            )
        return {"id": knowledge_id, "status": status}

    def generation_context(self, source_ids: list[str]) -> dict[str, Any]:
        ids = sorted(set(source_ids))
        if not ids:
            raise ValueError("至少选择一项资料")
        sources = [self.get_source(source_id) for source_id in ids]
        if any(not source for source in sources):
            raise ValueError("所选资料不存在")
        if any(
            source.get("source_role", "evidence") != "evidence"
            for source in sources
            if source
        ):
            raise ValueError("AI研究笔记不能作为资料证据或再次进入模型检索")
        if any(
            source.get("status") != "reviewed"
            or source.get("recognition_status") not in PUBLISH_READY_RECOGNITION
            for source in sources
            if source
        ):
            raise ValueError("未经确认的资料不能参与问答与输出")
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            knowledge_rows = connection.execute(
                f"""
                SELECT DISTINCT k.*
                FROM published_knowledge k
                JOIN lineage_edges l
                  ON l.downstream_type = 'knowledge' AND l.downstream_id = k.id
                WHERE l.source_id IN ({placeholders}) AND k.status = 'approved'
                ORDER BY k.approved_at
                """,
                ids,
            ).fetchall()
        knowledge = [self._json_row(row) for row in knowledge_rows]
        excerpts: list[dict[str, Any]] = []
        unit_ids: list[str] = []
        for source_id in ids:
            source = self.get_source(source_id) or {}
            for unit in self.list_units(source_id)[:16]:
                unit_ids.append(unit["id"])
                excerpts.append(
                    {
                        "sourceId": source_id,
                        "sourceTitle": source.get("title", "资料"),
                        "sourceStatus": source.get("status", "parsed"),
                        "sourceRecognitionStatus": source.get(
                            "recognition_status", "unverified"
                        ),
                        "locatorType": unit["locator_type"],
                        "locator": unit["locator_value"],
                        "text": unit["text_content"][:1800],
                    }
                )
        return {
            "records": [
                item["content"] for item in knowledge if item["knowledge_type"] == "record"
            ],
            "knowledge": knowledge,
            "excerpts": excerpts,
            "unitIds": unit_ids,
            "sources": [
                {
                    "id": source.get("id", ""),
                    "title": source.get("title", "资料"),
                    "status": source.get("status", "parsed"),
                    "recognitionStatus": source.get("recognition_status", "unverified"),
                }
                for source in sources
                if source
            ],
        }

    def source_revision_signature(self, source_ids: Iterable[str]) -> str:
        ids = sorted(set(source_ids))
        if not ids:
            return "no-source"
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT id, parse_version, content_hash FROM source_documents WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return ";".join(
            f"{row['id']}@{row['parse_version']}:{row['content_hash'][:12]}" for row in rows
        )

    def prompt_for(self, kind: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM prompt_versions
                WHERE artifact_kind = ? AND active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                (kind,),
            ).fetchone()
        if not row:
            raise KeyError("输出类型没有提示词版本")
        return dict(row)

    def create_artifact(
        self,
        *,
        kind: str,
        title: str,
        content: dict[str, Any],
        model: str,
        prompt_version: str,
        generation_instruction: str = "",
        source_ids: list[str],
        unit_ids: list[str],
    ) -> dict[str, Any]:
        if kind not in ARTIFACT_KINDS:
            raise ValueError("作品类型无效")
        artifact_id = make_id("artifact")
        content = normalize_artifact_content(kind, content, artifact_id)
        timestamp = now_iso()
        signature = self.source_revision_signature(source_ids)
        instruction = generation_instruction.strip()
        if len(instruction) > 500:
            raise ValueError("生成要求不能超过500字")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts
                (id, kind, title, content_json, status, model, prompt_version,
                 generation_instruction, source_revision_sig, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    kind,
                    title,
                    json.dumps(content, ensure_ascii=False),
                    model,
                    prompt_version,
                    instruction,
                    signature,
                    timestamp,
                    timestamp,
                ),
            )
            for source_id in source_ids:
                connection.execute(
                    """
                    INSERT INTO lineage_edges
                    (upstream_type, upstream_id, downstream_type, downstream_id,
                     relation, source_id, created_at)
                    VALUES ('source', ?, 'artifact', ?, 'generated_from', ?, ?)
                    """,
                    (source_id, artifact_id, source_id, timestamp),
                )
            for unit_id in unit_ids:
                unit = connection.execute(
                    "SELECT source_id FROM source_units WHERE id = ?", (unit_id,)
                ).fetchone()
                if unit:
                    connection.execute(
                        """
                        INSERT INTO lineage_edges
                        (upstream_type, upstream_id, downstream_type, downstream_id,
                         relation, source_id, unit_id, created_at)
                        VALUES ('unit', ?, 'artifact', ?, 'generated_from', ?, ?, ?)
                        """,
                        (unit_id, artifact_id, unit["source_id"], unit_id, timestamp),
                    )
        return self.get_artifact(artifact_id) or {}

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            return None
        item = self._json_row(row)
        item["sources"] = self.lineage_for("artifact", artifact_id)
        item["source_groups"] = group_lineage_edges(item["sources"])
        return item

    def edit_artifact(
        self,
        artifact_id: str,
        *,
        title: str,
        content: dict[str, Any],
        kind: str | None = None,
        reviewer: str = "本地审核人",
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            current = connection.execute(
                "SELECT kind, publication_state FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if not current:
                raise KeyError("作品不存在")
            next_kind = str(kind or current["kind"])
            if next_kind not in ARTIFACT_KINDS:
                raise ValueError("作品类型无效")
            content = normalize_artifact_content(next_kind, content, artifact_id)
            publication_state = (
                "public_stale"
                if current["publication_state"] in {"public", "public_stale", "replacement_pending"}
                else "private"
            )
            connection.execute(
                """
                UPDATE artifacts
                SET kind = ?, title = ?, content_json = ?, status = 'draft',
                    publication_state = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_kind,
                    title.strip() or "未命名作品",
                    json.dumps(content, ensure_ascii=False),
                    publication_state,
                    timestamp,
                    artifact_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'artifact', ?, 'edit', ?, '编辑后退回草稿并等待审核', ?)
                """,
                (make_id("review"), artifact_id, reviewer, timestamp),
            )
        return self.get_artifact(artifact_id) or {}

    def list_artifacts(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM artifacts {where} ORDER BY updated_at DESC", params
            ).fetchall()
        items = [self._json_row(row) for row in rows]
        for item in items:
            item["sources"] = self.lineage_for("artifact", item["id"])
            item["source_groups"] = group_lineage_edges(item["sources"])
        return items

    def review_artifact(
        self,
        artifact_id: str,
        action: str,
        reviewer: str = "本地审核人",
        note: str = "",
    ) -> dict[str, Any]:
        if action not in {"approve", "reject", "withdraw"}:
            raise ValueError("审核动作无效")
        if action == "approve":
            with self.connect() as connection:
                unreviewed = connection.execute(
                    """
                    SELECT DISTINCT s.title
                    FROM lineage_edges l
                    JOIN source_documents s ON s.id = l.source_id
                    WHERE l.downstream_type = 'artifact'
                      AND l.downstream_id = ?
                      AND (
                          s.status != 'reviewed'
                          OR s.recognition_status NOT IN ('text_ready', 'ocr_ready')
                      )
                    ORDER BY s.title
                    """,
                    (artifact_id,),
                ).fetchall()
            if unreviewed:
                titles = "、".join(str(row["title"]) for row in unreviewed[:3])
                suffix = "等" if len(unreviewed) > 3 else ""
                raise ValueError(f"作品依赖尚未确认的资料：{titles}{suffix}")
        timestamp = now_iso()
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT status, publication_state FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if not exists:
                raise KeyError("作品不存在")
            current_status = "approved" if exists["status"] == "published" else exists["status"]
            status = (
                "approved"
                if action == "approve"
                else (current_status if action == "withdraw" else "rejected")
            )
            if action == "withdraw":
                publication_state = "withdrawn"
            elif action == "approve" and exists["publication_state"] in {
                "public", "public_stale", "replacement_pending"
            }:
                publication_state = "replacement_pending"
            else:
                publication_state = "private"
            connection.execute(
                """
                UPDATE artifacts
                SET status = ?, publication_state = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, publication_state, timestamp, artifact_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'artifact', ?, ?, ?, ?, ?)
                """,
                (make_id("review"), artifact_id, action, reviewer, note, timestamp),
            )
        return {"id": artifact_id, "status": status}

    def mark_artifact_media_changed(
        self,
        artifact_id: str,
        *,
        content: dict[str, Any] | None = None,
        reviewer: str = "百炼媒体生成",
        note: str = "生成媒体已变化，需重新批准后发布",
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            current = connection.execute(
                "SELECT kind, publication_state FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if not current:
                raise KeyError("作品不存在")
            publication_state = (
                "public_stale"
                if current["publication_state"] in {
                    "public",
                    "public_stale",
                    "replacement_pending",
                }
                else "private"
            )
            if content is None:
                connection.execute(
                    """
                    UPDATE artifacts
                    SET status = 'draft', publication_state = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (publication_state, timestamp, artifact_id),
                )
            else:
                normalized = normalize_artifact_content(
                    str(current["kind"]), content, artifact_id
                )
                connection.execute(
                    """
                    UPDATE artifacts
                    SET content_json = ?, status = 'draft', publication_state = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(normalized, ensure_ascii=False),
                        publication_state,
                        timestamp,
                        artifact_id,
                    ),
                )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'artifact', ?, 'media_generate', ?, ?, ?)
                """,
                (make_id("review"), artifact_id, reviewer, note, timestamp),
            )
        return self.get_artifact(artifact_id) or {}

    def delete_artifact(self, artifact_id: str) -> dict[str, Any]:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise KeyError("作品不存在")
        if artifact.get("publication_state") in {
            "public", "public_stale", "replacement_pending"
        }:
            raise ValueError("作品仍在当前公众版本中，请先撤销发布")
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM lineage_edges WHERE downstream_type = 'artifact' AND downstream_id = ?",
                (artifact_id,),
            )
            connection.execute(
                "DELETE FROM review_events WHERE target_type = 'artifact' AND target_id = ?",
                (artifact_id,),
            )
            connection.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        return {"id": artifact_id, "status": "deleted"}

    def bulk_review_candidates(
        self, ids: list[str], action: str, reviewer: str = "本地审核人"
    ) -> list[dict[str, Any]]:
        return [self.review_candidate(item, action, reviewer=reviewer) for item in ids]

    def bulk_review_artifacts(
        self, ids: list[str], action: str, reviewer: str = "本地审核人"
    ) -> list[dict[str, Any]]:
        return [self.review_artifact(item, action, reviewer=reviewer) for item in ids]

    def lineage_for(self, downstream_type: str, downstream_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT l.upstream_type, l.upstream_id, l.relation, l.source_id,
                       l.unit_id, s.title AS source_title, s.status AS source_status,
                       s.recognition_status AS source_recognition_status,
                       u.locator_type, u.locator_value
                FROM lineage_edges l
                LEFT JOIN source_documents s ON s.id = l.source_id
                LEFT JOIN source_units u ON u.id = l.unit_id
                WHERE l.downstream_type = ? AND l.downstream_id = ?
                ORDER BY l.id
                """,
                (downstream_type, downstream_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def invalidate_source(self, source_id: str, reason: str) -> dict[str, int]:
        timestamp = now_iso()
        counts = {"candidates": 0, "knowledge": 0, "artifacts": 0}
        with self.connect() as connection:
            candidate_ids = [
                row["downstream_id"]
                for row in connection.execute(
                    "SELECT DISTINCT downstream_id FROM lineage_edges WHERE source_id = ? AND downstream_type = 'candidate'",
                    (source_id,),
                )
            ]
            knowledge_ids = [
                row["downstream_id"]
                for row in connection.execute(
                    "SELECT DISTINCT downstream_id FROM lineage_edges WHERE source_id = ? AND downstream_type = 'knowledge'",
                    (source_id,),
                )
            ]
            artifact_ids = [
                row["downstream_id"]
                for row in connection.execute(
                    "SELECT DISTINCT downstream_id FROM lineage_edges WHERE source_id = ? AND downstream_type = 'artifact'",
                    (source_id,),
                )
            ]
            for ids, table, key in (
                (candidate_ids, "knowledge_candidates", "candidates"),
                (knowledge_ids, "published_knowledge", "knowledge"),
            ):
                if not ids:
                    continue
                placeholders = ",".join("?" for _ in ids)
                cursor = connection.execute(
                    f"UPDATE {table} SET status = 'stale', updated_at = ? WHERE id IN ({placeholders})",
                    (timestamp, *ids),
                )
                counts[key] = cursor.rowcount
            if artifact_ids:
                placeholders = ",".join("?" for _ in artifact_ids)
                cursor = connection.execute(
                    f"""
                    UPDATE artifacts
                    SET status = 'stale',
                        publication_state = CASE
                            WHEN publication_state IN ('public','public_stale','replacement_pending')
                                THEN 'public_stale'
                            ELSE publication_state
                        END,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (timestamp, *artifact_ids),
                )
                counts["artifacts"] = cursor.rowcount
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'source', ?, 'invalidate', 'system', ?, ?)
                """,
                (make_id("review"), source_id, reason, timestamp),
            )
        return counts

    def delete_source(self, source_id: str) -> dict[str, Any]:
        source = self.get_source(source_id)
        if not source or source["status"] == "deleted":
            raise KeyError("资料不存在")
        invalidated = self.invalidate_source(source_id, "资料已删除")
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE source_documents
                SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ?
                """,
                (timestamp, timestamp, source_id),
            )
        return {"sourceId": source_id, "status": "deleted", "invalidated": invalidated}

    def mark_source_reviewed(self, source_id: str, reviewer: str = "本地审核人") -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            source = connection.execute(
                "SELECT status, recognition_status, source_role FROM source_documents WHERE id = ?",
                (source_id,),
            ).fetchone()
            if not source or source["status"] not in {"parsed", "reviewed"}:
                raise ValueError("资料必须先完成解析")
            if source["source_role"] != "evidence":
                raise ValueError("AI研究笔记不是原始证据，不能标记为资料确认")
            if source["recognition_status"] not in PUBLISH_READY_RECOGNITION:
                raise ValueError("资料必须先完成OCR重建与文本确认")
            connection.execute(
                "UPDATE source_documents SET status = 'reviewed', updated_at = ? WHERE id = ?",
                (timestamp, source_id),
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'source', ?, 'approve', ?, '资料解析结果已人工核对', ?)
                """,
                (make_id("review"), source_id, reviewer, timestamp),
            )
        return {"sourceId": source_id, "status": "reviewed"}

    def unreview_source(self, source_id: str, reviewer: str = "本地审核人") -> dict[str, Any]:
        timestamp = now_iso()
        with self.connect() as connection:
            source = connection.execute(
                "SELECT status, kind, recognition_status FROM source_documents WHERE id = ?",
                (source_id,),
            ).fetchone()
            if not source or source["status"] != "reviewed":
                raise ValueError("只有已确认资料可以取消确认")
            is_ocr_source = (
                source["kind"] == "pdf" and source["recognition_status"] == "ocr_ready"
            )
            next_recognition = "ocr_needs_review" if is_ocr_source else source["recognition_status"]
            connection.execute(
                "UPDATE source_documents SET status = 'parsed', recognition_status = ?, updated_at = ? WHERE id = ?",
                (next_recognition, timestamp, source_id),
            )
            connection.execute(
                "INSERT INTO review_events (id, target_type, target_id, action, reviewer, note, created_at) VALUES (?, 'source', ?, 'unapprove', ?, ?, ?)",
                (
                    make_id("review"),
                    source_id,
                    reviewer,
                    "OCR确认已撤回，返回OCR待确认" if is_ocr_source else "资料确认已撤回",
                    timestamp,
                ),
            )
        self.invalidate_source(source_id, "来源确认已撤回")
        return {
            "sourceId": source_id,
            "status": "parsed",
            "recognitionStatus": next_recognition,
        }

    def update_source(self, source_id: str, title: str, reviewer: str = "本地审核人") -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("资料标题不能为空")
        timestamp = now_iso()
        with self.connect() as connection:
            if not connection.execute("SELECT id FROM source_documents WHERE id = ?", (source_id,)).fetchone():
                raise KeyError("资料不存在")
            connection.execute("UPDATE source_documents SET title = ?, updated_at = ? WHERE id = ?", (title, timestamp, source_id))
            connection.execute("INSERT INTO review_events (id, target_type, target_id, action, reviewer, note, created_at) VALUES (?, 'source', ?, 'edit', ?, '修改资料标题', ?)", (make_id("review"), source_id, reviewer, timestamp))
        return self.get_source(source_id) or {}

    def record_snapshot(
        self,
        snapshot_id: str,
        snapshot_hash: str,
        path: str,
        counts: dict[str, int],
        *,
        title: str = "",
        description: str = "",
        created_by: str = "",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO publish_snapshots
                (id, snapshot_hash, path, item_counts_json, title, description, created_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?)
                """,
                (
                    snapshot_id,
                    snapshot_hash,
                    path,
                    json.dumps(counts),
                    title,
                    description,
                    created_by,
                    now_iso(),
                ),
            )

    def mark_approved_artifacts_published(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE artifacts
                SET status = 'approved', publication_state = 'public', updated_at = ?
                WHERE status IN ('approved','published') AND publication_state != 'withdrawn'
                """,
                (now_iso(),),
            )

    def list_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM publish_snapshots ORDER BY created_at DESC"
            ).fetchall()
        items = [self._json_row(row) for row in rows]
        for item in items:
            stored_path = str(item.get("path", "")).replace("\\", "/")
            archive = ROOT / stored_path
            item["restorable"] = (
                "release-history" in archive.parts and archive.exists()
            )
        return items

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM publish_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return self._json_row(row) if row else None

    def delete_snapshot(self, snapshot_id: str, reviewer: str = "本地审核人") -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM publish_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if not row:
                raise KeyError("发布版本不存在")
            connection.execute(
                "DELETE FROM publish_snapshots WHERE id = ?", (snapshot_id,)
            )
            connection.execute(
                """
                INSERT INTO review_events
                (id, target_type, target_id, action, reviewer, note, created_at)
                VALUES (?, 'snapshot', ?, 'delete', ?, '删除历史版本归档', ?)
                """,
                (make_id("review"), snapshot_id, reviewer, timestamp),
            )

    def set_public_artifacts(self, artifact_ids: list[str]) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE artifacts SET publication_state = 'private', updated_at = ? WHERE publication_state IN ('public','public_stale','replacement_pending')",
                (timestamp,),
            )
            if artifact_ids:
                placeholders = ",".join("?" for _ in artifact_ids)
                connection.execute(
                    f"""
                    UPDATE artifacts
                    SET status = CASE WHEN status = 'published' THEN 'approved' ELSE status END,
                        publication_state = 'public', updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (timestamp, *artifact_ids),
                )

    def _site_content_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._json_row(row)
        default = site_section_default(str(item["content_key"])) or {}
        item["section_type"] = str(item.get("section_type") or default.get("section_type") or "standard")
        item["nav_label"] = str(item.get("nav_label") or default.get("nav_label") or item.get("title") or "栏目")
        item["kicker"] = str(item.get("kicker") or default.get("kicker") or "")
        item["summary"] = str(item.get("summary") or default.get("summary") or "")
        item["body_html"] = str(item.get("body_html") or default.get("body_html") or "")
        item["enabled"] = bool(item.get("enabled", 1))
        item["sort_order"] = int(item["sort_order"] if item.get("sort_order") is not None else default.get("sort_order") or 0)
        item["has_published_content"] = bool(item.get("published_content"))
        item.pop("published_content", None)
        return item

    def _virtual_site_content(self, content_key: str) -> dict[str, Any] | None:
        default = site_section_default(content_key)
        if not default:
            return None
        timestamp = "2026-07-24T00:00:00+00:00"
        return {
            "id": f"site-{content_key}",
            **default,
            "status": "approved",
            "publication_state": "public",
            "model": "manual",
            "prompt_version": "site-content:seed-v2",
            "generation_instruction": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "approved_at": timestamp,
            "published_at": timestamp,
            "has_published_content": True,
            "virtual": True,
        }

    def list_site_content(self, *, include_system: bool = False) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM site_content_entries ORDER BY sort_order, created_at, content_key"
            ).fetchall()
        all_items = [self._site_content_row(row) for row in rows]
        items = [item for item in all_items if item.get("generation_instruction") != "__deleted__"]
        if include_system:
            existing = {str(item["content_key"]) for item in all_items}
            for content_key in SITE_SYSTEM_DEFAULTS:
                if content_key not in existing:
                    virtual = self._virtual_site_content(content_key)
                    if virtual:
                        items.append(virtual)
        return sorted(items, key=lambda item: (int(item.get("sort_order") or 0), str(item.get("created_at") or "")))

    def get_site_content(self, content_key: str, *, include_virtual: bool = True) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM site_content_entries WHERE content_key = ?",
                (content_key,),
            ).fetchone()
        if row:
            return self._site_content_row(row)
        return self._virtual_site_content(content_key) if include_virtual else None

    def _materialize_site_content(self, content_key: str) -> dict[str, Any]:
        existing = self.get_site_content(content_key, include_virtual=False)
        if existing:
            return existing
        virtual = self._virtual_site_content(content_key)
        if not virtual:
            raise KeyError("站点栏目不存在")
        timestamp = now_iso()
        payload = {
            "content": virtual["content"],
            "meta": {
                key: virtual[key]
                for key in ("title", "section_type", "nav_label", "kicker", "summary", "body_html", "enabled", "sort_order")
            },
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO site_content_entries
                (id, content_key, title, section_type, nav_label, kicker, summary,
                 body_html, enabled, sort_order, content_json, published_content_json,
                 status, publication_state, model, prompt_version,
                 generation_instruction, created_at, updated_at, approved_at, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', 'public',
                        'manual', 'site-content:seed-v2', '', ?, ?, ?, ?)
                """,
                (
                    virtual["id"], content_key, virtual["title"], virtual["section_type"],
                    virtual["nav_label"], virtual["kicker"], virtual["summary"],
                    virtual["body_html"], 1 if virtual["enabled"] else 0,
                    virtual["sort_order"], json.dumps(virtual["content"], ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False), timestamp, timestamp, timestamp, timestamp,
                ),
            )
        return self.get_site_content(content_key, include_virtual=False) or {}

    def create_site_content(
        self,
        *,
        title: str,
        nav_label: str = "",
        section_type: str = "standard",
        kicker: str = "",
        summary: str = "",
        body_html: str = "<p>在这里编辑栏目正文。</p>",
        enabled: bool = True,
        reviewer: str = "本地编辑人",
    ) -> dict[str, Any]:
        cleaned_title = _site_text(title, 120)
        if not cleaned_title:
            raise ValueError("请输入栏目标题")
        kind = section_type if section_type in {"standard", "data"} else "standard"
        base = re.sub(r"[^a-z0-9-]", "-", str(nav_label or "section").strip().lower()).strip("-") or "section"
        with self.connect() as connection:
            existing_keys = {
                str(row[0]) for row in connection.execute("SELECT content_key FROM site_content_entries").fetchall()
            } | set(SITE_CONTENT_DEFAULTS) | set(SITE_SYSTEM_DEFAULTS)
            content_key = base[:48]
            index = 2
            while content_key in existing_keys:
                suffix = f"-{index}"
                content_key = f"{base[:48-len(suffix)]}{suffix}"
                index += 1
            order = connection.execute(
                "SELECT CASE WHEN COALESCE(MAX(sort_order), 0) < 6 THEN 7 ELSE MAX(sort_order) + 1 END FROM site_content_entries"
            ).fetchone()[0]
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO site_content_entries
                (id, content_key, title, section_type, nav_label, kicker, summary,
                 body_html, enabled, sort_order, content_json, published_content_json,
                 status, publication_state, model, prompt_version,
                 generation_instruction, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', NULL,
                        'draft', 'private', 'manual', 'manual:v1', '', ?, ?)
                """,
                (
                    make_id("site"), content_key, cleaned_title, kind,
                    _site_text(nav_label, 30, cleaned_title), _site_text(kicker, 80),
                    _site_text(summary, 800), validate_site_shortcodes(body_html),
                    1 if enabled else 0, int(order), timestamp, timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO site_content_review_events VALUES (?, ?, 'create', ?, ?, ?)",
                (make_id("site-review"), content_key, reviewer, "新增公众站栏目", timestamp),
            )
        return self.get_site_content(content_key, include_virtual=False) or {}

    def save_site_content(
        self,
        content_key: str,
        content: dict[str, Any],
        *,
        model: str = "manual",
        prompt_version: str = "manual:v1",
        generation_instruction: str = "",
        reviewer: str = "本地编辑人",
        title: str | None = None,
        section_type: str | None = None,
        nav_label: str | None = None,
        kicker: str | None = None,
        summary: str | None = None,
        body_html: str | None = None,
        enabled: bool | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        self._materialize_site_content(content_key)
        normalized = normalize_site_content(content_key, content)
        timestamp = now_iso()
        instruction = _site_text(generation_instruction, 1800)
        with self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM site_content_entries WHERE content_key = ?",
                (content_key,),
            ).fetchone()
            if not current:
                raise KeyError("站点内容不存在")
            publication_state = "outdated" if current["published_content_json"] else "private"
            published_raw = current["published_content_json"]
            if published_raw:
                published_value = json.loads(published_raw)
                if not (isinstance(published_value, dict) and isinstance(published_value.get("meta"), dict)):
                    published_raw = json.dumps(
                        {
                            "content": published_value,
                            "meta": {
                                key: current[key]
                                for key in ("title", "section_type", "nav_label", "kicker", "summary", "body_html", "enabled", "sort_order")
                            },
                        },
                        ensure_ascii=False,
                    )
            next_type = section_type if section_type in {"hero", "standard", "data"} else current["section_type"]
            next_body = validate_site_shortcodes(body_html if body_html is not None else current["body_html"])
            connection.execute(
                """
                UPDATE site_content_entries
                SET title = ?, section_type = ?, nav_label = ?, kicker = ?, summary = ?,
                    body_html = ?, enabled = ?, sort_order = ?, content_json = ?,
                    published_content_json = ?, status = 'draft', publication_state = ?,
                    model = ?, prompt_version = ?, generation_instruction = ?,
                    updated_at = ?, approved_at = NULL
                WHERE content_key = ?
                """,
                (
                    _site_text(title if title is not None else current["title"], 120, "未命名栏目"),
                    next_type,
                    _site_text(nav_label if nav_label is not None else current["nav_label"], 30, "栏目"),
                    _site_text(kicker if kicker is not None else current["kicker"], 80),
                    _site_text(summary if summary is not None else current["summary"], 800),
                    next_body,
                    1 if (bool(enabled) if enabled is not None else bool(current["enabled"])) else 0,
                    max(0, min(999, int(sort_order if sort_order is not None else current["sort_order"] or 0))),
                    json.dumps(normalized, ensure_ascii=False),
                    published_raw,
                    publication_state,
                    _site_text(model, 120, "manual"),
                    _site_text(prompt_version, 120, "manual:v1"),
                    instruction,
                    timestamp,
                    content_key,
                ),
            )
            connection.execute(
                "INSERT INTO site_content_review_events VALUES (?, ?, 'edit', ?, ?, ?)",
                (
                    make_id("site-review"),
                    content_key,
                    reviewer,
                    "AI生成站点内容草稿" if model != "manual" else "手动编辑站点内容草稿",
                    timestamp,
                ),
            )
        return self.get_site_content(content_key) or {}

    def reorder_site_content(self, content_keys: list[str], *, reviewer: str = "本地编辑人") -> list[dict[str, Any]]:
        clean_keys = [str(item) for item in content_keys]
        available = {item["content_key"] for item in self.list_site_content(include_system=True)}
        if set(clean_keys) != available or len(clean_keys) != len(available):
            raise ValueError("栏目排序清单与当前栏目不一致")
        for content_key in clean_keys:
            self._materialize_site_content(content_key)
        timestamp = now_iso()
        with self.connect() as connection:
            for order, content_key in enumerate(clean_keys):
                current = connection.execute(
                    "SELECT sort_order, published_content_json FROM site_content_entries WHERE content_key = ?", (content_key,)
                ).fetchone()
                if current and int(current["sort_order"] or 0) == order:
                    continue
                connection.execute(
                    """
                    UPDATE site_content_entries
                    SET sort_order = ?, status = 'draft', publication_state = ?,
                        updated_at = ?, approved_at = NULL
                    WHERE content_key = ?
                    """,
                    (order, "outdated" if current and current["published_content_json"] else "private", timestamp, content_key),
                )
            connection.execute(
                "INSERT INTO site_content_review_events VALUES (?, '*', 'reorder', ?, ?, ?)",
                (make_id("site-review"), reviewer, "调整公众站栏目顺序", timestamp),
            )
        return self.list_site_content(include_system=True)

    def delete_site_content(self, content_key: str, *, reviewer: str = "本地编辑人") -> None:
        if content_key == "hero":
            raise ValueError("Banner 不能删除，可改为隐藏")
        self._materialize_site_content(content_key)
        timestamp = now_iso()
        with self.connect() as connection:
            if content_key in SITE_SYSTEM_DEFAULTS:
                connection.execute(
                    """
                    UPDATE site_content_entries
                    SET enabled = 0, status = 'draft', publication_state = 'outdated',
                        generation_instruction = '__deleted__', updated_at = ?, approved_at = NULL
                    WHERE content_key = ?
                    """,
                    (timestamp, content_key),
                )
            else:
                connection.execute("DELETE FROM site_content_entries WHERE content_key = ?", (content_key,))
            connection.execute(
                "INSERT INTO site_content_review_events VALUES (?, ?, 'delete', ?, ?, ?)",
                (make_id("site-review"), content_key, reviewer, "删除公众站栏目，当前发布版本保持不变", timestamp),
            )

    def review_site_content(
        self,
        content_key: str,
        action: str,
        *,
        reviewer: str = "本地审核人",
        note: str = "",
    ) -> dict[str, Any]:
        if action not in {"approve", "unapprove"}:
            raise ValueError("站点内容审核动作无效")
        self._materialize_site_content(content_key)
        timestamp = now_iso()
        with self.connect() as connection:
            current = connection.execute(
                "SELECT id FROM site_content_entries WHERE content_key = ?",
                (content_key,),
            ).fetchone()
            if not current:
                raise KeyError("站点内容不存在")
            connection.execute(
                """
                UPDATE site_content_entries
                SET status = ?, approved_at = ?, updated_at = ?
                WHERE content_key = ?
                """,
                (
                    "approved" if action == "approve" else "draft",
                    timestamp if action == "approve" else None,
                    timestamp,
                    content_key,
                ),
            )
            connection.execute(
                "INSERT INTO site_content_review_events VALUES (?, ?, ?, ?, ?, ?)",
                (
                    make_id("site-review"), content_key, action, reviewer,
                    _site_text(note, 500, "批准公开内容" if action == "approve" else "取消批准"),
                    timestamp,
                ),
            )
        return self.get_site_content(content_key) or {}

    def list_site_content_reviews(self, content_key: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM site_content_review_events WHERE content_key = ? ORDER BY created_at DESC",
                (content_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def store_site_asset(
        self, filename: str, mime_type: str, content: bytes
    ) -> dict[str, Any]:
        if not content or len(content) > MAX_SITE_ASSET_BYTES:
            raise ValueError("站点媒体为空或超过24MB")
        mime = str(mime_type or "").lower().split(";", 1)[0].strip()
        formats = {
            "image/png": ("image", ".png"),
            "image/jpeg": ("image", ".jpg"),
            "image/webp": ("image", ".webp"),
            "video/mp4": ("video", ".mp4"),
            "video/webm": ("video", ".webm"),
        }
        if mime not in formats:
            raise ValueError("仅支持PNG、JPEG、WebP、MP4或WebM")
        media_type, suffix = formats[mime]
        valid_signature = (
            (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
            or (mime == "image/jpeg" and content.startswith(b"\xff\xd8"))
            or (mime == "image/webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP")
            or (mime == "video/mp4" and len(content) > 12 and content[4:8] == b"ftyp")
            or (mime == "video/webm" and content.startswith(b"\x1aE\xdf\xa3"))
        )
        if not valid_signature:
            raise ValueError("站点媒体文件格式与声明类型不一致")
        digest = sha256_bytes(content)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM site_assets WHERE content_hash = ?", (digest,)
            ).fetchone()
            if existing:
                return dict(existing)
        asset_id = make_id("siteasset")
        asset_dir = self.private_dir / "site-assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        path = asset_dir / f"{asset_id}{suffix}"
        path.write_bytes(content)
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO site_assets
                (id, filename, media_type, mime_type, private_path, content_hash, byte_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id, clean_filename(filename, suffix), media_type, mime,
                    self._stored_path(path), digest, len(content), timestamp,
                ),
            )
        return self.get_site_asset(asset_id) or {}

    def get_site_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM site_assets WHERE id = ?", (asset_id,)
            ).fetchone()
        return dict(row) if row else None

    def site_asset_file(self, asset_id: str) -> tuple[Path, dict[str, Any]]:
        asset = self.get_site_asset(asset_id)
        if not asset:
            raise KeyError("站点媒体不存在")
        path = self._resolved_private_path(str(asset["private_path"])).resolve()
        private_root = self.private_dir.resolve()
        if private_root not in path.parents or not path.exists():
            raise KeyError("站点媒体文件不存在")
        return path, asset

    def _public_site_entry(self, item: dict[str, Any], raw: Any) -> dict[str, Any] | None:
        value = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(value, dict) and isinstance(value.get("meta"), dict) and isinstance(value.get("content"), dict):
            content_value = value["content"]
            meta = value["meta"]
        else:
            content_value = value if isinstance(value, dict) else {}
            meta = item
        if not bool(meta.get("enabled", item.get("enabled", True))):
            return None
        content_key = str(item["content_key"])
        content = normalize_site_content(content_key, content_value)
        if content_key == "hero":
            for slide in content.get("slides", []):
                if slide.get("assetId"):
                    slide["mediaUrl"] = f"/api/public/site-media/{slide['assetId']}"
                if slide.get("posterAssetId"):
                    slide["posterUrl"] = f"/api/public/site-media/{slide['posterAssetId']}"
        elif content_key == "history" and content.get("image", {}).get("assetId"):
            content["image"]["url"] = f"/api/public/site-media/{content['image']['assetId']}"
        body_html = str(meta.get("body_html") or "")
        body_html = re.sub(
            r"/api/research/site-content/assets/(siteasset-[0-9a-f]{12})",
            r"/api/public/site-media/\1",
            body_html,
        )
        return {
            "title": _site_text(meta.get("title"), 120, str(item.get("title") or "栏目")),
            "sectionType": str(meta.get("section_type") or item.get("section_type") or "standard"),
            "navLabel": _site_text(meta.get("nav_label"), 30, str(item.get("nav_label") or "栏目")),
            "kicker": _site_text(meta.get("kicker"), 80),
            "summary": _site_text(meta.get("summary"), 800),
            "bodyHtml": validate_site_shortcodes(body_html),
            "enabled": True,
            "sortOrder": int(meta["sort_order"] if meta.get("sort_order") is not None else item.get("sort_order") or 0),
            "content": content,
            "updatedAt": item.get("updated_at") if item.get("status") == "approved" else item.get("published_at"),
        }

    def public_site_content(self, *, include_system: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        items = self.list_site_content(include_system=include_system)
        for item in items:
            if item.get("virtual"):
                raw = item.get("content")
            else:
                with self.connect() as connection:
                    row = connection.execute(
                        "SELECT content_json, published_content_json FROM site_content_entries WHERE content_key = ?",
                        (item["content_key"],),
                    ).fetchone()
                raw = row["content_json"] if row and item["status"] == "approved" else (row["published_content_json"] if row else None)
            if raw is None or raw == "":
                continue
            public_entry = self._public_site_entry(item, raw)
            if public_entry:
                result[str(item["content_key"])] = public_entry
        return result

    def set_published_site_content(self, site_content: dict[str, Any]) -> None:
        timestamp = now_iso()
        keys = set(site_content)
        for content_key in keys:
            if not self.get_site_content(content_key, include_virtual=False):
                if site_section_default(content_key):
                    self._materialize_site_content(content_key)
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM site_content_entries").fetchall()
            for row in rows:
                content_key = str(row["content_key"])
                entry = site_content.get(content_key)
                if not isinstance(entry, dict) or not isinstance(entry.get("content"), dict):
                    connection.execute(
                        """
                        UPDATE site_content_entries
                        SET published_content_json = NULL, publication_state = 'private', published_at = ?
                        WHERE content_key = ?
                        """,
                        (timestamp, content_key),
                    )
                    continue
                normalized = normalize_site_content(content_key, entry["content"])
                meta = {
                    "title": entry.get("title") or row["title"],
                    "section_type": entry.get("sectionType") or row["section_type"],
                    "nav_label": entry.get("navLabel") or row["nav_label"],
                    "kicker": entry.get("kicker") or "",
                    "summary": entry.get("summary") or "",
                    "body_html": entry.get("bodyHtml") or "",
                    "enabled": bool(entry.get("enabled", True)),
                    "sort_order": int(entry.get("sortOrder") or 0),
                }
                encoded = json.dumps({"content": normalized, "meta": meta}, ensure_ascii=False)
                current_entry = self._site_content_row(row)
                current_public = self._public_site_entry(current_entry, row["content_json"])
                comparable = dict(entry)
                comparable.pop("updatedAt", None)
                current_comparable = dict(current_public or {})
                current_comparable.pop("updatedAt", None)
                state = "public" if row["status"] == "approved" and current_comparable == comparable else "outdated"
                connection.execute(
                    """
                    UPDATE site_content_entries
                    SET published_content_json = ?, publication_state = ?, published_at = ?
                    WHERE content_key = ?
                    """,
                    (encoded, state, timestamp, content_key),
                )

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as connection:
            counts = {
                "sources": connection.execute("SELECT COUNT(*) FROM source_documents WHERE status != 'deleted'").fetchone()[0],
                "evidenceSources": connection.execute("SELECT COUNT(*) FROM source_documents WHERE status != 'deleted' AND source_role = 'evidence'").fetchone()[0],
                "researchNotes": connection.execute("SELECT COUNT(*) FROM source_documents WHERE status != 'deleted' AND source_role = 'generated_note'").fetchone()[0],
                "reviewedSources": connection.execute(
                    "SELECT COUNT(*) FROM source_documents WHERE source_role = 'evidence' AND status = 'reviewed' AND recognition_status IN ('text_ready','ocr_ready')"
                ).fetchone()[0],
                "ocrPending": connection.execute(
                    "SELECT COUNT(*) FROM source_documents WHERE status != 'deleted' AND recognition_status IN ('unverified','ocr_pending','ocr_failed')"
                ).fetchone()[0],
                "ocrProcessing": connection.execute(
                    "SELECT COUNT(*) FROM source_documents WHERE recognition_status = 'ocr_processing'"
                ).fetchone()[0],
                "ocrNeedsReview": connection.execute(
                    "SELECT COUNT(*) FROM source_documents WHERE recognition_status = 'ocr_needs_review'"
                ).fetchone()[0],
                "candidates": connection.execute("SELECT COUNT(*) FROM knowledge_candidates WHERE status = 'candidate'").fetchone()[0],
                "approvedKnowledge": connection.execute("SELECT COUNT(*) FROM published_knowledge WHERE status = 'approved'").fetchone()[0],
                "draftArtifacts": connection.execute("SELECT COUNT(*) FROM artifacts WHERE status = 'draft'").fetchone()[0],
                "approvedArtifacts": connection.execute("SELECT COUNT(*) FROM artifacts WHERE status = 'approved'").fetchone()[0],
                "publishedArtifacts": connection.execute("SELECT COUNT(*) FROM artifacts WHERE publication_state IN ('public','public_stale','replacement_pending')").fetchone()[0],
                "staleItems": connection.execute("SELECT COUNT(*) FROM artifacts WHERE status = 'stale'").fetchone()[0],
                "draftSiteContent": connection.execute("SELECT COUNT(*) FROM site_content_entries WHERE status = 'draft'").fetchone()[0],
                "approvedSiteContent": connection.execute("SELECT COUNT(*) FROM site_content_entries WHERE status = 'approved'").fetchone()[0],
            }
            latest = connection.execute(
                "SELECT * FROM publish_snapshots WHERE status = 'published' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return {
            "counts": counts,
            "latestSnapshot": self._json_row(latest) if latest else None,
            "sources": self.list_sources()[:8],
            "ocrRuns": self.list_ocr_runs()[:8],
            "artifacts": self.list_artifacts()[:8],
        }
