# GitHub 项目说明

## 项目介绍

“甲骨里的日光缺口”是一个面向科学传播的历史天文学多模态研究与展示系统。项目以商代甲骨日食记录为证据入口，将文献、图像、古文字释读和学术争议组织成可审计的证据链，并输出公众科普站、研究工作台、问答、图卡、音频、视频、幻灯片、白板和思维导图。

系统采用 Qwen/DashScope 完成 OCR、检索增强问答、语音和视觉草稿生成；文字、证据边界、版权范围和最终发布由本地程序与人工审核控制。公众端仅读取 `data/published-snapshot.json`，不会展示论文原文、OCR 原文或页码。

## 仓库结构

- `server.py`：HTTP 服务、公众站和研究台 API。
- `research_store.py`：SQLite 私有研究库、审核和失效传播。
- `bailian_adapter.py`：Qwen/DashScope 适配层。
- `research/`：研究工作台前端。
- `assets/`：已审核的公开图片、音频、视频和字体素材。
- `data/published-snapshot.json`：公众运行时快照。
- `docs/`、`deploy/`：产品、技术和部署说明。
- `tests/`：研究工作流与安全边界测试。

私有数据库、原始 PDF、OCR 页面、生成缓存和部署密钥不属于 GitHub 仓库内容，使用本地目录或 Coolify 持久化卷保存。

## 本地部署

```powershell
copy .env.example .env
python -m pip install -r deploy/ubuntu/requirements-server.txt
python server.py --host 127.0.0.1 --port 8010
```

公众站地址：`http://127.0.0.1:8010/`。研究台地址：`http://127.0.0.1:8010/research/`。`.env` 由 `python-dotenv` 在启动时读取；也可以直接设置当前用户环境变量覆盖它。

## Coolify 部署

使用仓库根目录 `Dockerfile` 构建。在 Coolify Environment Variables/Secrets 中设置：

```text
DASHSCOPE_API_KEY=<secret>
ORACLE_RESEARCH_USERNAME=<workbench-user>
ORACLE_RESEARCH_PASSWORD=<strong-password>
ORACLE_PUBLIC_CORS_ORIGIN=https://your-domain.example
ORACLE_RESEARCH_DB_PATH=/app/runtime-data/research.db
```

创建持久化存储并挂载到 `/app/runtime-data`。演示数据库应通过持久化卷注入，不要提交 `research.db`。公网演示通过 Coolify 反向代理提供 HTTPS，并参照 `deploy/公网比赛演示部署说明.md` 配置 `--public-demo`、可信代理和安全 Cookie。

## 安全与版权

不要提交 API Key、研究台密码、原始论文、OCR 页面或私有数据库。若凭据曾经出现在 Git 历史中，应立即在对应平台轮换并按 GitHub 文档清理历史。项目仅用于学生竞赛科研演示；正式落地前需取得文献版权方许可。

## 验证

```powershell
python -m unittest discover -s tests -v
node --check app.js
node --check research/research.js
python -m py_compile server.py research_store.py bailian_adapter.py media_exports.py snapshot_manager.py
```
