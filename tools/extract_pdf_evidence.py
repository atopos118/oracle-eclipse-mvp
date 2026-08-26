from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = ROOT / "source-materials"
PDF_DIR = PRIVATE_ROOT / "pdfs"
EXTRACTED_DIR = PRIVATE_ROOT / "extracted"
PLAN_PATH = PRIVATE_ROOT / "core-source-plan.json"
MANIFEST_PATH = PRIVATE_ROOT / "manifest.json"
EVIDENCE_PATH = PRIVATE_ROOT / "evidence-index.json"
KEYWORDS = [
    "日食",
    "乙巳",
    "癸酉",
    "祖庚",
    "日有食",
    "日又戠",
    "日夕",
    "甲骨文合集",
    "合集",
    "著录",
]


def normalize(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_hits(text: str, page_number: int) -> list[dict[str, Any]]:
    compact = re.sub(r"\s+", " ", text)
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for keyword in KEYWORDS:
        for match in re.finditer(re.escape(keyword), compact, flags=re.IGNORECASE):
            start = max(0, match.start() - 100)
            end = min(len(compact), match.end() + 140)
            excerpt = compact[start:end].strip()
            key = (keyword, excerpt)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {
                    "keyword": keyword,
                    "pdfPage": page_number,
                    "excerpt": excerpt,
                    "reviewStatus": "待人工对照页面图像",
                }
            )
            if len(hits) >= 12:
                return hits
    return hits


def find_pdf(source: dict[str, Any]) -> Path | None:
    expected = source.get("localFile")
    if expected and (PDF_DIR / expected).exists():
        return PDF_DIR / expected
    source_id = str(source["id"])
    candidates = sorted(PDF_DIR.glob(f"{source_id}_*.pdf"))
    if candidates:
        return candidates[0]
    site_name = source.get("expectedSiteFileName")
    if site_name and (PDF_DIR / site_name).exists():
        return PDF_DIR / site_name
    return None


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for source in plan["sources"]:
        pdf_path = find_pdf(source)
        if pdf_path is None:
            manifest.append(
                {
                    "sourceId": source["id"],
                    "title": source["title"],
                    "status": "missing",
                    "expectedLocalFile": source["localFile"],
                }
            )
            continue

        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        source_hits: list[dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = normalize(page.extract_text() or "")
            pages.append(f"--- PDF PAGE {page_number} ---\n{text}")
            source_hits.extend(page_hits(text, page_number))

        output_path = EXTRACTED_DIR / f"{source['id']}.txt"
        output_path.write_text("\n\n".join(pages) + "\n", encoding="utf-8")
        manifest.append(
            {
                "sourceId": source["id"],
                "title": source["title"],
                "status": "extracted",
                "localFile": pdf_path.name,
                "sha256": sha256(pdf_path),
                "pdfPages": len(reader.pages),
                "extractedCharacters": sum(len(page) for page in pages),
                "extractedFile": output_path.name,
            }
        )
        evidence.append(
            {
                "sourceId": source["id"],
                "title": source["title"],
                "sourceUrl": source["sourceUrl"],
                "focus": source["focus"],
                "hits": source_hits,
            }
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    MANIFEST_PATH.write_text(
        json.dumps(
            {"generatedAt": generated_at, "files": manifest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    EVIDENCE_PATH.write_text(
        json.dumps(
            {
                "generatedAt": generated_at,
                "notice": "自动摘录仅用于定位，正式入库前必须对照PDF页面图像复核。",
                "sources": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    extracted_count = sum(item["status"] == "extracted" for item in manifest)
    print(f"extracted {extracted_count}/{len(manifest)} core sources")


if __name__ == "__main__":
    main()
