from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bailian_adapter import BailianAdapter, clean_audio_script
from artifact_content import normalize_slide_deck_content


MEDIA_EXPORTS = {
    "audio_guide": {"format": "wav", "label": "下载WAV音频"},
    "visual_card_set": {"format": "png-zip", "label": "下载PNG图卡包"},
    "slide_deck": {"format": "pptx", "label": "下载PPTX"},
    "video_package": {"format": "zip", "videoFormat": "mp4", "label": "播放/下载视频", "packageLabel": "下载视频制作包"},
}
PUBLIC_MEDIA_DIR = Path(__file__).resolve().parent / "assets" / "public-media"


def _packaged_media_path(filename: str) -> Path | None:
    candidate = PUBLIC_MEDIA_DIR / Path(filename).name
    return candidate if candidate.is_file() else None


def _safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\u3400-\u9fff-]+", "-", str(value or "").strip()).strip("-_")
    return (cleaned or fallback)[:80]


def _source_manifest(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for edge in artifact.get("sources", []):
        source_id = str(edge.get("source_id") or "")
        if not source_id:
            continue
        item = grouped.setdefault(
            source_id,
            {
                "sourceId": source_id,
                "title": str(edge.get("source_title") or "来源资料"),
                "locators": [],
            },
        )
        locator = str(edge.get("locator_value") or "").strip()
        if locator:
            label = f"{edge.get('locator_type') or '位置'} {locator}"
            if label not in item["locators"]:
                item["locators"].append(label)
    return list(grouped.values())


def _manifest(artifact: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "schemaVersion": "0.4-media",
        "artifactId": artifact.get("id"),
        "kind": artifact.get("kind"),
        "title": artifact.get("title"),
        "reviewStatus": artifact.get("status"),
        "publicationState": artifact.get("publication_state"),
        "model": artifact.get("model"),
        "promptVersion": artifact.get("prompt_version"),
        "generationInstruction": artifact.get("generation_instruction") or "",
        "sourceRevisionSignature": artifact.get("source_revision_sig"),
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "sources": _source_manifest(artifact),
        "notice": "AI辅助生成的待审核作品；不得替代原始甲骨图版或文献证据。",
    }
    if artifact.get("kind") == "audio_guide":
        adapter = BailianAdapter()
        media = artifact.get("media") if isinstance(artifact.get("media"), dict) else {}
        manifest["speech"] = {
            "provider": "aliyun-bailian",
            "model": media.get("model") or adapter.tts_model,
            "voice": media.get("voice") or adapter.tts_voice,
        }
    if artifact.get("kind") == "visual_card_set":
        adapter = BailianAdapter()
        manifest["visualGeneration"] = {
            "provider": "aliyun-bailian",
            "model": adapter.image_model,
            "mode": "explicit-per-card",
            "note": "无文字插图由模型生成，标题、正文、页码和来源由本地排版。",
        }
    if artifact.get("kind") == "slide_deck":
        adapter = BailianAdapter()
    if artifact.get("kind") == "video_package":
        adapter = BailianAdapter()
        media = artifact.get("content", {}).get("video", {}) if isinstance(artifact.get("content"), dict) else {}
        manifest["video"] = {
            "provider": "aliyun-bailian",
            "model": media.get("model") or adapter.video_model,
            "duration": media.get("duration") or 10,
            "status": media.get("status") or "not_started",
        }
        manifest["presentation"] = {
            "renderer": "@oai/artifact-tool",
            "imageProvider": "aliyun-bailian",
            "imageModel": adapter.image_model,
            "editable": True,
            "features": [
                "rich-text",
                "lucide-icons",
                "images",
                "native-diagrams",
                "native-charts",
                "speaker-notes",
                "transitions",
                "auto-advance",
            ],
        }
    return manifest


def _audio_cache_path(
    artifact: dict[str, Any], model: str, voice: str, text: str
) -> Path:
    configured = os.getenv("ORACLE_AUDIO_CACHE_DIR", "").strip()
    cache_dir = Path(configured) if configured else Path(__file__).resolve().parent / "source-materials" / "generated" / "audio"
    signature = hashlib.sha256(
        json.dumps(
            {
                "artifactId": artifact.get("id"),
                "text": text,
                "model": model,
                "voice": voice,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:20]
    artifact_id = _safe_filename(str(artifact.get("id") or "audio"), "audio")
    output = cache_dir / f"{artifact_id}-{signature}.wav"
    return _packaged_media_path(output.name) or output


def _visual_card_prompt(card: dict[str, Any]) -> str:
    title = str(card.get("title") or "甲骨日食科普").strip()
    direction = str(card.get("visualDirection") or "日食科学与甲骨研究的博物馆式编辑插图").strip()
    return (
        "为中国古代天文学科普图卡创作一幅竖版编辑插图。"
        f"主题：{title}。画面方向：{direction}。"
        "视觉应克制、准确、具有博物馆展览质感，使用日食、月影、天文观测、纸本文献等可辨识元素；"
        "不得生成任何文字、字母、水印、徽标，不得伪造甲骨原片或甲骨文字。"
    )


def _visual_background_path(
    artifact: dict[str, Any], card_index: int, model: str, prompt: str
) -> Path:
    configured = os.getenv("ORACLE_IMAGE_CACHE_DIR", "").strip()
    cache_dir = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parent / "source-materials" / "generated" / "images"
    )
    signature = hashlib.sha256(
        json.dumps(
            {
                "artifactId": artifact.get("id"),
                "card": card_index,
                "model": model,
                "prompt": prompt,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:20]
    artifact_id = _safe_filename(str(artifact.get("id") or "visual-card"), "visual-card")
    output = cache_dir / f"{artifact_id}-card-{card_index + 1:02d}-{signature}.png"
    return _packaged_media_path(output.name) or output


def generate_visual_card_background(
    artifact: dict[str, Any], card_index: int
) -> dict[str, Any]:
    from PIL import Image

    content = artifact.get("content") or {}
    cards = content.get("cards") if isinstance(content.get("cards"), list) else []
    if not cards or card_index < 0 or card_index >= len(cards):
        raise ValueError("图卡编号无效")
    card = cards[card_index] if isinstance(cards[card_index], dict) else {}
    adapter = BailianAdapter()
    prompt = _visual_card_prompt(card)
    output = _visual_background_path(artifact, card_index, adapter.image_model, prompt)
    if not output.exists():
        raw = adapter.generate_image(prompt, size="1024*1024")
        try:
            with Image.open(io.BytesIO(raw)) as generated:
                image = generated.convert("RGB")
                if image.width < 256 or image.height < 256:
                    raise ValueError("百炼文生图返回的图片尺寸过小")
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_suffix(".tmp")
                image.save(temporary, format="PNG", optimize=True)
                temporary.replace(output)
        except (OSError, ValueError) as exc:
            raise RuntimeError("百炼文生图返回的文件不是有效图片") from exc
    return {
        "card": card_index,
        "model": adapter.image_model,
        "provider": "aliyun-bailian",
        "cached": True,
    }


def visual_card_background_exists(artifact: dict[str, Any], card_index: int) -> bool:
    content = artifact.get("content") or {}
    cards = content.get("cards") if isinstance(content.get("cards"), list) else []
    if card_index < 0 or card_index >= len(cards):
        return False
    card = cards[card_index] if isinstance(cards[card_index], dict) else {}
    adapter = BailianAdapter()
    prompt = _visual_card_prompt(card)
    return _visual_background_path(
        artifact, card_index, adapter.image_model, prompt
    ).exists()


def render_audio_wav(artifact: dict[str, Any]) -> bytes:
    text = clean_audio_script(str((artifact.get("content") or {}).get("text") or ""))
    if not text:
        raise ValueError("音频导览没有可朗读的正文")
    adapter = BailianAdapter()
    media = artifact.get("media") if isinstance(artifact.get("media"), dict) else {}
    model = str(media.get("model") or adapter.tts_model)
    voice = str(media.get("voice") or adapter.tts_voice)
    output = _audio_cache_path(artifact, model, voice, text)
    if output.exists():
        raw = output.read_bytes()
        if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
            return raw
    raw = adapter.synthesize_wav(text, model=model, voice=voice)
    if not (raw.startswith(b"RIFF") and raw[8:12] == b"WAVE"):
        raise RuntimeError("百炼语音合成返回的文件不是有效WAV")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.replace(output)
    return raw


def render_audio_mp3(artifact: dict[str, Any]) -> bytes:
    """Create a compact public playback file while retaining WAV as the master."""
    text = clean_audio_script(str((artifact.get("content") or {}).get("text") or ""))
    if not text:
        raise ValueError("音频导览没有可朗读的正文")
    adapter = BailianAdapter()
    media = artifact.get("media") if isinstance(artifact.get("media"), dict) else {}
    model = str(media.get("model") or adapter.tts_model)
    voice = str(media.get("voice") or adapter.tts_voice)
    wav_path = _audio_cache_path(artifact, model, voice, text)
    wav_raw = render_audio_wav(artifact)
    mp3_path = wav_path.with_suffix(".mp3")
    if mp3_path.exists():
        cached = mp3_path.read_bytes()
        if cached.startswith(b"ID3") or cached[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            return cached
    ffmpeg = os.getenv("ORACLE_FFMPEG_BIN", "").strip() or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("生成轻量音频需要安装 FFmpeg")
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    if not wav_path.exists():
        wav_path.write_bytes(wav_raw)
    with tempfile.NamedTemporaryFile(dir=wav_path.parent, suffix=".mp3", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
                "-vn", "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "80k",
                str(temporary),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0 or temporary.stat().st_size == 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"轻量音频转换失败：{detail or 'FFmpeg 未返回音频'}")
        temporary.replace(mp3_path)
    finally:
        temporary.unlink(missing_ok=True)
    return mp3_path.read_bytes()


def public_image_webp(path: Path, *, max_width: int = 1920, quality: int = 82) -> bytes:
    """Return a cached WebP derivative without changing the private master image."""
    from PIL import Image, ImageOps

    output = path.with_suffix(".public.webp")
    if output.exists() and output.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        return output.read_bytes()
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".webp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            image.save(temporary, format="WEBP", quality=quality, method=6)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return output.read_bytes()


def audio_duration_seconds(raw: bytes) -> float:
    with wave.open(io.BytesIO(raw), "rb") as audio:
        return round(audio.getnframes() / max(1, audio.getframerate()), 2)


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    bundled = Path(__file__).resolve().parent / "assets" / "fonts"
    windows = Path("C:/Windows/Fonts")
    candidates = [
        bundled / ("NotoSansSC-Bold.otf" if bold else "NotoSansSC-Regular.otf"),
        windows / ("msyhbd.ttc" if bold else "msyh.ttc"),
        windows / ("simhei.ttf" if bold else "simsun.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except (OSError, ValueError):
                continue
    return ImageFont.load_default()


def _has_replacement_text(value: Any) -> bool:
    """Detect irreversible decode damage before exporting a media artifact."""
    return "\ufffd" in str(value or "")


def _wrap_lines(draw: Any, value: str, font: Any, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(value or "").replace("\r", "").split("\n"):
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = character
                if len(lines) >= max_lines:
                    break
            else:
                current = candidate
        if len(lines) >= max_lines:
            break
        if current:
            lines.append(current)
        elif paragraph == "":
            lines.append("")
        if len(lines) >= max_lines:
            break
    if len(lines) >= max_lines:
        last = lines[max_lines - 1].rstrip("。；，、 ")
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines = lines[: max_lines - 1] + [last + "…"]
    return lines


def _render_visual_card_image(artifact: dict[str, Any], card_index: int):
    from PIL import Image, ImageDraw, ImageOps

    content = artifact.get("content") or {}
    cards = content.get("cards") if isinstance(content.get("cards"), list) else []
    if not cards:
        raise ValueError("图卡作品没有可导出的卡片")
    if card_index < 0 or card_index >= len(cards):
        raise ValueError("图卡编号无效")
    card = cards[card_index] if isinstance(cards[card_index], dict) else {}
    if any(_has_replacement_text(card.get(key)) for key in ("title", "body", "points", "evidence", "citations")):
        raise ValueError("图卡文字包含编码损坏字符，请重新生成或编辑后再导出")
    image = Image.new("RGB", (1080, 1350), "#f7f9fb")
    draw = ImageDraw.Draw(image)
    ink = "#17212b"
    blue = "#245cb8"
    gold = "#c89b2c"
    muted = "#5e6a75"
    red = "#a63a36"

    draw.rectangle((0, 0, 1080, 118), fill=ink)
    draw.rectangle((0, 118, 1080, 126), fill=gold)
    draw.text((68, 40), "甲骨里的日光缺口", font=_font(30, bold=True), fill="white")
    draw.text((826, 46), f"{card_index + 1:02d} / {len(cards):02d}", font=_font(22), fill="#cad3dc")

    adapter = BailianAdapter()
    prompt = _visual_card_prompt(card)
    background_path = _visual_background_path(
        artifact, card_index, adapter.image_model, prompt
    )
    has_generated_background = bool(
        artifact.get("_allow_generated_visuals", True) and background_path.exists()
    )
    if has_generated_background:
        try:
            with Image.open(background_path) as background:
                visual = ImageOps.fit(background.convert("RGB"), (1080, 410))
                image.paste(visual, (0, 126))
            shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(shade).rectangle((0, 430, 1080, 536), fill=(10, 20, 28, 120))
            image = Image.alpha_composite(image.convert("RGBA"), shade).convert("RGB")
            draw = ImageDraw.Draw(image)
        except OSError:
            has_generated_background = False

    if not has_generated_background:
        # The eclipse mark identifies the science theme when no generated illustration exists.
        draw.ellipse((812, 168, 1000, 356), fill="#f0c958")
        draw.ellipse((754, 145, 942, 333), fill=ink)
        draw.arc((812, 168, 1000, 356), 245, 115, fill=red, width=8)

    title = str(card.get("title") or f"科普图卡 {card_index + 1}")
    title_font = _font(48 if has_generated_background else 54, bold=True)
    title_lines = _wrap_lines(draw, title, title_font, 922 if has_generated_background else 700, 2 if has_generated_background else 3)
    y = 585 if has_generated_background else 188
    for line in title_lines:
        draw.text((68, y), line, font=title_font, fill=ink)
        y += 68 if has_generated_background else 78
    draw.rectangle((68, y + 22, 168, y + 29), fill=blue)

    body = card.get("body") or card.get("points") or ""
    if isinstance(body, list):
        body = "\n".join(f"• {item}" for item in body)
    body_font = _font(28 if has_generated_background else 32)
    body_lines = _wrap_lines(draw, str(body), body_font, 922, 7 if has_generated_background else 16)
    y += 68 if has_generated_background else 76
    for line in body_lines:
        draw.text((72, y), line, font=body_font, fill=ink, spacing=12)
        y += 43 if has_generated_background else 49

    evidence = card.get("evidence") or card.get("citations") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence_text = "；".join(str(item) for item in evidence if str(item).strip()) or "来源页码待补充"
    draw.rounded_rectangle((68, 1086, 1012, 1222), radius=10, fill="#eaf0f8", outline="#c8d5e7", width=2)
    draw.text((94, 1110), "资料依据", font=_font(23, bold=True), fill=blue)
    for offset, line in enumerate(_wrap_lines(draw, evidence_text, _font(22), 865, 3)):
        draw.text((94, 1150 + offset * 31), line, font=_font(22), fill=muted)
    # draw.text((68, 1278), "AI辅助排版 · 需完成事实与视觉审核后发布", font=_font(20), fill=red)

    return image


def render_visual_card_png(artifact: dict[str, Any], card_index: int) -> bytes:
    image = _render_visual_card_image(artifact, card_index)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_visual_card_webp(artifact: dict[str, Any], card_index: int) -> bytes:
    """Return a compact reading preview while keeping PNG for lossless export."""
    from PIL import Image

    image = _render_visual_card_image(artifact, card_index)
    image = image.resize((864, 1080), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=78, method=6)
    return buffer.getvalue()


def _visual_card_zip(artifact: dict[str, Any]) -> bytes:
    cards = (artifact.get("content") or {}).get("cards") or []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(len(cards)):
            archive.writestr(f"card-{index + 1:02d}.png", render_visual_card_png(artifact, index))
        archive.writestr(
            "manifest.json",
            json.dumps(_manifest(artifact), ensure_ascii=False, indent=2),
        )
    return buffer.getvalue()


def _slide_deck(artifact: dict[str, Any]) -> bytes:
    content = normalize_slide_deck_content(artifact.get("content") or {})
    artifact = {**artifact, "content": content}
    slides = content.get("slides") if isinstance(content.get("slides"), list) else []
    if not slides:
        raise ValueError("幻灯片作品没有可导出的页面")
    project_root = Path(__file__).resolve().parent
    runtime_home = Path(os.getenv("USERPROFILE") or os.getenv("HOME") or Path.home())
    node = Path(
        os.getenv(
            "ORACLE_NODE_BIN",
            str(
                runtime_home
                / ".cache"
                / "codex-runtimes"
                / "codex-primary-runtime"
                / "dependencies"
                / "node"
                / "bin"
                / ("node.exe" if os.name == "nt" else "node")
            ),
        )
    )
    exporter = project_root / "tools" / "export_presentation.mjs"
    if not node.is_file():
        raise RuntimeError("未找到用于导出PPTX的Node.js运行环境")
    if not exporter.is_file():
        raise RuntimeError("未找到增强PPTX导出器")
    asset_root = Path(
        os.getenv(
            "ORACLE_EDITOR_ASSET_DIR",
            str(project_root / "source-materials" / "generated" / "editor"),
        )
    )
    with tempfile.TemporaryDirectory(prefix="oracle-slide-export-") as temporary:
        workspace = Path(temporary)
        input_path = workspace / "artifact.json"
        output_path = workspace / "deck.pptx"
        input_path.write_text(
            json.dumps(artifact, ensure_ascii=False), encoding="utf-8"
        )
        try:
            completed = subprocess.run(
                [
                    str(node),
                    str(exporter),
                    str(input_path),
                    str(output_path),
                    str(asset_root),
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("增强PPTX导出超时") from exc
        if completed.returncode != 0 or not output_path.is_file():
            detail = (completed.stderr or completed.stdout or "未知错误").strip()[-1200:]
            raise RuntimeError(f"增强PPTX导出失败：{detail}")
        return _inject_pptx_playback(output_path.read_bytes(), content)


def _inject_pptx_playback(raw: bytes, content: dict[str, Any]) -> bytes:
    presentation_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ET.register_namespace("p", presentation_ns)
    playback = content.get("playback") if isinstance(content.get("playback"), dict) else {}
    slides = content.get("slides") if isinstance(content.get("slides"), list) else []
    default_transition = str(playback.get("transition") or "fade")
    default_seconds = max(3, min(60, float(playback.get("seconds") or 8)))
    auto_advance = bool(playback.get("autoAdvance", False))
    loop = bool(playback.get("loop", False))
    pages: list[dict[str, Any]] = [
        {
            "transition": {
                "type": default_transition,
                "duration": 0.7,
                "advanceAfter": default_seconds,
            }
        },
        *[item if isinstance(item, dict) else {} for item in slides],
    ]
    transition_children = {
        "fade": ("fade", {}),
        "push": ("push", {"dir": "l"}),
        "wipe": ("wipe", {"dir": "l"}),
        "split": ("split", {"orient": "vert", "dir": "out"}),
        "cover": ("cover", {"dir": "l"}),
    }
    source_buffer = io.BytesIO(raw)
    output_buffer = io.BytesIO()
    with zipfile.ZipFile(source_buffer, "r") as source, zipfile.ZipFile(
        output_buffer, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            slide_match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename)
            if slide_match:
                page_index = int(slide_match.group(1)) - 1
                if page_index < len(pages):
                    page = pages[page_index]
                    transition = page.get("transition") if isinstance(page.get("transition"), dict) else {}
                    transition_type = str(transition.get("type") or default_transition)
                    duration = max(0.2, min(3.0, float(transition.get("duration") or 0.7)))
                    seconds = max(
                        3,
                        min(60, float(transition.get("advanceAfter") or default_seconds)),
                    )
                    root = ET.fromstring(data)
                    existing = root.find(f"{{{presentation_ns}}}transition")
                    if existing is not None:
                        root.remove(existing)
                    if transition_type != "none" or auto_advance:
                        speed = "fast" if duration <= 0.45 else ("slow" if duration >= 1.4 else "med")
                        attributes = {"spd": speed, "advClick": "1"}
                        if auto_advance:
                            attributes["advTm"] = str(int(round(seconds * 1000)))
                        transition_element = ET.Element(
                            f"{{{presentation_ns}}}transition", attributes
                        )
                        child = transition_children.get(transition_type)
                        if child:
                            ET.SubElement(
                                transition_element,
                                f"{{{presentation_ns}}}{child[0]}",
                                child[1],
                            )
                        children = list(root)
                        insert_at = next(
                            (
                                index + 1
                                for index, element in enumerate(children)
                                if element.tag
                                == f"{{{presentation_ns}}}clrMapOvr"
                            ),
                            2,
                        )
                        root.insert(insert_at, transition_element)
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            elif info.filename == "ppt/presProps.xml" and (auto_advance or loop):
                root = ET.fromstring(data)
                show = root.find(f"{{{presentation_ns}}}showPr")
                if show is None:
                    show = ET.SubElement(root, f"{{{presentation_ns}}}showPr")
                show.set("useTimings", "1")
                show.set("showAnimation", "1")
                show.set("loop", "1" if loop else "0")
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(info, data)
    return output_buffer.getvalue()


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _video_package(artifact: dict[str, Any]) -> bytes:
    content = artifact.get("content") or {}
    scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
    if not scenes:
        raise ValueError("视频制作包没有可导出的分镜")
    script_lines = [f"# {artifact.get('title') or '视频制作包'}", ""]
    srt_blocks: list[str] = []
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["镜头", "开始秒", "结束秒", "画面", "屏幕文字", "旁白", "资料依据"])
    for index, raw_scene in enumerate(scenes, 1):
        scene = raw_scene if isinstance(raw_scene, dict) else {}
        start = float(scene.get("start") or scene.get("startSeconds") or (index - 1) * 20)
        end = float(scene.get("end") or scene.get("endSeconds") or start + 20)
        narration = str(scene.get("narration") or "").strip()
        visual = str(scene.get("visual") or "").strip()
        on_screen = str(scene.get("onScreenText") or scene.get("text") or "").strip()
        citations = scene.get("citations") or scene.get("evidence") or []
        if isinstance(citations, str):
            citations = [citations]
        citation_text = "；".join(str(value) for value in citations)
        writer.writerow([index, start, end, visual, on_screen, narration, citation_text])
        script_lines.extend(
            [
                f"## 镜头 {index:02d}｜{start:g}–{end:g} 秒",
                f"- 画面：{visual or '待设计'}",
                f"- 屏幕文字：{on_screen or '无'}",
                f"- 旁白：{narration or '待补充'}",
                f"- 资料依据：{citation_text or '页码待补充'}",
                "",
            ]
        )
        caption = narration or on_screen
        if caption:
            srt_blocks.append(
                f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{caption}\n"
            )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("script.md", "\n".join(script_lines))
        archive.writestr("storyboard.csv", "\ufeff" + csv_buffer.getvalue())
        archive.writestr("captions.srt", "\n".join(srt_blocks))
        archive.writestr(
            "manifest.json",
            json.dumps(_manifest(artifact), ensure_ascii=False, indent=2),
        )
    return buffer.getvalue()


def export_artifact(
    artifact: dict[str, Any], export_format: str, *, card_index: int = 0
) -> tuple[bytes, str, str]:
    kind = str(artifact.get("kind") or "")
    title = _safe_filename(str(artifact.get("title") or ""), kind or "artifact")
    if kind == "audio_guide":
        if export_format == "wav":
            return render_audio_wav(artifact), "audio/wav", f"{title}.wav"
        if export_format == "mp3":
            return render_audio_mp3(artifact), "audio/mpeg", f"{title}.mp3"
        raise ValueError("音频导览仅支持MP3播放或WAV导出")
    if kind == "visual_card_set":
        if export_format == "png":
            return render_visual_card_png(artifact, card_index), "image/png", f"{title}-{card_index + 1:02d}.png"
        if export_format == "webp":
            return render_visual_card_webp(artifact, card_index), "image/webp", f"{title}-{card_index + 1:02d}.webp"
        if export_format in {"zip", "png-zip"}:
            return _visual_card_zip(artifact), "application/zip", f"{title}-PNG图卡.zip"
        raise ValueError("科普图卡仅支持PNG预览或PNG图卡包")
    if kind == "slide_deck":
        if export_format != "pptx":
            raise ValueError("讲解幻灯片仅支持PPTX导出")
        return _slide_deck(artifact), "application/vnd.openxmlformats-officedocument.presentationml.presentation", f"{title}.pptx"
    if kind == "video_package":
        if export_format == "mp4":
            video = artifact.get("content", {}).get("video", {}) if isinstance(artifact.get("content"), dict) else {}
            asset_path = str(video.get("assetPath") or "")
            configured = os.getenv("ORACLE_VIDEO_ASSET_DIR", "").strip()
            video_root = Path(configured) if configured else Path(__file__).resolve().parent / "source-materials" / "generated" / "video"
            path = video_root / Path(asset_path).name
            path = path if path.is_file() else (_packaged_media_path(Path(asset_path).name) or path)
            if not asset_path or not path.is_file() or path.suffix.lower() != ".mp4":
                raise ValueError("视频成片尚未生成")
            return path.read_bytes(), "video/mp4", f"{title}.mp4"
        if export_format != "zip":
            raise ValueError("视频作品仅支持MP4播放或ZIP制作包导出")
        return _video_package(artifact), "application/zip", f"{title}.zip"
    raise ValueError("该作品类型没有媒体导出")
