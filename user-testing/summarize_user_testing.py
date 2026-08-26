from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "汇总表.csv"
DEFAULT_OUTPUT = ROOT / "用户测试汇总.md"
REQUIRED_COLUMNS = {
    "participant_id",
    "audience",
    "consent",
    "scenario",
    "completed_tasks",
    "total_tasks",
    "help_count",
    "error_count",
    "sus_score",
    "key_issue",
    "severity",
    "status",
}


def number(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0)
    except ValueError:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总甲骨日食项目用户测试")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fields = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise SystemExit(f"汇总表缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)
    if not 5 <= len(rows) <= 10:
        raise SystemExit("首轮测试席位应为5至10人")
    if args.validate_only:
        print(f"模板有效：{len(rows)}个测试席位，{sum(row['status'] == 'completed' for row in rows)}人已完成")
        return 0

    completed = [row for row in rows if row.get("status", "").strip().lower() == "completed"]
    valid = [row for row in completed if row.get("consent", "").strip().lower() in {"yes", "是", "true", "1"}]
    task_total = sum(number(row, "total_tasks") for row in valid)
    tasks_done = sum(number(row, "completed_tasks") for row in valid)
    completion_rate = round(tasks_done / task_total * 100, 1) if task_total else 0
    sus_values = [number(row, "sus_score") for row in valid if row.get("sus_score", "").strip()]
    average_sus = round(statistics.mean(sus_values), 1) if sus_values else 0
    issues = [row for row in valid if row.get("key_issue", "").strip()]
    lines = [
        "# 用户测试汇总",
        "",
        f"- 有效参与者：{len(valid)} / {len(rows)}",
        f"- 任务完成率：{completion_rate}%",
        f"- 平均SUS：{average_sus if sus_values else '未填写'}",
        f"- 总求助：{int(sum(number(row, 'help_count') for row in valid))}",
        f"- 总错误：{int(sum(number(row, 'error_count') for row in valid))}",
        "",
        "## 用户构成",
        "",
    ]
    for row in valid:
        lines.append(f"- {row['participant_id']}：{row['audience']}（{row['scenario']}）")
    lines.extend(["", "## 关键问题", ""])
    if issues:
        for row in issues:
            lines.append(f"- [{row.get('severity') or '未分级'}] {row['key_issue']}（{row['participant_id']}）")
    else:
        lines.append("- 尚未登记。")
    passed = len(valid) >= 5 and completion_rate >= 80 and bool(sus_values) and average_sus >= 68
    lines.extend(
        [
            "",
            "## 门槛判断",
            "",
            f"结论：{'达到首轮可用性门槛，仍需关闭严重问题。' if passed else '尚未达到首轮完成门槛。'}",
            "",
            "古文字与天文学准确性另按专家复核记录签署，不由SUS分数替代。",
            "",
        ]
    )
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成：{args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
