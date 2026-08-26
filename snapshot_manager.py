from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bailian_adapter import BailianAdapter, clean_public_explainer
from media_exports import visual_card_background_exists
from research_store import ResearchStore, compact_locator_values, group_lineage_edges


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SNAPSHOT_PATH = DATA_DIR / "published-snapshot.json"
RELEASE_DIR = DATA_DIR / "release-history"
PUBLISH_READY_RECOGNITION = {"text_ready", "ocr_ready"}
MAX_RELEASE_TITLE_LENGTH = 80
MAX_RELEASE_DESCRIPTION_LENGTH = 500


def load_json(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def release_metadata(
    title: str = "", description: str = "", created_by: str = ""
) -> dict[str, str]:
    cleaned_title = str(title or "").strip()
    cleaned_description = str(description or "").strip()
    cleaned_creator = str(created_by or "").strip()
    if len(cleaned_title) > MAX_RELEASE_TITLE_LENGTH:
        raise ValueError(f"版本名称不能超过{MAX_RELEASE_TITLE_LENGTH}字")
    if len(cleaned_description) > MAX_RELEASE_DESCRIPTION_LENGTH:
        raise ValueError(f"版本说明不能超过{MAX_RELEASE_DESCRIPTION_LENGTH}字")
    return {
        "title": cleaned_title or "公众内容更新",
        "description": cleaned_description,
        "createdBy": cleaned_creator or "本地审核人",
    }


def current_snapshot_id(path: Path = SNAPSHOT_PATH) -> str:
    if not path.exists():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("snapshotId") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def snapshot_archive_path(
    release: dict[str, Any], path: Path = SNAPSHOT_PATH
) -> Path:
    # Snapshot metadata can move between Windows and Linux with the SQLite DB.
    # Normalize legacy Windows separators before applying the strict path checks.
    stored_path = str(release.get("path", "")).replace("\\", "/")
    archive = (ROOT / stored_path).resolve()
    release_dir = (
        RELEASE_DIR
        if path.resolve() == SNAPSHOT_PATH.resolve()
        else path.parent / "release-history"
    ).resolve()
    if archive.parent != release_dir or archive.suffix.lower() != ".json":
        raise ValueError("发布版本归档路径无效")
    if archive.stem != str(release.get("id", "")):
        raise ValueError("发布版本归档与版本编号不一致")
    return archive


def public_artifact(item: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for group in item.get("source_groups") or group_lineage_edges(item.get("sources", [])):
        locator_types = group.get("locator_types") or [group.get("locator_type")]
        pages = group.get("pdf_page_values", []) if "pdf_page" in locator_types else []
        sources.append(
            {
                "sourceId": group.get("source_id"),
                "title": group.get("source_title") or "来源资料",
                "pdfPages": pages,
                "pdfPageLabel": compact_locator_values(pages),
            }
        )

    content = json.loads(json.dumps(item["content"], ensure_ascii=False))
    if item.get("kind") == "public_explainer" and isinstance(content, dict):
        content["text"] = clean_public_explainer(str(content.get("text") or ""))

    public_item = {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "content": content,
        "model": item["model"],
        "promptVersion": item["prompt_version"],
        "updatedAt": item["updated_at"],
        "provenance": {
            "sourceCount": len(sources),
            "sources": sources,
        },
    }
    if item.get("kind") == "audio_guide":
        adapter = BailianAdapter()
        public_item["media"] = {
            "format": "wav",
            "url": f"/api/public/artifacts/{item['id']}/audio",
            "provider": "aliyun-bailian",
            "model": adapter.tts_model,
            "voice": adapter.tts_voice,
        }
    if item.get("kind") == "visual_card_set":
        adapter = BailianAdapter()
        cards = content.get("cards") if isinstance(content.get("cards"), list) else []
        public_item["media"] = {
            "format": "png-set",
            "provider": "aliyun-bailian+local-layout",
            "model": adapter.image_model,
            "visualBackgrounds": [
                visual_card_background_exists(item, index)
                for index in range(len(cards))
            ],
        }
    return public_item


def mark_reviewed_literature(
    literature: dict[str, Any], sources: list[dict[str, Any]]
) -> None:
    reviewed = [
        source
        for source in sources
        if source["status"] == "reviewed"
        and source.get("recognition_status") in PUBLISH_READY_RECOGNITION
    ]
    matched_source_ids: set[str] = set()
    for item in literature.get("items", []):
        item_id = str(item.get("id", ""))
        item_title = str(item.get("title", "")).strip()
        item_url = str(item.get("sourceUrl", "")).strip()
        match = next(
            (
                source
                for source in reviewed
                if str(source["id"]) not in matched_source_ids
                if (source.get("external_id") and str(source["external_id"]) == item_id)
                or (source.get("source_url") and str(source["source_url"]).strip() == item_url)
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    source
                    for source in reviewed
                    if str(source["id"]) not in matched_source_ids
                    and str(source.get("title", "")).strip() == item_title
                ),
                None,
            )
        item["researchStatus"] = "reviewed" if match else "lead"
        if match:
            matched_source_ids.add(str(match["id"]))
            if match.get("page_count"):
                item["reviewedPageCount"] = match["page_count"]
    literature["reviewedCount"] = len(reviewed)
    literature["coreTarget"] = 7


def public_literature_item(item: dict[str, Any]) -> dict[str, Any]:
    source_id = str(item.get("id", ""))
    return {
        "id": source_id,
        "title": item.get("title", "未命名来源"),
        "authors": item.get("authors", []),
        "publication": item.get("publication", "来源不详"),
        "publishedAt": item.get("publishedAt", "日期不详"),
        "access": item.get("access", "已进入私有研究库，原始文件不公开"),
        "researchStatus": item.get("researchStatus", "reviewed"),
        "reviewedPageCount": item.get("reviewedPageCount"),
        "detailUrl": f"/source.html?id={source_id}",
    }


def records_from_published_tables(
    artifacts: list[dict[str, Any]], literature_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    literature_by_title = {
        str(item.get("title", "")).strip(): str(item.get("id", ""))
        for item in literature_items
        if item.get("title") and item.get("id")
    }
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        if artifact.get("kind") != "record_table":
            continue
        source_ids = [
            literature_by_title[title]
            for source in artifact.get("provenance", {}).get("sources", [])
            if (title := str(source.get("title", "")).strip()) in literature_by_title
        ]
        for index, row in enumerate(artifact.get("content", {}).get("rows", [])):
            inscription = str(row.get("卜辞", "")).strip()
            catalog_number = str(row.get("著录", "")).strip()
            if not inscription or (inscription, catalog_number) in seen:
                continue
            seen.add((inscription, catalog_number))
            status = str(row.get("状态") or "研究线索")
            disputes = [
                part.strip()
                for part in str(row.get("争议", "")).replace("\n", "；").split("；")
                if part.strip()
            ]
            records.append(
                {
                    "id": f"{artifact['id']}-row-{index + 1}",
                    "headline": catalog_number or "已发布记录表条目",
                    "inscription": inscription,
                    "status": status,
                    "reviewed": not any(token in status for token in ("待核", "尚未", "未确认")),
                    "translation": str(row.get("释义") or "当前已公开卜辞、著录、年代与争议；基本释义尚待古文字学复核后补充。"),
                    "dating": str(row.get("年代") or "尚不清楚"),
                    "catalogNumber": catalog_number or "尚待核对",
                    "scholarViews": [],
                    "disputes": disputes,
                    "sourceIds": source_ids,
                    "sourceEvidence": [],
                    "reviewLevel": "来自已审核发布的记录表",
                }
            )
    return records


def build_snapshot(
    store: ResearchStore,
    *,
    title: str = "",
    description: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    knowledge_base = load_json("knowledge-base.json")
    legacy_records = load_json("eclipse-records.json")
    literature = load_json("literature.json")
    literature = json.loads(json.dumps(literature, ensure_ascii=False))
    literature.pop("source", None)
    policy = literature.get("collectionPolicy", {})
    if "scope" in policy:
        policy["scope"] = "公开展示题名、作者、出版信息、内部来源详情及页码级核验结论"
    if "privateResearchCopies" in policy:
        policy["privateResearchCopies"] = "授权取得的PDF保存在私有研究区，仅用于研究和知识提取，不公开分发"
    evidence = load_json("evidence-register.json")
    published = store.list_published_knowledge()
    records = [item["content"] for item in published if item["knowledge_type"] == "record"]
    topics = [item["content"] for item in published if item["knowledge_type"] == "topic"]
    artifacts = []
    for item in store.list_artifacts():
        publishable_status = item["status"] in {"approved", "published"}
        publication_enabled = item.get("publication_state") != "withdrawn"
        source_edges = [edge for edge in item.get("sources", []) if edge.get("source_id")]
        sources_ready = bool(source_edges) and all(
            edge.get("source_status") == "reviewed"
            and edge.get("source_recognition_status") in PUBLISH_READY_RECOGNITION
            for edge in source_edges
        )
        if publishable_status and publication_enabled and sources_ready:
            artifacts.append(public_artifact(item))
    site_content = store.public_site_content(include_system=True)
    sources = store.list_sources()
    reviewed_sources = sum(
        source["status"] == "reviewed"
        and source.get("recognition_status") in PUBLISH_READY_RECOGNITION
        for source in sources
    )
    mark_reviewed_literature(literature, sources)
    literature["items"] = [
        public_literature_item(item)
        for item in literature.get("items", [])
        if item.get("researchStatus") == "reviewed"
    ]
    if not records:
        records = records_from_published_tables(artifacts, literature["items"])
    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = release_metadata(title, description, created_by)
    snapshot = {
        "schemaVersion": "0.6",
        "snapshotId": "building",
        "publishedAt": generated_at,
        "release": {
            "title": metadata["title"],
            "description": metadata["description"],
        },
        "project": {
            **knowledge_base.get("project", {}),
            "version": "MVP 0.4",
        "dataPolicy": "公众站只展示研究工作台审核并发布的内容；原始资料仅保留在研究工作台。",
        },
        "knowledge": knowledge_base,
        "recordsMeta": {
            **legacy_records,
            "version": "0.4-release",
            "scope": "这里展示的是研究台已审核并发布的甲骨日食记录与研究线索。数据来自已确认的论文与页码原文；仍有争议的内容会明确标为研究线索或待核。",
            "completion": {
                **legacy_records.get("completion", {}),
                "status": f"{reviewed_sources}/7篇核心资料已审核进入研究闭环",
                "sourcesExtracted": reviewed_sources,
            },
            "topicEvidence": topics or legacy_records.get("topicEvidence", []),
            "records": records,
        },
        "literatureMeta": literature,
        "evidenceRegister": evidence,
        "siteContent": site_content,
        "works": artifacts,
        "audit": {
            "reviewedSources": reviewed_sources,
            "publishedKnowledge": len(published),
            "publishedWorks": len(artifacts),
            "publishedSiteContent": len(site_content),
            "rawFilesIncluded": False,
        },
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    snapshot_hash = hashlib.sha256(canonical).hexdigest()
    snapshot["snapshotId"] = f"snapshot-{generated_at[:10]}-{snapshot_hash[:10]}"
    return snapshot


def publish_snapshot(
    store: ResearchStore,
    path: Path = SNAPSHOT_PATH,
    *,
    title: str = "",
    description: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    metadata = release_metadata(title, description, created_by)
    snapshot = build_snapshot(
        store,
        title=metadata["title"],
        description=metadata["description"],
        created_by=metadata["createdBy"],
    )
    raw = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    snapshot_hash = hashlib.sha256(raw).hexdigest()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    release_dir = RELEASE_DIR if path.resolve() == SNAPSHOT_PATH.resolve() else path.parent / "release-history"
    release_dir.mkdir(parents=True, exist_ok=True)
    archive = release_dir / f"{snapshot['snapshotId']}.json"
    archive.write_bytes(raw)
    counts = {
        "records": len(snapshot["recordsMeta"]["records"]),
        "knowledge": snapshot["audit"]["publishedKnowledge"],
        "works": len(snapshot["works"]),
        "reviewedSources": snapshot["audit"]["reviewedSources"],
        "siteContent": sum(key in snapshot.get("siteContent", {}) for key in ("hero", "science", "history", "records")),
    }
    store.record_snapshot(
        snapshot["snapshotId"],
        snapshot_hash,
        str(archive.relative_to(ROOT)),
        counts,
        title=metadata["title"],
        description=metadata["description"],
        created_by=metadata["createdBy"],
    )
    store.set_public_artifacts([str(item["id"]) for item in snapshot.get("works", [])])
    store.set_published_site_content(snapshot.get("siteContent", {}))
    return {"snapshotId": snapshot["snapshotId"], "hash": snapshot_hash, "counts": counts}


def restore_snapshot(
    store: ResearchStore,
    snapshot_id: str,
    path: Path = SNAPSHOT_PATH,
    *,
    created_by: str = "",
) -> dict[str, Any]:
    release = store.get_snapshot(snapshot_id)
    if not release:
        raise KeyError("发布版本不存在")
    archive = snapshot_archive_path(release, path)
    if not archive.exists():
        raise KeyError("发布版本文件不存在")
    snapshot = json.loads(archive.read_text(encoding="utf-8"))
    generated_at = datetime.now(timezone.utc).isoformat()
    source_title = str(
        release.get("title")
        or snapshot.get("release", {}).get("title")
        or snapshot_id
    )
    metadata = release_metadata(
        f"恢复：{source_title}"[:MAX_RELEASE_TITLE_LENGTH],
        f"由历史版本 {snapshot_id} 恢复生成。",
        created_by,
    )
    snapshot["publishedAt"] = generated_at
    snapshot["restoredFrom"] = snapshot_id
    snapshot["release"] = {
        "title": metadata["title"],
        "description": metadata["description"],
    }
    snapshot["snapshotId"] = "building"
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    snapshot["snapshotId"] = f"release-{generated_at[:10]}-{hashlib.sha256(canonical).hexdigest()[:10]}"
    raw = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    snapshot_hash = hashlib.sha256(raw).hexdigest()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    release_dir = (
        RELEASE_DIR
        if path.resolve() == SNAPSHOT_PATH.resolve()
        else path.parent / "release-history"
    )
    release_dir.mkdir(parents=True, exist_ok=True)
    new_archive = release_dir / f"{snapshot['snapshotId']}.json"
    new_archive.write_bytes(raw)
    counts = {
        "records": len(snapshot["recordsMeta"]["records"]),
        "knowledge": snapshot["audit"]["publishedKnowledge"],
        "works": len(snapshot["works"]),
        "reviewedSources": snapshot["audit"]["reviewedSources"],
        "siteContent": len(snapshot.get("siteContent", {})),
    }
    store.record_snapshot(
        snapshot["snapshotId"],
        snapshot_hash,
        str(new_archive.relative_to(ROOT)),
        counts,
        title=metadata["title"],
        description=metadata["description"],
        created_by=metadata["createdBy"],
    )
    store.set_public_artifacts([str(item["id"]) for item in snapshot.get("works", [])])
    store.set_published_site_content(snapshot.get("siteContent", {}))
    return {"snapshotId": snapshot["snapshotId"], "restoredFrom": snapshot_id, "hash": snapshot_hash, "counts": counts}


def snapshot_detail(
    store: ResearchStore, snapshot_id: str, path: Path = SNAPSHOT_PATH
) -> dict[str, Any]:
    release = store.get_snapshot(snapshot_id)
    if not release:
        raise KeyError("发布版本不存在")
    archive = snapshot_archive_path(release, path)
    if not archive.exists():
        raise KeyError("发布版本文件不存在")
    snapshot = json.loads(archive.read_text(encoding="utf-8"))
    release_info = snapshot.get("release", {})
    works = [
        {
            "id": str(item.get("id", "")),
            "title": str(item.get("title", "未命名作品")),
            "kind": str(item.get("kind", "")),
            "updatedAt": item.get("updatedAt"),
        }
        for item in snapshot.get("works", [])
        if isinstance(item, dict)
    ]
    return {
        "id": snapshot_id,
        "title": str(release.get("title") or release_info.get("title") or "历史发布版本"),
        "description": str(release.get("description") or release_info.get("description") or ""),
        "createdBy": str(release.get("created_by") or "本地审核人"),
        "createdAt": release.get("created_at") or snapshot.get("publishedAt"),
        "publishedAt": snapshot.get("publishedAt") or release.get("created_at"),
        "hash": str(release.get("snapshot_hash") or ""),
        "itemCounts": release.get("item_counts") or {},
        "works": works,
        "siteContent": [
            {
                "key": str(key),
                "title": str(item.get("title") or key),
                "updatedAt": item.get("updatedAt"),
            }
            for key, item in (snapshot.get("siteContent") or {}).items()
            if isinstance(item, dict)
        ],
        "audit": snapshot.get("audit") or {},
        "current": snapshot_id == current_snapshot_id(path),
        "restorable": True,
        "restoredFrom": snapshot.get("restoredFrom"),
    }


def delete_snapshot(
    store: ResearchStore,
    snapshot_id: str,
    path: Path = SNAPSHOT_PATH,
    *,
    reviewer: str = "本地审核人",
) -> dict[str, Any]:
    if snapshot_id == current_snapshot_id(path):
        raise ValueError("当前公众版本不能删除，请先发布或恢复其他版本")
    release = store.get_snapshot(snapshot_id)
    if not release:
        raise KeyError("发布版本不存在")
    archive = snapshot_archive_path(release, path)
    if not archive.exists():
        raise KeyError("发布版本文件不存在")
    archive.unlink()
    store.delete_snapshot(snapshot_id, reviewer)
    return {"snapshotId": snapshot_id, "deleted": True}


def withdraw_artifact(
    store: ResearchStore,
    artifact_id: str,
    path: Path = SNAPSHOT_PATH,
    *,
    created_by: str = "",
) -> dict[str, Any]:
    artifact = store.get_artifact(artifact_id)
    if not artifact or artifact.get("publication_state") not in {
        "public", "public_stale", "replacement_pending"
    }:
        raise ValueError("作品不在当前公众版本中")
    if not path.exists():
        raise KeyError("当前公众快照不存在")
    store.review_artifact(artifact_id, "withdraw", note="从当前公众快照撤销发布")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["works"] = [item for item in snapshot.get("works", []) if str(item.get("id")) != artifact_id]
    snapshot["publishedAt"] = datetime.now(timezone.utc).isoformat()
    snapshot["snapshotId"] = "building"
    snapshot["audit"]["publishedWorks"] = len(snapshot["works"])
    metadata = release_metadata(
        f"撤销发布：{artifact.get('title') or artifact_id}"[:MAX_RELEASE_TITLE_LENGTH],
        f"从公众端撤销作品 {artifact.get('title') or artifact_id}。",
        created_by,
    )
    snapshot["release"] = {
        "title": metadata["title"],
        "description": metadata["description"],
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    snapshot["snapshotId"] = f"snapshot-{snapshot['publishedAt'][:10]}-{hashlib.sha256(canonical).hexdigest()[:10]}"
    raw = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    snapshot_hash = hashlib.sha256(raw).hexdigest()
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    release_dir = RELEASE_DIR if path.resolve() == SNAPSHOT_PATH.resolve() else path.parent / "release-history"
    release_dir.mkdir(parents=True, exist_ok=True)
    archive = release_dir / f"{snapshot['snapshotId']}.json"
    archive.write_bytes(raw)
    counts = {
        "records": len(snapshot.get("recordsMeta", {}).get("records", [])),
        "knowledge": snapshot.get("audit", {}).get("publishedKnowledge", 0),
        "works": len(snapshot["works"]),
        "reviewedSources": snapshot.get("audit", {}).get("reviewedSources", 0),
    }
    store.record_snapshot(
        snapshot["snapshotId"],
        snapshot_hash,
        str(archive.relative_to(ROOT)),
        counts,
        title=metadata["title"],
        description=metadata["description"],
        created_by=metadata["createdBy"],
    )
    store.set_public_artifacts([str(item["id"]) for item in snapshot["works"]])
    return {"snapshotId": snapshot["snapshotId"], "artifactId": artifact_id, "hash": snapshot_hash, "counts": counts}
