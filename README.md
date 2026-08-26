# 甲骨里的日光缺口 正式版 1.0.0

## GitHub 快速开始

本仓库包含公众科普站、登录后的研究工作台，以及基于 Qwen/DashScope 的多模态作品生成能力。公开运行时只读取 `data/published-snapshot.json`；论文原文和 OCR 文本属于私有研究数据，不应提交到 GitHub。

### 本地运行

```powershell
copy .env.example .env
# 编辑 .env，至少设置 ORACLE_RESEARCH_USERNAME 和 ORACLE_RESEARCH_PASSWORD
python -m pip install -r deploy/ubuntu/requirements-server.txt
python server.py --host 127.0.0.1 --port 8010
```

打开 `http://127.0.0.1:8010/` 查看公众站，打开 `http://127.0.0.1:8010/research/` 进入研究台。需要 Qwen 能力时，在当前用户环境变量或部署平台 Secret 中设置 `DASHSCOPE_API_KEY`；不要把真实 Key 写入 `.env` 后提交，`.env` 已被 Git 忽略。

### Docker / Coolify

项目提供 `Dockerfile`。Coolify 中建议使用环境变量/Secret 配置凭证，而不是上传 `.env` 文件：

```text
DASHSCOPE_API_KEY=<secret>
ORACLE_RESEARCH_USERNAME=<workbench-user>
ORACLE_RESEARCH_PASSWORD=<strong-password>
ORACLE_PUBLIC_CORS_ORIGIN=https://your-domain.example
ORACLE_RESEARCH_DB_PATH=/app/runtime-data/research.db
```

将持久化卷挂载到 `/app/runtime-data`，并在首次部署前将演示数据库放入该卷。数据库文件不在 Git 仓库中，重建镜像不会覆盖持久化数据。公网演示必须通过 Coolify/Nginx/Caddy 的 HTTPS 反向代理，并按 `deploy/公网比赛演示部署说明.md` 配置 `--public-demo`、可信代理和安全 Cookie。

### 环境变量说明

`.env.example` 只是本地配置模板，不能作为生产密钥文件。生产环境的 `DASHSCOPE_API_KEY`、研究台账号密码和域名应由 Coolify Environment Variables/Secrets、systemd EnvironmentFile 或云平台 Secret 管理。完整变量模板见 `deploy/ubuntu/oracle-eclipse.env.example` 与 `deploy/aliyun/oracle-eclipse.env.example`。

### 运行验证

```powershell
python -m unittest discover -s tests -v
node --check app.js
node --check research/research.js
python -m py_compile server.py research_store.py bailian_adapter.py media_exports.py snapshot_manager.py
```

更多架构、数据边界和部署细节见 `docs/`、`deploy/` 和本文后续章节。

当前版本：`1.0.0`。这是面向云端部署的正式发布基线；运行时版本可通过 `ORACLE_APP_VERSION` 覆盖，默认值为 `1.0.0`。

项目由公众科普站、研究工作台、输出工作室、审核发布中心、阿里云百炼适配层和可审计证据库组成。首期范围限定为7篇核心资料，不建设通用NotebookLM替代产品。

MVP 0.4在记录表、观点对照、大众讲解稿和音频导览四类核心输出之外，新增可审计的科普图卡组、讲解幻灯片、视频制作包、研究白板和思维导图。音频导览通过阿里云百炼语音模型生成中文WAV，图卡结构由百炼生成、插图按卡片显式调用百炼文生图后与本地文字排版合成PNG，幻灯片结构由百炼生成并本地导出可编辑PPTX，视频作品先保留脚本、分镜、SRT字幕和来源清单，再通过百炼 HappyHorse 异步生成并拼接为可直接播放的短片MP4；不把AI画面当作甲骨原片。图卡和幻灯片在研究工作台与公众站均支持单页翻页阅读；白板和思维导图共用可审计节点关系模型，支持版面预设、自定义宽高、节点边界回收、曲线关系和四类节点视觉语义，在公众端只读展示已审核发布版本。全部20类输出均可填写最多500字的可选生成要求，该字段只控制表达方式，不能改变资料事实和来源边界。

研究工作台另设“站点内容”，统一管理公众站全部内容栏目。栏目支持新增、删除、排序、显示/隐藏；引言、标题和摘要采用结构化字段，其余正文使用可视HTML/源码双模式编辑器。日食互动、甲骨记录、研究成果、公众问答和研究依据通过白名单简码读取已审核数据。Banner继续支持图片、MP4/WebM视频、封面图和动态轮播。AI编辑简化为“生成完整栏目”和“仅生成正文HTML”两个范围：前者生成引言、导航名、标题、摘要、正文、组件文案并调用百炼生成私有栏目配图，后者只改正文HTML；两者都可叠加自定义提示词。所有修改都先保存为草稿，批准后随新版本发布；AI只改变表达，不补写甲骨事实，也不把纪录片内容当作证据。

纪录片内容转化与版权、证据边界见`docs/06-纪录片内容转化规范.md`。

## 本机研究模式

```powershell
python server.py --port 8000
```

首次使用先配置研究工作台登录账号。密码使用隐藏输入，不写入项目代码或数据库：

```powershell
powershell -ExecutionPolicy Bypass -File tools/configure_research_login.ps1
```

配置百炼和研究账号后，建议从普通 PowerShell 运行 `tools/start_research.ps1`。脚本会先检查
`dashscope.aliyuncs.com:443` 是否可访问。若出现 `WinError 10013`，说明请求尚未到达百炼，
需要允许当前 `python.exe` 的 HTTPS 出站连接，并检查 Windows 防火墙、安全软件、VPN 或单位网络策略。

普通问答和作品生成默认等待百炼响应120秒，可通过用户环境变量`QWEN_REQUEST_TIMEOUT`设置为30至300秒。作品生成只向模型发送每篇资料中与日食、卜辞、断代和争议最相关的有限页码摘录，完整逐页来源关系仍保留在本地。若作品生成超过时限，系统会透明切换到本地证据模板并在作品模型字段中记录超时降级，不会把失败结果写入证据库。

- 公众站：`http://127.0.0.1:8000/`
- 研究工作台：`http://127.0.0.1:8000/research/`（登录后访问）
- 公开来源详情：`http://127.0.0.1:8000/source.html?id=<来源编号>`

研究工作台默认只允许本机访问，并要求账号登录；会话 Cookie 仅供本站使用、不能被前端脚本读取，默认登录有效期为8小时。工作台支持PDF、网页链接和手动文本汇入。资料自动解析后先经过文本质量门：正常文本层可查看但不能进入问答与输出，异常PDF进入百炼逐页OCR；OCR文本确认后会同步完成来源确认，不再增加独立的“资料复核”步骤。PDF详情提供嵌入式原页和页码原文联动校核；作品批准与发布只在准备公众内容时形成门槛；“待确认知识”不再是研究前置模块。

正式WAV使用阿里云百炼原生 Qwen3-TTS 接口和`qwen3-tts-flash`，默认中文声音为`Cherry`。可通过`QWEN_TTS_MODEL`和`QWEN_TTS_VOICE`调整；生成文件缓存在私有目录，研究工作台可直接播放和下载，公众端只提供当前发布版本中的音频。

### 视频成片

视频制作包在研究工作台中提供测试模式和正式模式。测试模式固定生成5个镜头、每个3秒，总时长15秒，分辨率为640×360；正式模式暂不制作。测试片段由 FFmpeg 按顺序拼接并校验实际时长。Windows 本地运行时可将 FFmpeg 路径设置到`ORACLE_FFMPEG_BIN`。单个任务默认最多等待900秒，可通过`QWEN_VIDEO_TIMEOUT`调整。模型权限和账户余额仍由百炼账号控制。

## 公众部署模式

```powershell
python server.py --host 127.0.0.1 --port 8000 --public-only
```

该模式禁用研究UI和研究API。公众站只读取`data/published-snapshot.json`，不读取私有数据库、候选知识或草稿。应用只监听本机地址，再由Caddy或安全隧道提供HTTPS公网入口；不要直接开放8000端口。
`data/`采用公开白名单：除稳定快照外，旧迁移JSON均返回403；公开证据登记统一通过`/api/evidence`提供。

云端正式部署建议使用 `--public-demo`（公众站 + 受保护的研究工作台），并通过 systemd 管理进程、Nginx/Caddy 终止 HTTPS。部署模板位于 `deploy/aliyun/` 和 `deploy/ubuntu/`，正式环境必须设置 `ORACLE_APP_VERSION=1.0.0`、研究账号、密钥和可信代理来源，且不要将 `.env` 或 SQLite 私库放入代码仓库。

Coolify 演示部署请为应用创建持久化目录并挂载到容器内（例如 `/app/runtime-data`），设置运行时变量
`ORACLE_RESEARCH_DB_PATH=/app/runtime-data/research.db`。首次启动前，仅当该文件不存在时，
从仓库内的 `source-materials/research-pre-quality-reassessment-20260721.db` 复制一份作为演示初始库；
后续部署不得覆盖该文件。这样数据库只保存在 Coolify 持久化存储中，不进入 Git，也不会因重新构建容器而丢失。

## 公网比赛演示模式

比赛演示需要同时开放公众站和登录后的研究工作台时，应用仍必须绑定`127.0.0.1`，再由Caddy或安全隧道提供HTTPS入口：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_public_demo.ps1 -PublicOrigin "https://demo.example.com"
```

该模式启用Secure会话Cookie、受信任本机代理来源识别、登录限流和公众问答限流；未配置研究账号时拒绝启动。公网入口包括公众站`/`、参赛作品入口`/showcase/`、在线技术报告`/showcase/technical-report.html`和登录后的研究工作台`/research/`。禁止把8000端口直接暴露到公网。通用步骤见`deploy/公网比赛演示部署说明.md`；阿里云正式部署包、ECS安全组、域名迁移、备份和验收见`deploy/aliyun/阿里云ECS部署与迁移说明.md`。

本机研究模式在已配置研究账号后，会在登录按钮下方显示“一键登录研究工作台”，直接签发服务端 HttpOnly 会话，不把账号密码发送到浏览器。公开演示模式默认隐藏该入口；如比赛现场确需评委免输账号进入，启动前显式设置`ORACLE_QUICK_LOGIN_ENABLED=1`，并仅通过 HTTPS 反向代理提供访问。普通公网部署保持默认`0`。

## 百炼配置

正式百炼问答、作品生成、云端OCR和语音合成需要 API Key；资料导入、质量检测、审核和发布版本不需要。不要把密钥写入代码、`.env`、数据库或聊天内容。OCR模型可通过`QWEN_OCR_MODEL`配置，默认`qwen-vl-ocr-latest`；语音模型和声音分别通过`QWEN_TTS_MODEL`、`QWEN_TTS_VOICE`配置。

推荐使用隐藏输入脚本，将密钥保存到当前 Windows 用户环境变量：

```powershell
powershell -ExecutionPolicy Bypass -File tools/configure_bailian.ps1
```

配置后先停止旧服务，再使用统一启动脚本。该脚本会主动从 Windows 用户环境变量加载密钥，避免原 PowerShell 窗口没有刷新环境变量：

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_research.ps1
```

启动后在研究工作台顶部点击模型状态，即可执行一次低成本连接检测。连接成功后显示`百炼 · qwen-plus`。

密钥只从环境变量读取，状态接口不会返回密钥。无密钥时，公众问答、私有资料问答和输出工作室使用确定性的本地保底；百炼调用失败时返回本地发布知识或相关资料摘录。清除配置：

调用百炼时不会上传原始PDF或整个私有数据库。OCR只发送本机渲染的单页PNG；公众问答只发送当前发布版本中检索到的相关知识；私有资料问答和作品生成只发送用户主动选择资料中的相关解析文本片段。相关页面或片段会传输到阿里云百炼完成推理，因此涉及第三方传输的资料必须先获得相应使用授权。

```powershell
powershell -ExecutionPolicy Bypass -File tools/clear_bailian.ps1
```

## 数据边界

| 数据 | 存储 | 公开情况 |
|---|---|---|
| 原始PDF、网页正文、手动文本、逐页文本 | `source-materials/`与私有SQLite | 不公开 |
| 发布知识与审核事件 | 私有SQLite | 不公开，只有批准内容进入快照 |
| 已批准知识 | 私有SQLite | 发布时进入快照 |
| 作品草稿 | 私有SQLite | 审核前不公开 |
| 站点内容草稿与Banner媒体 | 私有SQLite与`source-materials/site-assets/` | 批准并发布后，仅允许当前版本引用的媒体通过公众接口读取 |
| 媒体导出文件 | 根据结构化作品按需生成 | 仅随对应作品的审核与发布边界使用，不包含原始PDF |
| 稳定公众快照 | `data/published-snapshot.json` | 公众端唯一运行时数据源 |

公众端论文标题只链接项目内部来源详情，不链接原始文献平台，也不提供私有PDF。原始取得地址只保留在私有研究资料元数据中。

模型生成结果可以保存为带有`generated_note`角色的AI研究笔记或作品草稿，但不允许成为证据库上游，也不参与后续模型检索。资料删除或重解析会将依赖知识和作品标记为`stale`，必须重新审核后才能发布。

研究与发布采用双通道：通过文本质量门的资料先完成一次来源确认，只有`reviewed`资料才能进入本机问答和草稿生成；未经确认的资料不参与问答与输出。PDF点击一次“确认OCR文本”后即标记为`reviewed`，正常文本点击一次“确认资料”后标记为`reviewed`，随后可进入下一公众发布版本。发布知识保留为公众快照的数据层，但不再单独设置“待确认知识”导航或前置审核队列。

PDF识别增加独立质量状态：`ocr_pending -> ocr_processing -> ocr_needs_review -> ocr_ready`。低质量旧文本不会参与问答或知识提取；OCR完成后生成新的解析版本，人工确认前仅供私有探索，确认后同步完成来源确认。

## 主要文件

- `research_store.py`：SQLite数据模型、资料工作流、站点内容、私有媒体、审核和失效传播。
- `bailian_adapter.py`：百炼与本地输出适配。
- `media_exports.py`、`tools/export_presentation.mjs`：调用百炼语音、视频并通过`@oai/artifact-tool`把媒体作品导出为WAV、PNG、增强可编辑PPTX和视频制作包ZIP。
- `ocr_pipeline.py`、`text_quality.py`：PDF逐页渲染、百炼OCR、识别版本与文本质量门。
- `snapshot_manager.py`：稳定公众快照生成与发布。
- `research/`：研究工作台、输出工作室和审核发布界面。
- `server.py`：公众API、研究API和两种运行模式。
- `data/published-snapshot.json`：公众站与公众问答共同读取的快照。
- `tools/init_research_store.py`：将MVP 0.3已核验内容迁入研究库。
- `tests/test_research_workflow.py`：即时研究、发布审核门、去重、失效传播、隐私与拒答测试。
- `evaluation/`：25题百炼正式问题集、自动检查脚本与不回流研究库的验收报告。
- `user-testing/`：8人用户测试任务、观察记录、SUS问卷、汇总表和汇总工具。
- `docs/01-产品设计_MVP0.4.md`至`05-预期成果_MVP0.4.md`：实施基线。

## 验证

```powershell
python -m unittest discover -s tests -v
node --check app.js
node --check research/research.js
python -m py_compile server.py research_store.py bailian_adapter.py media_exports.py snapshot_manager.py
```

## 当前资料进度

- 核心资料：7篇均已导入，共81页；OCR重建和来源确认均已完成。
- 已据原刊核验：《合集》11480、《合集》21298（《宫藏谢》17）、《合集》33696。
- 输出能力：富文本作品支持受控Lucide图标、配图计划、手动图片和按位置调用百炼生成配图；幻灯片支持逐页版式、富文本、图标、图片、原生智能图形、真实数据图表、讲者备注、在线播放、自动换页和转场，并导出为可继续编辑的PPTX。
- 自动验证：72项测试覆盖研究工作流、HTTP边界、来源失效、生成要求、媒体文件结构、作品文生图适配、增强PPTX图表/备注/转场、栏目编排与简码安全、站点媒体发布隔离、公众翻页资源、结构化画布约束和公众问答检索边界。
- 百炼验收：25题首轮全部由`qwen-plus`回答，23题自动通过；发现的总结缺引用和范围外问题误挂引用已修复并由回归测试覆盖，待正常重启服务后复跑并完成人工签署。
- 用户测试：8个测试席位、任务、观察记录、SUS问卷和汇总工具已组织完成；真实参与者仍待招募和执行，不预填结果。
- 下一步：先确认白板/思维导图视觉方案，再由古文字学与天文学教师完成百炼报告人工复核，并执行至少5名真实用户测试。第7、8项在这些工作完成后启动。
