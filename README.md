# PrivacyLens 隐私防护小型实验

基于 [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) 数据，使用 Qwen 比较基础提示、隐私增强提示和 PII 过滤对情境隐私泄露与任务完成的影响。项目属于 [Pattern Recognition 课程 Assignment 1 的 T02-B](https://github.com/tulip-lab/pattern-classification-lab/blob/develop/Assignments/frontier-ai-presentation/topics.md)，采用独立轻量实现。

实验条件为 A0 基础提示、A1 隐私增强提示与 A2 对对应 A0 输出进行 PII 过滤。当前入口连接任务输入、模型生成与自动评价；评价结果通过人工抽查校准。

## 目录

```text
run.py                     统一命令入口
experiment/
  prepare_data.py          准备生成输入与评价标签
  build_prompts.py         构造 A0/A1 请求
  run_input.py             调用模型生成最终动作
  run_comment.py           独立评价隐私与任务完成度
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
```

按照 `.env.example` 配置本机 `.env`：

```dotenv
DASHSCOPE_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=your_qwen_base_url
BASE_MODEL=qwen3.5-flash
REF_MODEL=qwen3.5-flash
```

生成与隐私裁判使用 `BASE_MODEL`；helpfulness 裁判使用 `REF_MODEL`。默认复用 Flash。裁判选择与人工校准方法见 [评价协议](docs/evaluation.md)。

## 准备样本与提示

所有命令在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe .\run.py prepare --limit 5
.\.venv\Scripts\python.exe .\run.py prompts
```

准备阶段默认读取 `data/main_data.json` 的前 5 条，将模型可见字段写入 `data/pilot/inputs.json`，评价数据写入 `labels.json`，选择信息写入 `manifest.json`。可用 `--source`、`--output-dir` 和 `--limit` 指定数据来源、产物目录与开发案例数量。

提示阶段默认读取 `data/pilot/inputs.json`，生成 `artifacts/prompts/pilot_v2.jsonl`；支持 `--input` 与 `--output` 指定路径。A0 为 `a0_v1`，A1 为 `a1_v2`，两者共用同一份案例正文，A1 追加情境隐私要求。模板说明见 [prompts/README.md](prompts/README.md)。

## 运行两个阶段

先离线查看两个案例的生成请求计划：

```powershell
.\.venv\Scripts\python.exe .\run.py input --all --limit 2 --max-requests 4 --dry-run
```

已有生成结果可单独评价。将下面的 `<RUN_ID>` 替换为相应运行目录名：

```powershell
.\.venv\Scripts\python.exe .\run.py comment --input "artifacts/runs/<RUN_ID>/results.jsonl" --all --max-requests 4 --dry-run
```

`comment` 的 `--input` 接受一个或多个结果文件；`--context` 和 `--labels` 分别指定对应任务上下文与评价标签，默认使用 `data/pilot/` 下的文件。

也可以通过统一入口串联生成和评价：

```powershell
.\.venv\Scripts\python.exe .\run.py pipeline --all --limit 1 --max-requests 6 --dry-run
```

`--dry-run` 使用 `.env.example` 保存离线请求计划。`pipeline` 的离线模式保存生成计划并核对整个流程的请求额度，实际评判消息由生成结果决定。移除 `--dry-run` 后，入口读取本机模型配置并真实调用 API。

| 参数 | 含义 |
| --- | --- |
| `--input` | 生成阶段读取请求 JSONL，评价阶段读取结果 JSONL |
| `--case-id` | 选择一个或多个案例 |
| `--all` | 选择输入文件中的全部案例 |
| `--limit` | 最多选择多少个案例，保留同案例的全部条件 |
| `--max-requests` | 本阶段或整个 pipeline 的请求尝试上限 |

默认选择输入中的第一个案例。A0/A1 配对下，每案例生成需要 2 次请求，隐私与 helpfulness 评价共需 4 次，完整 pipeline 共需 6 次。额度在调用前核对；每条请求尝试一次，故障记录后停止后续调用。

## 参数与产物

生成参数集中在 `experiment/common.py`：温度 0、非思考模式、非流式、JSON Object 输出；生成的单次输出上限为 1024 tokens，裁判为 2048 tokens，连接与读取超时分别为 10 与 60 秒。模型裁判接口通过离线模拟检查，实际模型可用性与评分质量需要服务试跑和人工校准。[结构化输出文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)说明了 JSON Object 的适用范围。

- `artifacts/previews/input/`、`previews/comment/`：离线请求计划。
- `artifacts/runs/<run_id>/`：生成配置、原始响应和候选动作。
- `artifacts/comments/<run_id>/`：裁判配置、原始响应、逐项评分与 `summary.json`。

## 来源与许可

- benchmark 与方法参考：[PrivacyLens，NeurIPS 2024](https://papers.nips.cc/paper_files/paper/2024/hash/a2a7e58309d5190082390ff10ff3b2b8-Abstract-Datasets_and_Benchmarks_Track.html)，数据来源见 [data/README.md](data/README.md)。
- 原创代码采用 [MIT License](LICENSE)；第三方内容遵循各自许可，提示与工具说明的来源见 [prompts/README.md](prompts/README.md)。
