from __future__ import annotations

import io
import os
import threading
from pathlib import Path
from typing import Any

from bailian_adapter import BailianAdapter
from research_store import ROOT, ResearchStore


OCR_SEMAPHORE = threading.Semaphore(max(1, int(os.getenv("QWEN_OCR_WORKERS", "1"))))


def run_source_ocr(store: ResearchStore, source_id: str, run_id: str) -> dict[str, Any]:
    with OCR_SEMAPHORE:
        adapter = BailianAdapter()
        try:
            import pypdfium2
        except ImportError as exc:
            store.fail_ocr_run(run_id, source_id, "缺少pypdfium2，无法渲染PDF页面")
            raise RuntimeError("缺少pypdfium2，无法渲染PDF页面") from exc

        try:
            path, _ = store.source_file(source_id)
            document = pypdfium2.PdfDocument(str(path))
            total_pages = len(document)
            store.begin_ocr_run(run_id, total_pages)
            run = next(item for item in store.list_ocr_runs(source_id) if item["id"] == run_id)
            page_dir_value = str(run.get("page_dir") or "")
            page_dir = Path(page_dir_value)
            if not page_dir.is_absolute():
                page_dir = ROOT / page_dir
            page_dir.mkdir(parents=True, exist_ok=True)
            scale = max(1.8, min(3.0, float(os.getenv("OCR_RENDER_SCALE", "2.4"))))

            for page_index in range(total_pages):
                page_number = page_index + 1
                image = document[page_index].render(scale=scale).to_pil()
                image_path = page_dir / f"page-{page_number:04d}.png"
                image.save(image_path, format="PNG", optimize=True)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                text = adapter.ocr_page(buffer.getvalue(), page_number)
                store.save_ocr_page_result(run_id, source_id, page_number, text)

            return store.complete_ocr_run(run_id, source_id, adapter.ocr_model)
        except Exception as exc:
            store.fail_ocr_run(run_id, source_id, str(exc) or "OCR处理失败")
            return {"runId": run_id, "status": "failed", "error": str(exc)}
