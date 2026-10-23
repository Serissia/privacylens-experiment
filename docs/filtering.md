# 英文 GLiNER 过滤

## 模型与运行

`run.py setup-filter` 下载 `urchade/gliner_medium-v2.1` 的固定修订版及配套 DeBERTa 配置、tokenizer，并生成可直接加载的 fast tokenizer。转换使用英文相对路径读取 SentencePiece 词表，模型配置使用 ASCII 转义，以支持 Windows 中文项目目录。权重、tokenizer、模型卡和来源记录位于 `models/gliner_medium-v2.1/`，编码器资料位于其中的 `encoder/`。`source.json` 记录两者的仓库与修订版本。

在项目根目录安装 README 中的依赖、spaCy 模型及 GLiNER 后执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 .\run.py filter --input "artifacts/runs/<RUN_ID>/results.jsonl" --all
```

`filter` 从本地读取模型和对应 A0，生成 `presidio_gliner_v6` A2。

GLiNER 模型参数保存在 `gliner_config.json`，DeBERTa 编码器配置保存在 `encoder/config.json`。

## 识别职责与标签

Presidio 注册 `GLiNERRecognizer` 的项目子类，结合邮箱、电话、信用卡、IBAN、美国社保号多类识别器和称谓、问候语姓名规则。spaCy 的词性和词形供候选筛选及 Presidio 上下文增强使用。

| GLiNER 标签 | Presidio 类型 |
| --- | --- |
| person | PERSON |
| organization | ORGANIZATION |
| location | LOCATION |
| date、time | DATE_TIME |
| nationality、religious group、political group | NRP |
| flight number | FLIGHT_NUMBER |
| train number | TRAIN_NUMBER |
| booking reference、reservation number | BOOKING_REFERENCE |

模型与全局阈值均为 0.4；模型候选保存实际模型分数。姓名格式规则分为 0.7，唯一别名传播分为 0.95，两者为规则排序分。候选筛选结合词性，机构候选中的全小写普通名词与明显的句式、主题片段分别处理。零样本标签的实际识别效果需要独立样本检验。

## 长文本与坐标

GLiNER 的词单元上限与编码器的 subword 上限属于两层限制。项目复用模型实际 words splitter，以完整词边界切分，再用同一 tokenizer 测量包含标签前缀和特殊 token 的完整编码输入。完整输入预算取 384、模型 `max_len` 和 tokenizer 上限的最小值，分块保留 32 个词单元的重叠。单个词及标签前缀超出预算时明确报错。

Presidio 合并重叠区候选，将坐标加上分块起点，按同类型重叠和最高分去重。每个外发字段的 `gliner_chunks` 保存分块原文范围、词数和完整输入 token 数；所有坐标均为原字段 Python 字符索引 `[start, end)`。

## 替换与审计

`consistent_surrogates_v3` 使用英文 Faker，一条 A0 内跨字段共享身份与编号映射。航班号、车次号、预订号与结构化号码有独立的格式保持分支；同类型编号忽略分隔符和大小写归并，替换时恢复各次出现的分隔符和字母大小写。不同实体簇使用各自可复现的替换值。

候选、筛选丢弃项、冲突处理后的实际操作、前后文本、实体簇和映射均写入过滤产物。新编号类型沿用相同审计结构；模型将 `Flight`、`booking reference` 等引导词并入编号时，保留引导词，只替换编号，候选的 `model_span` 记录裁剪前的模型片段和坐标。过滤器处理外发内容字段，实际路由由工具参数表示。

## 正反标签与操作决策

`context_policy.py` 的 `context_labels_v1` 复用已加载的 GLiNER，增加独立的上下文标签识别，使用 `flat_ner=false`、`multi_label=true` 保留同一片段的不同预测。

| 作用 | 标签 | 阈值 |
| --- | --- | --- |
| 保留候选 | message recipient name、message sender name、public figure、celebrity、famous landmark、travel destination、job application company、public event、public event date、public event time | 0.6 |
| 私人姓名替换 | private person | 0.4 |
| 住宅概括 | home address、private residence | 0.6 |
| 敏感片段概括 | medical condition、private family problem | 0.4 |
| 私人预约泛化 | private appointment date | 0.65 |

保留标签须覆盖整个对应类型的候选。私人住宅和敏感片段优先使用 `[private location]`、`[private information]` 概括；重叠的普通实体由该操作覆盖。邮箱、电话、账号与旅行编号执行替换。人名在开头称呼和结束语后的落款位置保留；模型预测的发送者／收件人标签同时保存在审计中。私人预约日期约束同一分句内的日期与时刻；其后依次考虑公开／任务标签以及默认替换。同一个名字的其他出现位置分别决策。

任务明确提及且被正项标签确认的目标机构或地点，允许在同一字段内保留相同名称的重复提及；该依据按片段记录，住宅与敏感事实保护优先。公开活动标签允许同一分句内的日期列表和时刻保留，私人预约证据仍优先。

上下文从 `filter --context` 指定的任务输入中选取 `user_name` 与 `user_instruction`，加上动作中的工具和收件人。各字段分别最多保留 8、40、8 个词（工具名按原值）；实际使用的上下文保存为字段级 `context_analysis.context`。过滤上下文只使用这些允许字段。

每个正文块前重复最小任务上下文，标签和上下文都计入 384 token 完整预算。模型预测的上下文部分被排除，正文位置恢复到原字段坐标。`context_analysis.signals/chunks` 保存标签、模型或规则来源、分块和坐标；`policy_decisions` 按 candidate_id 保存 KEEP、REPLACE、GENERALIZE 或 COVERED 及 signal_ids。最终实际操作继续记录在 `replacements`，其中直接概括的 cluster_id 为 null。

## 来源

- [模型卡](https://huggingface.co/urchade/gliner_medium-v2.1)：英文模型、许可与使用方法。
- [GLiNER 0.2.22](https://github.com/urchade/GLiNER/tree/v0.2.22)：模型加载与实际输入处理。
- [Presidio GLiNERRecognizer](https://github.com/microsoft/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/ner/gliner_recognizer.py)：识别器、分块接口与原文坐标转换。
