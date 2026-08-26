from __future__ import annotations

import re
from typing import Any


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SUSPICIOUS_RE = re.compile(
    r"[\u0400-\u052f\u0a80-\u0aff\u0c80-\u0cff\u0f00-\u109f\u10a0-\u10ff]"
)


def assess_text_quality(text: str) -> dict[str, Any]:
    normalized = str(text or "").strip()
    visible = [character for character in normalized if not character.isspace()]
    visible_count = len(visible)
    cjk_count = len(_CJK_RE.findall(normalized))
    latin_count = len(_LATIN_RE.findall(normalized))
    suspicious_count = len(_SUSPICIOUS_RE.findall(normalized))
    replacement_count = normalized.count("�")
    linguistic_count = max(1, cjk_count + latin_count + suspicious_count)
    cjk_ratio = cjk_count / linguistic_count
    suspicious_ratio = (suspicious_count + replacement_count) / max(1, visible_count)

    length_score = min(1.0, visible_count / 120)
    script_score = max(0.0, 1.0 - suspicious_ratio * 8)
    recognized_ratio = (cjk_count + latin_count) / linguistic_count
    language_score = min(1.0, recognized_ratio) if visible_count >= 40 else 0.55
    score = round((length_score * 0.2) + (script_score * 0.5) + (language_score * 0.3), 4)

    errors: list[str] = []
    warnings: list[str] = []
    if visible_count == 0:
        errors.append("页面未识别到文本")
        page_type = "empty"
    elif visible_count < 20:
        warnings.append("页面文字较少，可能为图版或空白页，建议人工核对")
        page_type = "sparse"
    elif cjk_ratio < 0.15 and latin_count >= 20:
        warnings.append("页面以英文、数字或图表标注为主，建议人工核对")
        page_type = "latin_dominant"
    elif cjk_ratio < 0.35 and latin_count >= 20:
        warnings.append("页面中英文混排或图表标注较多，建议人工核对")
        page_type = "mixed_language"
    else:
        page_type = "chinese_text"
    if suspicious_ratio >= 0.02:
        errors.append("检测到异常文字编码")
        page_type = "garbled"
    status = "failed" if errors else "needs_review" if warnings or score < 0.72 else "passed"
    return {
        "score": score,
        "status": status,
        "pageType": page_type,
        "visibleCharacters": visible_count,
        "cjkCharacters": cjk_count,
        "latinCharacters": latin_count,
        "suspiciousCharacters": suspicious_count + replacement_count,
        "cjkRatio": round(cjk_ratio, 4),
        "suspiciousRatio": round(suspicious_ratio, 4),
        "errors": errors,
        "warnings": warnings,
        "reasons": [*errors, *warnings],
    }


def aggregate_quality(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        return {
            "score": 0.0,
            "status": "failed",
            "pages": 0,
            "passedPages": 0,
            "recognizedPages": 0,
            "reviewPages": 0,
            "failedPages": 0,
            "reviewPageNumbers": [],
            "failedPageNumbers": [],
            "problemPageNumbers": [],
            "errors": ["没有可评估的页面文本"],
            "warnings": [],
            "reasons": ["没有可评估的页面文本"],
        }
    passed_pages = sum(report.get("status") == "passed" for report in reports)
    review_reports = [
        (int(report.get("pageNumber") or index), report)
        for index, report in enumerate(reports, 1)
        if report.get("status") == "needs_review"
    ]
    failed_reports = [
        (int(report.get("pageNumber") or index), report)
        for index, report in enumerate(reports, 1)
        if report.get("status") == "failed"
    ]
    score = round(sum(float(report.get("score", 0)) for report in reports) / len(reports), 4)
    errors = list(
        dict.fromkeys(
            error
            for report in reports
            for error in report.get("errors", [])
        )
    )
    warnings = list(
        dict.fromkeys(
            warning
            for report in reports
            for warning in report.get("warnings", [])
        )
    )
    # Reports written before page-type detection treated low Chinese ratios as
    # hard failures. Keep them reviewable when an old run is opened again.
    legacy_review_reasons = {
        "中文字符比例异常",
        "页面文本过少或为空",
    }
    for page_number, report in list(failed_reports):
        reasons = set(report.get("reasons", []))
        if reasons and reasons.issubset(legacy_review_reasons):
            failed_reports.remove((page_number, report))
            review_reports.append((page_number, report))
            warnings.extend(reason for reason in reasons if reason not in warnings)

    for _, report in failed_reports:
        errors.extend(
            reason
            for reason in report.get("reasons", [])
            if reason not in errors
        )
    for _, report in review_reports:
        warnings.extend(
            reason
            for reason in report.get("reasons", [])
            if reason not in warnings and reason not in errors
        )

    status = "failed" if failed_reports else "needs_review" if review_reports else "passed"
    review_pages = sorted(page_number for page_number, _ in review_reports)
    failed_pages = sorted(page_number for page_number, _ in failed_reports)
    problem_pages = sorted({*review_pages, *failed_pages})
    recognized_pages = len(reports) - len(failed_reports)
    reasons = [*errors, *warnings]
    return {
        "score": score,
        "status": status,
        "pages": len(reports),
        "passedPages": passed_pages,
        "recognizedPages": recognized_pages,
        "reviewPages": len(review_reports),
        "failedPages": len(failed_reports),
        "reviewPageNumbers": review_pages,
        "failedPageNumbers": failed_pages,
        "problemPageNumbers": problem_pages,
        "errors": errors,
        "warnings": warnings,
        "reasons": reasons,
    }
