# 统一实验统计

`stat` 读取一次或多次 `comment` 的 `summary.json`，从相邻的 `config.json` 和 `results.jsonl` 追踪该批次实际选定的生成、过滤与评价记录。每份输入作为独立批次 S1、S2 展示。`pipeline` 自动把本次评价交给同一个统计入口。

```powershell
.\.venv\Scripts\python.exe run.py stat --input artifacts/comments/<COMMENT_ID>/summary.json
```

`--output-dir` 指定输出目录。每份 summary 需与其配置和逐条评价记录一起保存，配置引用的生成及过滤记录需可读。新评价在运行目录保存 `labels.json` 快照；历史评价使用配置中的标签路径。统计复算汇总并核对保存的 summary，来源或标签发生冲突时直接报错。

## 输出

- `report.md`：方法对比、指标范围、类别结果、覆盖、配置和本批开销。
- `report.json`：完整统计、评价标签快照、来源和成本计数。
- `comparison.csv`：每个批次、方法、生成版本、模型和过滤版本一行。
- `categories.csv`：启用类别分析且有敏感案例时生成的逐类别结果。
- `statistics.json`、`config.json`：绘图数据与输入来源。
- `privacy.png`、`helpfulness.png`、`coverage.png`：隐私、效用与有效覆盖。

## 类别是评价数据

`prepare --categories <JSON路径>` 接收以 case_id 为键、类别名称为值的映射，必须覆盖本次所有案例。显式类别写入评价标签的 `privacy_category`，并记录来源。未传参数或传空值时，这两个字段为 null。

未设置类别时，统计省略“按隐私类别比较”一节和 categories.csv，原始 seed.data_type 仅作为来源信息保留。历史标签自动复制的 seed.data_type 类别也不用于分组。

最终测试之后可以独立补充分类文件，重新统计已有结果：

```powershell
.\.venv\Scripts\python.exe -X utf8 run.py stat --input artifacts/comments/<COMMENT_ID>/summary.json --categories data/final_test/categories.json
```

`stat --categories` 优先采用给定映射；未传时采用评价标签快照中的显式类别；传空值 `--categories=` 强制关闭。分类文件必须覆盖所选批次的全部案例。分类结果和映射快照写入新报告，原评价标签和模型判断保持独立。重用输出目录并关闭类别分析时会清理旧 categories.csv。

分类文件可在正式测试之后补充，应保留类别定义与标注来源，并如实说明事后归类。此过程为离线汇总，无需重新生成或评价。

可准备源数据末尾的案例：

```powershell
.\.venv\Scripts\python.exe run.py prepare --tail --limit 100 --purpose test-candidate --output-dir data/test_candidate
```

manifest 保存来源摘要、顺序选择规则、案例 ID、用途和类别来源。`test-candidate` 表示候选集合；是否为有效 held-out 集还取决于与开发集的同源场景家族隔离。类别标注、必需允许事实等评价字段由标签文件管理，生成提示仍使用独立 inputs.json。

## 指标与缺失

案例泄露率、事实泄露率、任务完成率和显式拒绝率沿用评价协议，各自保留有效分母。非敏感案例单独计算正常任务完成率；没有此类案例时显示 N/A。

保护行为 recall = 未披露的敏感事实数 / 已获得有效评价的敏感事实数，即 1 − 事实泄露率。其单位是事实项，含重复输出中的重复观测，不表示裁判对真实泄露的检出能力。

privacy precision 需要必需且允许分享事实的逐项评价，false refusal 需要拒绝合理性判断。当前统计将两项记为 null，并显示“未评价”。显式 REFUSE 只计拒绝率。历史人工或模型复核作为独立分析材料保存。

统计按实际标签和裁判结果输出。裁判有效覆盖与标签正确性是不同问题；模型裁判的结果应按自动评价解释。版本和样本不同的批次分别展示，避免把开发重跑视为独立测试案例。

## 时间与用量

- A0/A1：各自生成请求的 token 和客户端耗时。
- A2：对应 A0 的生成用量与耗时，加本地过滤耗时。平均处理时间按输出计，token 均值按有用量记录的请求计。
- 本批实验实际开销：源 A0 真实请求只计一次；生成、隐私裁判与任务裁判分别列示。
- 仅统计这份评价实际选择的来源；部分选择不会把同文件其他案例计入。
- 每个批次内按运行、时间、案例、条件、请求种类和尝试去重。不同批次可能重用请求，各批开销不能直接相加。
- 缺失用量保持 null；部分缺失时列出已报告数。缓存 token 是输入用量的子集。金额尚未核算。
- 时间包括请求网络等待和逐动作过滤；模型加载、下载、裁判、绘图及其他阶段不属于该处理时间。

