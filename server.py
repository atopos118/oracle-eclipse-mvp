from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import html
import ipaddress
import json
import math
import mimetypes
import os
import posixpath
import re
import secrets
import shutil
import subprocess
import threading
import tempfile
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # Keep the server usable before optional dependencies are installed.
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        env_file = Path(__file__).with_name(".env")
        if not env_file.exists():
            return False
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")
        return True

load_dotenv()

from artifact_content import (
    artifact_references_asset,
    editor_image_path,
    normalize_slide_deck_content,
    store_editor_image,
)
from bailian_adapter import ARTIFACT_TITLES, BailianAdapter, parse_model_json_object
from media_exports import (
    MEDIA_EXPORTS,
    export_artifact,
    generate_visual_card_background,
    public_image_webp,
)
from ocr_pipeline import run_source_ocr
from research_store import (
    MAX_IMPORT_BYTES,
    MAX_SITE_ASSET_BYTES,
    SITE_CONTENT_DEFAULTS,
    SITE_CONTENT_KEYS,
    SITE_SHORTCODES,
    ResearchStore,
    normalize_site_content,
    validate_site_shortcodes,
)
from snapshot_manager import (
    SNAPSHOT_PATH,
    current_snapshot_id,
    delete_snapshot,
    publish_snapshot,
    restore_snapshot,
    snapshot_detail,
    withdraw_artifact,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PUBLIC_MEDIA_DIR = ROOT / "assets" / "public-media"
MAX_JSON_BYTES = 36 * 1024 * 1024
PUBLIC_DATA_PATH = "/data/published-snapshot.json"
OCR_THREADS: dict[str, threading.Thread] = {}
OCR_THREADS_LOCK = threading.Lock()
VIDEO_THREADS: dict[str, threading.Thread] = {}
VIDEO_JOBS: dict[str, dict[str, Any]] = {}
VIDEO_JOBS_LOCK = threading.Lock()
DEFAULT_VIDEO_TOTAL_SECONDS = 15.0
TEST_VIDEO_SCENES = 5
TEST_VIDEO_SCENE_SECONDS = 3.0
RESEARCH_SESSION_COOKIE = "oracle_research_session"
DEFAULT_RESEARCH_SESSION_SECONDS = 8 * 60 * 60
DEFAULT_LOGIN_RATE_LIMIT = 10
DEFAULT_PUBLIC_CHAT_RATE_LIMIT = 30


def environment_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def bounded_environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))

DOCUMENTARY_CREATIVE_FRAMEWORK = {
    "version": "documentary-method-v2",
    "title": "现象—尺度—机制—互动—证据",
    "summary": "把纪录片的沉浸感转化为可观察、可操作、可核验的公众科普体验。",
    "stages": [
        {
            "id": "phenomenon",
            "title": "现象",
            "description": "从天光、影子、温度或日面形态等可观察变化切入，不虚构观测经历。",
        },
        {
            "id": "scale",
            "title": "尺度",
            "description": "在观察者、地球阴影路径和日月地空间关系之间切换尺度。",
        },
        {
            "id": "mechanism",
            "title": "机制",
            "description": "用遮挡、影锥和视位置解释因果，类比必须说明适用边界。",
        },
        {
            "id": "interaction",
            "title": "互动",
            "description": "先让用户预测或操作，再揭示结果和原因，互动不能只是装饰。",
        },
        {
            "id": "evidence",
            "title": "证据",
            "description": "回到已审核资料、页码和争议范围，明确已知、推测与尚不清楚。",
        },
    ],
    "interactionPatterns": [
        {
            "id": "auto",
            "title": "按栏目自动匹配",
            "instruction": "根据当前栏目和现有字段选择一个最有帮助的互动，不虚构页面不存在的控件。",
        },
        {
            "id": "predict_reveal",
            "title": "预测后揭晓",
            "instruction": "先提出一个可以凭观察作答的问题，再揭示结果与科学原因。",
        },
        {
            "id": "alignment_drag",
            "title": "拖动日月地对齐",
            "instruction": "围绕日月地视位置变化组织文案，适配拖动对齐与影锥变化的交互。",
        },
        {
            "id": "timeline_scrub",
            "title": "拖动时间进程",
            "instruction": "按初亏、食甚、复圆等观测进程组织信息，适配时间轴逐步揭示。",
        },
        {
            "id": "type_compare",
            "title": "日食类型对比",
            "instruction": "突出日全食、日环食与日偏食的同一机制和关键差异，适配切换比较。",
        },
        {
            "id": "evidence_layers",
            "title": "证据逐层展开",
            "instruction": "先给公众可读结论，再逐层展开释义、年代、观点、争议与来源边界。",
        },
    ],
    "contentBriefs": {
        "hero": "用一个真实可观察的日食瞬间建立现场感，只保留一个核心悬念和清晰入口。",
        "science": "优先解释日月地关系、影锥与三类日食；让用户先预测，再通过操作理解因果。",
        "history": "从现代可观察现象过渡到甲骨记录，突出记录行为和认识边界，避免神秘化复原。",
        "records": "把条目设计为可展开的研究档案，明确释义、断代、观点、争议和核验状态。",
    },
    "boundary": "纪录片观察笔记只用于叙事、镜头和交互方法；事实必须来自已审核知识。不得复制脚本、下载未授权画面或把影视化重现当作甲骨证据。",
}

DOCUMENTARY_AGENT_METHOD = (
    "当问题适合科学科普时，使用‘现象—尺度—机制—互动—证据’的方法："
    "先从一个可观察变化切入，再切换到太阳—月球—地球的空间尺度解释因果；"
    "必要时给出一个可预测、可比较或可操作的问题，最后回到已知事实、来源与不确定性。"
    "沉浸感来自准确的观察顺序和空间想象，不得虚构亲历场景，不得把类比、影视化重现或纪录片表达当作证据。"
)

SITE_CONTENT_GENERATION_MODES = {
    "section_package": {
        "title": "生成完整栏目",
        "description": "生成栏目引言、导航名称、标题、摘要、HTML、内置组件文案和一张栏目配图。",
        "instruction": (
            "生成当前栏目的完整内容包。面向公众清晰表达，先给可观察现象和核心结论，"
            "再解释机制与证据边界；已有数据简码必须原样保留。"
        ),
    },
    "html_body": {
        "title": "仅生成正文 HTML",
        "description": "读取现有栏目信息和自定义提示词，只替换安全 HTML 正文。",
        "instruction": (
            "只生成当前栏目的HTML正文，不改栏目引言、导航名称、标题、摘要、图片或内置组件配置。"
            "正文应补充结构和阅读体验，不重复标题与摘要；已有数据简码必须原样保留。"
        ),
    },
}


def editor_asset_root() -> Path:
    configured = os.environ.get("ORACLE_EDITOR_ASSET_DIR", "").strip()
    return Path(configured) if configured else ROOT / "source-materials" / "generated" / "editor"


def video_asset_root(*, create: bool = False) -> Path:
    configured = os.environ.get("ORACLE_VIDEO_ASSET_DIR", "").strip()
    root = Path(configured) if configured else ROOT / "source-materials" / "generated" / "video"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def video_asset_path(artifact_id: str) -> Path:
    clean_id = re.sub(r"[^A-Za-z0-9_-]", "", str(artifact_id))
    if not clean_id:
        raise ValueError("作品编号无效")
    return video_asset_root() / f"{clean_id}.mp4"


def public_video_asset_path(artifact_id: str) -> Path:
    """Resolve a published video from the private cache or packaged demo media."""
    generated = video_asset_path(artifact_id)
    if generated.is_file():
        return generated
    packaged = PUBLIC_MEDIA_DIR / generated.name
    return packaged if packaged.is_file() else generated


def packaged_site_asset_path(asset_id: str) -> Path | None:
    """Return a tracked public site asset when the private research DB is absent."""
    if not re.fullmatch(r"siteasset-[0-9a-f]{12}", asset_id):
        return None
    for suffix in (".webp", ".png", ".jpg", ".jpeg", ".mp4", ".webm"):
        candidate = PUBLIC_MEDIA_DIR / f"{asset_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _safe_filename_for_http(value: Any) -> str:
    cleaned = re.sub(r"[^\w\u3400-\u9fff-]+", "-", str(value or "视频成片").strip()).strip("-_")
    return (cleaned or "视频成片")[:80]


def _video_seconds(value: Any, fallback: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def video_storyboard_duration(artifact: dict[str, Any]) -> float:
    """Return the declared storyboard duration, including the last scene boundary."""
    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    declared = _video_seconds(content.get("durationSeconds"), 0.0) or 0.0
    scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
    last_end = 0.0
    for raw_scene in scenes:
        scene = raw_scene if isinstance(raw_scene, dict) else {}
        end = _video_seconds(scene.get("end", scene.get("endSeconds")), 0.0) or 0.0
        last_end = max(last_end, end)
    total = max(declared, last_end)
    return total if total > 0 else 10.0


def shorten_video_storyboard(artifact: dict[str, Any], maximum: float = DEFAULT_VIDEO_TOTAL_SECONDS) -> dict[str, Any]:
    """Scale long storyboards down while keeping every scene boundary proportional."""
    total = video_storyboard_duration(artifact)
    if total <= maximum:
        return artifact
    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    ratio = maximum / total
    scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
    scaled_scenes = []
    for raw_scene in scenes:
        scene = dict(raw_scene) if isinstance(raw_scene, dict) else {}
        for start_key in ("start", "startSeconds"):
            if start_key in scene:
                start = _video_seconds(scene[start_key], 0.0) or 0.0
                scene[start_key] = round(start * ratio, 3)
        for end_key in ("end", "endSeconds"):
            if end_key in scene:
                end = _video_seconds(scene[end_key], 0.0) or 0.0
                scene[end_key] = round(end * ratio, 3)
        scaled_scenes.append(scene)
    return {
        **artifact,
        "content": {
            **content,
            "durationSeconds": round(maximum, 3),
            "scenes": scaled_scenes,
        },
    }


def video_generation_plan(artifact: dict[str, Any], mode: str = "test") -> list[dict[str, float]]:
    """Build the fixed five-shot test plan or a bounded fallback plan."""
    if mode == "test":
        return [
            {
                "start": index * TEST_VIDEO_SCENE_SECONDS,
                "end": (index + 1) * TEST_VIDEO_SCENE_SECONDS,
                "duration": TEST_VIDEO_SCENE_SECONDS,
                "requestDuration": TEST_VIDEO_SCENE_SECONDS,
            }
            for index in range(TEST_VIDEO_SCENES)
        ]
    total = video_storyboard_duration(artifact)
    segment_limit = 8.0
    plan: list[dict[str, float]] = []
    start = 0.0
    while start < total - 1e-6:
        target = min(segment_limit, total - start)
        plan.append({
            "start": start,
            "end": start + target,
            "duration": target,
            "requestDuration": float(max(3, min(8, math.ceil(target)))),
        })
        start += target
    return plan or [{"start": 0.0, "end": total, "duration": total, "requestDuration": float(max(3, min(10, math.ceil(total))))}]


def _safe_video_scene_text(value: Any, *, visual: bool = False) -> str:
    """Remove text-heavy or artifact-reconstruction instructions before image generation."""
    text = clean_answer_text(str(value or ""))
    text = re.sub(r"[‘“\"「『].*?[’”\"」』]", "", text)
    text = re.sub(r"PDF\s*第?\s*\d+\s*页", "相关研究资料", text, flags=re.IGNORECASE)
    if visual and re.search(
        r"文字|字形|原文|拓片|截图|表格|标注|屏幕|大字|小字|字幕|引文|显示|高亮|标出|甲骨",
        text,
    ):
        return "抽象的无文字科学可视化，使用光影、轨迹和色块表达信息"
    return text[:260 if visual else 180]


def video_prompt_from_artifact(
    artifact: dict[str, Any],
    *,
    window_start: float | None = None,
    window_end: float | None = None,
) -> str:
    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
    segments: list[str] = []
    for index, raw_scene in enumerate(scenes[:8], 1):
        scene = raw_scene if isinstance(raw_scene, dict) else {}
        scene_start = _video_seconds(scene.get("start", scene.get("startSeconds")), 0.0) or 0.0
        scene_end = _video_seconds(scene.get("end", scene.get("endSeconds")), None)
        if window_start is not None and window_end is not None and scene_end is not None:
            if scene_end <= window_start or scene_start >= window_end:
                continue
        visual = _safe_video_scene_text(scene.get("visual"), visual=True)
        narration = _safe_video_scene_text(scene.get("narration"))
        if visual or narration:
            timing = f"（{scene_start:g}-{scene_end:g}秒）" if scene_end is not None else ""
            segments.append(f"镜头{index}{timing}：画面{visual}；信息{narration}")
    title = clean_answer_text(str(artifact.get("title") or "甲骨日食科学纪录片"))[:120]
    prompt = (
        f"制作一段关于《{title}》的现代科学纪录片风格短视频，主题是日食观测、日月地运行和甲骨文献研究。"
        "画面为严谨的科学可视化、日食光影、月影和纸本文献的抽象特写，使用现代博物馆展陈质感；"
        "只能生成无文字、无字幕、无标识、无可辨认符号的抽象科学画面；屏幕、地图、表格和文献只能表现为无文字色块与纹理。"
        "不得生成可辨认的汉字、甲骨字形、原文引文、文档图像、水印、伪造甲骨原片、伪造历史人物或未经资料支持的历史场景。"
        "镜头之间平滑剪辑，构图适合16:9横屏，光线稳定，画面清晰。"
    )
    if window_start is not None and window_end is not None:
        prompt += f"本片段对应总片第{window_start:g}-{window_end:g}秒，必须覆盖该时间窗。"
    return (prompt + "分镜参考：" + "；".join(segments))[:3500]


def concatenate_video_segments(segment_paths: list[Path], target_duration: float) -> bytes:
    """Concatenate generated clips and trim the result to the storyboard duration."""
    ffmpeg = os.environ.get("ORACLE_FFMPEG_BIN", "").strip() or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("分镜总时长超过百炼单任务10秒，需要安装FFmpeg后才能拼接视频")
    with tempfile.TemporaryDirectory(prefix="oracle-video-join-") as temporary:
        workspace = Path(temporary)
        concat_file = workspace / "segments.txt"
        output_path = workspace / "joined.mp4"
        lines = []
        for path in segment_paths:
            escaped = path.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-t", f"{max(0.1, target_duration):.3f}",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
            ],
            capture_output=True,
            timeout=900,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size < 8:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[-1000:]
            raise RuntimeError(f"视频片段拼接失败：{detail or 'FFmpeg 未返回有效MP4'}")
        return output_path.read_bytes()


def probe_video_duration(path: Path) -> float | None:
    """Read the final MP4 duration when FFprobe is available alongside FFmpeg."""
    configured = os.environ.get("ORACLE_FFPROBE_BIN", "").strip()
    ffprobe = configured or shutil.which("ffprobe")
    if not ffprobe:
        ffmpeg = os.environ.get("ORACLE_FFMPEG_BIN", "").strip()
        if ffmpeg:
            candidate = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
            if candidate.is_file():
                ffprobe = str(candidate)
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        value = float((completed.stdout or "").strip())
        return value if math.isfinite(value) and value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def rescale_video_storyboard(artifact: dict[str, Any], target: float) -> dict[str, Any]:
    """Keep scene boundaries aligned when the encoded MP4 duration differs slightly."""
    current = video_storyboard_duration(artifact)
    if current <= 0 or target <= 0 or abs(current - target) < 0.05:
        return artifact
    content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
    ratio = target / current
    scenes = content.get("scenes") if isinstance(content.get("scenes"), list) else []
    scaled = []
    for raw_scene in scenes:
        scene = dict(raw_scene) if isinstance(raw_scene, dict) else {}
        for key in ("start", "startSeconds", "end", "endSeconds"):
            if key in scene:
                number = _video_seconds(scene[key], 0.0) or 0.0
                scene[key] = round(number * ratio, 3)
        scaled.append(scene)
    return {**artifact, "content": {**content, "durationSeconds": round(target, 3), "scenes": scaled}}


def video_job_snapshot(artifact_id: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    with VIDEO_JOBS_LOCK:
        job = dict(VIDEO_JOBS.get(artifact_id) or {})
    if job:
        return job
    content = artifact.get("content") if isinstance(artifact, dict) else {}
    video = content.get("video") if isinstance(content, dict) and isinstance(content.get("video"), dict) else {}
    if video:
        return {"artifactId": artifact_id, **video}
    return {"artifactId": artifact_id, "status": "not_started"}


def run_video_job(artifact_id: str, mode: str = "test") -> None:
    try:
        store = research_store()
        artifact = store.get_artifact(artifact_id)
        if not artifact or artifact.get("kind") != "video_package":
            raise ValueError("只有视频制作包可以生成视频成片")
        artifact = rescale_video_storyboard(
            shorten_video_storyboard(artifact, TEST_VIDEO_SCENES * TEST_VIDEO_SCENE_SECONDS),
            TEST_VIDEO_SCENES * TEST_VIDEO_SCENE_SECONDS,
        )
        adapter = BailianAdapter()
        plan = video_generation_plan(artifact, mode)
        storyboard_duration = video_storyboard_duration(artifact)
        with VIDEO_JOBS_LOCK:
            VIDEO_JOBS[artifact_id] = {
                "artifactId": artifact_id,
                "status": "running",
                "model": adapter.video_model,
                "duration": storyboard_duration,
                "segment": 0,
                "segments": len(plan),
            }
        segment_paths: list[Path] = []
        task_ids: list[str] = []
        with tempfile.TemporaryDirectory(
            prefix="oracle-video-segments-", dir=video_asset_root(create=True)
        ) as temporary_dir:
            workspace = Path(temporary_dir)
            for index, segment in enumerate(plan, 1):
                with VIDEO_JOBS_LOCK:
                    VIDEO_JOBS[artifact_id].update({"segment": index, "segments": len(plan)})
                raw, metadata = adapter.generate_video(
                    video_prompt_from_artifact(
                        artifact,
                        window_start=segment["start"],
                        window_end=segment["end"],
                    ),
                    duration=int(segment["requestDuration"]),
                )
                if len(raw) < 8 or not (raw.startswith(b"ftyp") or raw[4:8] == b"ftyp"):
                    raise RuntimeError(f"百炼视频第{index}段返回的文件不是有效MP4")
                segment_path = workspace / f"segment-{index:03d}.mp4"
                segment_path.write_bytes(raw)
                segment_paths.append(segment_path)
                task_id = str(metadata.get("taskId") or "")
                if task_id:
                    task_ids.append(task_id)
            exact_duration = plan[0]["duration"] == plan[0]["requestDuration"]
            raw = (
                segment_paths[0].read_bytes()
                if len(segment_paths) == 1 and exact_duration
                else concatenate_video_segments(segment_paths, storyboard_duration)
            )
        path = video_asset_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".mp4.tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        actual_duration = probe_video_duration(path) or storyboard_duration
        artifact = rescale_video_storyboard(artifact, actual_duration)
        content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
        content = {
            **content,
            "video": {
                "status": "ready",
                "model": metadata.get("model") or adapter.video_model,
                "taskId": task_ids[-1] if task_ids else "",
                "taskIds": task_ids,
                "duration": actual_duration,
                "assetPath": path.name,
                "mimeType": "video/mp4",
            },
        }
        store.mark_artifact_media_changed(
            artifact_id,
            content=content,
            reviewer="百炼视频生成",
            note="视频成片已生成，需重新批准后发布",
        )
        with VIDEO_JOBS_LOCK:
            VIDEO_JOBS[artifact_id] = {
                "artifactId": artifact_id,
                "status": "ready",
                "model": metadata.get("model") or adapter.video_model,
                "duration": actual_duration,
                "taskId": task_ids[-1] if task_ids else "",
                "taskIds": task_ids,
                "segment": len(plan),
                "segments": len(plan),
            }
    except Exception as exc:
        with VIDEO_JOBS_LOCK:
            VIDEO_JOBS[artifact_id] = {
                "artifactId": artifact_id,
                "status": "failed",
                "error": str(exc) or exc.__class__.__name__,
            }
    finally:
        with VIDEO_JOBS_LOCK:
            VIDEO_THREADS.pop(artifact_id, None)


def clean_answer_text(value: str) -> str:
    return re.sub(r"\*{2,}", "", str(value or "")).strip()


def strip_public_attributions(value: Any) -> str:
    """Remove publication/page attribution while retaining nearby oracle text."""
    text = clean_answer_text(str(value or ""))
    text = re.sub(r"《[^》]+》(?=\s*PDF第)", "", text)
    text = re.sub(r"《[^》]+》\s*PDF第[^，。；]*页表[^，。；]*截图", "", text)
    text = re.sub(r"《[^》]+》\s*PDF第[^，。；]*页", "", text)
    text = re.sub(r"PDF第[0-9、\-~]+页(?:表[^，。；]*截图)?", "", text)
    text = re.sub(r"(?:《[^》]+》|[^。；\n]{2,50}(?:研究|日食|行星历表)[^。；\n]{0,30})\s*[·•]\s*(?:PDF\s*)?第\s*\d+页", "", text)
    text = re.sub(r"\s*[·•]\s*(?:PDF\s*)?第\s*\d+页", "", text)
    text = re.sub(r"(?:《(?:癸酉日食说|说“癸酉日食”)》?|故宫博物院藏甲骨卜辞中记载的祖庚时期日食|殷卜辞乙巳日食的初步研究|基于JPL行星历表的殷卜辞乙巳日食观测的研究)\s*", "", text)
    text = re.sub(r"所有(?:画面、文字与旁白|结论)均[^。]*?(?:出处|页码)[^。]*。?", "", text)
    text = re.sub(r"本制作包依据给定资料生成[^。]*。?", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ，,；;。")


def sanitize_media_content(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    """Keep generated media readable without exposing viewpoint citations."""
    if kind not in {"slide_deck", "video_package", "whiteboard", "mind_map"}:
        return content
    result = json.loads(json.dumps(content, ensure_ascii=False))
    collection_key = "slides" if kind == "slide_deck" else "scenes"
    if kind in {"whiteboard", "mind_map"}:
        for node in result.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node["reference"] = {"type": "", "id": "", "label": "", "page": ""}
            for field in ("title", "body"):
                if isinstance(node.get(field), str):
                    node[field] = strip_public_attributions(node[field])
        result.pop("citations", None)
        return result
    for item in result.get(collection_key, []):
        if not isinstance(item, dict):
            continue
        item["citations"] = []
        for field in ("title", "subtitle", "takeaway", "visual", "narration", "onScreenText", "caption"):
            if isinstance(item.get(field), str):
                item[field] = strip_public_attributions(item[field])
        for field in ("bullets",):
            if isinstance(item.get(field), list):
                item[field] = [strip_public_attributions(value) for value in item[field]]
        if isinstance(item.get("richText"), list):
            for line in item["richText"]:
                if isinstance(line, dict):
                    for field in ("lead", "text"):
                        if isinstance(line.get(field), str):
                            line[field] = strip_public_attributions(line[field])
    result.pop("citations", None)
    return result


def public_answer_text(value: str) -> str:
    """Normalize public answers without changing stored research records."""
    return (
        clean_answer_text(value)
        .replace("韩宇娇", "有学者")
        .replace("韩语娇", "有学者")
    )


def generated_image_file_type(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg", ".jpg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("百炼返回的栏目配图格式无效")


def generate_artifact_editor_image(
    artifact: dict[str, Any], prompt: str, *, filename: str, size: str
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("配图提示词不能为空")
    adapter = BailianAdapter()
    raw = adapter.generate_image(clean_prompt, size=size)
    stored = store_editor_image(
        editor_asset_root(),
        str(artifact.get("id") or ""),
        filename,
        base64.b64encode(raw).decode("ascii"),
    )
    return {
        **stored,
        "provider": "aliyun-bailian",
        "model": adapter.image_model,
        "prompt": clean_prompt,
    }


def run_ocr_job(store: ResearchStore, source_id: str, run_id: str) -> None:
    try:
        run_source_ocr(store, source_id, run_id)
    finally:
        with OCR_THREADS_LOCK:
            OCR_THREADS.pop(run_id, None)


class PayloadTooLarge(Exception):
    pass


def normalize_request_path(path: str) -> str:
    decoded = urllib.parse.unquote(path).replace("\\", "/")
    had_trailing_slash = decoded.endswith("/") and decoded != "/"
    normalized = posixpath.normpath("/" + decoded.lstrip("/"))
    if had_trailing_slash and normalized != "/":
        normalized += "/"
    return normalized


def static_path_is_private(path: str) -> bool:
    normalized = normalize_request_path(path)
    private_prefixes = (
        "/source-materials",
        "/tmp",
        "/data/.cache",
        "/__pycache__",
        "/.git",
    )
    if normalized == "/data" or normalized.startswith("/data/"):
        return normalized != PUBLIC_DATA_PATH
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in private_prefixes
    )


def load_json(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def load_published_snapshot() -> dict[str, Any] | None:
    if not SNAPSHOT_PATH.exists():
        return None
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    for work in snapshot.get("works", []):
        if work.get("kind") != "slide_deck" or not isinstance(work.get("content"), dict):
            continue
        try:
            work["content"] = normalize_slide_deck_content(work["content"])
        except ValueError:
            # Keep the published version available even if a legacy deck exceeds
            # current limits; the browser still applies plain-text clipping.
            pass
    return snapshot


def load_all() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = load_published_snapshot()
    if snapshot:
        return (
            snapshot["knowledge"],
            snapshot["recordsMeta"],
            snapshot["literatureMeta"],
        )
    return (
        load_json("knowledge-base.json"),
        load_json("eclipse-records.json"),
        load_json("literature.json"),
    )


def research_store() -> ResearchStore:
    store = ResearchStore()
    store.initialize()
    return store


def site_content_schema(content_key: str) -> dict[str, Any]:
    return SITE_CONTENT_DEFAULTS.get(content_key, {}).get("content", {})


def documentary_generation_context(
    content_key: str,
    interaction_pattern: str,
    reference_notes: str,
) -> dict[str, Any]:
    patterns = DOCUMENTARY_CREATIVE_FRAMEWORK["interactionPatterns"]
    selected = next(
        (item for item in patterns if item["id"] == interaction_pattern),
        None,
    )
    if not selected:
        raise ValueError("纪录片互动模式无效")
    notes = reference_notes.strip()
    if len(notes) > 2000:
        raise ValueError("纪录片观察笔记不能超过2000字")
    return {
        "methodVersion": DOCUMENTARY_CREATIVE_FRAMEWORK["version"],
        "stages": DOCUMENTARY_CREATIVE_FRAMEWORK["stages"],
        "contentBrief": DOCUMENTARY_CREATIVE_FRAMEWORK["contentBriefs"].get(
            content_key, DOCUMENTARY_CREATIVE_FRAMEWORK["summary"]
        ),
        "interactionPattern": selected,
        "creativeReferenceNotes": notes,
        "evidenceBoundary": DOCUMENTARY_CREATIVE_FRAMEWORK["boundary"],
    }


def preserve_site_shortcodes(current_html: str, generated_html: str) -> str:
    result = generated_html
    for shortcode in SITE_SHORTCODES:
        if shortcode in current_html and shortcode not in result:
            result = f"{result}<p>{shortcode}</p>"
    return result


def preserve_site_media_fields(
    content_key: str,
    current_content: dict[str, Any],
    generated_content: dict[str, Any],
) -> dict[str, Any]:
    result = json.loads(json.dumps(generated_content, ensure_ascii=False))
    if content_key == "hero":
        current_slides = current_content.get("slides") if isinstance(current_content.get("slides"), list) else []
        generated_slides = result.get("slides") if isinstance(result.get("slides"), list) else []
        current_by_id = {
            str(item.get("id")): item for item in current_slides
            if isinstance(item, dict) and item.get("id")
        }
        for index, slide in enumerate(generated_slides):
            if not isinstance(slide, dict):
                continue
            current = current_by_id.get(str(slide.get("id")))
            if not current and index < len(current_slides) and isinstance(current_slides[index], dict):
                current = current_slides[index]
            if not current:
                continue
            for field in ("mediaType", "mediaUrl", "assetId", "posterUrl", "posterAssetId"):
                slide[field] = current.get(field, "")
    elif content_key == "history":
        current_image = current_content.get("image") if isinstance(current_content.get("image"), dict) else {}
        generated_image = result.get("image") if isinstance(result.get("image"), dict) else {}
        result["image"] = generated_image
        for field in ("url", "assetId"):
            generated_image[field] = current_image.get(field, "")
    return result


def attach_generated_site_image(
    content_key: str,
    content: dict[str, Any],
    body_html: str,
    asset_id: str,
    image_spec: dict[str, str],
) -> tuple[dict[str, Any], str]:
    result = json.loads(json.dumps(content, ensure_ascii=False))
    alt = clean_answer_text(image_spec.get("alt") or "栏目主题配图")[:160]
    caption = clean_answer_text(image_spec.get("caption") or "AI生成栏目配图，非甲骨原片")[:100]
    if content_key == "hero":
        slides = result.get("slides") if isinstance(result.get("slides"), list) else []
        if slides:
            target = next((item for item in slides if isinstance(item, dict) and item.get("enabled", True)), slides[0])
            if isinstance(target, dict):
                target["mediaType"] = "image"
                target["assetId"] = asset_id
                target["posterAssetId"] = ""
                target["caption"] = caption
        return result, body_html
    if content_key == "history":
        image = result.get("image") if isinstance(result.get("image"), dict) else {}
        image.update({"assetId": asset_id, "alt": alt, "caption": caption})
        result["image"] = image
        return result, body_html
    clean_body = re.sub(
        r'<figure class="site-generated-visual">.*?</figure>',
        "",
        body_html,
        flags=re.DOTALL,
    ).strip()
    figure = (
        '<figure class="site-generated-visual">'
        f'<img src="/api/research/site-content/assets/{asset_id}" alt="{html.escape(alt, quote=True)}">'
        f'<figcaption>{html.escape(caption)}</figcaption></figure>'
    )
    return result, f"{clean_body}{figure}"


def generate_site_content(
    content_key: str,
    current_entry: dict[str, Any],
    generation_mode: str,
    custom_instruction: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], str, str]:
    mode = SITE_CONTENT_GENERATION_MODES.get(generation_mode)
    if not mode:
        raise ValueError("栏目生成范围无效")
    custom_instruction = custom_instruction.strip()
    if len(custom_instruction) > 1600:
        raise ValueError("自定义提示词不能超过1600字")
    instruction = str(mode["instruction"])
    if custom_instruction:
        instruction = f"{instruction}\n用户补充要求：{custom_instruction}"
    adapter = BailianAdapter()
    if adapter.mode != "qwen":
        raise ValueError("尚未配置百炼 API Key，无法使用站点内容 AI 助手")
    public_snapshot = load_published_snapshot() or {}
    knowledge = public_snapshot.get("knowledge") or load_json("knowledge-base.json")
    current_content = current_entry.get("content") if isinstance(current_entry.get("content"), dict) else {}
    current_meta = {
        "title": current_entry.get("title") or "未命名栏目",
        "navLabel": current_entry.get("nav_label") or "栏目",
        "kicker": current_entry.get("kicker") or "",
        "summary": current_entry.get("summary") or "",
        "bodyHtml": current_entry.get("body_html") or "",
    }
    package_mode = generation_mode == "section_package"
    system_prompt = (
        "你是《甲骨里的日光缺口》的站点内容编辑助手。"
        "只输出一个JSON对象，不要输出Markdown、代码围栏或解释。必须完整保留输入示例的字段结构和字段名。"
        "文字要科学准确、面向公众、可视化且适合交互界面；不得补写甲骨原文、著录号、年代或学者结论。"
        "使用‘现象—尺度—机制—互动—证据’框架，但只输出当前字段结构能承载的内容，不得虚构页面控件。"
        "不得声称AI生成画面是甲骨原片，不得复制或模仿任何具体纪录片脚本。"
        "不得创造或修改媒体地址、assetId、posterAssetId、mediaUrl和posterUrl；服务端会单独生成并登记栏目配图。"
        "bodyHtml只能使用输入中列出的简码；简码的方括号、文字和数量必须保持不变。"
        "禁止星号、井号、代码块及生成说明。"
        + (
            "完整栏目模式必须返回title、navLabel、kicker、summary、bodyHtml、content和image。"
            "image只包含prompt、alt、caption；prompt描述一张无文字、无水印、非甲骨原片的科学传播配图。"
            if package_mode else
            "仅HTML模式只能返回bodyHtml，不得返回或修改任何其他字段。"
        )
    )
    schema_example = (
        {
            **current_meta,
            "content": current_content or site_content_schema(content_key),
            "image": {
                "prompt": "栏目配图的中文视觉描述，不包含画面文字",
                "alt": "无障碍替代文字",
                "caption": "图片说明",
            },
        }
        if package_mode else
        {"bodyHtml": current_meta["bodyHtml"]}
    )
    raw = adapter.complete(
        system_prompt,
        {
            "task": str(mode["title"]),
            "generationMode": generation_mode,
            "contentKey": content_key,
            "contentTitle": current_entry.get("title") or SITE_CONTENT_DEFAULTS.get(content_key, {}).get("title") or "公众站栏目",
            "instruction": instruction,
            "currentSection": {**current_meta, "content": current_content},
            "requiredSchemaExample": schema_example,
            "allowedShortcodes": list(SITE_SHORTCODES),
            "verifiedPublicKnowledge": {
                "astronomy": knowledge.get("astronomy", {}),
                "history": knowledge.get("history", {}),
            },
        },
        max_tokens=3600,
        json_mode=True,
    )
    parsed = parse_model_json_object(raw)
    body_html = preserve_site_shortcodes(
        current_meta["bodyHtml"],
        clean_answer_text(parsed.get("bodyHtml") or current_meta["bodyHtml"]),
    )
    if package_mode:
        generated_content = parsed.get("content") if isinstance(parsed.get("content"), dict) else current_content
        generated_content = preserve_site_media_fields(content_key, current_content, generated_content)
        generated_meta = {
            "title": str(parsed.get("title") or current_meta["title"]),
            "nav_label": str(parsed.get("navLabel") or current_meta["navLabel"]),
            "kicker": str(parsed.get("kicker") or current_meta["kicker"]),
            "summary": str(parsed.get("summary") or current_meta["summary"]),
            "body_html": validate_site_shortcodes(body_html),
        }
        raw_image = parsed.get("image") if isinstance(parsed.get("image"), dict) else {}
        image_spec = {
            "prompt": clean_answer_text(raw_image.get("prompt") or f"{generated_meta['title']}，{generated_meta['summary']}，高品质科学纪录片风格，无文字无水印")[:1200],
            "alt": clean_answer_text(raw_image.get("alt") or f"{generated_meta['title']}主题配图")[:160],
            "caption": clean_answer_text(raw_image.get("caption") or "AI生成栏目配图，非甲骨原片")[:100],
        }
    else:
        generated_content = current_content
        generated_meta = {
            "title": current_meta["title"],
            "nav_label": current_meta["navLabel"],
            "kicker": current_meta["kicker"],
            "summary": current_meta["summary"],
            "body_html": validate_site_shortcodes(body_html),
        }
        image_spec = {}
    return (
        normalize_site_content(content_key, generated_content),
        generated_meta,
        image_spec,
        adapter.model,
        f"site-content:{generation_mode}-v1",
    )


def public_snapshot_references_site_asset(snapshot: dict[str, Any], asset_id: str) -> bool:
    site_content = snapshot.get("siteContent") if isinstance(snapshot.get("siteContent"), dict) else {}
    for entry in site_content.values():
        content = entry.get("content") if isinstance(entry, dict) else {}
        if not isinstance(content, dict):
            continue
        if asset_id in str(entry.get("bodyHtml") or ""):
            return True
        if content.get("image", {}).get("assetId") == asset_id:
            return True
        for slide in content.get("slides", []):
            if isinstance(slide, dict) and asset_id in {
                slide.get("assetId"), slide.get("posterAssetId")
            }:
                return True
    return False


def record_text(record: dict[str, Any]) -> str:
    parts = [
        record.get("headline", ""),
        record.get("inscription", ""),
        record.get("translation", ""),
        record.get("dating", ""),
        record.get("catalogNumber", ""),
        record.get("reviewLevel", ""),
        *record.get("scholarViews", []),
        *record.get("disputes", []),
        *(
            item.get("purpose", "")
            for item in record.get("sourceEvidence", [])
        ),
    ]
    return " ".join(map(str, parts)).lower()


def query_terms(query: str) -> list[str]:
    normalized = query.strip().lower()
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", normalized)
    for entity in (
        "乙巳",
        "乙丑",
        "癸酉",
        "祖庚",
        "故宫",
        "合集",
        "宫藏谢",
        "日全食",
        "日环食",
        "日偏食",
    ):
        if entity in normalized:
            terms.append(entity)
    return list(dict.fromkeys(terms))


def select_records(query: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = query_terms(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        haystack = record_text(record)
        score = 0
        for term in terms:
            if term not in haystack:
                continue
            if term.isdigit() and term in str(record.get("catalogNumber", "")):
                score += 12
            elif term in record.get("inscription", ""):
                score += 8
            elif term in str(record.get("catalogNumber", "")):
                score += 7
            elif term in record.get("headline", ""):
                score += 4
            else:
                score += 1
        if score:
            scored.append((score, record))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:3]]


def citations_for(
    selected: list[dict[str, Any]], literature: list[dict[str, Any]]
) -> list[dict[str, str]]:
    by_id = {str(item.get("id")): item for item in literature}
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in selected:
        for evidence in record.get("sourceEvidence", []):
            source_id = str(evidence.get("sourceId", ""))
            item = by_id.get(source_id)
            key = source_id
            if not item or key in seen:
                continue
            seen.add(key)
            title = item.get("title", "来源文献")
            citations.append(
                {
                    "id": source_id,
                    "label": title,
                    "url": item.get("sourceUrl", "#sources"),
                }
            )
        for source_id in record.get("sourceIds", []):
            item = by_id.get(str(source_id))
            if not item or any(
                str(key).startswith(f"{source_id}:") for key in seen
            ) or str(source_id) in seen:
                continue
            seen.add(str(source_id))
            citations.append(
                {
                    "id": str(source_id),
                    "label": item.get("title", "来源文献"),
                    "url": item.get("sourceUrl", "#sources"),
                }
            )
    return citations[:6]


def citations_for_topic(
    topic: dict[str, Any] | None, literature: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not topic:
        return []
    by_id = {str(item.get("id")): item for item in literature}
    source_id = str(topic.get("sourceId", ""))
    source = by_id.get(source_id)
    if not source:
        return []
    title = source.get("title", "来源文献")
    return [
        {
            "id": source_id,
            "label": title,
            "url": source.get("sourceUrl", "#sources"),
        }
    ]


def record_answer(record: dict[str, Any]) -> str:
    disputes = "；".join(
        str(item).rstrip("。；") for item in record.get("disputes", [])
    )
    if disputes:
        disputes += "。"
    return (
        f"{record.get('translation', '')}\n\n"
        f"著录：{record.get('catalogNumber') or '尚待核对'}\n"
        f"年代：{record.get('dating') or '尚不清楚'}。\n"
        f"主要争议：{disputes or '尚待补录'}"
    )


def mock_chat(
    message: str,
    knowledge: dict[str, Any],
    records_meta: dict[str, Any],
    literature_meta: dict[str, Any],
) -> dict[str, Any]:
    records = records_meta.get("records", [])
    literature = literature_meta.get("items", [])
    selected = select_records(message, records)
    lowered = message.lower()
    citation_override: list[dict[str, str]] | None = None

    if re.search(r"凶|吉|预兆|征兆|怎么看|认为", lowered):
        answer = (
            "有学者认为，日月食被视作严重异象或不吉之象："
            "人们会向祖先报告、反复询问祭牲，并担心它是否给商王带来忧祸。"
            "但一条卜辞提出问题，并不等于它已经给出固定的凶吉占断；"
            "具体判断还要结合上下辞、占辞、验辞、材料分期和同类辞例。"
        )
        topic = next(
            (
                item
                for item in records_meta.get("topicEvidence", [])
                if item.get("id") == "shang-attitude"
            ),
            None,
        )
        citation_override = citations_for_topic(topic, literature)
    elif any(name in lowered for name in ("日全食", "日环食", "日偏食")):
        eclipse_type = next(
            (
                item
                for item in knowledge["astronomy"].get("types", [])
                if item["name"] in message
            ),
            None,
        )
        answer = (
            f"{eclipse_type['name']}：{eclipse_type['explanation']}\n\n"
            f"要点：{eclipse_type['fact']}"
            if eclipse_type
            else knowledge["astronomy"]["plainExplanation"]
        )
    elif re.search(r"原理|为什么|怎么发生", lowered):
        answer = (
            f"{knowledge['astronomy']['plainExplanation']}\n\n"
            "月球轨道面与黄道面约有5度倾角，因此多数朔月时，月影会从地球上方或下方掠过。"
        )
    elif re.search(r"记录表|列表|表格|列出|有哪些记录|哪几条|多少条", lowered):
        verified = sum(bool(record.get("reviewed")) for record in records)
        lines = [
            f"{index}. {record['inscription']}｜{record.get('catalogNumber') or '著录待核'}｜{record['status']}"
            for index, record in enumerate(records, 1)
        ]
        answer = (
            f"当前知识库展示{len(records)}条，其中{verified}条已据原刊核验，"
            f"{len(records) - verified}条仍是待取得论文的研究线索：\n"
            + "\n".join(lines)
            + "\n\n这些线索还不是“全部甲骨日食记录”的最终定本。"
        )
        selected = records
    elif selected:
        answer = record_answer(selected[0])
        selected = selected[:1]
    else:
        answer = (
            "现有资料还不足以对这个问题给出可靠结论。"
            "你可以指定“乙巳”“癸酉”或“祖庚时期”，也可以询问日食的科学原理。"
        )

    return {
        "mode": "mock",
        "model": "local-grounded-rules",
        "answer": public_answer_text(answer),
        "citations": citation_override or citations_for(selected, literature),
        "boundary": records_meta.get("scope", ""),
    }


def qwen_chat(
    message: str,
    knowledge: dict[str, Any],
    records_meta: dict[str, Any],
    literature_meta: dict[str, Any],
) -> dict[str, Any]:
    adapter = BailianAdapter()
    if adapter.mode != "qwen":
        return mock_chat(message, knowledge, records_meta, literature_meta)

    records = records_meta.get("records", [])
    selected = select_records(message, records)
    if not selected and re.search(
        r"凶|吉|记录表|列表|哪些|商代|古人|总结|概括|结论|中学生|价值|局限",
        message,
    ):
        selected = records
    literature = literature_meta.get("items", [])
    citations = citations_for(selected, literature)
    relevant_topics = [
        item
        for item in records_meta.get("topicEvidence", [])
        if (
            item.get("id") == "shang-attitude"
            and re.search(r"凶|吉|预兆|征兆|怎么看|认为|忧祸", message)
        )
        or (
            item.get("id") == "shang-ritual"
            and re.search(r"救日|仪式|祭祀", message)
        )
    ]
    if relevant_topics:
        citations = [
            citation
            for topic in relevant_topics
            for citation in citations_for_topic(topic, literature)
        ] + citations
    sources = {
        item["id"]: item
        for item in literature
        if item.get("id") in {source_id for record in selected for source_id in record.get("sourceIds", [])}
    }
    context = {
        "science": knowledge.get("astronomy", {}),
        "historicalInterpretation": knowledge.get("history", {}),
        "records": selected,
        "topicEvidence": relevant_topics,
        "sources": sources,
        "scope": records_meta.get("scope", ""),
    }
    system_prompt = (
        "你是《甲骨里的日光缺口》的公众问答助手。只能依据用户问题后附的资料回答。"
        "不得补写甲骨原文、著录号、年代或学者结论；方框代表无法可靠转写的字，资料不足时直接说尚不清楚。"
        "要区分论文转述、作者观点和类比推测，不要把卜辞中的贞问直接判作固定的凶或吉。"
        "使用清楚、简洁的中文，先回答问题，再说明争议。"
        + DOCUMENTARY_AGENT_METHOD
        + "不要使用Markdown粗体或连续星号。"
        "不要伪造链接或参考文献，引用由系统在回答外统一附加。"
    )
    try:
        answer = adapter.complete(
            system_prompt,
            {"question": message, "groundedContext": context},
        )
        return {
            "mode": "qwen",
            "model": adapter.model,
            "answer": public_answer_text(answer),
            "citations": citations,
            "boundary": records_meta.get("scope", ""),
        }
    except RuntimeError as exc:
        fallback = mock_chat(message, knowledge, records_meta, literature_meta)
        fallback["warning"] = f"百炼调用失败，已切换本地知识库：{exc}"
        return fallback


def select_research_excerpts(
    question: str, excerpts: list[dict[str, Any]], limit: int = 12
) -> list[dict[str, Any]]:
    terms = query_terms(question)
    broad_question = bool(re.search(r"总结|概括|比较|对照|共同|各篇|这些资料", question))
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, excerpt in enumerate(excerpts):
        text = str(excerpt.get("text", "")).lower()
        score = sum(3 if term in text else 0 for term in terms)
        if "日食" in text:
            score += 1
        scored.append((score, -index, excerpt))

    selected: list[dict[str, Any]] = []
    if broad_question or not any(score for score, _, _ in scored):
        per_source: dict[str, int] = {}
        for excerpt in excerpts:
            source_id = str(excerpt.get("sourceId", ""))
            if per_source.get(source_id, 0) >= 2:
                continue
            selected.append(excerpt)
            per_source[source_id] = per_source.get(source_id, 0) + 1
            if len(selected) >= limit:
                break
    else:
        selected = [item for _, _, item in sorted(scored, reverse=True)[:limit]]
    return selected


def research_chat(message: str, context: dict[str, Any]) -> dict[str, Any]:
    excerpts = select_research_excerpts(message, context.get("excerpts", []))
    if not excerpts:
        raise ValueError("所选资料没有可用于问答的解析文本")

    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for excerpt in excerpts:
        source_id = str(excerpt.get("sourceId", ""))
        locator = str(excerpt.get("locator", ""))
        key = f"{source_id}:{locator}"
        if key in seen:
            continue
        seen.add(key)
        locator_label = (
            f"PDF第{locator}页"
            if excerpt.get("locatorType") == "pdf_page"
            else f"原文分段{locator}"
        )
        citations.append(
            {
                "sourceId": source_id,
                "label": f"{excerpt.get('sourceTitle', '资料')} · {locator_label}",
                "locator": locator,
                "locatorType": str(excerpt.get("locatorType", "text_section")),
                "reviewStatus": (
                    "reviewed"
                    if excerpt.get("sourceStatus") == "reviewed"
                    and excerpt.get("sourceRecognitionStatus") in {"text_ready", "ocr_ready"}
                    else "unreviewed"
                ),
            }
        )

    adapter = BailianAdapter()
    warning = ""
    if adapter.mode == "qwen":
        system_prompt = (
        "你是《甲骨里的日光缺口》研究工作台的资料助手。只能依据给定的原始资料摘录和已批准知识回答。"
            "必须区分资料原文、学者观点与模型归纳；不得补写甲骨释文、著录号、断代或日食对应日期。"
            "资料之间冲突时并列说明，依据不足时明确说尚不清楚。回答使用简洁中文，不伪造引文或链接。"
            + DOCUMENTARY_AGENT_METHOD
            + "不要使用Markdown粗体或连续星号。"
            "这是研究草稿，不得声称已经专家复核或公开发布。"
        )
        try:
            answer = adapter.complete(
                system_prompt,
                {
                    "question": message,
                    "approvedKnowledge": context.get("records", []),
                    "sourceExcerpts": excerpts,
                },
                max_tokens=1800,
            )
            mode = "qwen"
            model = adapter.model
        except RuntimeError as exc:
            warning = f"百炼调用失败，已显示相关资料摘录：{exc}"
            mode = "local"
            model = "local-evidence-preview"
            answer = ""
    else:
        mode = "local"
        model = "local-evidence-preview"
        answer = ""

    if not answer:
        lines = [
            f"{index}. {item.get('sourceTitle', '资料')}（{('PDF第' + str(item.get('locator')) + '页') if item.get('locatorType') == 'pdf_page' else '原文分段' + str(item.get('locator'))}）：{str(item.get('text', '')).strip()[:260]}"
            for index, item in enumerate(excerpts[:5], 1)
        ]
        answer = (
            "当前本地模式先返回与问题最相关的资料摘录：\n\n"
            + "\n\n".join(lines)
            + "\n\n以上内容尚未形成经专家复核的结论。"
        )

    return {
        "mode": mode,
        "model": model,
        "answer": clean_answer_text(answer),
        "citations": citations,
        "reviewStatus": (
            "reviewed"
            if all(
                item.get("sourceStatus") == "reviewed"
                and item.get("sourceRecognitionStatus") in {"text_ready", "ocr_ready"}
                for item in excerpts
            )
            else "unreviewed"
        ),
        "boundary": "私有研究回答，可直接用于探索；进入发布知识库或公众作品前必须人工复核。",
        **({"warning": warning} if warning else {}),
    }


def mock_translate(payload: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    audience = payload.get("audience", "public")
    version = knowledge["audienceVersions"].get(
        audience, knowledge["audienceVersions"]["public"]
    )
    return {
        "mode": "mock",
        "model": "local-grounded-rules",
        "title": version["title"],
        "output": version["body"],
        "reviewFlags": knowledge["reviewFlags"],
    }


class AppHandler(SimpleHTTPRequestHandler):
    # Keep deployment identity explicit and overrideable without code edits.
    server_version = f"OracleEclipse/{os.environ.get('ORACLE_APP_VERSION', '1.0.0').strip() or '1.0.0'}"
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        configured_origin = str(getattr(self.server, "public_cors_origin", "") or "")
        request_origin = self.headers.get("Origin", "")
        if configured_origin and request_origin == configured_origin:
            self.send_header("Access-Control-Allow-Origin", configured_origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        if not any(
            header.lower().startswith(b"cache-control:")
            for header in getattr(self, "_headers_buffer", [])
        ):
            request_path = urllib.parse.urlparse(self.path).path
            if request_path.startswith("/assets/") or request_path.endswith((".css", ".js", ".svg", ".webp")):
                self.send_header("Cache-Control", "public, max-age=86400")
            else:
                self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(
        self,
        payload: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_binary(
        self,
        raw: bytes,
        content_type: str,
        filename: str,
        *,
        inline: bool = False,
        cache_control: str = "private, no-store",
    ) -> None:
        disposition = "inline" if inline else "attachment"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f"{disposition}; filename*=UTF-8''{urllib.parse.quote(filename)}",
        )
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(raw)

    def send_video_file(self, path: Path, filename: str, *, public: bool = False) -> None:
        size = path.stat().st_size
        range_header = self.headers.get("Range", "").strip()
        start = 0
        end = size - 1
        status = 200
        if range_header.lower().startswith("bytes="):
            spec = range_header[6:].split(",", 1)[0].strip()
            try:
                first, last = (spec.split("-", 1) + [""])[:2]
                if first:
                    start = int(first)
                    end = int(last) if last else min(size - 1, start + 1024 * 1024 - 1)
                elif last:
                    suffix = int(last)
                    start = max(0, size - suffix)
                else:
                    raise ValueError
                if start < 0 or start >= size or end < start:
                    raise ValueError
                end = min(end, size - 1)
                status = 206
            except (TypeError, ValueError):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header(
            "Content-Disposition",
            f"inline; filename*=UTF-8''{urllib.parse.quote(filename)}",
        )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header(
            "Cache-Control",
            "public, max-age=86400" if public else "private, no-store",
        )
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > MAX_JSON_BYTES:
            raise PayloadTooLarge
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def research_allowed(self) -> bool:
        enabled = bool(getattr(self.server, "research_enabled", False))
        if not enabled:
            return False
        if self.client_address[0] in {"127.0.0.1", "::1"}:
            return True
        return bool(getattr(self.server, "public_demo_network_access", False))

    def request_client_ip(self) -> str:
        peer = str(self.client_address[0])
        proxy_allowed = peer in {"127.0.0.1", "::1"} or bool(
            getattr(self.server, "public_demo_network_access", False)
        )
        if not getattr(self.server, "trust_proxy", False) or not proxy_allowed:
            return peer
        forwarded = self.headers.get("CF-Connecting-IP", "").strip()
        if not forwarded:
            forwarded = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded)) if forwarded else peer
        except ValueError:
            return peer

    def rate_limit_allowed(self, bucket: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        key = (bucket, self.request_client_ip())
        store = getattr(self.server, "rate_limits", {})
        lock = getattr(self.server, "rate_limits_lock", None)

        def update() -> bool:
            recent = [stamp for stamp in store.get(key, []) if stamp > now - window_seconds]
            if len(recent) >= limit:
                store[key] = recent
                return False
            recent.append(now)
            store[key] = recent
            return True

        if lock:
            with lock:
                return update()
        return update()

    def clear_rate_limit(self, bucket: str) -> None:
        key = (bucket, self.request_client_ip())
        store = getattr(self.server, "rate_limits", {})
        lock = getattr(self.server, "rate_limits_lock", None)
        if lock:
            with lock:
                store.pop(key, None)
        else:
            store.pop(key, None)

    def research_auth_required(self) -> bool:
        return bool(getattr(self.server, "research_auth_required", False))

    def research_credentials_configured(self) -> bool:
        return bool(
            getattr(self.server, "research_username", "")
            and getattr(self.server, "research_password_digest", b"")
        )

    def research_session_token(self) -> str:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except Exception:
            return ""
        morsel = cookie.get(RESEARCH_SESSION_COOKIE)
        return morsel.value if morsel else ""

    @staticmethod
    def research_session_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def research_username(self) -> str | None:
        if not self.research_auth_required():
            return str(getattr(self.server, "research_username", "研究用户") or "研究用户")
        token = self.research_session_token()
        if not token:
            return None
        sessions = getattr(self.server, "research_sessions", {})
        lock = getattr(self.server, "research_sessions_lock", None)
        now = time.time()
        session_key = self.research_session_key(token)

        def find_session() -> str | None:
            expired = [key for key, item in sessions.items() if item[1] <= now]
            for key in expired:
                sessions.pop(key, None)
            session = sessions.get(session_key)
            if not session or session[1] <= now:
                return None
            return str(session[0])

        if lock:
            with lock:
                return find_session()
        return find_session()

    def research_login(self, username: str, password: str) -> bool:
        expected_username = str(getattr(self.server, "research_username", ""))
        expected_digest = getattr(self.server, "research_password_digest", b"")
        supplied_digest = hashlib.sha256(password.encode("utf-8")).digest()
        return hmac.compare_digest(
            username.encode("utf-8"), expected_username.encode("utf-8")
        ) and hmac.compare_digest(supplied_digest, expected_digest)

    def create_research_session(self, username: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        ttl = int(
            getattr(
                self.server,
                "research_session_seconds",
                DEFAULT_RESEARCH_SESSION_SECONDS,
            )
        )
        sessions = getattr(self.server, "research_sessions", {})
        lock = getattr(self.server, "research_sessions_lock", None)
        session = (username, time.time() + ttl)
        if lock:
            with lock:
                sessions[self.research_session_key(token)] = session
        else:
            sessions[self.research_session_key(token)] = session
        return token, ttl

    def clear_research_session(self) -> None:
        token = self.research_session_token()
        if not token:
            return
        sessions = getattr(self.server, "research_sessions", {})
        lock = getattr(self.server, "research_sessions_lock", None)
        if lock:
            with lock:
                sessions.pop(self.research_session_key(token), None)
        else:
            sessions.pop(self.research_session_key(token), None)

    def research_cookie(self, token: str, max_age: int) -> str:
        cookie = (
            f"{RESEARCH_SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; "
            "HttpOnly; SameSite=Strict"
        )
        if getattr(self.server, "secure_cookies", False):
            cookie += "; Secure"
        return cookie

    def research_authenticated(self) -> bool:
        return not self.research_auth_required() or self.research_username() is not None

    def require_research(self) -> bool:
        if not self.research_allowed():
            self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
            return False
        if not self.research_auth_required():
            return True
        if not self.research_credentials_configured():
            self.send_json({"error": "研究工作台登录尚未配置"}, 503)
            return False
        if not self.research_authenticated():
            self.send_json({"error": "请先登录研究工作台"}, 401)
            return False
        return True

    def require_research_page(self, request_path: str) -> bool:
        if not self.research_allowed():
            self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
            return False
        if not self.research_auth_required():
            return True
        if not self.research_credentials_configured() or not self.research_authenticated():
            next_path = urllib.parse.quote(request_path, safe="/#!")
            self.send_redirect(f"/research/login.html?next={next_path}")
            return False
        return True

    def research_get(self, parsed: urllib.parse.ParseResult) -> bool:
        if not parsed.path.startswith("/api/research"):
            return False
        if parsed.path == "/api/research/session":
            if not self.research_allowed():
                self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
                return True
            username = self.research_username()
            self.send_json(
                {
                    "configured": self.research_credentials_configured(),
                    "authenticated": username is not None,
                    "username": username,
                    "deploymentMode": (
                        "public_demo"
                        if getattr(self.server, "public_demo", False)
                        else "local"
                    ),
                    "quickLoginEnabled": bool(
                        getattr(self.server, "quick_login_enabled", False)
                        and self.research_credentials_configured()
                    ),
                }
            )
            return True
        if not self.require_research():
            return True
        store = research_store()
        video_status_match = re.fullmatch(
            r"/api/research/artifacts/([^/]+)/video-status", parsed.path
        )
        if video_status_match:
            artifact_id = video_status_match.group(1)
            artifact = store.get_artifact(artifact_id)
            if not artifact:
                self.send_json({"error": "作品不存在"}, 404)
            else:
                self.send_json(video_job_snapshot(artifact_id, artifact))
            return True
        video_match = re.fullmatch(r"/api/research/artifacts/([^/]+)/video", parsed.path)
        if video_match:
            artifact_id = video_match.group(1)
            artifact = store.get_artifact(artifact_id)
            path = public_video_asset_path(artifact_id)
            if not artifact or artifact.get("kind") != "video_package":
                self.send_json({"error": "视频作品不存在"}, 404)
            elif not path.exists():
                self.send_json({"error": "视频成片尚未生成"}, 404)
            else:
                self.send_video_file(path, f"{_safe_filename_for_http(artifact.get('title'))}.mp4")
            return True
        if parsed.path == "/api/research/dashboard":
            self.send_json(store.dashboard())
            return True
        if parsed.path == "/api/research/sources":
            self.send_json({"items": store.list_sources()})
            return True
        if parsed.path == "/api/research/candidates":
            status = urllib.parse.parse_qs(parsed.query).get("status", [None])[0]
            self.send_json({"items": store.list_candidates(status)})
            return True
        if parsed.path == "/api/research/knowledge":
            self.send_json({"items": store.list_published_knowledge(include_stale=True)})
            return True
        if parsed.path == "/api/research/snapshots":
            current_id = current_snapshot_id()
            items = store.list_snapshots()
            for item in items:
                item["current"] = str(item.get("id")) == current_id
            self.send_json({"items": items})
            return True
        if parsed.path == "/api/research/site-content":
            self.send_json(
                {
                    "items": store.list_site_content(include_system=True),
                    "shortcodes": [
                        {"code": code, "renderer": renderer}
                        for code, renderer in SITE_SHORTCODES.items()
                    ],
                    "generationModes": [
                        {"id": key, **value}
                        for key, value in SITE_CONTENT_GENERATION_MODES.items()
                    ],
                }
            )
            return True
        site_asset_match = re.fullmatch(
            r"/api/research/site-content/assets/(siteasset-[0-9a-f]{12})",
            parsed.path,
        )
        if site_asset_match:
            try:
                asset_path, asset = store.site_asset_file(site_asset_match.group(1))
                self.send_binary(
                    asset_path.read_bytes(),
                    str(asset["mime_type"]),
                    str(asset["filename"]),
                    inline=True,
                )
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            return True
        snapshot_detail_match = re.fullmatch(
            r"/api/research/snapshots/([^/]+)", parsed.path
        )
        if snapshot_detail_match:
            try:
                self.send_json(snapshot_detail(store, snapshot_detail_match.group(1)))
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 422)
            return True
        if parsed.path == "/api/research/bailian/status":
            self.send_json(BailianAdapter().public_status())
            return True
        if parsed.path == "/api/research/artifacts":
            status = urllib.parse.parse_qs(parsed.query).get("status", [None])[0]
            self.send_json({"items": store.list_artifacts(status)})
            return True
        if parsed.path == "/api/research/artifact-kinds":
            bailian_status = BailianAdapter().public_status()
            self.send_json({
                "items": [
                    {
                        "id": kind,
                        "title": title,
                        **(
                            {
                                "export": {
                                    **MEDIA_EXPORTS[kind],
                                    **(
                                        {
                                            "provider": "aliyun-bailian",
                                            "model": bailian_status["ttsModel"],
                                            "voice": bailian_status["ttsVoice"],
                                        }
                                        if kind == "audio_guide"
                                        else {
                                            "provider": "aliyun-bailian",
                                            "model": bailian_status["imageModel"],
                                            "generationMode": "explicit-per-card",
                                            "reviewOnGenerate": True,
                                        }
                                        if kind == "visual_card_set"
                                        else {
                                            "provider": "aliyun-bailian",
                                            "model": bailian_status["model"],
                                            "imageModel": bailian_status["imageModel"],
                                            "generationMode": "explicit-per-slide",
                                            "rendering": "artifact-tool-editable-pptx",
                                            "transitions": True,
                                        }
                                        if kind == "slide_deck"
                                        else {
                                            "provider": "aliyun-bailian",
                                            "model": bailian_status["videoModel"],
                                            "generationMode": "async-video",
                                            "durationSeconds": "test: 5x3 seconds; 854x480 (480p)",
                                            "reviewOnGenerate": True,
                                        }
                                        if kind == "video_package"
                                        else {}
                                    ),
                                }
                            }
                            if kind in MEDIA_EXPORTS
                            else {}
                        ),
                    }
                    for kind, title in ARTIFACT_TITLES.items()
                ]
            })
            return True
        artifact_image_match = re.fullmatch(
            r"/api/research/artifacts/([^/]+)/images/([0-9a-f]{64}\.(?:png|jpg|webp))",
            parsed.path,
        )
        if artifact_image_match:
            artifact_id, asset_name = artifact_image_match.groups()
            try:
                if not store.get_artifact(artifact_id):
                    raise KeyError("作品不存在")
                image_path = editor_image_path(editor_asset_root(), artifact_id, asset_name)
                content_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".webp": "image/webp",
                }[image_path.suffix.lower()]
                self.send_binary(
                    image_path.read_bytes(), content_type, asset_name, inline=True
                )
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            return True
        artifact_export_match = re.fullmatch(
            r"/api/research/artifacts/([^/]+)/export", parsed.path
        )
        if artifact_export_match:
            try:
                artifact = store.get_artifact(artifact_export_match.group(1))
                if not artifact:
                    raise KeyError("作品不存在")
                params = urllib.parse.parse_qs(parsed.query)
                default_format = str(
                    MEDIA_EXPORTS.get(str(artifact.get("kind")), {}).get("format", "")
                )
                export_format = params.get("format", [default_format])[0]
                card_index = int(params.get("card", ["0"])[0])
                raw, content_type, filename = export_artifact(
                    artifact, export_format, card_index=card_index
                )
                self.send_binary(
                    raw,
                    content_type,
                    filename,
                    inline=export_format in {"png", "webp", "wav"},
                    cache_control=(
                        "private, max-age=3600"
                        if export_format == "webp"
                        else "private, no-store"
                    ),
                )
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            except (ValueError, RuntimeError, ImportError) as exc:
                self.send_json({"error": str(exc)}, 422)
            return True
        if parsed.path == "/api/research/ocr-runs":
            source_id = urllib.parse.parse_qs(parsed.query).get("sourceId", [""])[0]
            self.send_json({"items": store.list_ocr_runs(source_id or None)})
            return True
        if parsed.path == "/api/research/units":
            source_id = urllib.parse.parse_qs(parsed.query).get("sourceId", [""])[0]
            self.send_json({"items": store.list_units(source_id)})
            return True
        if parsed.path == "/api/research/reviews":
            params = urllib.parse.parse_qs(parsed.query)
            self.send_json({"items": store.list_review_events(params.get("type", [""])[0], params.get("id", [""])[0])})
            return True
        if parsed.path == "/api/research/source-file":
            source_id = urllib.parse.parse_qs(parsed.query).get("sourceId", [""])[0]
            try:
                file_path, filename = store.source_file(source_id)
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
                return True
            raw = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{urllib.parse.quote(filename)}"')
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        if parsed.path == "/api/research/source-page":
            params = urllib.parse.parse_qs(parsed.query)
            source_id = params.get("sourceId", [""])[0]
            try:
                page_number = int(params.get("page", ["1"])[0])
                image_path = store.source_page_image(source_id, page_number)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
                return True
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
                return True
            raw = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        if parsed.path == "/api/research/lineage":
            params = urllib.parse.parse_qs(parsed.query)
            target_type = params.get("type", [""])[0]
            target_id = params.get("id", [""])[0]
            self.send_json({"items": store.lineage_for(target_type, target_id)})
            return True
        self.send_json({"error": "研究接口不存在"}, 404)
        return True

    def research_post(self, path: str, payload: dict[str, Any]) -> bool:
        if not path.startswith("/api/research"):
            return False
        if path == "/api/research/login":
            if not self.research_allowed():
                self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
                return True
            login_limit = int(getattr(self.server, "login_rate_limit", DEFAULT_LOGIN_RATE_LIMIT))
            if not self.rate_limit_allowed("research-login", login_limit, 5 * 60):
                self.send_json(
                    {"error": "登录尝试过于频繁，请5分钟后再试"},
                    429,
                    headers={"Retry-After": "300"},
                )
                return True
            if not self.research_credentials_configured():
                self.send_json({"error": "研究工作台登录尚未配置"}, 503)
                return True
            username = str(payload.get("username", ""))[:128]
            password = str(payload.get("password", ""))[:1024]
            if not self.research_login(username, password):
                self.send_json({"error": "用户名或密码不正确"}, 401)
                return True
            self.clear_rate_limit("research-login")
            token, ttl = self.create_research_session(username)
            self.send_json(
                {"authenticated": True, "username": username},
                headers={"Set-Cookie": self.research_cookie(token, ttl)},
            )
            return True
        if path == "/api/research/quick-login":
            if not self.research_allowed():
                self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
                return True
            if not bool(getattr(self.server, "quick_login_enabled", False)):
                self.send_json({"error": "演示快捷登录未启用"}, 404)
                return True
            if not self.research_credentials_configured():
                self.send_json({"error": "研究工作台登录尚未配置"}, 503)
                return True
            username = str(getattr(self.server, "research_username", "") or "")
            self.clear_rate_limit("research-login")
            token, ttl = self.create_research_session(username)
            self.send_json(
                {"authenticated": True, "username": username, "quickLogin": True},
                headers={"Set-Cookie": self.research_cookie(token, ttl)},
            )
            return True
        if path == "/api/research/logout":
            self.clear_research_session()
            self.send_json(
                {"authenticated": False},
                headers={"Set-Cookie": self.research_cookie("", 0)},
            )
            return True
        if not self.require_research():
            return True
        store = research_store()
        try:
            if path == "/api/research/import":
                kind = str(payload.get("kind", ""))
                if kind == "pdf":
                    encoded = str(payload.get("contentBase64", ""))
                    content = base64.b64decode(encoded, validate=True)
                    result = store.import_pdf_bytes(
                        str(payload.get("filename", "source.pdf")),
                        content,
                        str(payload.get("title", "")),
                    )
                elif kind == "url":
                    result = store.import_url(
                        str(payload.get("url", "")), str(payload.get("title", ""))
                    )
                elif kind == "manual":
                    result = store.import_manual_text(
                        str(payload.get("title", "")), str(payload.get("text", ""))
                    )
                else:
                    raise ValueError("不支持的资料类型")
                auto_parse: dict[str, Any]
                if result.get("status") in {"imported", "parse_failed"}:
                    try:
                        auto_parse = store.parse_source(str(result["id"]), force=False)
                    except Exception as exc:  # Parser libraries expose format-specific errors.
                        auto_parse = {
                            "sourceId": result.get("id"),
                            "status": "parse_failed",
                            "error": str(exc) or "资料自动处理失败",
                        }
                else:
                    auto_parse = {
                        "sourceId": result.get("id"),
                        "status": result.get("status"),
                        "unchanged": True,
                    }
                self.send_json(
                    {**result, "status": auto_parse["status"], "autoParse": auto_parse},
                    200 if result.get("duplicate") else 201,
                )
                return True

            source_match = re.fullmatch(
                r"/api/research/sources/([^/]+)/(parse|reparse|review|unreview|extract|delete|edit|ocr|ocr-reassess|ocr-approve|ocr-reject|ocr-pending)",
                path,
            )
            if source_match:
                source_id, action = source_match.groups()
                if action == "parse":
                    result = store.parse_source(source_id)
                elif action == "reparse":
                    result = store.parse_source(source_id, force=True)
                elif action == "review":
                    result = store.mark_source_reviewed(
                        source_id, str(payload.get("reviewer", "本地审核人"))
                    )
                elif action == "unreview":
                    result = store.unreview_source(
                        source_id, str(payload.get("reviewer", "本地审核人"))
                    )
                elif action == "edit":
                    result = store.update_source(
                        source_id, str(payload.get("title", "")), str(payload.get("reviewer", "本地审核人"))
                    )
                elif action == "extract":
                    result = {"created": store.extract_candidates(source_id)}
                elif action == "ocr-pending":
                    result = store.mark_ocr_pending(
                        source_id, str(payload.get("reason", "人工标记文本质量异常"))
                    )
                elif action == "ocr-reassess":
                    result = store.reassess_ocr_results(source_id)
                elif action in {"ocr-approve", "ocr-reject"}:
                    result = store.review_ocr(
                        source_id,
                        "approve" if action == "ocr-approve" else "reject",
                        str(payload.get("reviewer", "本地审核人")),
                    )
                elif action == "ocr":
                    adapter = BailianAdapter()
                    if not adapter.api_key:
                        raise ValueError("尚未配置百炼 API Key，无法启动OCR")
                    run = store.start_ocr_run(source_id, adapter.ocr_model)
                    run_id = str(run["id"])
                    with OCR_THREADS_LOCK:
                        thread = OCR_THREADS.get(run_id)
                        if not thread or not thread.is_alive():
                            thread = threading.Thread(
                                target=run_ocr_job,
                                args=(store, source_id, run_id),
                                name=f"ocr-{source_id}",
                                daemon=True,
                            )
                            OCR_THREADS[run_id] = thread
                            thread.start()
                    result = {"runId": run_id, "status": run["status"]}
                else:
                    result = store.delete_source(source_id)
                self.send_json(result, 202 if action == "ocr" else 200)
                return True

            candidate_match = re.fullmatch(
                r"/api/research/candidates/([^/]+)/(review|edit)", path
            )
            if candidate_match:
                if candidate_match.group(2) == "edit":
                    result = store.edit_candidate(
                        candidate_match.group(1),
                        title=str(payload.get("title", "")),
                        summary=str(payload.get("summary", "")),
                        content=payload.get("content") if isinstance(payload.get("content"), dict) else {},
                    )
                else:
                    result = store.review_candidate(
                        candidate_match.group(1),
                        str(payload.get("action", "")),
                        reviewer=str(payload.get("reviewer", "本地审核人")),
                        note=str(payload.get("note", "")),
                        content=payload.get("content") if isinstance(payload.get("content"), dict) else None,
                    )
                self.send_json(result)
                return True

            if path == "/api/research/candidates/bulk-review":
                result = store.bulk_review_candidates(
                    [str(item) for item in payload.get("ids", [])],
                    str(payload.get("action", "")),
                )
                self.send_json({"items": result})
                return True

            knowledge_match = re.fullmatch(r"/api/research/knowledge/([^/]+)/(review|edit)", path)
            if knowledge_match:
                knowledge_id, action = knowledge_match.groups()
                if action == "edit":
                    result = store.edit_knowledge(
                        knowledge_id,
                        title=str(payload.get("title", "")),
                        content=payload.get("content") if isinstance(payload.get("content"), dict) else {},
                    )
                else:
                    result = store.review_knowledge(
                        knowledge_id, str(payload.get("action", "")),
                        note=str(payload.get("note", "")),
                    )
                self.send_json(result)
                return True

            if path == "/api/research/knowledge/bulk-review":
                result = [
                    store.review_knowledge(str(item), str(payload.get("action", "")))
                    for item in payload.get("ids", [])
                ]
                self.send_json({"items": result})
                return True

            if path == "/api/research/site-content/assets":
                encoded = str(payload.get("contentBase64", ""))
                if len(encoded) > (MAX_SITE_ASSET_BYTES * 4 // 3) + 16:
                    raise ValueError("站点媒体超过24MB")
                raw = base64.b64decode(encoded, validate=True)
                asset = store.store_site_asset(
                    str(payload.get("filename", "站点媒体")),
                    str(payload.get("mimeType", "")),
                    raw,
                )
                self.send_json(
                    {
                        "id": asset["id"],
                        "filename": asset["filename"],
                        "mediaType": asset["media_type"],
                        "mimeType": asset["mime_type"],
                        "byteSize": asset["byte_size"],
                        "previewUrl": f"/api/research/site-content/assets/{asset['id']}",
                    },
                    201,
                )
                return True

            if path == "/api/research/site-content":
                result = store.create_site_content(
                    title=str(payload.get("title", "")),
                    nav_label=str(payload.get("navLabel", "")),
                    section_type=str(payload.get("sectionType", "standard")),
                    kicker=str(payload.get("kicker", "")),
                    summary=str(payload.get("summary", "")),
                    body_html=str(payload.get("bodyHtml", "<p>在这里编辑栏目正文。</p>")),
                    enabled=bool(payload.get("enabled", True)),
                    reviewer=self.research_username() or "本地编辑人",
                )
                self.send_json(result, 201)
                return True

            if path == "/api/research/site-content/reorder":
                result = store.reorder_site_content(
                    [str(item) for item in payload.get("contentKeys", [])],
                    reviewer=self.research_username() or "本地编辑人",
                )
                self.send_json({"items": result})
                return True

            site_content_match = re.fullmatch(
                r"/api/research/site-content/([a-z][a-z0-9-]{0,60})/(save|generate|review|delete)",
                path,
            )
            if site_content_match:
                content_key, action = site_content_match.groups()
                if action == "delete":
                    store.delete_site_content(
                        content_key,
                        reviewer=self.research_username() or "本地编辑人",
                    )
                    self.send_json({"deleted": content_key})
                    return True
                if action == "save":
                    content = payload.get("content")
                    if not isinstance(content, dict):
                        raise ValueError("站点内容格式无效")
                    result = store.save_site_content(
                        content_key,
                        content,
                        reviewer=self.research_username() or "本地编辑人",
                        title=str(payload["title"]) if "title" in payload else None,
                        section_type=str(payload["sectionType"]) if "sectionType" in payload else None,
                        nav_label=str(payload["navLabel"]) if "navLabel" in payload else None,
                        kicker=str(payload["kicker"]) if "kicker" in payload else None,
                        summary=str(payload["summary"]) if "summary" in payload else None,
                        body_html=str(payload["bodyHtml"]) if "bodyHtml" in payload else None,
                        enabled=bool(payload["enabled"]) if "enabled" in payload else None,
                        sort_order=int(payload["sortOrder"]) if "sortOrder" in payload else None,
                    )
                elif action == "review":
                    result = store.review_site_content(
                        content_key,
                        str(payload.get("action", "")),
                        reviewer=self.research_username() or "本地审核人",
                        note=str(payload.get("note", "")),
                    )
                else:
                    current = store.get_site_content(content_key)
                    if not current:
                        raise KeyError("站点内容不存在")
                    generation_mode = str(payload.get("mode", "section_package"))
                    custom_instruction = str(payload.get("instruction", ""))
                    generated, generated_meta, image_spec, model, prompt_version = generate_site_content(
                        content_key,
                        current,
                        generation_mode,
                        custom_instruction,
                    )
                    generation_warning = ""
                    if image_spec:
                        try:
                            image_bytes = BailianAdapter().generate_image(
                                image_spec["prompt"],
                                size="1280*720" if content_key == "hero" else "1024*1024",
                            )
                            image_mime, image_suffix = generated_image_file_type(image_bytes)
                            asset = store.store_site_asset(
                                f"ai-{content_key}{image_suffix}",
                                image_mime,
                                image_bytes,
                            )
                            generated, generated_meta["body_html"] = attach_generated_site_image(
                                content_key,
                                generated,
                                generated_meta["body_html"],
                                str(asset["id"]),
                                image_spec,
                            )
                        except (ValueError, RuntimeError) as exc:
                            generation_warning = f"栏目文字已生成；配图未生成：{exc}"
                    result = store.save_site_content(
                        content_key,
                        generated,
                        model=model,
                        prompt_version=prompt_version,
                        generation_instruction="\n".join(
                            part
                            for part in (
                                SITE_CONTENT_GENERATION_MODES[generation_mode]["title"],
                                custom_instruction.strip(),
                            )
                            if part
                        ),
                        reviewer=self.research_username() or "本地编辑人",
                        title=generated_meta["title"],
                        section_type=str(current.get("section_type") or "standard"),
                        nav_label=generated_meta["nav_label"],
                        kicker=generated_meta["kicker"],
                        summary=generated_meta["summary"],
                        body_html=generated_meta["body_html"],
                        enabled=bool(current.get("enabled", True)),
                        sort_order=int(current.get("sort_order") or 0),
                    )
                    if generation_warning:
                        result["generation_warning"] = generation_warning
                self.send_json(result, 201 if action == "generate" else 200)
                return True

            if path == "/api/research/ask":
                question = str(payload.get("question", "")).strip()
                if not question:
                    raise ValueError("请输入研究问题")
                if len(question) > 2000:
                    raise ValueError("研究问题过长")
                source_ids = [str(item) for item in payload.get("sourceIds", [])]
                context = store.generation_context(source_ids)
                result = research_chat(question, context)
                result.update({"question": question, "sourceIds": source_ids})
                self.send_json(result)
                return True

            if path == "/api/research/notes/from-answer":
                source_ids = [str(item) for item in payload.get("sourceIds", [])]
                result = store.import_generated_note(
                    title=str(payload.get("title", "AI研究笔记")),
                    question=str(payload.get("question", "")),
                    answer=clean_answer_text(str(payload.get("answer", ""))),
                    source_ids=source_ids,
                    citations=payload.get("citations") if isinstance(payload.get("citations"), list) else [],
                    model=str(payload.get("model", "local-evidence-preview")),
                )
                self.send_json(result, 201)
                return True

            if path == "/api/research/artifacts/from-answer":
                kind = str(payload.get("kind", "research_qa"))
                source_ids = [str(item) for item in payload.get("sourceIds", [])]
                context = store.generation_context(source_ids)
                if kind not in ARTIFACT_TITLES:
                    raise ValueError("作品类型无效")
                answer = clean_answer_text(str(payload.get("answer", "")))
                if not answer:
                    raise ValueError("问答结果为空")
                question = str(payload.get("question", "")).strip()
                citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
                if kind in {"whiteboard", "mind_map"}:
                    nodes = [
                        {
                            "id": "node-answer",
                            "type": "note",
                            "title": question[:160] or "资料问答整理",
                            "body": answer,
                            "x": 465,
                            "y": 300,
                            "width": 270,
                            "height": 170,
                            "color": "gold",
                            "reference": {"type": "", "id": "", "label": "", "page": ""},
                        }
                    ]
                    for index, citation in enumerate(citations[:12], 1):
                        if not isinstance(citation, dict):
                            continue
                        nodes.append(
                            {
                                "id": f"node-source-{index}",
                                "type": "source",
                                "title": str(citation.get("label") or f"引用 {index}")[:160],
                                "body": "问答所依据的已确认资料位置。",
                                "x": 70 + ((index - 1) % 4) * 280,
                                "y": 55 + ((index - 1) // 4) * 190,
                                "width": 235,
                                "height": 125,
                                "color": "green",
                                "reference": {
                                    "type": "source",
                                    "id": str(citation.get("sourceId") or ""),
                                    "label": str(citation.get("label") or ""),
                                    "page": str(citation.get("locator") or ""),
                                },
                            }
                        )
                    content = {
                        "question": question,
                        "layout": "mind_map" if kind == "mind_map" else "free",
                        "viewport": {"width": 1200, "height": 760},
                        "nodes": nodes,
                        "edges": [
                            {
                                "id": f"edge-answer-{index}",
                                "from": "node-answer",
                                "to": node["id"],
                                "label": "依据",
                            }
                            for index, node in enumerate(nodes[1:], 1)
                        ],
                        "citations": citations,
                    }
                else:
                    content = {
                        "question": question,
                        "text": answer,
                        "citations": citations,
                    }
                artifact = store.create_artifact(
                    kind=kind,
                    title=str(payload.get("title", ARTIFACT_TITLES.get(kind, "研究问答草稿"))),
                    content=content,
                    model=str(payload.get("model", "local-evidence-preview")),
                    prompt_version=store.prompt_for(kind)["id"],
                    source_ids=source_ids,
                    unit_ids=context["unitIds"],
                )
                self.send_json(artifact, 201)
                return True

            if path == "/api/research/artifacts/generate":
                kind = str(payload.get("kind", ""))
                source_ids = [str(item) for item in payload.get("sourceIds", [])]
                generation_instruction = str(
                    payload.get("generationInstruction", "")
                ).strip()
                if len(generation_instruction) > 500:
                    raise ValueError("生成要求不能超过500字")
                context = store.generation_context(source_ids)
                prompt = store.prompt_for(kind)
                generated = BailianAdapter().generate_artifact(
                    kind,
                    prompt,
                    context["records"],
                    context["excerpts"],
                    generation_instruction,
                )
                generated["content"] = sanitize_media_content(
                    kind, generated.get("content") or {}
                )
                artifact = store.create_artifact(
                    kind=kind,
                    title=generated["title"],
                    content=generated["content"],
                    model=generated["model"],
                    prompt_version=prompt["id"],
                    generation_instruction=generation_instruction,
                    source_ids=source_ids,
                    unit_ids=context["unitIds"],
                )
                self.send_json(artifact, 201)
                return True

            video_generate_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/generate-video", path
            )
            if video_generate_match:
                artifact_id = video_generate_match.group(1)
                artifact = store.get_artifact(artifact_id)
                if not artifact:
                    raise KeyError("作品不存在")
                if artifact.get("kind") != "video_package":
                    raise ValueError("只有视频制作包可以生成视频成片")
                mode = str(payload.get("mode") or "test").strip().lower()
                if mode != "test":
                    raise ValueError("正式模式暂未制作，请使用测试模式")
                with VIDEO_JOBS_LOCK:
                    existing = VIDEO_THREADS.get(artifact_id)
                    if existing and existing.is_alive():
                        self.send_json(video_job_snapshot(artifact_id, artifact), 202)
                        return True
                    adapter = BailianAdapter()
                    VIDEO_JOBS[artifact_id] = {
                        "artifactId": artifact_id,
                        "status": "queued",
                        "model": adapter.video_model,
                        "mode": mode,
                        "duration": TEST_VIDEO_SCENES * TEST_VIDEO_SCENE_SECONDS,
                        "segments": TEST_VIDEO_SCENES,
                    }
                    thread = threading.Thread(
                        target=run_video_job,
                        args=(artifact_id, mode),
                        name=f"video-{artifact_id}",
                        daemon=True,
                    )
                    VIDEO_THREADS[artifact_id] = thread
                    thread.start()
                self.send_json(video_job_snapshot(artifact_id, artifact), 202)
                return True

            artifact_image_upload_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/images", path
            )
            if artifact_image_upload_match:
                artifact_id = artifact_image_upload_match.group(1)
                if not store.get_artifact(artifact_id):
                    raise KeyError("作品不存在")
                result = store_editor_image(
                    editor_asset_root(),
                    artifact_id,
                    str(payload.get("filename", "图片")),
                    str(payload.get("contentBase64", "")),
                )
                self.send_json(result, 201)
                return True

            card_image_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/generate-card-image", path
            )
            if card_image_match:
                artifact = store.get_artifact(card_image_match.group(1))
                if not artifact:
                    raise KeyError("作品不存在")
                if artifact.get("kind") != "visual_card_set":
                    raise ValueError("只有科普图卡作品可以生成插图")
                card_index = int(payload.get("cardIndex", 0))
                result = generate_visual_card_background(artifact, card_index)
                updated = store.mark_artifact_media_changed(
                    artifact["id"],
                    note=f"第 {card_index + 1} 张图卡生成百炼插图，需重新审核发布",
                )
                self.send_json(
                    {
                        **result,
                        "status": updated.get("status"),
                        "publicationState": updated.get("publication_state"),
                    },
                    201,
                )
                return True

            rich_image_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/generate-rich-image", path
            )
            if rich_image_match:
                artifact = store.get_artifact(rich_image_match.group(1))
                if not artifact:
                    raise KeyError("作品不存在")
                content = artifact.get("content") if isinstance(artifact.get("content"), dict) else {}
                if not isinstance(content.get("html"), str) and not isinstance(content.get("text"), str):
                    raise ValueError("当前作品不是富文本作品")
                visual_id = str(payload.get("visualId") or "")
                visuals = content.get("visuals") if isinstance(content.get("visuals"), list) else []
                planned = next(
                    (
                        item
                        for item in visuals
                        if isinstance(item, dict) and str(item.get("id") or "") == visual_id
                    ),
                    {},
                )
                prompt = str(payload.get("prompt") or planned.get("prompt") or "")
                result = generate_artifact_editor_image(
                    artifact,
                    prompt,
                    filename=f"{visual_id or 'rich-illustration'}.png",
                    size="1024*1024",
                )
                updated = store.mark_artifact_media_changed(
                    artifact["id"],
                    note=f"生成正文配图 {visual_id or result['asset']}，需重新审核发布",
                )
                self.send_json(
                    {
                        **result,
                        "visualId": visual_id,
                        "afterHeading": str(planned.get("afterHeading") or ""),
                        "alt": str(payload.get("alt") or planned.get("alt") or "科普内容配图"),
                        "caption": str(payload.get("caption") or planned.get("caption") or ""),
                        "status": updated.get("status"),
                        "publicationState": updated.get("publication_state"),
                    },
                    201,
                )
                return True

            slide_image_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/generate-slide-image", path
            )
            if slide_image_match:
                artifact = store.get_artifact(slide_image_match.group(1))
                if not artifact:
                    raise KeyError("作品不存在")
                if artifact.get("kind") != "slide_deck":
                    raise ValueError("只有幻灯片作品可以生成页面配图")
                content = dict(artifact.get("content") or {})
                slides = list(content.get("slides") or [])
                slide_index = int(payload.get("slideIndex", 0))
                if slide_index < 0 or slide_index >= len(slides):
                    raise ValueError("幻灯片页码无效")
                slide = dict(slides[slide_index] or {})
                visual = dict(slide.get("visual") or {})
                prompt = str(payload.get("prompt") or visual.get("prompt") or "")
                result = generate_artifact_editor_image(
                    artifact,
                    prompt,
                    filename=f"slide-{slide_index + 1:02d}.png",
                    size="1280*720",
                )
                visual.update(
                    {
                        "prompt": prompt,
                        "asset": result["asset"],
                        "alt": str(payload.get("alt") or visual.get("alt") or "幻灯片配图"),
                        "caption": str(payload.get("caption") or visual.get("caption") or ""),
                    }
                )
                slide["visual"] = visual
                slides[slide_index] = slide
                content["slides"] = slides
                updated = store.mark_artifact_media_changed(
                    artifact["id"],
                    content=content,
                    note=f"第 {slide_index + 1} 页生成百炼配图，需重新审核发布",
                )
                self.send_json(
                    {
                        **result,
                        "slideIndex": slide_index,
                        "status": updated.get("status"),
                        "publicationState": updated.get("publication_state"),
                    },
                    201,
                )
                return True

            artifact_match = re.fullmatch(
                r"/api/research/artifacts/([^/]+)/(review|edit|delete)", path
            )
            if artifact_match:
                artifact_id, action = artifact_match.groups()
                if action == "delete":
                    result = store.delete_artifact(artifact_id)
                elif action == "edit":
                    result = store.edit_artifact(
                        artifact_id,
                        title=str(payload.get("title", "")),
                        content=payload.get("content") if isinstance(payload.get("content"), dict) else {},
                        kind=str(payload.get("kind", "")) or None,
                    )
                else:
                    result = store.review_artifact(
                        artifact_id,
                        str(payload.get("action", "")),
                        reviewer=str(payload.get("reviewer", "本地审核人")),
                        note=str(payload.get("note", "")),
                    )
                self.send_json(result)
                return True

            withdraw_match = re.fullmatch(r"/api/research/artifacts/([^/]+)/withdraw", path)
            if withdraw_match:
                result = withdraw_artifact(
                    store,
                    withdraw_match.group(1),
                    created_by=self.research_username() or "本地审核人",
                )
                self.send_json(result, 201)
                return True

            if path == "/api/research/artifacts/bulk-review":
                result = store.bulk_review_artifacts(
                    [str(item) for item in payload.get("ids", [])],
                    str(payload.get("action", "")),
                )
                self.send_json({"items": result})
                return True

            if path == "/api/research/publish":
                result = publish_snapshot(
                    store,
                    title=str(payload.get("title", "")),
                    description=str(payload.get("description", "")),
                    created_by=self.research_username() or "本地审核人",
                )
                self.send_json(result, 201)
                return True

            if path == "/api/research/bailian/test":
                self.send_json(BailianAdapter().probe())
                return True

            snapshot_match = re.fullmatch(
                r"/api/research/snapshots/([^/]+)/(restore|delete)", path
            )
            if snapshot_match:
                snapshot_id, action = snapshot_match.groups()
                if action == "restore":
                    result = restore_snapshot(
                        store,
                        snapshot_id,
                        created_by=self.research_username() or "本地审核人",
                    )
                    self.send_json(result, 201)
                else:
                    result = delete_snapshot(
                        store,
                        snapshot_id,
                        reviewer=self.research_username() or "本地审核人",
                    )
                    self.send_json(result)
                return True
        except KeyError as exc:
            self.send_json({"error": str(exc).strip("'")}, 404)
            return True
        except (ValueError, RuntimeError, binascii.Error) as exc:
            self.send_json({"error": str(exc)}, 422)
            return True
        self.send_json({"error": "研究接口不存在"}, 404)
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        request_path = normalize_request_path(parsed.path)
        parsed = parsed._replace(path=request_path)
        if static_path_is_private(request_path):
            self.send_json({"error": "该目录仅供本地研究，不通过网站提供"}, 403)
            return
        if self.research_get(parsed):
            return
        if request_path == "/research":
            if not self.require_research_page("/research/"):
                return
            self.send_redirect("/research/")
            return
        login_paths = {
            "/research/login.html",
            "/research/login.css",
            "/research/login.js",
        }
        if request_path in login_paths:
            if not self.research_allowed():
                self.send_json({"error": "研究工作台仅在本机研究模式开放"}, 403)
                return
            if request_path == "/research/login.html" and self.research_authenticated():
                self.send_redirect("/research/")
                return
        elif request_path.startswith("/research/") and not self.require_research_page(
            request_path
        ):
            return
        knowledge, records_meta, literature_meta = load_all()
        snapshot = load_published_snapshot()
        if request_path == "/api/public/snapshot":
            if not snapshot:
                self.send_json({"error": "尚未发布公众内容"}, 404)
            else:
                self.send_json(snapshot)
            return
        public_site_media_match = re.fullmatch(
            r"/api/public/site-media/(siteasset-[0-9a-f]{12})", request_path
        )
        if public_site_media_match:
            asset_id = public_site_media_match.group(1)
            if not snapshot or not public_snapshot_references_site_asset(snapshot, asset_id):
                self.send_json({"error": "该媒体未在当前公众版本中发布"}, 404)
                return
            try:
                asset_path, asset = research_store().site_asset_file(asset_id)
            except KeyError:
                fallback = packaged_site_asset_path(asset_id)
                if not fallback:
                    self.send_json({"error": "站点媒体文件不存在"}, 404)
                    return
                content_type = mimetypes.guess_type(fallback.name)[0] or "application/octet-stream"
                self.send_binary(
                    fallback.read_bytes(),
                    content_type,
                    fallback.name,
                    inline=True,
                    cache_control="public, max-age=604800, immutable",
                )
                return
            try:
                if str(asset.get("media_type")) == "image":
                    raw = public_image_webp(asset_path)
                    filename = f"{Path(str(asset['filename'])).stem}.webp"
                    self.send_binary(raw, "image/webp", filename, inline=True, cache_control="public, max-age=604800, immutable")
                else:
                    self.send_binary(asset_path.read_bytes(), str(asset["mime_type"]), str(asset["filename"]), inline=True, cache_control="public, max-age=86400")
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            return
        public_audio_match = re.fullmatch(
            r"/api/public/artifacts/([^/]+)/audio(?:\.(mp3|wav))?", request_path
        )
        if public_audio_match:
            artifact_id, audio_format = public_audio_match.groups()
            work = next(
                (
                    item
                    for item in (snapshot or {}).get("works", [])
                    if str(item.get("id")) == artifact_id
                    and item.get("kind") == "audio_guide"
                ),
                None,
            )
            if not work:
                self.send_json({"error": "该音频未在当前公众版本中发布"}, 404)
                return
            try:
                raw, content_type, filename = export_artifact(work, audio_format or "wav")
                self.send_binary(raw, content_type, filename, inline=True, cache_control="public, max-age=604800, immutable")
            except (ValueError, RuntimeError) as exc:
                self.send_json({"error": str(exc)}, 422)
            return
        public_video_match = re.fullmatch(
            r"/api/public/artifacts/([^/]+)/video", request_path
        )
        if public_video_match:
            artifact_id = public_video_match.group(1)
            work = next(
                (
                    item
                    for item in (snapshot or {}).get("works", [])
                    if str(item.get("id")) == artifact_id
                    and item.get("kind") == "video_package"
                ),
                None,
            )
            video = ((work or {}).get("content") or {}).get("video", {}) if isinstance((work or {}).get("content"), dict) else {}
            path = public_video_asset_path(artifact_id)
            if not work or video.get("status") != "ready" or not path.exists():
                self.send_json({"error": "该视频未在当前公众版本中发布"}, 404)
            else:
                self.send_video_file(path, f"{_safe_filename_for_http(work.get('title'))}.mp4", public=True)
            return
        public_card_match = re.fullmatch(
            r"/api/public/artifacts/([^/]+)/cards/(\d+)\.(png|webp)", request_path
        )
        if public_card_match:
            artifact_id, page_value, image_format = public_card_match.groups()
            work = next(
                (
                    item
                    for item in (snapshot or {}).get("works", [])
                    if str(item.get("id")) == artifact_id
                    and item.get("kind") == "visual_card_set"
                ),
                None,
            )
            if not work:
                self.send_json({"error": "该图卡未在当前公众版本中发布"}, 404)
                return
            try:
                page_number = int(page_value)
                if page_number < 1:
                    raise ValueError("图卡页码无效")
                visual_backgrounds = (
                    (work.get("media") or {}).get("visualBackgrounds", [])
                    if isinstance(work.get("media"), dict)
                    else []
                )
                public_work = {
                    **work,
                    "_allow_generated_visuals": bool(
                        page_number <= len(visual_backgrounds)
                        and visual_backgrounds[page_number - 1]
                    ),
                }
                raw, content_type, filename = export_artifact(
                    public_work, image_format, card_index=page_number - 1
                )
                self.send_binary(
                    raw,
                    content_type,
                    filename,
                    inline=True,
                    cache_control="public, max-age=86400, immutable",
                )
            except (ValueError, RuntimeError) as exc:
                self.send_json({"error": str(exc)}, 422)
            return
        public_editor_image_match = re.fullmatch(
            r"/api/public/artifacts/([^/]+)/images/([0-9a-f]{64}\.(?:png|jpg|webp))",
            request_path,
        )
        if public_editor_image_match:
            artifact_id, asset_name = public_editor_image_match.groups()
            work = next(
                (
                    item
                    for item in (snapshot or {}).get("works", [])
                    if str(item.get("id")) == artifact_id
                ),
                None,
            )
            if not work or not artifact_references_asset(
                work.get("content") if isinstance(work.get("content"), dict) else {},
                artifact_id,
                asset_name,
            ):
                self.send_json({"error": "该图片未在当前公众版本中发布"}, 404)
                return
            try:
                image_path = editor_image_path(editor_asset_root(), artifact_id, asset_name)
                content_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".webp": "image/webp",
                }[image_path.suffix.lower()]
                self.send_binary(
                    image_path.read_bytes(), content_type, asset_name, inline=True
                )
            except KeyError as exc:
                self.send_json({"error": str(exc).strip("'")}, 404)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            return
        if request_path == "/api/health":
            adapter = BailianAdapter()
            self.send_json(
                {
                    "ok": True,
                    "mode": "qwen" if adapter.mode == "qwen" else "mock",
                    "model": adapter.model,
                    "records": len(records_meta.get("records", [])),
                    "sources": len(literature_meta.get("items", [])),
                    "snapshotId": snapshot.get("snapshotId") if snapshot else None,
                    "researchEnabled": self.research_allowed(),
                }
            )
            return
        if request_path == "/api/snapshot":
            self.send_json(snapshot or {"error": "尚未发布快照"}, 200 if snapshot else 404)
            return
        if request_path == "/api/knowledge":
            self.send_json(knowledge)
            return
        if request_path == "/api/records":
            self.send_json(records_meta)
            return
        if request_path == "/api/literature":
            self.send_json(literature_meta)
            return
        if request_path == "/api/evidence":
            self.send_json(
                snapshot.get("evidenceRegister", {}) if snapshot else load_json("evidence-register.json")
            )
            return
        if request_path == "/api/search":
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            records = select_records(query, records_meta.get("records", []))
            self.send_json({"query": query, "count": len(records), "records": records})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self.read_json()
        except PayloadTooLarge:
            self.send_json({"error": "请求超过36MB限制"}, 413)
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json({"error": "请求内容不是有效 JSON"}, 400)
            return
        path = urllib.parse.urlparse(self.path).path
        if self.research_post(path, payload):
            return
        knowledge, records_meta, literature_meta = load_all()
        if path == "/api/chat":
            message = str(payload.get("message", "")).strip()
            if not message:
                self.send_json({"error": "问题不能为空"}, 400)
                return
            if len(message) > 2000:
                self.send_json({"error": "问题不能超过2000字"}, 400)
                return
            chat_limit = int(
                getattr(self.server, "public_chat_rate_limit", DEFAULT_PUBLIC_CHAT_RATE_LIMIT)
            )
            if not self.rate_limit_allowed("public-chat", chat_limit, 60):
                self.send_json(
                    {"error": "公众问答请求过于频繁，请稍后再试"},
                    429,
                    headers={"Retry-After": "60"},
                )
                return
            self.send_json(qwen_chat(message, knowledge, records_meta, literature_meta))
            return
        if path == "/api/translate":
            self.send_json(mock_translate(payload, knowledge))
            return
        self.send_json({"error": "接口不存在"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="甲骨里的日光缺口 web service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="禁用研究工作台和研究API",
    )
    parser.add_argument(
        "--public-demo",
        action="store_true",
        help="经HTTPS反向代理公开公众站和受登录保护的研究工作台",
    )
    args = parser.parse_args()
    if args.public_only and args.public_demo:
        parser.error("--public-only 与 --public-demo 不能同时使用")
    mimetypes.add_type("application/javascript", ".js")
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    is_loopback = args.host in {"127.0.0.1", "::1", "localhost"}
    allow_non_loopback_public_demo = environment_flag(
        "ORACLE_ALLOW_NONLOOPBACK_PUBLIC_DEMO"
    )
    public_demo_allowed = bool(
        args.public_demo and (is_loopback or allow_non_loopback_public_demo)
    )
    if args.public_demo and not public_demo_allowed:
        server.server_close()
        parser.error(
            "非回环地址启用比赛演示模式必须设置ORACLE_ALLOW_NONLOOPBACK_PUBLIC_DEMO=1"
        )
    # Loopback runs are the local research mode; public-demo is additionally
    # allowed when explicitly requested and remains subject to authentication.
    server.research_enabled = bool((is_loopback or public_demo_allowed) and not args.public_only)  # type: ignore[attr-defined]
    server.public_demo = bool(args.public_demo)  # type: ignore[attr-defined]
    server.public_demo_network_access = bool(public_demo_allowed)  # type: ignore[attr-defined]
    username = os.environ.get("ORACLE_RESEARCH_USERNAME", "").strip()
    password = os.environ.get("ORACLE_RESEARCH_PASSWORD", "")
    server.research_auth_required = bool(server.research_enabled)  # type: ignore[attr-defined]
    # Local research mode is already loopback-only, so a configured account may
    # use the convenience entry. Public demo mode keeps it opt-in explicitly.
    server.quick_login_enabled = bool(  # type: ignore[attr-defined]
        server.research_enabled
        and username
        and password
        and (not server.public_demo or environment_flag("ORACLE_QUICK_LOGIN_ENABLED"))
    )
    server.research_username = username  # type: ignore[attr-defined]
    server.research_password_digest = (  # type: ignore[attr-defined]
        hashlib.sha256(password.encode("utf-8")).digest() if password else b""
    )
    server.research_sessions = {}  # type: ignore[attr-defined]
    server.research_sessions_lock = threading.Lock()  # type: ignore[attr-defined]
    server.secure_cookies = bool(  # type: ignore[attr-defined]
        args.public_demo or environment_flag("ORACLE_SECURE_COOKIES")
    )
    server.trust_proxy = bool(  # type: ignore[attr-defined]
        args.public_demo or environment_flag("ORACLE_TRUST_PROXY")
    )
    server.public_cors_origin = os.environ.get("ORACLE_PUBLIC_CORS_ORIGIN", "").strip()  # type: ignore[attr-defined]
    server.rate_limits = {}  # type: ignore[attr-defined]
    server.rate_limits_lock = threading.Lock()  # type: ignore[attr-defined]
    server.login_rate_limit = bounded_environment_int(  # type: ignore[attr-defined]
        "ORACLE_LOGIN_RATE_LIMIT", DEFAULT_LOGIN_RATE_LIMIT, 3, 100
    )
    server.public_chat_rate_limit = bounded_environment_int(  # type: ignore[attr-defined]
        "ORACLE_PUBLIC_CHAT_RATE_LIMIT", DEFAULT_PUBLIC_CHAT_RATE_LIMIT, 1, 300
    )
    try:
        session_hours = float(os.environ.get("ORACLE_RESEARCH_SESSION_HOURS", "8"))
    except ValueError:
        session_hours = 8
    server.research_session_seconds = int(  # type: ignore[attr-defined]
        max(0.25, min(session_hours, 72)) * 60 * 60
    )
    if args.public_demo and not (username and password):
        server.server_close()
        parser.error("比赛演示模式必须配置ORACLE_RESEARCH_USERNAME和ORACLE_RESEARCH_PASSWORD")
    print(f"Serving {ROOT} at http://{args.host}:{args.port}", flush=True)
    if args.public_demo:
        print(
            "Public demo mode: HTTPS proxy required; secure cookies and proxy-aware rate limits enabled.",
            flush=True,
        )
    if server.research_enabled and not (username and password):
        print(
            "Research login is not configured. Set ORACLE_RESEARCH_USERNAME and "
            "ORACLE_RESEARCH_PASSWORD before opening /research/.",
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
