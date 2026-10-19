# PrivacyLens 隐私防护小型实验

基于 [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) benchmark&dataset，使用单一 LLM，比较不同防护方式对情境隐私泄露与任务完成的影响。本仓库是独立的[Pattern Recognition 课程实验项目](https://github.com/tulip-lab/pattern-classification-lab/blob/develop/Assignments/frontier-ai-presentation/topics.md)，主题选取为 T02-B Privacy attacks in the LLM and agentic-AI era，参考官方数据与实现，不依赖官方完整运行环境。

## 实验设计

- **A0：无附加防护**——使用基础任务提示生成最终动作。
- **A1：隐私提示**——使用同一模型，加入隐私增强提示。
- **A2：PII 过滤**——对对应的 A0 输出进行个人身份信息过滤。

采用人工标注评价泄露、任务完成和误拒绝，并记录运行配置、耗时和 token 用量。仅使用公开 benchmark 或完全合成的数据，所有对外动作均在本地模拟。

## 环境配置

建议使用 Windows PowerShell、Python 3.10 或 3.11，以及独立虚拟环境。模型通过 API 调用，无需下载权重或配置本地 GPU 推理。

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 开发样本准备

使用已有虚拟环境，在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe .\prepare_data.py
```

脚本按自身位置定位 `data/main_data.json`，取前 5 条并保留原始顺序，将官方 `name` 映射为 `case_id`。这些样本用于开发流程检查，不是正式 held-out 测试集。

`data/pilot/inputs.json` 保存模型可见的任务字段与原始工具轨迹，`final_action` 表示官方指定的目标动作类型；`labels.json` 保存供人工评价的 `seed`、`vignette` 和 `sensitive_info_items`；`manifest.json` 记录源路径、选取方式、数量、案例 ID 和用途。输入字段提取参考官方 `evaluation/get_final_action.py`，工具轨迹中的敏感上下文原样保留，评价标签单独存放。

数据来源见 [data/README.md](data/README.md)。

## 离线提示构造

准备好开发样本后，在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe .\build_prompts.py
```

脚本读取 `data/pilot/inputs.json` 和 `prompts/` 下的模板、工具说明，为每个案例生成配对的 A0/A1 请求，保存至 `artifacts/prompt_preview.jsonl`。当前 5 个案例对应 10 条预览，每条包含案例 ID、条件、提示版本、消息正文字符总数和完整 `messages`。

A0 使用公共系统提示；A1 在相同系统提示后追加情境隐私要求，两组共用同一份案例正文。模型任务是依据已有轨迹提出最后一步动作及参数。输出协议为 `action` 与 `action_input` 两个字段，拒绝通过 `REFUSE` 动作和 `reason` 参数表示。

模板说明、版本约定及第三方来源见 [prompts/README.md](prompts/README.md)。开发过程与验证结果见 [LOG.md](LOG.md)。

## 来源与许可

- benchmark 与方法参考：[Shao et al., PrivacyLens, NeurIPS 2024](https://papers.nips.cc/paper_files/paper/2024/hash/a2a7e58309d5190082390ff10ff3b2b8-Abstract-Datasets_and_Benchmarks_Track.html)。使用数据时记录来源、版本与实验划分。
- 本仓库原创代码采用 [MIT License](LICENSE)；第三方代码、数据与其他引用内容遵循其各自许可证。
