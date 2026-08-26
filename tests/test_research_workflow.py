from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import io
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server as server_module
from artifact_content import (
    artifact_references_asset,
    editor_image_path,
    normalize_artifact_content,
    normalize_board_content,
    normalize_record_table,
    normalize_rich_visuals,
    normalize_slide_deck_content,
    research_asset_url,
    sanitize_rich_html,
    store_editor_image,
)
from bailian_adapter import (
    ARTIFACT_TITLES,
    BailianAdapter,
    clean_audio_script,
    clean_public_explainer,
    describe_request_error,
    parse_model_json_object,
    select_artifact_excerpts,
)
from media_exports import (
    audio_duration_seconds,
    export_artifact,
    generate_visual_card_background,
    public_image_webp,
    render_audio_mp3,
    render_visual_card_png,
    render_visual_card_webp,
)
from research_store import (
    ResearchStore,
    compact_locator_values,
    group_lineage_edges,
)
from server import (
    AppHandler,
    clean_answer_text,
    load_all,
    mock_chat,
    qwen_chat,
    research_chat,
    rescale_video_storyboard,
    shorten_video_storyboard,
    static_path_is_private,
    video_generation_plan,
    video_prompt_from_artifact,
    video_storyboard_duration,
)
from snapshot_manager import (
    build_snapshot,
    delete_snapshot,
    publish_snapshot,
    restore_snapshot,
    snapshot_detail,
    withdraw_artifact,
)
from text_quality import assess_text_quality


ROOT = Path(__file__).resolve().parents[1]


def test_wav_bytes(duration_seconds: float = 0.12) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * int(16000 * duration_seconds))
    return buffer.getvalue()


def test_png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), "#183f55").save(buffer, format="PNG")
    return buffer.getvalue()


class ResearchWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {"DASHSCOPE_API_KEY": ""})
        self.environment.start()
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.private_dir = Path(self.temp.name)
        os.environ["ORACLE_AUDIO_CACHE_DIR"] = str(self.private_dir / "audio-cache")
        os.environ["ORACLE_IMAGE_CACHE_DIR"] = str(self.private_dir / "image-cache")
        self.store = ResearchStore(self.private_dir / "research.db", self.private_dir)
        self.store.initialize()

    def test_private_source_paths_are_portable_between_windows_and_linux(self) -> None:
        store = ResearchStore(ROOT / "tmp" / "portable-paths.db")
        expected = ROOT / "source-materials" / "imports" / "example.pdf"
        self.assertEqual(
            store._resolved_private_path(r"source-materials\imports\example.pdf"),
            expected,
        )
        self.assertEqual(
            store._stored_path(expected),
            "source-materials/imports/example.pdf",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.environment.stop()

    def test_video_generation_uses_storyboard_duration_and_segments_long_runs(self) -> None:
        artifact = {
            "content": {
                "durationSeconds": 180,
                "scenes": [{"start": 0, "end": 20}, {"start": 20, "end": 180}],
            }
        }
        self.assertEqual(video_storyboard_duration(artifact), 180)
        plan = video_generation_plan(artifact)
        self.assertEqual(len(plan), 5)
        self.assertEqual(plan[0]["requestDuration"], 3)
        self.assertEqual(plan[-1]["end"], 15)

    def test_long_video_storyboard_scales_to_one_minute(self) -> None:
        artifact = {
            "content": {
                "durationSeconds": 180,
                "scenes": [{"start": 0, "end": 20}, {"start": 20, "end": 180}],
            }
        }
        shortened = shorten_video_storyboard(artifact)
        self.assertEqual(shortened["content"]["durationSeconds"], 15)
        self.assertEqual(shortened["content"]["scenes"][-1]["end"], 15)
        self.assertEqual(len(video_generation_plan(shortened)), 5)

    def test_video_storyboard_rescales_to_encoded_duration(self) -> None:
        artifact = {
            "content": {
                "durationSeconds": 60,
                "scenes": [{"start": 0, "end": 30}, {"start": 30, "end": 60}],
            }
        }
        adjusted = rescale_video_storyboard(artifact, 58.4)
        self.assertEqual(adjusted["content"]["durationSeconds"], 58.4)
        self.assertEqual(adjusted["content"]["scenes"][-1]["end"], 58.4)

    def test_video_generation_keeps_short_storyboard_duration_and_filters_prompt_window(self) -> None:
        artifact = {
            "title": "时间窗测试",
            "content": {
                "durationSeconds": 8,
                "scenes": [
                    {"start": 0, "end": 4, "visual": "第一镜头", "narration": "甲"},
                    {"start": 4, "end": 8, "visual": "第二镜头", "narration": "乙"},
                ],
            },
        }
        plan = video_generation_plan(artifact)
        self.assertEqual(plan[0]["requestDuration"], 3)
        prompt = video_prompt_from_artifact(artifact, window_start=0, window_end=4)
        self.assertIn("第一镜头", prompt)
        self.assertNotIn("第二镜头", prompt)

    def test_video_prompt_strips_text_and_artifact_reconstruction_requests(self) -> None:
        artifact = {
            "content": {
                "durationSeconds": 8,
                "scenes": [{
                    "start": 0,
                    "end": 8,
                    "visual": "显示甲骨拓片原文、PDF截图并高亮文字",
                    "narration": "依据‘癸酉贞，日夕有食’原文说明。",
                }],
            }
        }
        prompt = video_prompt_from_artifact(artifact)
        self.assertIn("无文字科学可视化", prompt)
        self.assertNotIn("PDF截图", prompt)
        self.assertNotIn("癸酉贞", prompt)

    def seed_manual_source(self) -> tuple[str, str]:
        source = self.store.import_manual_text(
            "测试日食材料",
            "乙丑卜，贞：日有食，不唯□。学者甲认为是忧祸，学者乙认为年代尚待核验。",
        )
        source_id = source["id"]
        self.store.parse_source(source_id)
        self.store.mark_source_reviewed(source_id, "测试审核人")
        candidates = self.store.extract_candidates(source_id)
        self.assertGreaterEqual(len(candidates), 1)
        candidate_id = candidates[0]["id"]
        self.store.review_candidate(candidate_id, "approve", reviewer="测试审核人")
        return source_id, candidate_id

    def seed_pdf_source(self) -> str:
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        document = canvas.Canvas(buffer)
        document.drawString(72, 760, "OCR page 1")
        document.showPage()
        document.drawString(72, 760, "OCR page 2")
        document.save()
        source = self.store.import_pdf_bytes("ocr-test.pdf", buffer.getvalue(), "OCR测试论文")
        return source["id"]

    def test_bailian_network_errors_remain_actionable(self) -> None:
        self.assertEqual(describe_request_error(TimeoutError()), "请求超时")
        error = urllib.error.URLError("连接被阻止")
        self.assertEqual(describe_request_error(error), "网络不可达（连接被阻止）")
        permission_error = urllib.error.URLError(
            OSError(10013, "socket access was denied")
        )
        detail = describe_request_error(permission_error)
        self.assertIn("本机阻止了百炼 HTTPS 出站连接", detail)
        self.assertIn("dashscope.aliyuncs.com:443", detail)

    def test_bailian_overdue_account_error_is_actionable(self) -> None:
        error = urllib.error.HTTPError(
            "https://dashscope.aliyuncs.com/api/v1/tasks",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"message":"Access denied: overdue payment"}'),
        )
        self.assertIn("账号欠费", describe_request_error(error))

    def test_artifact_model_context_is_bounded_with_source_coverage(self) -> None:
        excerpts = [
            {
                "sourceId": f"source-{source}",
                "sourceTitle": f"资料{source}",
                "locator": str(page),
                "text": ("日食 卜辞 争议 " if page % 3 == 0 else "一般文字 ") + "甲" * 1800,
            }
            for source in range(7)
            for page in range(16)
        ]
        selected = select_artifact_excerpts(excerpts)
        self.assertLessEqual(len(selected), 32)
        self.assertTrue(all(len(item["text"]) <= 1200 for item in selected))
        source_counts = {
            source_id: sum(item["sourceId"] == source_id for item in selected)
            for source_id in {item["sourceId"] for item in selected}
        }
        self.assertEqual(len(source_counts), 7)
        self.assertTrue(all(count <= 5 for count in source_counts.values()))

    def test_artifact_timeout_falls_back_to_local_evidence_template(self) -> None:
        adapter = BailianAdapter()
        adapter.api_key = "test-only"
        with patch.object(
            adapter,
            "complete",
            side_effect=RuntimeError("百炼调用失败：请求超时"),
        ):
            result = adapter.generate_artifact(
                "whiteboard",
                {"template": "生成白板"},
                [],
                [
                    {
                        "sourceId": "source-1",
                        "sourceTitle": "测试论文",
                        "locatorType": "pdf_page",
                        "locator": "3",
                        "text": "乙巳日有食，相关解释仍有争议。",
                    }
                ],
            )
        self.assertEqual(
            result["model"], "local-grounded-templates-after-bailian-timeout"
        )
        self.assertGreaterEqual(len(result["content"]["nodes"]), 1)

    def test_bailian_tts_uses_configured_model_voice_and_merges_chunks(self) -> None:
        requests: list[dict[str, object]] = []

        class AudioResponse:
            headers = {"Content-Type": "audio/wav"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return test_wav_bytes()

        def fake_urlopen(request, timeout=0):
            self.assertEqual(timeout, 120)
            requests.append(json.loads(request.data.decode("utf-8")))
            return AudioResponse()

        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "test-key",
                "QWEN_TTS_MODEL": "qwen3-tts-flash",
                "QWEN_TTS_VOICE": "Cherry",
            },
        ):
            with patch("bailian_adapter.urllib.request.urlopen", side_effect=fake_urlopen):
                raw = BailianAdapter().synthesize_wav("甲" * 600)

        self.assertEqual(len(requests), 2)
        self.assertTrue(all(item["model"] == "qwen3-tts-flash" for item in requests))
        self.assertTrue(all(item["input"]["voice"] == "Cherry" for item in requests))
        self.assertTrue(all(item["input"]["language_type"] == "Chinese" for item in requests))
        self.assertTrue(all(item["input"]["text"] for item in requests))
        self.assertGreater(audio_duration_seconds(raw), 0.2)

    def test_bailian_tts_accepts_native_audio_url_response(self) -> None:
        downloaded_urls: list[str] = []

        class JsonResponse:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "output": {
                            "audio": {
                                "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav"
                            }
                        }
                    }
                ).encode("utf-8")

        class AudioResponse:
            headers = {"Content-Type": "audio/wav"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return test_wav_bytes()

        def fake_urlopen(request_or_url, timeout=0):
            if isinstance(request_or_url, str):
                self.assertEqual(timeout, 90)
                downloaded_urls.append(request_or_url)
                return AudioResponse()
            return JsonResponse()

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with patch("bailian_adapter.urllib.request.urlopen", side_effect=fake_urlopen):
                raw = BailianAdapter().synthesize_wav("测试音频")
        self.assertTrue(raw.startswith(b"RIFF"))
        self.assertEqual(
            downloaded_urls,
            ["https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/test.wav"],
        )

    def test_bailian_tts_rejects_non_aliyun_audio_url(self) -> None:
        adapter = BailianAdapter()
        with self.assertRaisesRegex(RuntimeError, "example.com"):
            adapter._download_audio_result("https://example.com/audio.wav")

    def test_audio_script_cleaner_removes_only_generation_preamble(self) -> None:
        text = (
            "以下是一份约3分钟的中文音频导览脚本草稿，严格依据您提供的全部资料编写。\n\n"
            "——\n各位观众，欢迎收听甲骨日食主题导览。"
        )
        self.assertEqual(clean_audio_script(text), "各位观众，欢迎收听甲骨日食主题导览。")
        self.assertEqual(
            clean_audio_script("以下为音频导览脚本草稿，资料待审核。\n\n---\n正文开始。"),
            "正文开始。",
        )
        normal = "各位观众，欢迎收听甲骨日食主题导览。\n\n今天我们从日食原理开始。"
        self.assertEqual(clean_audio_script(normal), normal)

    def test_public_explainer_removes_markdown_bold_markers(self) -> None:
        self.assertEqual(
            clean_public_explainer("**一、结论**\n\n这是**大众讲解**。"),
            "一、结论\n\n这是大众讲解。",
        )

    def test_question_answers_remove_markdown_double_stars(self) -> None:
        self.assertEqual(
            clean_answer_text("**结论**\n\n这是***重点***。"),
            "结论\n\n这是重点。",
        )
        result = research_chat(
            "资料怎样记载？",
            {
                "records": [],
                "excerpts": [
                    {
                        "sourceId": "source-test",
                        "sourceTitle": "测试资料",
                        "sourceStatus": "reviewed",
                        "sourceRecognitionStatus": "text_ready",
                        "locator": "1",
                        "locatorType": "pdf_page",
                        "text": "**乙巳日有食**，夕告于上甲。",
                    }
                ],
            },
        )
        self.assertNotIn("**", result["answer"])

    def test_public_qwen_summary_gets_sources_but_out_of_scope_question_does_not(self) -> None:
        knowledge, records_meta, literature = load_all()
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-only"}):
            with patch.object(BailianAdapter, "complete", return_value="按发布资料概括。"):
                summary = qwen_chat(
                    "用中学生能理解的语言概括三个结论",
                    knowledge,
                    records_meta,
                    literature,
                )
                out_of_scope = qwen_chat(
                    "玛雅人如何记录日食？请只根据这个项目的资料回答。",
                    knowledge,
                    records_meta,
                    literature,
                )
        self.assertGreaterEqual(len(summary["citations"]), 1)
        self.assertEqual(out_of_scope["citations"], [])

    def test_record_table_editor_content_is_normalized(self) -> None:
        content = normalize_record_table(
            {
                "columns": ["卜辞", "年代"],
                "rows": [{"卜辞": "日有食", "年代": "尚不清楚", "隐藏字段": "不保留"}],
                "note": "保留作品级字段",
            }
        )
        self.assertEqual(content["columns"], ["卜辞", "年代"])
        self.assertEqual(content["rows"], [{"卜辞": "日有食", "年代": "尚不清楚"}])
        self.assertEqual(content["note"], "保留作品级字段")
        with self.assertRaisesRegex(ValueError, "不能重复"):
            normalize_record_table({"columns": ["年代", "年代"], "rows": []})

    def test_board_content_is_bounded_and_invalid_edges_are_removed(self) -> None:
        content = normalize_board_content(
            {
                "layout": "mind_map",
                "viewport": {"width": 1200, "height": 760},
                "nodes": [
                    {
                        "id": "root node",
                        "type": "evidence",
                        "title": "中心证据",
                        "body": "保留内容",
                        "x": -20,
                        "y": 900,
                        "width": 230,
                        "height": 140,
                        "color": "blue",
                        "reference": {"type": "source", "id": "src-1", "label": "论文", "page": "3"},
                    },
                    {"id": "root node", "type": "unknown", "title": "分支"},
                ],
                "edges": [
                    {"id": "edge 1", "from": "root-node", "to": "root-node-2", "label": "支撑"},
                    {"id": "bad", "from": "missing", "to": "root-node-2"},
                ],
            }
        )
        self.assertEqual([node["id"] for node in content["nodes"]], ["root-node", "root-node-2"])
        self.assertEqual(content["nodes"][0]["x"], 0)
        self.assertLessEqual(content["nodes"][0]["y"], 620)
        self.assertEqual(content["nodes"][1]["type"], "note")
        self.assertEqual(content["edges"], [{"id": "edge-1", "from": "root-node", "to": "root-node-2", "label": "支撑"}])

        normalized = normalize_artifact_content(
            "mind_map", content, "artifact-board-test"
        )
        self.assertEqual(normalized["layout"], "mind_map")

        resized = normalize_board_content(
            {
                "viewport": {"width": 99999, "height": 120},
                "nodes": [
                    {
                        "id": "node-edge",
                        "title": "边界节点",
                        "x": 8000,
                        "y": 8000,
                        "width": 520,
                        "height": 420,
                    }
                ],
                "edges": [],
            }
        )
        self.assertEqual(resized["viewport"], {"width": 4000, "height": 480})
        self.assertEqual(resized["nodes"][0]["x"], 3480)
        self.assertEqual(resized["nodes"][0]["y"], 60)

    def test_board_editor_exposes_resize_and_visual_semantics(self) -> None:
        research_js = (ROOT / "research" / "research.js").read_text(encoding="utf-8")
        research_css = (ROOT / "research" / "research.css").read_text(encoding="utf-8")
        public_js = (ROOT / "app.js").read_text(encoding="utf-8")
        public_css = (ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-board-size-input="width"', research_js)
        self.assertIn('data-board-size-input="height"', research_js)
        self.assertIn('data-board-action="resize"', research_js)
        self.assertIn("applyBoardViewport", research_js)
        self.assertIn("boardEdgeGeometry", research_js)
        for node_type in ("note", "evidence", "source", "artifact"):
            self.assertIn(f"board-type-${{escapeHTML(type)}}", research_js)
            self.assertIn(f".board-node.board-type-{node_type}", research_css)
            self.assertIn(f".public-board-node.board-type-{node_type}", public_css)
        self.assertIn("board-type-${escapeHTML(nodeType)}", public_js)
        self.assertIn("public-board-stage.is-mind-map", public_css)

    def test_rich_text_is_sanitized_and_plain_text_stays_in_sync(self) -> None:
        artifact_id = "artifact-editor-test"
        asset_name = f"{'a' * 64}.png"
        raw = (
            '<h2 onclick="alert(1)">甲骨日食</h2>'
            '<script>alert("bad")</script>'
            '<p style="color:red">正文<strong>重点</strong></p>'
            '<a href="javascript:alert(1)">危险链接</a>'
            f'<img src="{research_asset_url(artifact_id, asset_name)}" onerror="alert(1)">'
        )
        clean_html, plain_text = sanitize_rich_html(raw, artifact_id)
        self.assertIn("<h2>甲骨日食</h2>", clean_html)
        self.assertIn(research_asset_url(artifact_id, asset_name), clean_html)
        self.assertNotIn("script", clean_html)
        self.assertNotIn("alert", clean_html)
        self.assertNotIn("onclick", clean_html)
        self.assertNotIn("style=", clean_html)
        self.assertNotIn("javascript:", clean_html)
        self.assertEqual(plain_text, "甲骨日食\n正文重点\n危险链接")

        content = normalize_artifact_content(
            "public_explainer",
            {"html": "<p>新正文</p>", "text": "不应保留的旧正文"},
            artifact_id,
        )
        self.assertEqual(content["text"], "新正文")

    def test_rich_icons_visual_plans_and_slide_structure_are_constrained(self) -> None:
        artifact_id = "artifact-rich-structure"
        clean_html, _ = sanitize_rich_html(
            '<p><span data-icon="sun" onclick="bad()"></span>日食'
            '<span data-icon="unknown" class="unsafe"></span></p>',
            artifact_id,
        )
        self.assertIn('data-icon="sun"', clean_html)
        self.assertIn('class="artifact-icon artifact-icon-sun"', clean_html)
        self.assertNotIn("onclick", clean_html)
        self.assertNotIn('data-icon="unknown"', clean_html)
        self.assertNotIn('class="unsafe"', clean_html)

        visuals = normalize_rich_visuals(
            {
                "visuals": [
                    {
                        "id": f"visual {index}",
                        "afterHeading": "资料线索",
                        "prompt": f"配图 {index}",
                        "alt": "替代文字",
                    }
                    for index in range(6)
                ]
            }
        )["visuals"]
        self.assertEqual(len(visuals), 4)
        self.assertEqual(visuals[0]["id"], "visual-0")

        deck = normalize_slide_deck_content(
            {
                "playback": {
                    "autoAdvance": True,
                    "seconds": 9,
                    "loop": True,
                    "transition": "wipe",
                },
                "slides": [
                    {
                        "title": "真实资料支持的数量关系",
                        "layout": "chart",
                        "icon": "chart",
                        "chart": {
                            "type": "bar",
                            "categories": ["甲", "乙"],
                            "series": [{"name": "数量", "values": [2, 5]}],
                        },
                        "transition": {
                            "type": "split",
                            "duration": 0.8,
                            "advanceAfter": 10,
                        },
                    }
                ],
            }
        )
        self.assertTrue(deck["playback"]["autoAdvance"])
        self.assertEqual(deck["slides"][0]["chart"]["series"][0]["values"], [2.0, 5.0])
        self.assertEqual(deck["slides"][0]["transition"]["type"], "split")

    def test_slide_deck_strips_html_markdown_and_splits_overlong_pages(self) -> None:
        dirty = (
            "**<html><body><h2>商朝的日食和月食记录</h2>"
            "<p>郭胜强</p><p>中国古代天文观测形成了长期记录。"
            + "这段资料用于检验自动拆页与页面容量。" * 45
            + "</p></body></html>**"
        )
        deck = normalize_slide_deck_content(
            {
                "subtitle": "**<p>甲骨日食研究</p>**",
                "slides": [
                    {
                        "title": dirty,
                        "takeaway": "**<strong>原文线索</strong>**",
                        "layout": "statement",
                        "richText": [{"lead": "**原文线索**", "text": dirty}],
                        "citations": ["<p>测试资料 · PDF第1页</p>"],
                    }
                ],
            }
        )
        self.assertGreater(len(deck["slides"]), 1)
        serialized = json.dumps(deck, ensure_ascii=False)
        for fragment in ("<html", "<body", "<h2", "<p>", "**"):
            self.assertNotIn(fragment, serialized.lower())
        for slide in deck["slides"]:
            self.assertLessEqual(len(slide["title"]), 22)
            self.assertLessEqual(len(slide["richText"]), 4)
            self.assertLessEqual(
                sum(len(item["lead"]) + len(item["text"]) for item in slide["richText"]),
                320,
            )
        self.assertTrue(deck["slides"][1]["title"].endswith("（续）"))

    def test_editor_images_are_validated_and_content_addressed(self) -> None:
        root = self.private_dir / "editor-assets"
        encoded = base64.b64encode(test_png_bytes()).decode("ascii")
        first = store_editor_image(root, "artifact-test", "甲骨图.png", encoded)
        second = store_editor_image(root, "artifact-test", "重复上传.png", encoded)
        self.assertEqual(first["asset"], second["asset"])
        self.assertEqual(first["contentType"], "image/png")
        self.assertTrue(editor_image_path(root, "artifact-test", first["asset"]).is_file())
        with self.assertRaisesRegex(ValueError, "路径|编号"):
            editor_image_path(root, "artifact-test", "../outside.png")
        with self.assertRaisesRegex(ValueError, "有效图片"):
            store_editor_image(
                root,
                "artifact-test",
                "fake.png",
                base64.b64encode(b"not an image").decode("ascii"),
            )

    def test_public_editor_image_requires_snapshot_reference(self) -> None:
        artifact_id = "artifact-test"
        asset_name = f"{'b' * 64}.png"
        content = {"html": f'<figure><img src="{research_asset_url(artifact_id, asset_name)}"></figure>'}
        self.assertTrue(artifact_references_asset(content, artifact_id, asset_name))
        self.assertFalse(artifact_references_asset({"html": "<p>无图</p>"}, artifact_id, asset_name))

    def test_editor_image_endpoints_respect_current_public_version(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="public_explainer",
            title="图文讲解",
            content={"text": "正文"},
            model="local",
            prompt_version=self.store.prompt_for("public_explainer")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        asset_root = self.private_dir / "editor-endpoint-assets"
        snapshot_holder: dict[str, dict[str, object]] = {"value": {"works": []}}
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        with (
            patch("server.research_store", return_value=self.store),
            patch("server.editor_asset_root", return_value=asset_root),
            patch(
                "server.load_published_snapshot",
                side_effect=lambda: snapshot_holder["value"],
            ),
        ):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                upload_request = urllib.request.Request(
                    f"{base}/api/research/artifacts/{artifact['id']}/images",
                    data=json.dumps(
                        {
                            "filename": "甲骨图.png",
                            "contentBase64": base64.b64encode(test_png_bytes()).decode("ascii"),
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(upload_request) as response:
                    uploaded = json.loads(response.read().decode("utf-8"))
                self.assertTrue(uploaded["url"].startswith("/api/research/artifacts/"))

                self.store.edit_artifact(
                    artifact["id"],
                    title="图文讲解",
                    content={
                        "html": f'<p>正文</p><figure><img src="{uploaded["url"]}"></figure>',
                        "text": "将由服务端同步",
                    },
                )
                self.store.review_artifact(artifact["id"], "approve")
                published_snapshot = build_snapshot(self.store)
                snapshot_holder["value"] = published_snapshot

                with urllib.request.urlopen(f"{base}{uploaded['url']}") as response:
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                public_url = uploaded["url"].replace("/api/research/", "/api/public/")
                with urllib.request.urlopen(f"{base}{public_url}") as response:
                    self.assertEqual(response.status, 200)

                snapshot_holder["value"] = {**published_snapshot, "works": []}
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"{base}{public_url}")
                self.assertEqual(raised.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()

    def test_bailian_rich_and_slide_image_endpoints_update_artifact_media(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        rich = self.store.create_artifact(
            kind="public_explainer",
            title="富文本讲解",
            content={
                "html": "<h2>日食机制</h2><p>正文</p>",
                "visuals": [
                    {
                        "id": "visual-1",
                        "afterHeading": "日食机制",
                        "prompt": "无文字日食机制示意",
                        "alt": "日食机制示意",
                        "caption": "AI生成的传播插图",
                    }
                ],
            },
            model="local",
            prompt_version=self.store.prompt_for("public_explainer")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        slide = self.store.create_artifact(
            kind="slide_deck",
            title="讲解幻灯片",
            content={
                "slides": [
                    {
                        "title": "日食机制",
                        "layout": "image-right",
                        "visual": {
                            "prompt": "无文字日食机制横版示意",
                            "alt": "日食机制示意",
                            "caption": "AI生成的传播插图",
                            "asset": "",
                        },
                    }
                ]
            },
            model="local",
            prompt_version=self.store.prompt_for("slide_deck")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        asset_root = self.private_dir / "generated-artifact-images"
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        with (
            patch("server.research_store", return_value=self.store),
            patch("server.editor_asset_root", return_value=asset_root),
            patch.object(BailianAdapter, "generate_image", return_value=test_png_bytes()),
        ):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                def post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
                    request = urllib.request.Request(
                        f"{base}{path}",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        return json.loads(response.read().decode("utf-8"))

                rich_result = post_json(
                    f"/api/research/artifacts/{rich['id']}/generate-rich-image",
                    {"visualId": "visual-1"},
                )
                self.assertEqual(rich_result["afterHeading"], "日食机制")
                self.assertTrue(
                    editor_image_path(asset_root, rich["id"], rich_result["asset"]).is_file()
                )

                slide_result = post_json(
                    f"/api/research/artifacts/{slide['id']}/generate-slide-image",
                    {"slideIndex": 0},
                )
                updated = self.store.get_artifact(slide["id"])
                self.assertEqual(updated["status"], "draft")
                self.assertEqual(
                    updated["content"]["slides"][0]["visual"]["asset"],
                    slide_result["asset"],
                )
                self.assertTrue(
                    artifact_references_asset(
                        updated["content"], slide["id"], slide_result["asset"]
                    )
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_bailian_image_generation_polls_and_downloads_trusted_result(self) -> None:
        calls: list[str] = []

        class JsonResponse:
            headers = {"Content-Type": "application/json"}

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        class ImageResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return test_png_bytes()

        def fake_urlopen(request_or_url, timeout=0):
            if isinstance(request_or_url, str):
                calls.append(request_or_url)
                return ImageResponse()
            calls.append(request_or_url.full_url)
            if "/tasks/" in request_or_url.full_url:
                return JsonResponse(
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "results": [
                                {
                                    "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/card.png"
                                }
                            ],
                        }
                    }
                )
            return JsonResponse({"output": {"task_id": "task-1"}})

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with patch("bailian_adapter.time.sleep"), patch(
                "bailian_adapter.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                raw = BailianAdapter().generate_image("日食科普插图")
        self.assertTrue(raw.startswith(b"\x89PNG"))
        self.assertTrue(any("/tasks/task-1" in item for item in calls))
        self.assertIn(
            "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/card.png", calls
        )

    def test_visual_card_background_is_cached_and_composited(self) -> None:
        artifact = {
            "id": "artifact-card-test",
            "title": "科普图卡",
            "content": {
                "cards": [
                    {
                        "title": "日食为何发生",
                        "body": ["月球运行到太阳与地球之间。"],
                        "evidence": ["测试资料 · PDF第1页"],
                        "visualDirection": "日月地空间关系",
                    }
                ]
            },
        }
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            with patch(
                "media_exports.BailianAdapter.generate_image",
                return_value=test_png_bytes(),
            ) as generate:
                result = generate_visual_card_background(artifact, 0)
                generated_card = render_visual_card_png(artifact, 0)
                generated_preview = render_visual_card_webp(artifact, 0)
                generate_visual_card_background(artifact, 0)
        self.assertEqual(result["provider"], "aliyun-bailian")
        generate.assert_called_once()
        self.assertTrue(generated_card.startswith(b"\x89PNG"))
        self.assertTrue(generated_preview.startswith(b"RIFF"))
        self.assertEqual(generated_preview[8:12], b"WEBP")
        self.assertLess(len(generated_preview), len(generated_card))
        from PIL import Image

        with Image.open(io.BytesIO(generated_preview)) as preview_image:
            self.assertEqual(preview_image.size, (864, 1080))

    def test_public_site_image_uses_smaller_cached_webp_derivative(self) -> None:
        from PIL import Image

        original = self.private_dir / "site-assets" / "siteasset-test.png"
        original.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2400, 1350), "#17332d").save(original, format="PNG")
        preview = public_image_webp(original, max_width=1600, quality=80)
        self.assertTrue(preview.startswith(b"RIFF"))
        self.assertEqual(preview[8:12], b"WEBP")
        self.assertLess(len(preview), original.stat().st_size)
        with Image.open(io.BytesIO(preview)) as image:
            self.assertEqual(image.size, (1600, 900))
        self.assertEqual(preview, public_image_webp(original, max_width=1600, quality=80))
        self.assertEqual(AppHandler.extensions_map[".webp"], "image/webp")

    def test_generated_card_media_returns_published_work_to_review(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="visual_card_set",
            title="媒体复核测试",
            content={"cards": [{"title": "图卡", "body": ["正文"]}]},
            model="test-model",
            prompt_version=self.store.prompt_for("visual_card_set")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        publish_snapshot(self.store, self.private_dir / "public.json")
        changed = self.store.mark_artifact_media_changed(artifact["id"])
        self.assertEqual(changed["status"], "draft")
        self.assertEqual(changed["publication_state"], "public_stale")

    def test_source_page_ranges_are_compacted_without_losing_edges(self) -> None:
        edges = [
            {
                "source_id": "source-1",
                "source_title": "癸酉日食说",
                "source_status": "reviewed",
                "source_recognition_status": "ocr_ready",
                "locator_type": "pdf_page",
                "locator_value": str(page),
            }
            for page in (1, 2, 3, 4, 5, 6)
        ]
        grouped = group_lineage_edges(edges)
        self.assertEqual(len(edges), 6)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["locator_range"], "1~6")
        self.assertEqual(compact_locator_values(["1", "2", "4", "5"]), "1~2、4~5")

    def test_audio_generation_cleans_model_preamble(self) -> None:
        prompt = {"template": "请生成音频导览", "id": "audio_guide:v2"}
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}):
            adapter = BailianAdapter()
            with patch.object(
                adapter,
                "complete",
                return_value="以下是一份音频导览脚本草稿，依据资料生成。\n\n——\n正文开始。",
            ):
                generated = adapter.generate_artifact("audio_guide", prompt, [], [])
        self.assertEqual(generated["content"]["text"], "正文开始。")

    def test_unconfirmed_source_is_blocked_from_research_and_publication(self) -> None:
        first = self.store.import_manual_text("资料A", "日有食，材料正文。")
        duplicate = self.store.import_manual_text("资料A副本", "日有食，材料正文。")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["id"], duplicate["id"])
        self.store.parse_source(first["id"])
        with self.assertRaisesRegex(ValueError, "未经确认的资料"):
            self.store.generation_context([first["id"]])

        self.store.mark_source_reviewed(first["id"])
        context = self.store.generation_context([first["id"]])
        self.assertEqual(len(context["excerpts"]), 1)
        self.assertEqual(context["excerpts"][0]["locator"], "1")
        self.assertEqual(context["excerpts"][0]["sourceStatus"], "reviewed")

        artifact = self.store.create_artifact(
            kind="public_explainer",
            title="未复核资料草稿",
            content={"text": "私有研究草稿"},
            model="test-model",
            prompt_version="public_explainer:v1",
            source_ids=[first["id"]],
            unit_ids=context["unitIds"],
        )
        approved = self.store.review_artifact(artifact["id"], "approve")
        self.assertEqual(approved["status"], "approved")

    def test_private_research_answer_rejects_unconfirmed_sources(self) -> None:
        source = self.store.import_manual_text(
            "未复核日食论文",
            "乙巳日有食。学者甲认为年代仍有争议，需结合历组断代继续判断。",
        )
        self.store.parse_source(source["id"])
        with self.assertRaisesRegex(ValueError, "未经确认的资料"):
            self.store.generation_context([source["id"]])

    def test_private_research_api_accepts_parsed_source(self) -> None:
        source = self.store.import_manual_text("接口测试资料", "乙巳日有食，年代仍有争议。")
        self.store.parse_source(source["id"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        payload = json.dumps(
            {"question": "乙巳日食年代是否确定？", "sourceIds": [source["id"]]},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/api/research/ask",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with patch.object(server_module, "research_store", return_value=self.store):
                with patch.dict(os.environ, {"DASHSCOPE_API_KEY": ""}):
                    with urllib.request.urlopen(request) as response:
                        result = json.loads(response.read().decode("utf-8"))
            self.fail("未确认资料不应进入问答接口")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 422)
            result = json.loads(error.read().decode("utf-8"))
            self.assertIn("未经确认的资料", result["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_artifact_kind_catalog_is_exposed_to_research_ui(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server_module, "research_store", return_value=self.store):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/research/artifact-kinds"
                ) as response:
                    result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(len(result["items"]), len(ARTIFACT_TITLES))
            self.assertEqual(
                {item["id"] for item in result["items"]}, set(ARTIFACT_TITLES)
            )
            media = {
                item["id"]: item.get("export")
                for item in result["items"]
                if item["id"] in {"audio_guide", "visual_card_set", "slide_deck", "video_package"}
            }
            self.assertEqual(media["audio_guide"]["format"], "wav")
            self.assertEqual(media["visual_card_set"]["format"], "png-zip")
            self.assertEqual(media["slide_deck"]["format"], "pptx")
            self.assertEqual(media["video_package"]["format"], "zip")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_research_ui_supports_fullscreen_editing_and_resizable_panes(self) -> None:
        index = (ROOT / "research" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "research" / "research.js").read_text(encoding="utf-8")
        styles = (ROOT / "research" / "research.css").read_text(encoding="utf-8")
        self.assertNotIn('class="nav-index"', index)
        for pane in ("sourceList", "studioSetup", "studioList"):
            self.assertIn(f'data-pane-resizer="{pane}"', index)
        self.assertIn('data-pane-resizer="pdfViewer"', script)
        self.assertIn("data-artifact-fullscreen-open", script)
        self.assertIn("data-artifact-fullscreen-close", script)
        self.assertIn("artifact-editor-fullscreen-open", script)
        self.assertIn("--studio-setup-width", styles)
        self.assertIn("--studio-list-width", styles)
        self.assertIn("--pdf-viewer-width", styles)
        self.assertIn("@container inspector", styles)
        self.assertIn("研究工作台", index)
        self.assertIn('id="logout-button"', index)
        self.assertIn('id="workspace-sync-state"', index)
        self.assertIn('id="access-mode"', index)
        self.assertIn('id="release-description"', index)
        self.assertIn('request("/api/research/sources")', script)
        self.assertIn('request("/api/research/session")', script)
        self.assertIn('session.deploymentMode === "public_demo"', script)
        self.assertIn('Promise.allSettled', script)
        self.assertIn('window.addEventListener("load", init)', script)
        self.assertIn('if (!section) return false', script)
        self.assertIn('document.getElementById(section)', script)
        self.assertNotIn('$(`#${initial}[data-workspace-section]`)', script)
        self.assertIn('document.addEventListener("visibilitychange"', script)
        self.assertIn('data-snapshot-action="delete"', script)
        self.assertIn('<button type="button" class="command primary" data-inspector-action="artifact-approve"', script)
        self.assertIn('<button type="button" data-inspector-action="artifact-withdraw"', script)
        self.assertIn('<button type="button" data-inspector-action="artifact-delete"', script)
        self.assertIn('if (!action) return; event.preventDefault();', script)

        public_index = (ROOT / "index.html").read_text(encoding="utf-8")
        public_script = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('class="workbench-entry" href="/research/"', public_index)
        self.assertIn('id="back-to-top"', public_index)
        self.assertIn('window.scrollTo({ top: 0, left: 0, behavior: "smooth" })', public_script)

        login_html = (ROOT / "research" / "login.html").read_text(encoding="utf-8")
        login_script = (ROOT / "research" / "login.js").read_text(encoding="utf-8")
        showcase_html = (ROOT / "showcase" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="quick-login-button"', login_html)
        self.assertIn('id="quick-login-divider"', login_html)
        self.assertIn('/api/research/quick-login', login_script)
        self.assertIn('class="header-actions"', showcase_html)
        self.assertIn('href="/research/"', showcase_html)

    def test_research_login_protects_pages_apis_and_logout(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        server.research_auth_required = True  # type: ignore[attr-defined]
        server.research_username = "teacher"  # type: ignore[attr-defined]
        server.research_password_digest = hashlib.sha256(b"strong-password").digest()  # type: ignore[attr-defined]
        server.research_sessions = {}  # type: ignore[attr-defined]
        server.research_sessions_lock = threading.Lock()  # type: ignore[attr-defined]
        server.research_session_seconds = 3600  # type: ignore[attr-defined]
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post_json(path: str, payload: dict[str, str]):
            return opener.open(
                urllib.request.Request(
                    f"{base}{path}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
            )

        try:
            with opener.open(f"{base}/research/") as response:
                self.assertTrue(response.geturl().endswith("/research/login.html?next=/research/"))
                self.assertIn("登录研究工作台", response.read().decode("utf-8"))

            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                opener.open(f"{base}/api/research/dashboard")
            self.assertEqual(unauthorized.exception.code, 401)

            with self.assertRaises(urllib.error.HTTPError) as invalid:
                post_json(
                    "/api/research/login",
                    {"username": "teacher", "password": "wrong-password"},
                )
            self.assertEqual(invalid.exception.code, 401)

            with post_json(
                "/api/research/login",
                {"username": "teacher", "password": "strong-password"},
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("HttpOnly", response.headers.get("Set-Cookie", ""))
                self.assertIn("SameSite=Strict", response.headers.get("Set-Cookie", ""))

            with opener.open(f"{base}/api/research/session") as response:
                session = json.loads(response.read().decode("utf-8"))
                self.assertTrue(session["authenticated"])

            with patch.object(server_module, "research_store", return_value=self.store):
                with opener.open(f"{base}/api/research/dashboard") as response:
                    self.assertEqual(response.status, 200)
                with opener.open(f"{base}/research/") as response:
                    self.assertIn("研究工作台", response.read().decode("utf-8"))

            with post_json("/api/research/logout", {}) as response:
                self.assertEqual(response.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as logged_out:
                opener.open(f"{base}/api/research/dashboard")
            self.assertEqual(logged_out.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_research_quick_login_is_explicit_and_uses_secure_session(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        server.research_auth_required = True  # type: ignore[attr-defined]
        server.research_username = "teacher"  # type: ignore[attr-defined]
        server.research_password_digest = hashlib.sha256(b"strong-password").digest()  # type: ignore[attr-defined]
        server.research_sessions = {}  # type: ignore[attr-defined]
        server.research_sessions_lock = threading.Lock()  # type: ignore[attr-defined]
        server.research_session_seconds = 3600  # type: ignore[attr-defined]
        server.quick_login_enabled = True  # type: ignore[attr-defined]
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with opener.open(f"{base}/api/research/session") as response:
                session = json.loads(response.read().decode("utf-8"))
                self.assertTrue(session["quickLoginEnabled"])
                self.assertFalse(session["authenticated"])

            with opener.open(
                urllib.request.Request(
                    f"{base}/api/research/quick-login",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(result["authenticated"])
                self.assertTrue(result["quickLogin"])
                cookie = response.headers.get("Set-Cookie", "")
                self.assertIn("HttpOnly", cookie)
                self.assertIn("SameSite=Strict", cookie)

            with patch.object(server_module, "research_store", return_value=self.store):
                with opener.open(f"{base}/api/research/dashboard") as response:
                    self.assertEqual(response.status, 200)

            server.quick_login_enabled = False  # type: ignore[attr-defined]
            with self.assertRaises(urllib.error.HTTPError) as disabled:
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"{base}/api/research/quick-login",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                )
            self.assertEqual(disabled.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_public_demo_security_headers_secure_cookie_and_rate_limits(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        server.research_auth_required = True  # type: ignore[attr-defined]
        server.research_username = "teacher"  # type: ignore[attr-defined]
        server.research_password_digest = hashlib.sha256(b"strong-password").digest()  # type: ignore[attr-defined]
        server.research_sessions = {}  # type: ignore[attr-defined]
        server.research_sessions_lock = threading.Lock()  # type: ignore[attr-defined]
        server.research_session_seconds = 3600  # type: ignore[attr-defined]
        server.secure_cookies = True  # type: ignore[attr-defined]
        server.trust_proxy = True  # type: ignore[attr-defined]
        server.public_cors_origin = ""  # type: ignore[attr-defined]
        server.rate_limits = {}  # type: ignore[attr-defined]
        server.rate_limits_lock = threading.Lock()  # type: ignore[attr-defined]
        server.login_rate_limit = 2  # type: ignore[attr-defined]
        server.public_chat_rate_limit = 1  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post_json(path: str, payload: dict[str, str], client_ip: str):
            return urllib.request.urlopen(
                urllib.request.Request(
                    f"{base}{path}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-Forwarded-For": client_ip,
                    },
                    method="POST",
                )
            )

        try:
            with urllib.request.urlopen(f"{base}/") as response:
                self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
                self.assertIn("frame-ancestors 'none'", response.headers.get("Content-Security-Policy", ""))
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

            with post_json(
                "/api/research/login",
                {"username": "teacher", "password": "strong-password"},
                "203.0.113.11",
            ) as response:
                cookie = response.headers.get("Set-Cookie", "")
                self.assertIn("HttpOnly", cookie)
                self.assertIn("SameSite=Strict", cookie)
                self.assertIn("Secure", cookie)

            for _ in range(2):
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    post_json(
                        "/api/research/login",
                        {"username": "teacher", "password": "wrong-password"},
                        "203.0.113.12",
                    )
                self.assertEqual(invalid.exception.code, 401)
            with self.assertRaises(urllib.error.HTTPError) as limited_login:
                post_json(
                    "/api/research/login",
                    {"username": "teacher", "password": "wrong-password"},
                    "203.0.113.12",
                )
            self.assertEqual(limited_login.exception.code, 429)
            self.assertEqual(limited_login.exception.headers.get("Retry-After"), "300")

            with patch.object(server_module, "qwen_chat", return_value={"answer": "ok"}):
                with post_json("/api/chat", {"message": "日食是什么？"}, "203.0.113.13") as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(urllib.error.HTTPError) as limited_chat:
                    post_json("/api/chat", {"message": "日食是什么？"}, "203.0.113.13")
                self.assertEqual(limited_chat.exception.code, 429)
                self.assertEqual(limited_chat.exception.headers.get("Retry-After"), "60")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_source_page_endpoint_returns_requested_pdf_page(self) -> None:
        source_id = self.seed_pdf_source()
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server_module, "research_store", return_value=self.store):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/research/source-page?sourceId={source_id}&page=2"
                ) as response:
                    payload = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "image/png")
            self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_ocr_quality_gate_and_version_commit(self) -> None:
        source_id = self.seed_pdf_source()
        pending = self.store.mark_ocr_pending(source_id, "测试乱码")
        self.assertEqual(pending["recognitionStatus"], "ocr_pending")
        with self.assertRaisesRegex(ValueError, "未经确认的资料"):
            self.store.generation_context([source_id])

        run = self.store.start_ocr_run(source_id, "test-ocr-model")
        self.store.begin_ocr_run(run["id"], 2)
        clean_text = "中国古代天文学记录日食现象，并讨论甲骨卜辞的释读、年代与学者观点。" * 8
        self.store.save_ocr_page_result(run["id"], source_id, 1, clean_text)
        self.store.save_ocr_page_result(run["id"], source_id, 2, clean_text)
        completed = self.store.complete_ocr_run(run["id"], source_id, "test-ocr-model")
        self.assertEqual(completed["status"], "completed")
        source = self.store.get_source(source_id)
        self.assertEqual(source["recognition_status"], "ocr_needs_review")
        self.assertEqual(source["parse_version"], 1)
        with self.assertRaisesRegex(ValueError, "未经确认的资料"):
            self.store.generation_context([source_id])

        approved = self.store.review_ocr(source_id, "approve")
        self.assertEqual(approved["status"], "reviewed")
        reviewed = self.store.get_source(source_id)
        self.assertEqual(reviewed["recognition_status"], "ocr_ready")
        self.assertEqual(reviewed["status"], "reviewed")

        withdrawn = self.store.unreview_source(source_id)
        self.assertEqual(withdrawn["recognitionStatus"], "ocr_needs_review")
        self.assertEqual(self.store.get_source(source_id)["status"], "parsed")
        self.store.review_ocr(source_id, "approve")

    def test_sparse_image_page_enters_ocr_review_instead_of_failing(self) -> None:
        source_id = self.seed_pdf_source()
        self.store.mark_ocr_pending(source_id, "测试图版页")
        run = self.store.start_ocr_run(source_id, "test-ocr-model")
        self.store.begin_ocr_run(run["id"], 5)
        clean_text = "中国古代天文学记录日食现象，并讨论甲骨卜辞的释读、年代与学者观点。" * 8
        for page_number in (1, 2, 4, 5):
            self.store.save_ocr_page_result(run["id"], source_id, page_number, clean_text)
        self.store.save_ocr_page_result(run["id"], source_id, 3, "故宫博物院 商祖丁尊")

        completed = self.store.complete_ocr_run(run["id"], source_id, "test-ocr-model")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["quality"]["status"], "needs_review")
        self.assertEqual(completed["quality"]["problemPageNumbers"], [3])
        source = self.store.get_source(source_id)
        self.assertEqual(source["recognition_status"], "ocr_needs_review")
        self.assertEqual(len(self.store.list_units(source_id)), 5)

    def test_latin_and_mixed_pages_are_review_warnings_not_ocr_failures(self) -> None:
        source_id = self.seed_pdf_source()
        self.store.mark_ocr_pending(source_id, "测试中英混排与图表页")
        run = self.store.start_ocr_run(source_id, "test-ocr-model")
        self.store.begin_ocr_run(run["id"], 5)
        chinese = "中国古代天文学记录日食现象，并讨论甲骨卜辞的释读、年代与学者观点。" * 8
        latin = "Solar eclipse path JPL ephemeris longitude latitude contact time 12:34 " * 20
        mixed = "乙巳日食 JPL ephemeris contact time longitude latitude 12:34 " * 20
        for page_number, text in enumerate((chinese, chinese, latin, mixed, latin), 1):
            self.store.save_ocr_page_result(run["id"], source_id, page_number, text)

        completed = self.store.complete_ocr_run(run["id"], source_id, "test-ocr-model")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["quality"]["status"], "needs_review")
        self.assertEqual(completed["quality"]["recognizedPages"], 5)
        self.assertEqual(completed["quality"]["reviewPageNumbers"], [3, 4, 5])
        self.assertEqual(completed["quality"]["failedPages"], 0)
        self.assertEqual(self.store.get_source(source_id)["recognition_status"], "ocr_needs_review")

    def test_failed_legacy_ocr_can_be_reassessed_without_model_call(self) -> None:
        source_id = self.seed_pdf_source()
        self.store.mark_ocr_pending(source_id, "测试旧质量规则误判")
        run = self.store.start_ocr_run(source_id, "test-ocr-model")
        self.store.begin_ocr_run(run["id"], 2)
        chinese = "中国古代天文学记录日食现象，并讨论甲骨卜辞的释读、年代与学者观点。" * 8
        latin = "Solar eclipse path JPL ephemeris longitude latitude contact time 12:34 " * 20
        self.store.save_ocr_page_result(run["id"], source_id, 1, chinese)
        self.store.save_ocr_page_result(run["id"], source_id, 2, latin)
        legacy_report = {
            "score": 0.72,
            "status": "failed",
            "pageNumber": 2,
            "reasons": ["中文字符比例异常"],
        }
        with self.store.connect() as connection:
            connection.execute(
                """
                UPDATE ocr_page_results
                SET quality_score = 0.72, quality_status = 'failed', quality_report_json = ?
                WHERE run_id = ? AND page_number = 2
                """,
                (json.dumps(legacy_report, ensure_ascii=False), run["id"]),
            )
            connection.execute(
                "UPDATE ocr_runs SET status = 'failed', error = 'OCR文本质量未通过' WHERE id = ?",
                (run["id"],),
            )
            connection.execute(
                "UPDATE source_documents SET status = 'parsed', recognition_status = 'ocr_failed' WHERE id = ?",
                (source_id,),
            )

        completed = self.store.reassess_ocr_results(source_id)

        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["reusedStoredText"])
        self.assertEqual(completed["quality"]["reviewPageNumbers"], [2])
        source = self.store.get_source(source_id)
        self.assertEqual(source["recognition_status"], "ocr_needs_review")
        self.assertEqual(len(self.store.list_units(source_id)), 2)

    def test_hard_ocr_encoding_error_still_blocks_commit(self) -> None:
        source_id = self.seed_pdf_source()
        self.store.mark_ocr_pending(source_id, "测试硬错误")
        run = self.store.start_ocr_run(source_id, "test-ocr-model")
        self.store.begin_ocr_run(run["id"], 5)
        clean_text = "中国古代天文学记录日食现象，并讨论甲骨卜辞的释读、年代与学者观点。" * 8
        for page_number in (1, 2, 4, 5):
            self.store.save_ocr_page_result(run["id"], source_id, page_number, clean_text)
        self.store.save_ocr_page_result(run["id"], source_id, 3, "ರᄅႵొ ѾՊ ࡊܠ ࣃࣘ " * 20)

        failed = self.store.complete_ocr_run(run["id"], source_id, "test-ocr-model")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.store.get_source(source_id)["recognition_status"], "ocr_failed")

    def test_text_quality_detects_garbled_pdf_mapping(self) -> None:
        garbled = "ರᄅႵൊ ѾՊ ࡊܠ ࣃࣘ " * 20
        report = assess_text_quality(garbled)
        self.assertEqual(report["status"], "failed")
        self.assertGreater(report["suspiciousCharacters"], 0)

    def test_candidate_is_not_published_before_approval(self) -> None:
        source = self.store.import_manual_text("资料B", "乙丑日有食，年代尚不清楚。")
        self.store.parse_source(source["id"])
        created = self.store.extract_candidates(source["id"])
        self.assertGreaterEqual(len(created), 1)
        self.assertEqual(self.store.list_published_knowledge(), [])
        with self.assertRaisesRegex(ValueError, "来源尚未完成确认"):
            self.store.review_candidate(created[0]["id"], "approve")
        self.store.mark_source_reviewed(source["id"])
        self.store.review_candidate(created[0]["id"], "approve")
        self.assertEqual(len(self.store.list_published_knowledge()), 1)

    def test_import_api_auto_parses_but_does_not_extract_candidates(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        payload = json.dumps(
            {"kind": "manual", "title": "自动处理测试", "text": "乙丑日有食，年代尚不清楚。"},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/api/research/import",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with patch.object(server_module, "research_store", return_value=self.store):
                with urllib.request.urlopen(request) as response:
                    result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 201)
            self.assertEqual(result["status"], "parsed")
            self.assertEqual(result["autoParse"]["units"], 1)
            self.assertEqual(self.store.get_source(result["id"])["status"], "parsed")
            self.assertEqual(len(self.store.list_units(result["id"])), 1)
            self.assertEqual(self.store.list_candidates(), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bailian_status_does_not_expose_key_and_probe_requires_config(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = True  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "", "QWEN_MODEL": "qwen-plus"}):
                with urllib.request.urlopen(f"{base}/api/research/bailian/status") as response:
                    status = json.loads(response.read().decode("utf-8"))
                self.assertFalse(status["configured"])
                self.assertNotIn("api_key", status)
                request = urllib.request.Request(
                    f"{base}/api/research/bailian/test",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                self.assertEqual(raised.exception.code, 422)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bailian_structured_artifacts_are_validated(self) -> None:
        adapter = BailianAdapter()
        adapter.api_key = "test-only"
        prompt = {"template": "测试模板"}
        with patch.object(
            adapter,
            "complete",
            return_value=json.dumps(
                {"columns": ["卜辞", "著录"], "rows": [{"卜辞": "日有食", "著录": "合集11480"}]},
                ensure_ascii=False,
            ),
        ):
            result = adapter.generate_artifact("record_table", prompt, [], [])
        self.assertEqual(result["content"]["rows"][0]["卜辞"], "日有食")
        with patch.object(adapter, "complete", return_value="not-json"):
            result = adapter.generate_artifact("viewpoint_comparison", prompt, [], [])
        self.assertEqual(
            result["model"],
            "local-grounded-templates-after-bailian-invalid-json",
        )
        board_payload = {
            "layout": "free",
            "viewport": {"width": 1200, "height": 760},
            "nodes": [{"id": "node-1", "type": "note", "title": "中心", "body": "资料关系"}],
            "edges": [],
        }
        with patch.object(
            adapter,
            "complete",
            return_value=json.dumps(board_payload, ensure_ascii=False),
        ):
            result = adapter.generate_artifact("whiteboard", prompt, [], [])
        self.assertEqual(result["content"]["nodes"][0]["title"], "中心")

    def test_model_json_parser_accepts_fences_and_explanatory_text(self) -> None:
        fenced = '```json\n{"items":[{"record":"癸酉日食说"}]}\n```'
        self.assertEqual(
            parse_model_json_object(fenced)["items"][0]["record"],
            "癸酉日食说",
        )
        narrated = '以下是结构化结果：\n{"columns":["卜辞"],"rows":[]}\n请审核。'
        self.assertEqual(parse_model_json_object(narrated)["columns"], ["卜辞"])

    def test_bailian_truncated_json_falls_back_to_local_template(self) -> None:
        adapter = BailianAdapter()
        adapter.api_key = "test-only"
        with patch.object(
            adapter,
            "complete",
            return_value='```json\n{"nodes":[',
        ):
            result = adapter.generate_artifact(
                "whiteboard", {"template": "测试模板"}, [], []
            )
        self.assertEqual(
            result["model"],
            "local-grounded-templates-after-bailian-invalid-json",
        )
        self.assertGreaterEqual(len(result["content"]["nodes"]), 1)

    def test_bailian_invalid_schema_falls_back_to_local_template(self) -> None:
        adapter = BailianAdapter()
        adapter.api_key = "test-only"
        with patch.object(
            adapter,
            "complete",
            return_value=json.dumps({"summary": "缺少表格行列"}, ensure_ascii=False),
        ):
            result = adapter.generate_artifact(
                "record_table", {"template": "测试模板"}, [], []
            )
        self.assertEqual(
            result["model"],
            "local-grounded-templates-after-bailian-invalid-schema",
        )
        self.assertIn("rows", result["content"])

    def test_model_output_never_becomes_evidence(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("public_explainer")
        generated = BailianAdapter().generate_artifact(
            "public_explainer", prompt, context["records"], context["excerpts"]
        )
        artifact = self.store.create_artifact(
            kind="public_explainer",
            title=generated["title"],
            content=generated["content"],
            model=generated["model"],
            prompt_version=prompt["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.assertEqual(artifact["status"], "draft")
        with self.store.connect() as connection:
            forbidden = connection.execute(
                "SELECT COUNT(*) FROM lineage_edges WHERE upstream_type = 'artifact'"
            ).fetchone()[0]
        self.assertEqual(forbidden, 0)
        self.store.review_artifact(artifact["id"], "approve")
        snapshot = build_snapshot(self.store)
        self.assertEqual(len(snapshot["works"]), 1)
        self.assertEqual(snapshot["works"][0]["provenance"]["sourceCount"], 1)
        provenance_source = snapshot["works"][0]["provenance"]["sources"][0]
        self.assertEqual(provenance_source["title"], "测试日食材料")
        self.assertEqual(provenance_source["pdfPages"], [])

    def test_published_record_table_populates_public_records(self) -> None:
        source = self.store.import_manual_text("记录表来源", "乙丑卜，贞：日有食，不唯□。")
        self.store.parse_source(source["id"])
        self.store.mark_source_reviewed(source["id"])
        context = self.store.generation_context([source["id"]])
        artifact = self.store.create_artifact(
            kind="record_table",
            title="甲骨日食记录表",
            content={
                "columns": ["卜辞", "著录", "年代", "状态", "争议"],
                "rows": [
                    {
                        "卜辞": "乙丑卜，贞：日有食，不唯□。",
                        "著录": "测试著录1",
                        "年代": "尚不清楚",
                        "状态": "来源已确认",
                        "争议": "释字仍待复核；具体年代未定",
                    }
                ],
            },
            model="test-model",
            prompt_version="record_table:v1",
            source_ids=[source["id"]],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")

        snapshot = build_snapshot(self.store)

        self.assertEqual(len(snapshot["recordsMeta"]["records"]), 1)
        record = snapshot["recordsMeta"]["records"][0]
        self.assertEqual(record["inscription"], "乙丑卜，贞：日有食，不唯□。")
        self.assertEqual(record["disputes"], ["释字仍待复核", "具体年代未定"])

    def test_answer_can_be_saved_as_non_evidence_note(self) -> None:
        source_id, _ = self.seed_manual_source()
        note = self.store.import_generated_note(
            title="问答笔记",
            question="日食在卜辞中如何被描述？",
            answer="回答草稿，仅依据所选资料。",
            source_ids=[source_id],
            citations=[{"sourceId": source_id, "locator": "1"}],
            model="local-evidence-preview",
        )
        self.assertEqual(note["source_role"], "generated_note")
        self.assertFalse(note["provenance"]["evidenceEligible"])
        self.assertEqual(note["provenance"]["citations"][0]["sourceId"], source_id)
        note_units = self.store.list_units(note["id"])
        self.assertEqual(len(note_units), 1)
        self.assertIn("回答草稿", note_units[0]["text_content"])
        research_js = (ROOT / "research" / "research.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(research_js.count('id="source-units"'), 2)
        self.assertIn("data-note-source-id", research_js)
        self.assertIn("openNoteCitation", research_js)
        self.assertIn("compactLocatorValues(locators)", research_js)
        self.assertIn('const key = `${sourceId}\\u0000${locatorType}`', research_js)
        with self.assertRaisesRegex(ValueError, "不能作为资料证据"):
            self.store.generation_context([note["id"]])

    def test_artifact_lifecycle_supports_more_types_and_delete(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="research_qa",
            title="问答草稿",
            content={"text": "回答"},
            model="local-evidence-preview",
            prompt_version=self.store.prompt_for("research_qa")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.assertIn("research_qa", ARTIFACT_TITLES)
        edited = self.store.edit_artifact(
            artifact["id"], title="课堂稿", content={"text": "修订"}, kind="lesson_material"
        )
        self.assertEqual(edited["kind"], "lesson_material")
        approved = self.store.review_artifact(artifact["id"], "approve")
        self.assertEqual(approved["status"], "approved")
        deleted = self.store.delete_artifact(artifact["id"])
        self.assertEqual(deleted["status"], "deleted")

    def test_board_artifacts_generate_from_confirmed_sources(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        for kind, layout in (("whiteboard", "free"), ("mind_map", "mind_map")):
            prompt = self.store.prompt_for(kind)
            generated = BailianAdapter().generate_artifact(
                kind, prompt, context["records"], context["excerpts"]
            )
            artifact = self.store.create_artifact(
                kind=kind,
                title=generated["title"],
                content=generated["content"],
                model=generated["model"],
                prompt_version=prompt["id"],
                source_ids=[source_id],
                unit_ids=context["unitIds"],
            )
            self.assertEqual(artifact["content"]["layout"], layout)
            self.assertGreaterEqual(len(artifact["content"]["nodes"]), 1)
            self.assertEqual(artifact["status"], "draft")

    def test_media_artifact_generation_and_exports_are_structured(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        expectations = {
            "visual_card_set": "cards",
            "slide_deck": "slides",
            "video_package": "scenes",
        }
        artifacts: dict[str, dict[str, object]] = {}
        for kind, key in expectations.items():
            prompt = self.store.prompt_for(kind)
            generated = BailianAdapter().generate_artifact(
                kind, prompt, context["records"], context["excerpts"]
            )
            self.assertIsInstance(generated["content"].get(key), list)
            self.assertGreater(len(generated["content"][key]), 0)
            artifacts[kind] = self.store.create_artifact(
                kind=kind,
                title=generated["title"],
                content=generated["content"],
                model=generated["model"],
                prompt_version=prompt["id"],
                source_ids=[source_id],
                unit_ids=context["unitIds"],
            )

        card_zip, card_type, _ = export_artifact(
            artifacts["visual_card_set"], "png-zip"
        )
        self.assertEqual(card_type, "application/zip")
        with zipfile.ZipFile(io.BytesIO(card_zip)) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            self.assertTrue(any(name.endswith(".png") for name in names))

        slide_artifact = artifacts["slide_deck"]
        editor_root = self.private_dir / "slide-editor-assets"
        stored = store_editor_image(
            editor_root,
            str(slide_artifact["id"]),
            "eclipse.png",
            base64.b64encode(test_png_bytes()).decode("ascii"),
        )
        slide_artifact["content"]["playback"] = {
            "autoAdvance": True,
            "seconds": 8,
            "loop": True,
            "transition": "fade",
        }
        slide_artifact["content"]["slides"][0].update(
            {
                "layout": "image-right",
                "visual": {
                    "asset": stored["asset"],
                    "prompt": "日食机制示意",
                    "alt": "日食机制示意",
                    "caption": "AI生成的科学传播插图",
                },
                "speakerNotes": "先解释月影，再说明资料边界。",
                "transition": {
                    "type": "wipe",
                    "duration": 0.8,
                    "advanceAfter": 9,
                },
            }
        )
        slide_artifact["content"]["slides"].append(
            {
                "title": "资料中的真实数量关系",
                "takeaway": "图表只使用资料已经提供的数值。",
                "layout": "chart",
                "icon": "chart",
                "richText": [{"lead": "边界", "text": "不为图表虚构数据。"}],
                "bullets": [],
                "visual": {"asset": "", "prompt": "", "alt": "", "caption": ""},
                "diagram": {"type": "", "nodes": []},
                "chart": {
                    "type": "bar",
                    "title": "示例数量",
                    "categories": ["甲", "乙", "丙"],
                    "series": [{"name": "数量", "values": [2, 5, 3]}],
                },
                "speakerNotes": "说明数值来自资料。",
                "citations": ["测试资料 · PDF第1页"],
                "transition": {"type": "split", "duration": 0.7, "advanceAfter": 8},
            }
        )
        with patch.dict(os.environ, {"ORACLE_EDITOR_ASSET_DIR": str(editor_root)}):
            deck, deck_type, deck_name = export_artifact(slide_artifact, "pptx")
        self.assertIn("presentationml.presentation", deck_type)
        self.assertTrue(deck_name.endswith(".pptx"))
        with zipfile.ZipFile(io.BytesIO(deck)) as archive:
            names = archive.namelist()
            self.assertGreaterEqual(len([name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]), 3)
            self.assertTrue(any("/charts/chart" in name for name in names))
            self.assertTrue(any(name.startswith("ppt/media/image") for name in names))
            self.assertTrue(any(name.startswith("ppt/notesSlides/notesSlide") for name in names))
            slide_xml = archive.read("ppt/slides/slide2.xml").decode("utf-8")
            self.assertIn("transition", slide_xml)
            self.assertIn("advTm=\"9000\"", slide_xml)
            self.assertIn("wipe", slide_xml)
            pres_props = archive.read("ppt/presProps.xml").decode("utf-8")
            self.assertIn("useTimings=\"1\"", pres_props)
            self.assertIn("loop=\"1\"", pres_props)

        package, package_type, _ = export_artifact(
            artifacts["video_package"], "zip"
        )
        self.assertEqual(package_type, "application/zip")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertEqual(
                {"script.md", "storyboard.csv", "captions.srt", "manifest.json"},
                set(archive.namelist()),
            )

    def test_generation_instruction_is_audited_and_audio_exports_as_wav(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("audio_guide")
        instruction = "面向高中生，语气清楚克制，控制在三分钟内。"
        generated = BailianAdapter().generate_artifact(
            "audio_guide",
            prompt,
            context["records"],
            context["excerpts"],
            instruction,
        )
        artifact = self.store.create_artifact(
            kind="audio_guide",
            title=generated["title"],
            content={"text": "你好。这里是甲骨日食音频导览测试。"},
            model=generated["model"],
            prompt_version=prompt["id"],
            generation_instruction=instruction,
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.assertEqual(artifact["generation_instruction"], instruction)

        with patch(
            "media_exports.BailianAdapter.synthesize_wav",
            return_value=test_wav_bytes(),
        ) as synthesize:
            raw, content_type, filename = export_artifact(artifact, "wav")
        synthesize.assert_called_once()
        self.assertEqual(content_type, "audio/wav")
        self.assertTrue(filename.endswith(".wav"))
        self.assertEqual(raw[:4], b"RIFF")
        self.assertEqual(raw[8:12], b"WAVE")
        self.assertGreater(audio_duration_seconds(raw), 0)

        old_artifact = {
            **artifact,
            "id": "legacy-audio-guide",
            "content": {
                "text": "以下是一份音频导览脚本草稿，依据资料生成。\n\n---\n各位观众，正文开始。"
            },
        }
        with patch(
            "media_exports.BailianAdapter.synthesize_wav",
            return_value=test_wav_bytes(),
        ) as legacy_synthesize:
            export_artifact(old_artifact, "wav")
        self.assertEqual(legacy_synthesize.call_args.args[0], "各位观众，正文开始。")

        with self.assertRaisesRegex(ValueError, "500"):
            self.store.create_artifact(
                kind="audio_guide",
                title="超长要求",
                content={"text": "测试"},
                model="test-model",
                prompt_version=prompt["id"],
                generation_instruction="测" * 501,
                source_ids=[source_id],
                unit_ids=context["unitIds"],
            )

    def test_audio_mp3_is_cached_as_compact_public_playback(self) -> None:
        artifact = {
            "id": "artifact-audio-preview",
            "kind": "audio_guide",
            "title": "轻量导览",
            "content": {"text": "甲骨里的日光缺口，音频导览。"},
            "media": {"model": "test-model", "voice": "test-voice"},
        }

        class Completed:
            returncode = 0
            stderr = b""

        def fake_ffmpeg(command, **_kwargs):
            Path(command[-1]).write_bytes(b"ID3" + b"compact-audio")
            return Completed()

        with patch("media_exports.BailianAdapter.synthesize_wav", return_value=test_wav_bytes()):
            with patch("media_exports.shutil.which", return_value="ffmpeg"):
                with patch("media_exports.subprocess.run", side_effect=fake_ffmpeg) as convert:
                    raw = render_audio_mp3(artifact)
                    cached = render_audio_mp3(artifact)
        self.assertEqual(raw, b"ID3" + b"compact-audio")
        self.assertEqual(cached, raw)
        convert.assert_called_once()

    def test_public_audio_endpoint_only_serves_current_published_work(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("audio_guide")
        artifact = self.store.create_artifact(
            kind="audio_guide",
            title="公开音频测试",
            content={"text": "甲骨里的日光缺口，正式音频测试。"},
            model="test-model",
            prompt_version=prompt["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        snapshot = build_snapshot(self.store)
        public_work = next(item for item in snapshot["works"] if item["id"] == artifact["id"])
        self.assertEqual(public_work["media"]["format"], "wav")
        self.assertEqual(public_work["media"]["provider"], "aliyun-bailian")
        self.assertEqual(public_work["media"]["model"], "qwen3-tts-flash")

        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.object(server_module, "load_published_snapshot", return_value=snapshot):
                with patch(
                    "media_exports.BailianAdapter.synthesize_wav",
                    return_value=test_wav_bytes(),
                ):
                    with urllib.request.urlopen(
                        f"{base}/api/public/artifacts/{artifact['id']}/audio"
                    ) as response:
                        raw = response.read()
                        self.assertEqual(response.headers.get_content_type(), "audio/wav")
                    with patch("media_exports.render_audio_mp3", return_value=b"ID3compact"):
                        with urllib.request.urlopen(
                            f"{base}/api/public/artifacts/{artifact['id']}/audio.mp3"
                        ) as response:
                            preview = response.read()
                            self.assertEqual(response.headers.get_content_type(), "audio/mpeg")
                            self.assertEqual(
                                response.headers.get("Cache-Control"),
                                "public, max-age=604800, immutable",
                            )
            self.assertEqual(raw[:4], b"RIFF")
            self.assertEqual(preview, b"ID3compact")
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(
                    f"{base}/api/public/artifacts/not-published/audio"
                )
            self.assertEqual(missing.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_public_card_endpoint_only_serves_published_visual_work(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="visual_card_set",
            title="公开图卡测试",
            content={
                "cards": [
                    {
                        "title": "日食原理",
                        "body": ["月球运行到太阳与地球之间。"],
                        "evidence": ["测试资料 · 位置1"],
                    }
                ]
            },
            model="test-model",
            prompt_version=self.store.prompt_for("visual_card_set")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        snapshot = build_snapshot(self.store)
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.object(server_module, "load_published_snapshot", return_value=snapshot):
                with urllib.request.urlopen(
                    f"{base}/api/public/artifacts/{artifact['id']}/cards/1.png"
                ) as response:
                    raw = response.read()
                    self.assertEqual(response.headers.get_content_type(), "image/png")
                with urllib.request.urlopen(
                    f"{base}/api/public/artifacts/{artifact['id']}/cards/1.webp"
                ) as response:
                    preview = response.read()
                    self.assertEqual(response.headers.get_content_type(), "image/webp")
                    self.assertEqual(
                        response.headers.get("Cache-Control"),
                        "public, max-age=86400, immutable",
                    )
            self.assertTrue(raw.startswith(b"\x89PNG"))
            self.assertTrue(preview.startswith(b"RIFF"))
            self.assertLess(len(preview), len(raw))
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(
                    f"{base}/api/public/artifacts/not-published/cards/1.png"
                )
            self.assertEqual(missing.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unreview_source_invalidates_dependent_content(self) -> None:
        source_id, candidate_id = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("public_explainer")
        generated = BailianAdapter().generate_artifact(
            "public_explainer", prompt, context["records"], context["excerpts"]
        )
        artifact = self.store.create_artifact(
            kind="public_explainer",
            title=generated["title"],
            content=generated["content"],
            model=generated["model"],
            prompt_version=prompt["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        self.store.unreview_source(source_id)
        self.assertEqual(self.store.get_source(source_id)["status"], "parsed")
        candidate = next(item for item in self.store.list_candidates() if item["id"] == candidate_id)
        self.assertEqual(candidate["status"], "stale")
        self.assertEqual(self.store.get_artifact(artifact["id"])["status"], "stale")
        self.assertEqual(self.store.list_published_knowledge(), [])

    def test_edit_candidate_and_artifact_return_to_review(self) -> None:
        source_id, candidate_id = self.seed_manual_source()
        candidate = next(item for item in self.store.list_candidates() if item["id"] == candidate_id)
        self.store.edit_candidate(
            candidate_id,
            title="编辑后的候选",
            summary="人工修订摘要",
            content={**candidate["content"], "dating": "尚不清楚"},
        )
        edited_candidate = next(item for item in self.store.list_candidates() if item["id"] == candidate_id)
        self.assertEqual(edited_candidate["status"], "candidate")
        self.assertEqual(self.store.list_published_knowledge(), [])

        self.store.review_candidate(candidate_id, "approve")
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("audio_guide")
        generated = BailianAdapter().generate_artifact(
            "audio_guide", prompt, context["records"], context["excerpts"]
        )
        artifact = self.store.create_artifact(
            kind="audio_guide", title=generated["title"], content=generated["content"],
            model=generated["model"], prompt_version=prompt["id"],
            source_ids=[source_id], unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        edited = self.store.edit_artifact(artifact["id"], title="修订导览", content={"text": "修订正文"})
        self.assertEqual(edited["status"], "draft")
        self.assertEqual(edited["publication_state"], "private")

    def test_withdraw_and_restore_release_versions(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("public_explainer")
        generated = BailianAdapter().generate_artifact(
            "public_explainer", prompt, context["records"], context["excerpts"]
        )
        artifact = self.store.create_artifact(
            kind="public_explainer", title=generated["title"], content=generated["content"],
            model=generated["model"], prompt_version=prompt["id"],
            source_ids=[source_id], unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        public_path = self.private_dir / "public.json"
        first = publish_snapshot(self.store, public_path)
        self.assertEqual(first["counts"]["works"], 1)
        published = self.store.get_artifact(artifact["id"])
        self.assertEqual(published["status"], "approved")
        self.assertEqual(published["publication_state"], "public")
        self.store.review_artifact(artifact["id"], "withdraw")
        withdrawn = self.store.get_artifact(artifact["id"])
        self.assertEqual(withdrawn["status"], "approved")
        self.assertEqual(withdrawn["publication_state"], "withdrawn")
        second = publish_snapshot(self.store, public_path)
        self.assertEqual(second["counts"]["works"], 0)
        restored = restore_snapshot(self.store, first["snapshotId"], public_path)
        self.assertEqual(restored["counts"]["works"], 1)
        self.assertEqual(restored["restoredFrom"], first["snapshotId"])
        restored_artifact = self.store.get_artifact(artifact["id"])
        self.assertEqual(restored_artifact["status"], "approved")
        self.assertEqual(restored_artifact["publication_state"], "public")

    def test_release_metadata_detail_and_protected_history_delete(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="public_explainer",
            title="版本管理测试作品",
            content={"text": "正文"},
            model="local",
            prompt_version=self.store.prompt_for("public_explainer")["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        public_path = self.private_dir / "public.json"
        first = publish_snapshot(
            self.store,
            public_path,
            title="首个稳定版本",
            description="完成首轮公众作品发布。",
            created_by="teacher",
        )
        detail = snapshot_detail(self.store, first["snapshotId"], public_path)
        self.assertEqual(detail["title"], "首个稳定版本")
        self.assertEqual(detail["description"], "完成首轮公众作品发布。")
        self.assertEqual(detail["createdBy"], "teacher")
        self.assertEqual(detail["works"][0]["title"], "版本管理测试作品")
        self.assertTrue(detail["current"])

        release = self.store.get_snapshot(first["snapshotId"])
        windows_path = str(release["path"]).replace("/", "\\")
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE publish_snapshots SET path = ? WHERE id = ?",
                (windows_path, first["snapshotId"]),
            )
        portable_detail = snapshot_detail(self.store, first["snapshotId"], public_path)
        self.assertEqual(portable_detail["id"], first["snapshotId"])
        self.assertTrue(self.store.list_snapshots()[0]["restorable"])

        with self.assertRaisesRegex(ValueError, "当前公众版本不能删除"):
            delete_snapshot(self.store, first["snapshotId"], public_path)

        second = publish_snapshot(
            self.store,
            public_path,
            title="第二个稳定版本",
            description="用于验证历史版本删除。",
            created_by="teacher",
        )
        self.assertNotEqual(first["snapshotId"], second["snapshotId"])
        first_archive = self.private_dir / "release-history" / f"{first['snapshotId']}.json"
        result = delete_snapshot(
            self.store,
            first["snapshotId"],
            public_path,
            reviewer="teacher",
        )
        self.assertTrue(result["deleted"])
        self.assertFalse(first_archive.exists())
        self.assertIsNone(self.store.get_snapshot(first["snapshotId"]))
        self.assertIsNotNone(self.store.get_artifact(artifact["id"]))

    def test_public_artifact_review_and_publication_states_are_independent(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="public_explainer", title="公开讲解", content={"text": "正文"},
            model="local", prompt_version=self.store.prompt_for("public_explainer")["id"],
            source_ids=[source_id], unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        path = self.private_dir / "public.json"
        publish_snapshot(self.store, path)

        edited = self.store.edit_artifact(
            artifact["id"], title="修订讲解", content={"text": "修订正文"}
        )
        self.assertEqual(edited["status"], "draft")
        self.assertEqual(edited["publication_state"], "public_stale")

        self.store.review_artifact(artifact["id"], "approve")
        approved = self.store.get_artifact(artifact["id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["publication_state"], "replacement_pending")

        publish_snapshot(self.store, path)
        republished = self.store.get_artifact(artifact["id"])
        self.assertEqual(republished["status"], "approved")
        self.assertEqual(republished["publication_state"], "public")

    def test_withdraw_artifact_updates_current_public_snapshot(self) -> None:
        source_id, _ = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        artifact = self.store.create_artifact(
            kind="public_explainer", title="公开讲解", content={"text": "正文"},
            model="local", prompt_version=self.store.prompt_for("public_explainer")["id"],
            source_ids=[source_id], unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        path = self.private_dir / "public.json"
        publish_snapshot(self.store, path)
        result = withdraw_artifact(self.store, artifact["id"], path)
        self.assertEqual(result["counts"]["works"], 0)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["works"], [])

    def test_reparse_and_delete_invalidate_dependencies(self) -> None:
        source_id, candidate_id = self.seed_manual_source()
        context = self.store.generation_context([source_id])
        prompt = self.store.prompt_for("record_table")
        generated = BailianAdapter().generate_artifact(
            "record_table", prompt, context["records"], context["excerpts"]
        )
        artifact = self.store.create_artifact(
            kind="record_table",
            title=generated["title"],
            content=generated["content"],
            model=generated["model"],
            prompt_version=prompt["id"],
            source_ids=[source_id],
            unit_ids=context["unitIds"],
        )
        self.store.review_artifact(artifact["id"], "approve")
        before = build_snapshot(self.store)
        self.assertEqual(len(before["recordsMeta"]["records"]), 1)
        result = self.store.parse_source(source_id, force=True)
        self.assertEqual(result["parseVersion"], 2)
        self.assertEqual(self.store.get_artifact(artifact["id"])["status"], "stale")
        stale_candidate = next(item for item in self.store.list_candidates() if item["id"] == candidate_id)
        self.assertEqual(stale_candidate["status"], "stale")
        after = build_snapshot(self.store)
        self.assertEqual(after["recordsMeta"]["records"], [])
        deleted = self.store.delete_source(source_id)
        self.assertEqual(deleted["status"], "deleted")

    def test_snapshot_excludes_private_material(self) -> None:
        self.seed_manual_source()
        literature_source = self.store.import_manual_text(
            "故宫博物院藏甲骨卜辞中记载的祖庚时期日食",
            "日有食，作为文献状态匹配测试。",
        )
        self.store.parse_source(literature_source["id"])
        self.store.mark_source_reviewed(literature_source["id"])
        snapshot = build_snapshot(self.store)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("private_path", serialized)
        self.assertNotIn("source-materials", serialized)
        self.assertNotIn("jgw.aynu.edu.cn", serialized)
        self.assertNotIn('"sourceUrl"', serialized)
        self.assertFalse(snapshot["audit"]["rawFilesIncluded"])
        reviewed_item = next(
            item for item in snapshot["literatureMeta"]["items"] if str(item["id"]) == "52172"
        )
        self.assertEqual(reviewed_item["researchStatus"], "reviewed")
        self.assertEqual(reviewed_item["detailUrl"], "/source.html?id=52172")
        self.assertEqual(
            sum(
                item.get("researchStatus") == "reviewed"
                for item in snapshot["literatureMeta"]["items"]
            ),
            1,
        )

    def test_url_import_rejects_private_network(self) -> None:
        with self.assertRaisesRegex(ValueError, "私有网络"):
            self.store._validate_remote_url("http://127.0.0.1/internal")

    def test_public_mode_blocks_legacy_data_and_private_path_variants(self) -> None:
        self.assertFalse(static_path_is_private("/data/published-snapshot.json"))
        self.assertTrue(static_path_is_private("/data/eclipse-records.json"))
        self.assertTrue(static_path_is_private("/data/../source-materials/research.db"))
        self.assertFalse(static_path_is_private("/assets/../research/index.html"))

        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(f"{base}/data/published-snapshot.json") as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(f"{base}/api/evidence") as response:
                evidence = json.loads(response.read().decode("utf-8"))
                self.assertTrue(evidence)
            with urllib.request.urlopen(f"{base}/source.html?id=52172") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
            for path in (
                "/data/eclipse-records.json",
                "/data/evidence-register.json",
                "/data/literature.json",
                "/data/../source-materials/research.db",
                "/assets/../research/index.html",
                "/source-materials/pdfs/52172.pdf",
                "/api/research/dashboard",
                "/research/",
            ):
                with self.subTest(path=path):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(f"{base}{path}")
                    self.assertEqual(raised.exception.code, 403)

            server.research_enabled = True  # type: ignore[attr-defined]
            with urllib.request.urlopen(f"{base}/research/") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_conflicts_remain_separate_and_unknown_question_is_refused(self) -> None:
        records = [
            {"headline": "观点甲", "scholarViews": ["甲说发生在前1161年"], "disputes": ["年代有争议"]},
            {"headline": "观点乙", "scholarViews": ["乙说应取另一年代"], "disputes": ["材料分期不同"]},
        ]
        output = BailianAdapter()._local_artifact("viewpoint_comparison", records, [])
        self.assertEqual(len(output["content"]["items"]), 2)
        knowledge, records_meta, literature = load_all()
        answer = mock_chat("请解释一条知识库完全没有收录的火星卜辞", knowledge, records_meta, literature)
        self.assertIn("不足", answer["answer"])
        self.assertEqual(answer["citations"], [])

    def test_site_content_requires_save_approve_and_publish(self) -> None:
        items = self.store.list_site_content()
        self.assertEqual([item["content_key"] for item in items], ["hero", "science", "history", "records"])
        original = self.store.public_site_content()["records"]["content"]["heading"]
        records = self.store.get_site_content("records")
        updated = {**records["content"], "heading": "新标题**不带星号**"}
        draft = self.store.save_site_content("records", updated, reviewer="测试编辑人")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["publication_state"], "outdated")
        self.assertEqual(self.store.public_site_content()["records"]["content"]["heading"], original)

        approved = self.store.review_site_content("records", "approve", reviewer="测试审核人")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.store.public_site_content()["records"]["content"]["heading"], "新标题不带星号")
        published = publish_snapshot(self.store, self.private_dir / "site-content-snapshot.json")
        self.assertEqual(published["counts"]["siteContent"], 4)
        self.assertEqual(self.store.get_site_content("records")["publication_state"], "public")

    def test_site_section_composer_supports_crud_order_visibility_and_shortcodes(self) -> None:
        managed = self.store.list_site_content(include_system=True)
        self.assertEqual(
            [item["content_key"] for item in managed],
            ["hero", "science", "history", "records", "works", "ask", "sources"],
        )
        created = self.store.create_site_content(
            title="安全观测",
            nav_label="safety",
            kicker="先保护眼睛",
            summary="说明安全观测边界。",
            body_html="<p>只使用合格的太阳观测镜。</p><script>alert(1)</script>",
        )
        self.assertEqual(created["status"], "draft")
        self.assertNotIn("script", created["body_html"])
        self.assertNotIn(created["content_key"], self.store.public_site_content(include_system=True))

        with self.assertRaisesRegex(ValueError, "未知栏目简码"):
            self.store.save_site_content(
                created["content_key"],
                {},
                body_html="<p>[未经登记的数据]</p>",
            )

        saved = self.store.save_site_content(
            created["content_key"],
            {},
            title="安全观测日食",
            nav_label="安全观测",
            body_html="<p>观测前先检查设备。</p>",
            enabled=True,
        )
        self.assertEqual(saved["title"], "安全观测日食")
        self.store.review_site_content(created["content_key"], "approve")
        public = self.store.public_site_content(include_system=True)
        self.assertIn(created["content_key"], public)
        self.assertIn("观测前", public[created["content_key"]]["bodyHtml"])

        keys = [item["content_key"] for item in self.store.list_site_content(include_system=True)]
        reversed_keys = list(reversed(keys))
        reordered = self.store.reorder_site_content(reversed_keys)
        self.assertEqual([item["content_key"] for item in reordered], reversed_keys)

        hidden = self.store.save_site_content(
            created["content_key"],
            {},
            enabled=False,
        )
        self.assertFalse(hidden["enabled"])
        self.store.review_site_content(created["content_key"], "approve")
        self.assertNotIn(created["content_key"], self.store.public_site_content(include_system=True))
        self.store.delete_site_content(created["content_key"])
        self.assertNotIn(
            created["content_key"],
            [item["content_key"] for item in self.store.list_site_content(include_system=True)],
        )
        snapshot = build_snapshot(self.store)
        self.assertEqual(snapshot["schemaVersion"], "0.6")
        self.assertEqual(
            set(snapshot["siteContent"]),
            {"hero", "science", "history", "records", "works", "ask", "sources"},
        )

    def test_documentary_method_keeps_creative_notes_separate_from_evidence(self) -> None:
        context = server_module.documentary_generation_context(
            "science",
            "alignment_drag",
            "先观察日面缺口，再拉远到月球影锥；不要复述脚本。",
        )
        self.assertEqual(context["methodVersion"], "documentary-method-v2")
        self.assertEqual(context["interactionPattern"]["id"], "alignment_drag")
        self.assertIn("日月地关系", context["contentBrief"])
        self.assertIn("只用于叙事", context["evidenceBoundary"])
        self.assertNotIn("verifiedPublicKnowledge", context)
        self.assertIn("现象—尺度—机制—互动—证据", server_module.DOCUMENTARY_AGENT_METHOD)
        with self.assertRaisesRegex(ValueError, "互动模式无效"):
            server_module.documentary_generation_context("science", "unknown", "")
        with self.assertRaisesRegex(ValueError, "不能超过2000字"):
            server_module.documentary_generation_context("science", "auto", "观" * 2001)

    def test_site_generation_modes_keep_package_and_html_scope_separate(self) -> None:
        current = self.store.get_site_content("history")
        package_response = {
            "title": "甲骨时代的新标题",
            "navLabel": "走进甲骨时代",
            "kicker": "从一次天象记录开始",
            "summary": "面向公众的栏目摘要。",
            "bodyHtml": "<p>先观察记录行为，再理解证据边界。</p>",
            "content": {
                **current["content"],
                "image": {
                    "assetId": "siteasset-deadbeef0000",
                    "url": "https://invalid.example/image.png",
                    "alt": "模型生成的替代文字",
                    "caption": "模型生成的图片说明",
                },
            },
            "image": {
                "prompt": "深色天幕与日食影锥的科学传播画面，无文字",
                "alt": "日食与甲骨时代主题配图",
                "caption": "AI生成栏目配图，非甲骨原片",
            },
        }
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}), patch.object(
            BailianAdapter, "complete", return_value=json.dumps(package_response, ensure_ascii=False)
        ):
            content, meta, image_spec, _, prompt_version = server_module.generate_site_content(
                "history", current, "section_package", "语言简洁"
            )
        self.assertEqual(meta["nav_label"], "走进甲骨时代")
        self.assertIn("[甲骨时代导读]", meta["body_html"])
        self.assertEqual(content["image"]["assetId"], current["content"]["image"]["assetId"])
        self.assertEqual(content["image"]["url"], current["content"]["image"]["url"])
        self.assertIn("科学传播画面", image_spec["prompt"])
        self.assertEqual(prompt_version, "site-content:section_package-v1")

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key"}), patch.object(
            BailianAdapter,
            "complete",
            return_value=json.dumps({"bodyHtml": "<h3>只生成正文</h3><p>不改其他字段。</p>"}, ensure_ascii=False),
        ):
            html_content, html_meta, html_image, _, html_prompt_version = server_module.generate_site_content(
                "history", current, "html_body", "正文分成两个短段落"
            )
        self.assertEqual(html_content, current["content"])
        self.assertEqual(html_meta["title"], current["title"])
        self.assertEqual(html_meta["nav_label"], current["nav_label"])
        self.assertIn("只生成正文", html_meta["body_html"])
        self.assertIn("[甲骨时代导读]", html_meta["body_html"])
        self.assertEqual(html_image, {})
        self.assertEqual(html_prompt_version, "site-content:html_body-v1")

    def test_generated_site_image_uses_private_asset_reference(self) -> None:
        asset_id = "siteasset-abcdef123456"
        content, body_html = server_module.attach_generated_site_image(
            "science",
            self.store.get_site_content("science")["content"],
            "<p>[日食科学互动]</p>",
            asset_id,
            {"alt": "日月地关系示意配图", "caption": "科学传播配图"},
        )
        self.assertIn("site-generated-visual", body_html)
        self.assertIn(f"/api/research/site-content/assets/{asset_id}", body_html)
        saved = self.store.save_site_content("science", content, body_html=body_html)
        self.assertIn("site-generated-visual", saved["body_html"])
        self.assertIn("[日食科学互动]", saved["body_html"])

    def test_site_media_is_private_until_referenced_by_snapshot(self) -> None:
        asset = self.store.store_site_asset("banner.png", "image/png", test_png_bytes())
        self.assertEqual(asset["media_type"], "image")
        hero = self.store.get_site_content("hero")
        hero["content"]["slides"][0]["assetId"] = asset["id"]
        self.store.save_site_content("hero", hero["content"])
        before = self.store.public_site_content()["hero"]["content"]["slides"][0]
        self.assertFalse(before["assetId"])
        self.store.review_site_content("hero", "approve")
        snapshot = build_snapshot(self.store)
        slide = snapshot["siteContent"]["hero"]["content"]["slides"][0]
        self.assertEqual(slide["mediaUrl"], f"/api/public/site-media/{asset['id']}")
        self.assertTrue(server_module.public_snapshot_references_site_asset(snapshot, asset["id"]))
        self.assertFalse(server_module.public_snapshot_references_site_asset(snapshot, "siteasset-000000000000"))

        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        server.research_enabled = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server_module, "load_published_snapshot", return_value=snapshot):
                with patch.object(server_module, "research_store", return_value=self.store):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/public/site-media/{asset['id']}"
                    ) as response:
                        preview = response.read()
                        self.assertEqual(response.headers.get_content_type(), "image/webp")
                        self.assertEqual(
                            response.headers.get("Cache-Control"),
                            "public, max-age=604800, immutable",
                        )
            self.assertTrue(preview.startswith(b"RIFF"))
            self.assertEqual(preview[8:12], b"WEBP")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
