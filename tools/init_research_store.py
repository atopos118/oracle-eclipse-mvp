from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_store import DB_PATH, ResearchStore  # noqa: E402
from snapshot_manager import publish_snapshot  # noqa: E402


def load_data(name: str) -> dict:
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def unit_for_page(store: ResearchStore, source_id: str, page: int | None) -> str | None:
    if page is None:
        return None
    for unit in store.list_units(source_id):
        if unit["locator_type"] == "pdf_page" and unit["locator_value"] == str(page):
            return unit["id"]
    return None


def main() -> None:
    store = ResearchStore()
    store.initialize()
    literature = load_data("literature.json")
    source_meta = next(item for item in literature["items"] if str(item["id"]) == "52172")
    source = store.register_existing_pdf(
        ROOT / "source-materials" / "pdfs" / "52172_韩宇娇_祖庚时期日食.pdf",
        title=source_meta["title"],
        external_id="52172",
        source_url=source_meta["sourceUrl"],
    )
    source_id = source["id"]
    current = store.get_source(source_id)
    if current and current["status"] not in {"parsed", "reviewed"}:
        store.parse_source(source_id)
    if (store.get_source(source_id) or {}).get("status") != "reviewed":
        store.mark_source_reviewed(source_id, "MVP 0.3人工页码核验")

    records_meta = load_data("eclipse-records.json")
    for record in records_meta["records"]:
        if not record.get("reviewed"):
            continue
        links = [
            (source_id, unit_for_page(store, source_id, evidence.get("pdfPage")))
            for evidence in record.get("sourceEvidence", [])
            if str(evidence.get("sourceId")) == "52172"
        ]
        store.add_published_knowledge(
            record["id"],
            "record",
            record["headline"],
            record,
            links or [(source_id, None)],
        )

    for topic in records_meta.get("topicEvidence", []):
        links = [
            (source_id, unit_for_page(store, source_id, page))
            for page in topic.get("pdfPages", [])
        ]
        store.add_published_knowledge(
            topic["id"],
            "topic",
            topic["topic"],
            topic,
            links or [(source_id, None)],
        )

    result = publish_snapshot(store)
    print(
        json.dumps(
            {
                "database": str(DB_PATH),
                "sourceId": source_id,
                "dashboard": store.dashboard()["counts"],
                "snapshot": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
