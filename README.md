# PrivacyLens 隐私防护小型实验

基于 [PrivacyLens](https://github.com/SALT-NLP/PrivacyLens) benchmark，使用单一 LLM，比较不同防护方式对情境隐私泄露与任务完成的影响。本仓库是独立的[Pattern Recognition 课程实验项目](https://github.com/tulip-lab/pattern-classification-lab/blob/develop/Assignments/frontier-ai-presentation/topics.md)，主题选取为 T02-B Privacy attacks in the LLM and agentic-AI era，参考官方数据与实现，不依赖官方完整运行环境。

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

## 来源与许可

- benchmark 与方法参考：[Shao et al., PrivacyLens, NeurIPS 2024](https://papers.nips.cc/paper_files/paper/2024/hash/a2a7e58309d5190082390ff10ff3b2b8-Abstract-Datasets_and_Benchmarks_Track.html)。使用数据时记录来源、版本与实验划分。
- 本仓库原创代码采用 [MIT License](LICENSE)；第三方代码、数据与其他引用内容遵循其各自许可证。
