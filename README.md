# PrivacyLens 隐私防护小型实验

基于 [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) 数据，使用 Qwen 比较基础提示、隐私增强提示和 PII 过滤对情境隐私泄露与任务完成的影响。项目属于 [Pattern Recognition 课程 Assignment 1 的 T02-B](https://github.com/tulip-lab/pattern-classification-lab/blob/develop/Assignments/frontier-ai-presentation/topics.md)，采用独立轻量实现。

实验条件为 A0 基础提示、A1 隐私增强提示与 A2 对对应 A0 输出进行 PII 过滤。当前入口连接任务输入、模型生成、本地过滤与自动评价；评价结果通过人工抽查校准。

## 目录

```text
run.py                     统一命令入口
experiment/
  prepare_data.py          准备生成输入与评价标签
  build_prompts.py         构造 A0/A1 请求
  run_input.py             调用模型生成最终动作
  run_filter.py            使用本地 Presidio 从已有 A0 派生 A2
  gliner_recognizer.py     GLiNER 标签映射与长文本分块
  context_policy.py        正反项标签、上下文识别与片段处理决策
  setup_filter.py          下载过滤模型与 tokenizer
  pii_rules.py             一致伪名、明确姓名别名与概念泛化
  reproducibility.py       固定随机种子与确定性配置
  run_comment.py           独立评价隐私与任务完成度
  run_stat.py              汇总评价指标并生成图表
  run_pipeline.py          串联生成、过滤、评分和统计
  common.py                文件操作与 API 请求
prompts/                   任务模板、裁判标准、工具说明及版本归档
docs/                      各类文档
data/                      benchmark 与开发样本
artifacts/                 本地请求计划、运行与评价产物
```

## 环境与模型

建议使用 Windows PowerShell、Python 3.10 或 3.11，以及项目内虚拟环境。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_sm
.\.venv\Scripts\python.exe -X utf8 .\run.py setup-filter
```

`setup-filter` 首次联网下载 `urchade/gliner_medium-v2.1` 的权重、编码器配置与 tokenizer，保存至 `models/gliner_medium-v2.1/`。A2 随后在本地 CPU 运行，模型配置与分块规则见 [过滤说明](docs/filtering.md)。

按照 `.env.example` 配置本机 `.env`：

```dotenv
DASHSCOPE_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=your_qwen_base_url
BASE_MODEL=qwen3.5-flash
REF_MODEL=qwen3.5-flash
```

生成使用 `BASE_MODEL`；隐私与 helpfulness 裁判分别在独立会话中使用 `REF_MODEL`。默认复用 Flash。裁判选择与人工校准方法见 [评价协议](docs/evaluation.md)。

## 准备样本与提示

所有命令在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe .\run.py prepare --limit 5
.\.venv\Scripts\python.exe .\run.py prompts
```

准备阶段默认读取 `data/main_data.json` 的前 5 条，将模型可见字段写入 `data/pilot/inputs.json`，评价数据写入 `labels.json`，选择信息写入 `manifest.json`。可用 `--source`、`--output-dir` 和 `--limit` 指定数据来源、产物目录与开发案例数量。

提示阶段默认读取 `data/pilot/inputs.json`，生成 `artifacts/prompts/pilot_v2.jsonl`；支持 `--input` 与 `--output` 指定路径。A0 为 `a0_v1`，A1 为 `a1_v2`，两者共用同一份案例正文，A1 追加情境隐私要求。模板说明见 [prompts/README.md](prompts/README.md)。

## 运行流程

三组实验使用 `input → filter → comment → stat`。其中 A0/A1 来自模型生成，A2 由同一次 A0 输出派生：

```mermaid
flowchart LR
    I["input：生成 A0/A1"] --> F["filter：A0 派生 A2"]
    I --> C["comment：评价 A0/A1/A2"]
    F --> C
    C --> S["stat：统计与图表"]
```

| 命令 | 输入 → 输出 | 执行方式 |
| --- | --- | --- |
| `input` | 提示 JSONL → A0/A1 最终动作 | 调用 BASE_MODEL |
| `filter` | 生成结果中的 A0 → 配对 A2 | 本地 Presidio |
| `comment` | 一个或多个 A0/A1/A2 结果文件 → 裁判记录与 summary.json | 每条有效输出调用 REF_MODEL 两次 |
| `stat` | 一个或多个 summary.json → JSON 统计和 PNG 图 | 本地计算 |
| `pipeline` | 提示 JSONL → A0/A1/A2、联合评价与图表 | 顺序执行 `input → filter → comment → stat` |

完成上面的样本准备后，在项目根目录依次执行。每一步将 `<..._ID>` 替换为相应命令打印的实际目录名：

```powershell
# 生成 A0/A1
.\.venv\Scripts\python.exe .\run.py input --all
$inputResults = "artifacts/runs/<RUN_ID>/results.jsonl"

# 从同一批 A0 派生 A2
.\.venv\Scripts\python.exe .\run.py filter --input $inputResults --all
$filterResults = "artifacts/filters/<FILTER_RUN_ID>/results.jsonl"

# 一起评价三个条件
.\.venv\Scripts\python.exe .\run.py comment --input $inputResults $filterResults --all
$commentSummary = "artifacts/comments/<COMMENT_RUN_ID>/summary.json"

# 统计绘图
.\.venv\Scripts\python.exe .\run.py stat --input $commentSummary
```

一条命令运行完整三组实验。先查看四阶段计划，再执行真实运行：

```powershell
.\.venv\Scripts\python.exe .\run.py pipeline --all --dry-run
.\.venv\Scripts\python.exe .\run.py pipeline --all
```

`pipeline` 将同一次生成的 A0 交给过滤阶段，再联合评价 A0/A1/A2，最后使用该次 `summary.json` 统计绘图。`--input` 指向准备好的提示 JSONL；`--all` 选择其中的全部案例。`--context` 同时传给 filter 和 comment，`--labels` 用于 comment；默认均使用 `data/pilot/` 中的对应文件。

各阶段产物沿用独立命令的目录，`artifacts/pipelines/<时间戳>/config.json` 记录计划预算和各阶段实际目录。`--output-dir` 可指定统计图表目录。运行中断后，可根据已保存的中间结果使用独立命令继续后续阶段。

`--dry-run` 保存任务请求预览与四阶段依赖、数量和预算计划，位于 `artifacts/previews/input/` 和 `artifacts/previews/pipeline/`。过滤与评分所需的实际动作在生成阶段产生，离线预览到此返回。

| 参数 | 适用命令与含义 |
| --- | --- |
| `--case-id` | input/filter/comment/pipeline：选择一个或多个案例 |
| `--all` | input/filter/comment/pipeline：选择全部案例 |
| `--limit` | input/filter/comment/pipeline：最多选择 N 个案例，保留其全部条件或对应 A0 |
| `--max-requests` | input/comment/pipeline：请求尝试上限，缺省按实际计划计算 |
| `--dry-run` | input/comment/pipeline：使用 .env.example 保存离线计划 |
| `--context` | filter/comment/pipeline：任务上下文 JSON 数组路径，默认 data/pilot/inputs.json；按 case_id 匹配 |
| `--labels` | comment/pipeline：评价标签 JSON 数组路径，默认 data/pilot/labels.json |
| `--output-dir` | pipeline/stat：统计数据和图表的输出目录，默认 artifacts/stats/ 下的新时间戳目录 |

案例选择缺省为第一个案例。标准配对输入中，每个案例各运行一次时，N 个案例的 `input` 需要 2N 次请求，三组共同 `comment` 需要 6N 次，`pipeline` 合计 8N 次。整体预算在生成前核对，过滤与统计为本地操作；条件数量不均或存在重复观测时按实际选定记录计算。请求尝试一次，故障记录后停止；无效生成按状态保留，评价额度按有效输出计算。

生成、过滤和评分分别显示进度条，包含已完成数量、耗时、速率和剩余时间估计，并显示当前案例、条件或评分类型及状态。逐条结果和错误保存在各阶段 JSONL 中；统计结束后打印图表目录。

## A2 本地 PII 过滤

当前版本为 `presidio_gliner_v6`：GLiNER 识别人名、机构、地点、时间等语义实体，Presidio 保留邮箱、电话、信用卡、IBAN 与美国社保号规则，并接入航班号、车次号和预订号，共十三类实体。spaCy 提供词性和词形，辅助现有筛选。长文本按完整编码输入的 token 预算分块，保留重叠区和原文坐标。

Faker 英文伪名与编号以源 A0 动作为作用域，跨字段共享映射。明确别名复用同一身份；机构尽量保留类型，地点和时间使用概括，编号保留字符格式。模型阈值与全局阈值均为 0.4，姓名格式规则分为 0.7；模型分数和人工规则分分别记录。

`context_labels_v1` 使用同一个 GLiNER 模型进行第二次多标签识别：正项标签识别名人、名胜、旅行目的地、求职公司与公开活动；反项标签识别私人姓名、住宅、医疗／家庭事实及私人预约。称呼与落款按位置保留，私人住宅及敏感片段使用明确占位概括，其余未豁免实体使用一致替换。正项阈值为 0.6，住宅为 0.6，私人预约为 0.65，其余反项为 0.4。每个片段的标签证据与保留／替换决定进入审计。标签是模型预测，实际泄露与误删仍需独立评价。

处理帖子正文、邮件主题/正文和消息正文，保留原收件人及工具参数。每条 A0 对应一条 A2，过滤配置、来源关系、前后文本、实体簇与映射表保存在 `artifacts/filters/<run_id>/`。PII 检出与情境隐私泄露分别通过命中记录和独立评价衡量；伪名及泛化造成的任务信息变化同时计入 helpfulness 评价。

## 离线统计与图表

对本版 `comment` 产出的 `summary.json` 执行：

```powershell
.\.venv\Scripts\python.exe .\run.py stat --input "artifacts/comments/<COMMENT_RUN_ID>/summary.json"
```

支持多个 `--input` 路径和 `--output-dir`。默认写入 `artifacts/stats/<时间戳>/`，包含 `config.json` 来源配置、`statistics.json` 统计数据和以下三张 PNG 图：

| 图片 | 内容与分母 |
| --- | --- |
| `privacy.png` | 仅展示敏感样本。依次为案例泄露率（泄露案例数 / 有效隐私评价的敏感案例数）、调整后泄露率（任务完成度 >=2 且隐私与任务评价均有效的敏感案例中的泄露比例）、事实项泄露率（泄露敏感事实项数 / 有效评价的敏感事实项数）。 |
| `helpfulness.png` | 分别展示敏感与非敏感样本。依次为任务完成度均分（0–3 分）、任务完成率（分数 >=2 的输出数 / 有效任务评分数）、拒绝率（拒绝输出数 / 有效生成输出数）。 |
| `coverage.png` | 分别展示敏感与非敏感样本。前三项为有效生成数、有效隐私评价数、有效任务评价数各自占选定输出数的比例；第四项为已有效评价的敏感事实项数 / 计划敏感事实项总数，用于查看生成失败、评价失败或缺失造成的覆盖缺口。 |

各图保留 A0/A1/A2 条件、生成提示版本、被测模型、过滤版本与样本组。统计按过滤版本分组；A0/A1 及旧产物缺失的过滤版本统一为 JSON `null`，图中显示 `filter=null`。比例标注同时显示分子和分母，均分标注有效评分数量；标签中的 `n` 是选定输出条数，同案例多次运行属于重复观测。多份输入以 S1、S2 等编号独立展示，来源路径和裁判配置见 `config.json`。

标签中的 `sensitive_info_items` 非空表示敏感样本，空清单表示非敏感样本。汇总同时统计泄露案例数、泄露事实项数、已评价事实项数与计划事实项总数；隐私泄露率使用敏感样本的有效评价作为分母，非敏感样本单独展示任务完成与拒绝指标。零分母记录为 `null`，图中显示 `N/A`。指标定义见 [评价协议](docs/evaluation.md)。

## 参数与产物

生成参数集中在 `experiment/common.py`：温度 0、非思考模式、非流式、JSON Object 输出；生成的单次输出上限为 1024 tokens，裁判为 2048 tokens，连接与读取超时分别为 10 与 60 秒。模型裁判接口通过离线模拟检查，实际模型可用性与评分质量需要服务试跑和人工校准。[结构化输出文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)说明了 JSON Object 的适用范围。

`input`、`comment` 和 `pipeline` 结束时在控制台按模型打印请求数、输入 token、输出 token 和总 token。优先使用响应返回的模型名称，缺失时使用请求模型名称；pipeline 汇总本次生成与裁判请求，同一模型的用量合并。中途失败时也打印已记录请求的用量；服务未返回用量时显示 `N/A`，部分请求有用量时标注已报告数量与请求总数。

- `artifacts/previews/input/`、`previews/comment/`：离线请求计划。
- `artifacts/previews/pipeline/`：完整流程的离线阶段与预算计划。
- `artifacts/pipelines/<时间戳>/`：完整流程计划及各阶段产物目录关联。
- `artifacts/runs/<run_id>/`：生成配置、原始响应和候选动作。
- `artifacts/filters/<run_id>/`：本地 A2 配置、来源配对、过滤动作和字段审计记录。
- `artifacts/comments/<run_id>/`：裁判配置、原始响应、逐项评分与 `summary.json`。
- `artifacts/stats/<时间戳>/`：JSON 统计数据、来源配置与三张 PNG 图。

## 来源与许可

- benchmark 与方法参考：[PrivacyLens，NeurIPS 2024](https://papers.nips.cc/paper_files/paper/2024/hash/a2a7e58309d5190082390ff10ff3b2b8-Abstract-Datasets_and_Benchmarks_Track.html)，数据来源见 [data/README.md](data/README.md)。
- 原创代码采用 [MIT License](LICENSE)；第三方内容遵循各自许可，提示与工具说明的来源见 [prompts/README.md](prompts/README.md)。
