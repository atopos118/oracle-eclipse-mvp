# 技术报告：《甲骨里的日光缺口》MVP 0.4

## 1. 系统组成

系统分为公众科普站和本机研究域。研究域包含资料研究台、输出工作室和审核发布中心；公众域只读取审核发布后的稳定快照。

```text
PDF / URL / 手动文本
  -> 私有SQLite证据库
  -> 解析单元与页码
  -> 候选知识
  -> 人工审核
  -> 发布知识
  -> 输出草稿
  -> 人工审核
  -> 稳定公众快照
  -> 公众站与公众问答
```

## 2. 技术实现

- 前端：原生HTML、CSS和JavaScript。
- 服务：Python标准库`ThreadingHTTPServer`。
- 私有存储：SQLite，启用外键。
- PDF解析：`pypdf`，逐页保存定位信息。
- 模型：统一`BailianAdapter`；无密钥时使用本地模板。
- 发布：原子写入`data/published-snapshot.json`并记录发布批次。

## 3. 数据表

- `source_documents`：资料元数据、指纹、状态与解析版本。
- `source_units`：PDF页或文本单元。
- `knowledge_candidates`：模型/规则提取的候选知识。
- `published_knowledge`：审核通过的知识。
- `artifacts`：作品草稿与发布作品。
- `lineage_edges`：资料、页码、知识和作品的来源关系。
- `review_events`：审核、失效和发布事件。
- `prompt_versions`：提示词版本。
- `publish_snapshots`：发布批次。

`lineage_edges.upstream_type`只允许`source`、`unit`和`knowledge`，从结构上禁止作品或模型输出回流为证据。

## 4. 安全与发布

- 本机研究模式只接受`127.0.0.1`或`::1`访问研究域。
- `--public-only`关闭研究UI和研究API。
- 私有资料、数据库、缓存和临时目录均返回403。
- `data/`采用公开白名单，只允许稳定快照文件；旧迁移JSON和变形路径返回403。
- URL导入拒绝本机、私有网段和非HTTP(S)协议。
- PDF和JSON请求分别限制为25MB和36MB。
- 公众快照不包含内部路径、原始资料或全文块。

## 5. 首版输出

- 甲骨日食记录表。
- 学者观点与争议对照。
- 大众讲解稿。
- 音频导览文稿、百炼正式中文WAV、研究台/公众端网页播放器与下载。

每个草稿保存模型、提示词版本、输入资料版本和页码关系。草稿必须人工批准，发布时才进入作品库快照。

## 6. API

公众：`/api/health`、`/api/snapshot`、`/api/records`、`/api/evidence`、`/api/search`、`/api/chat`。  
研究：`/api/research/dashboard`、`sources`、`candidates`、`artifacts`、`lineage`、`publish`及对应审核动作。

## 7. 当前验证

- 8项隔离数据库与HTTP边界回归测试通过。
- 本机研究模式可访问研究台，私有目录返回403。
- 公众模式下研究UI、研究API和私有目录均返回403。
- 公众快照包含3条记录和5项审核知识，不含原始文件。
- 四类首版输出均已生成待审核草稿。
- 浏览器自动视觉读取受本地URL安全策略限制，桌面与移动端视觉检查保留为人工项。
