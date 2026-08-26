from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


BASE_URL = "https://jgw.aynu.edu.cn"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / ".cache" / "yinqi"
USER_AGENT = (
    "OracleEclipseResearch/0.2 "
    "(non-commercial educational metadata collection; low frequency)"
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def strip_markup(value: Any) -> str:
    parser = TextExtractor()
    parser.feed(html.unescape(str(value or "")))
    return parser.text()


@dataclass
class Client:
    cache_dir: Path
    delay: float = 1.5
    retries: int = 3

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_request_at = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed + random.uniform(0.05, 0.25))

    def json_request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cache_key = hashlib.sha256(
            method.encode("ascii") + path.encode("utf-8") + (body or b"")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        request = urllib.request.Request(
            urllib.parse.urljoin(BASE_URL, path),
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": USER_AGENT,
            },
            method=method,
        )
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._wait()
                with urllib.request.urlopen(request, timeout=35) as response:
                    raw = response.read().decode("utf-8")
                self.last_request_at = time.monotonic()
                data = json.loads(raw)
                cache_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return data
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                error = exc
                self.last_request_at = time.monotonic()
                if attempt + 1 < self.retries:
                    time.sleep((2**attempt) + random.uniform(0.1, 0.4))
        raise RuntimeError(f"request failed after {self.retries} attempts: {path}") from error


def literature_payload(query: str, page: int, sort_field: str) -> dict[str, Any]:
    return {
        "select": [
            {
                "conditionKey": "TM",
                "conditionValue": query,
                "conditionType": 2,
                "beforeConditionType": 0,
            }
        ],
        "condition": {
            "fieldName": "",
            "fieldValue": "",
            "pageIndex": page,
            "sortField": sort_field,
            "sortDescAsc": "desc",
            "classCode": "002",
        },
    }


def bone_payload(query: str, field: str, page: int, sort_field: str) -> dict[str, Any]:
    return {
        "select": [
            {
                "conditionKey": field,
                "conditionValue": query,
                "conditionType": 2,
                "beforeConditionType": 0,
            }
        ],
        "condition": {
            "fieldName": "",
            "fieldValue": "",
            "pageIndex": page,
            "sortField": sort_field,
            "sortDescAsc": "desc",
            "checkedCatID": "",
            "selectedCatTypeID": "2",
            "selectedGrade": "3",
        },
    }


def collect_literature(
    client: Client, query: str, max_pages: int, max_items: int
) -> dict[str, Any]:
    config = client.json_request("/AynuDoc/ConfigField")
    sorts = config.get("Data", {}).get("sortField", [])
    sort_field = sorts[0].get("RealFieldName", "FBSJ") if sorts else "FBSJ"
    items: list[dict[str, Any]] = []
    total = 0

    for page in range(1, max_pages + 1):
        result = client.json_request(
            "/AynuDoc/Search",
            method="POST",
            payload=literature_payload(query, page, sort_field),
        )
        if str(result.get("Code")) != "200":
            raise RuntimeError(result.get("Message") or "literature search failed")
        data = result.get("Data", {})
        page_info = (data.get("pageData") or [{}])[0]
        total = int(page_info.get("sumCount") or 0)
        for raw in data.get("Table1", []):
            db_code = str(raw.get("__sys_from", "")).split("#")
            db_code = db_code[1] if len(db_code) > 1 else ""
            sys_id = str(raw.get("SYS_FLD_SYSID", ""))
            items.append(
                {
                    "id": sys_id,
                    "title": strip_markup(raw.get("TM")),
                    "authors": [
                        name.strip()
                        for name in strip_markup(raw.get("ZZ")).split(";")
                        if name.strip()
                    ],
                    "publication": strip_markup(raw.get("LY")),
                    "publishedAt": strip_markup(raw.get("FBSJ")),
                    "dbCode": db_code,
                    "sourceUrl": (
                        f"{BASE_URL}/home/wx/detail/index.html?id={sys_id}"
                        f"&dbcode={urllib.parse.quote(db_code)}"
                    ),
                    "access": "详情页需登录；本文件仅保存公开搜索结果中的元数据",
                }
            )
            if len(items) >= max_items:
                break
        if len(items) >= max_items or page >= int(page_info.get("sumPage") or 0):
            break

    return {
        "dataset": "殷契文渊日食研究文献公开检索元数据",
        "query": query,
        "source": f"{BASE_URL}/home/wx/index.html",
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
        "collectionPolicy": {
            "authentication": "未使用登录凭据或浏览器 Cookie",
            "scope": "题名、作者、来源、发表时间、记录标识与来源链接",
            "excluded": "全文、PDF、图片及登录后详情字段",
            "rateLimitSeconds": client.delay,
        },
        "reportedTotal": total,
        "items": items,
    }


def collect_bones(
    client: Client, query: str, field: str, max_pages: int, max_items: int
) -> dict[str, Any]:
    config = client.json_request("/AynuBone/ConfigField?dbCode=bone")
    sorts = config.get("Data", {}).get("sortField", [])
    sort_field = sorts[0].get("FieldName", "PX") if sorts else "PX"
    items: list[dict[str, Any]] = []
    total = 0

    for page in range(1, max_pages + 1):
        result = client.json_request(
            "/AynuBone/Search",
            method="POST",
            payload=bone_payload(query, field, page, sort_field),
        )
        if str(result.get("Code")) != "200":
            raise RuntimeError(result.get("Message") or "bone search failed")
        data = result.get("Data", {})
        page_info = (data.get("pageData") or [{}])[0]
        total = int(page_info.get("sumCount") or 0)
        for raw in data.get("Table1", []):
            sys_id = str(raw.get("SYS_FLD_SYSID", ""))
            items.append(
                {
                    "id": sys_id,
                    "catalogNumber": strip_markup(raw.get("PM")),
                    "collectionNumber": strip_markup(raw.get("GCBH")),
                    "format": strip_markup(raw.get("JLXS")),
                    "sourceCollection": strip_markup(raw.get("CC")),
                    "sourceUrl": f"{BASE_URL}/home/zl/detail/index.html?id={sys_id}",
                    "access": "公开搜索结果；未保存图片 URL，详情释文需另行核验",
                }
            )
            if len(items) >= max_items:
                break
        if len(items) >= max_items or page >= int(page_info.get("sumPage") or 0):
            break

    return {
        "dataset": "殷契文渊著录库公开检索元数据",
        "query": query,
        "field": field,
        "source": f"{BASE_URL}/home/zl/index.html",
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
        "reportedTotal": total,
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-frequency public-metadata collector for 殷契文渊"
    )
    parser.add_argument("--mode", choices=("literature", "bone"), default="literature")
    parser.add_argument("--query", default="日食")
    parser.add_argument("--field", choices=("SW", "YW", "PM"), default="SW")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.max_pages < 1 or args.max_pages > 5:
        parser.error("--max-pages must be between 1 and 5")
    if args.max_items < 1 or args.max_items > 50:
        parser.error("--max-items must be between 1 and 50")
    if args.delay < 1:
        parser.error("--delay must be at least 1 second")

    client = Client(args.cache_dir, delay=args.delay, retries=args.retries)
    if args.mode == "literature":
        result = collect_literature(
            client, args.query, args.max_pages, args.max_items
        )
        output = args.output or ROOT / "data" / "literature.json"
    else:
        result = collect_bones(
            client, args.query, args.field, args.max_pages, args.max_items
        )
        output = args.output or ROOT / "data" / "bone-search-results.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"saved {len(result['items'])} items to {output}")


if __name__ == "__main__":
    main()
