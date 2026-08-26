from __future__ import annotations

import sys
from pathlib import Path

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing


def generate_qr(value: str, output: Path, size: int = 480) -> None:
    widget = qr.QrCodeWidget(value)
    x1, y1, x2, y2 = widget.getBounds()
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    padding = 18
    inner = size - padding * 2
    scale = min(inner / width, inner / height)
    drawing = Drawing(
        size,
        size,
        transform=[scale, 0, 0, scale, padding - x1 * scale, padding - y1 * scale],
    )
    drawing.add(widget)
    output.parent.mkdir(parents=True, exist_ok=True)
    renderSVG.drawToFile(drawing, str(output))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_qr.py URL OUTPUT_SVG")
    generate_qr(sys.argv[1], Path(sys.argv[2]))
