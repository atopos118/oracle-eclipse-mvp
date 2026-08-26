from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = Path(__file__).with_name("bailian-question-set.json")
DEFAULT_REPORTS = Path(__file__).with_name("reports")
REFUSAL_TERMS = ("不能", "无法", "不足", "尚不清楚", "不详", "不在", "并非")


def request_json(url: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def citation_is_valid(citation: Any) -> bool:
    if not isinstance(citation, dict):
        return False
    return all(str(citation.get(key, "")).strip() for key in ("id", "label", "url"))


def assess(question: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    answer = str(response.get("answer", "")).strip()
    citations = response.get("citations") if isinstance(response.get("citations"), list) else []
    citation_text = " ".join(str(item.get("label", "")) for item in citations if isinstance(item, dict))
    grounded_text = f"{answer}\n{citation_text}".lower()
    keyword_groups = question.get("mustIncludeAny", [])
    keyword_checks = [
        {
            "terms": group,
            "passed": any(str(term).lower() in grounded_text for term in group),
        }
        for group in keyword_groups
        if isinstance(group, list) and group
    ]
    forbidden = [r"\*\*", r"作为(?:一个|一名)?AI", r"根据我的训练数据"]
    forbidden.extend(question.get("forbiddenPatterns", []))
    forbidden_hits = [pattern for pattern in forbidden if re.search(pattern, answer, re.I)]
    expects_refusal = bool(question.get("expectsRefusal"))
    refusal_passed = not expects_refusal or any(term in answer for term in REFUSAL_TERMS)
    minimum_citations = int(question.get("minCitations", 0))
    checks = {
        "hasAnswer": bool(answer),
        "keywords": all(item["passed"] for item in keyword_checks),
        "citationCount": len(citations) >= minimum_citations,
        "citationStructure": all(citation_is_valid(item) for item in citations),
        "refusal": refusal_passed,
        "forbiddenExpression": not forbidden_hits,
    }
    return {
        "checks": checks,
        "keywordChecks": keyword_checks,
        "forbiddenHits": forbidden_hits,
        "autoPassed": all(checks.values()),
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 百炼正式验收报告",
        "",
        f"- 问题集：{report['questionSetVersion']}",
        f"- 执行时间：{report['startedAt']}",
        f"- 发布版本：{report.get('snapshotId') or '未取得'}",
        f"- 服务模型：{report['health'].get('model', '未知')}",
        f"- 自动通过：{summary['autoPassed']} / {summary['total']}",
        f"- 实际百炼回答：{summary['qwenResponses']} / {summary['total']}",
        f"- 平均延迟：{summary['averageLatencyMs']} ms",
        "",
        "自动检查只验证结构、关键词、引用数量、拒答信号和禁用表达。学术准确性必须人工逐题复核。",
        "",
        "| 编号 | 类别 | 模式 | 延迟 | 引用 | 自动结果 | 人工复核 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| {item['id']} | {item['category']} | {item.get('mode', '-')} | "
            f"{item['latencyMs']} ms | {len(item.get('citations', []))} | "
            f"{'通过' if item['assessment']['autoPassed'] else '待查'} | 待复核 |"
        )
    lines.extend(["", "## 逐题记录", ""])
    for item in report["results"]:
        lines.extend(
            [
                f"### {item['id']} · {item['category']}",
                "",
                f"问题：{item['question']}",
                "",
                f"回答：{item.get('answer') or item.get('error') or '无'}",
                "",
                "引用：" + ("；".join(str(c.get("label", "")) for c in item.get("citations", [])) or "无"),
                "",
                f"自动检查：{'通过' if item['assessment']['autoPassed'] else json.dumps(item['assessment']['checks'], ensure_ascii=False)}",
                "",
                f"人工复核重点：{item['manualFocus']}",
                "",
                "人工结论：待复核（准确 / 需修改 / 不通过）",
                "",
            ]
        )
    lines.extend(
        [
            "## 最终签署",
            "",
            "- 古文字学复核：待填写",
            "- 天文学复核：待填写",
            "- 产品复核：待填写",
            "- 技术复核：待填写",
            "- 最终结论：待签署",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行甲骨日食公众问答百炼验收集")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--question-set", type=Path, default=DEFAULT_SET)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--allow-fallback", action="store_true")
    args = parser.parse_args()

    question_set = json.loads(args.question_set.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc)
    base_url = args.base_url.rstrip("/")
    try:
        health = request_json(f"{base_url}/api/health", None, min(args.timeout, 30))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"无法访问验收服务：{exc}", file=sys.stderr)
        return 2

    results = []
    for question in question_set.get("questions", []):
        start = time.perf_counter()
        try:
            response = request_json(
                f"{base_url}/api/chat",
                {"message": question["question"]},
                args.timeout,
            )
            error = ""
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            response = {"answer": "", "citations": [], "mode": "error", "model": ""}
            error = str(exc)
        latency = round((time.perf_counter() - start) * 1000)
        assessment = assess(question, response)
        results.append(
            {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                "manualFocus": question.get("manualFocus", ""),
                "mode": response.get("mode", ""),
                "model": response.get("model", ""),
                "answer": response.get("answer", ""),
                "citations": response.get("citations", []),
                "boundary": response.get("boundary", ""),
                "warning": response.get("warning", ""),
                "error": error,
                "latencyMs": latency,
                "assessment": assessment,
                "humanReview": {"status": "pending", "reviewer": "", "notes": ""},
            }
        )
        print(
            f"{question['id']} {response.get('mode', 'error')} {latency}ms "
            f"{'PASS' if assessment['autoPassed'] else 'CHECK'}",
            flush=True,
        )

    qwen_responses = sum(item["mode"] == "qwen" and not item["warning"] for item in results)
    auto_passed = sum(item["assessment"]["autoPassed"] for item in results)
    average_latency = round(sum(item["latencyMs"] for item in results) / max(1, len(results)))
    snapshot_id = ""
    try:
        snapshot = json.loads((ROOT / "data" / "published-snapshot.json").read_text(encoding="utf-8"))
        snapshot_id = str(snapshot.get("snapshotId", ""))
    except (OSError, json.JSONDecodeError):
        pass
    report = {
        "schemaVersion": "1.0",
        "questionSetVersion": question_set.get("version", "unknown"),
        "startedAt": started.isoformat(),
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": base_url,
        "snapshotId": snapshot_id,
        "health": health,
        "summary": {
            "total": len(results),
            "autoPassed": auto_passed,
            "qwenResponses": qwen_responses,
            "averageLatencyMs": average_latency,
            "humanReviewStatus": "pending",
        },
        "results": results,
    }

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.astimezone().strftime("%Y%m%d-%H%M%S")
    json_path = args.reports_dir / f"bailian-evaluation-{stamp}.json"
    markdown_path = args.reports_dir / f"bailian-evaluation-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    shutil.copyfile(json_path, args.reports_dir / "latest.json")
    shutil.copyfile(markdown_path, args.reports_dir / "latest.md")
    print(f"报告：{markdown_path}")

    all_qwen = qwen_responses == len(results)
    if auto_passed != len(results):
        return 1
    if not args.allow_fallback and not all_qwen:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
