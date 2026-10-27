# Qwen3.5 Rubric 专项实验协议

本轮使用新模型重跑所有实验组。旧 Qwen2.5-14B-AWQ 的 27 次运行作为历史探索记录，
不与本轮成功率直接相减，也不把模型、显卡和服务版本的变化归因于 RubricMiddleware。

## 冻结条件

- 模型：Qwen/Qwen3.5-9B，原始 BF16 权重，单张 RTX 5090 32GB，仅加载语言模型。
- 权重 revision：`c202236235762e1c871ad0ccb60c8ee5ba337b9a`。
- 官方 Hugging Face 文件清单给出分片 SHA-256；下载镜像不作为版本标识，最终以哈希为准。
- 推理环境：vLLM 0.32.0，独立环境；完整依赖和实际 CUDA/GPU 信息保存到服务器 runtime/。
- 项目环境：uv.lock 冻结的 Deep Agents 0.7.14 与其他依赖。
- 运行时评分策略：public-contract-v2。开发 v1 发现模型会照抄 schema，且 grader 将
  候选缺陷误报为 failed；v2 对所有 actor 统一澄清 schema 的用途，对 grader 澄清
  needs_revision/failed 的语义。旧开发记录保留，修正前未启动留出集。
- 全组使用同一系统提示、公开任务、输入、隐藏验收、模型、采样参数和预算上限。
- temperature 0.7，关闭 thinking，max_completion_tokens 2048，禁用隐式 HTTP 重试。
- 每次运行最多 12 次 actor 调用、24 次 actor+grader 总调用、60 次实际工具调用、240 秒。
- grader 每次评审子调用最多 12 次模型调用；总回调预算仍跨子调用生效。

预算匹配指相同上限，不表示实际消耗相同。报告实际 token、调用、延迟、每个成功所需 token，
同时保留原版组作为低成本参照，不能把多花算力的改善全部解释为反馈质量提升。

## 四个实验组

| 组别 | 运行时行为 |
|---|---|
| default | Deep Agents 默认 bundle，首次自然结束后提交 |
| generic_retry | 最多三轮固定复核，反馈只有通用复核指令，最后候选提交 |
| rubric_transcript | RubricMiddleware 根据对话评分，最多三轮，无取证工具 |
| rubric_evidence | RubricMiddleware、只读取证工具、当前证据要求与放行门，最多三轮 |

evidence 组相对 transcript 组增加的是“证据工具、取证要求及放行门”这一整套策略，
不将两组差异归因为某一个工具或某一个提示词。全组保留 Deep Agents 默认子智能体等能力；
因此本实验研究默认 bundle 上的反馈策略，而非证明单一 agent 结构的优势。

## 任务与数据划分

`scripts/build_rubric_suite.py` 使用固定种子生成 24 个输入实例：

- 开发集：每个任务族 2 个实例，共 6 个；用于兼容性和运行故障排查。
- 留出集：每个任务族 6 个实例，共 18 个；每实例、每组 3 个配对种子，共 216 次运行。
- 任务族：联系人归并、发票折扣/舍入/付款状态、多文件销售汇总。
- 包含多条重复记录、空值、不同小数/折扣/税率、无/部分/全额/超额付款，
  多输入文件、大小写敏感状态、无 paid 订单和负金额等变化。

参考答案由生成器独立构造，再由现有隐藏确定性 validator 交叉验收。
开发和留出使用不同生成种子及输入；留出的是实例，三个任务族的规则已经公开。
这些是三个任务族的多个实例，不宣称新增了 24 类独立任务或满足广泛 benchmark 的任务覆盖。

先完成开发集检查、固定代码和协议，再启动留出集。留出开始后不根据结果调整
rubric、模型、提示词或预算；必要修复应保留旧结果并使用新协议/输出目录重跑。
运行器按 task/seed 成块随机化组别顺序，保存完整调度和代码/任务/锁文件哈希。
失败也是结果，不为提高通过率悄悄重跑。中断恢复跳过已写入 progress.jsonl 的作业。

## 运行与验收边界

HarnessRequest 只有公开任务和本次隔离 workspace。评分工具不能看到 BenchmarkCase、
私有 reference_submission、最终 validator、其他作业的 workspace 或项目宿主目录。
证据工具只读：检查当前候选的公共 schema、排序/唯一性、输出内部算术一致性、输入完整性，
以及读取公开文件。它不会直接计算业务标准答案，内部一致不代表业务正确。

每次自然结束先保存候选输出和文件，再评分；证据记录以 candidate_id 关联候选。
runtime_accepted 要求 satisfied、完整的指定标准覆盖；evidence 组还要求当前候选的
取证记录 ok=true。评审缺失、异常、预算耗尽或覆盖不足都不放行。

最终 success 始终由独立隐藏 validator 决定。运行结束后，在独立临时 workspace 中回放
保存的候选，事后验收首轮及中间产物；这些分数从不返回执行或评分循环。
文件快照还保留输入哈希，以免回放时恢复原输入而掩盖输入被修改的问题。

## 指标与统计

主指标为每组最终隐藏验收通过率。辅助指标包括：

- 首轮失败中最终修复的数量，以及首轮正确但最终退化的数量；
- 各任务族通过率、执行错误、grader_error、预算耗尽与其他终止状态；
- 原始 grader satisfied 的误判，以及放行门最终误放行；
- actor/grader 分角色调用和 token，总 token、延迟、每个成功的 token；
- 运行时放行且隐藏验收通过的数量，区分“产物有效”和“系统实际放行”。

比较相同实例和种子，先对同实例的重复结果求均值，再在任务族内按实例重采样，
使用 5,000 次 bootstrap 给出成功率差的 95% 区间。区间条件于当前三个任务族，
不把重复采样当作独立任务，也不推断未见任务族。小样本和同模型评分的相关偏差需保留。
服务器自托管没有 API 账单单价，报告 token 和 GPU 运行时间，不把未配置的美元价格当作免费。

主要比较为 rubric_evidence 对 generic_retry；其次比较证据策略与仅对话评分。
即使成功率没有提高，也保留成本、误判和失败机制分析，不只挑成功案例。

另在开发集构造 30 个冻结产物，包括正确、schema 错误、语义错误、误导性完成声明和缺失产物，
由真实评分模型分别在有/无证据策略下评审，共 60 次 judge-only 检查。
候选由脚本固定，不执行真实 actor 推理；标签由外部确定性验收独立生成。
它用于观察评分器误判，不算作 Agent 能力提升样本，也不称作人工标注验收集。

## 复现入口

```bash
.venv/bin/python -m harnesslab verify-benchmark benchmarks/rubric-v1/dev.yaml
.venv/bin/python -m harnesslab verify-benchmark benchmarks/rubric-v1/holdout.yaml
.venv/bin/python scripts/run_rubric_matrix.py --split dev --repeats 1 --output artifacts/rubric-dev
.venv/bin/python scripts/analyze_rubric_matrix.py artifacts/rubric-dev
.venv/bin/python scripts/run_rubric_matrix.py --split holdout --repeats 3 --output artifacts/rubric-holdout
.venv/bin/python scripts/analyze_rubric_matrix.py artifacts/rubric-holdout
```

推理服务只监听 127.0.0.1。服务脚本、工具调用/结构化输出检查分别位于
`scripts/server/serve-qwen35-9b.sh` 和 `scripts/server/smoke_qwen35.py`。
报告、分析 JSON、调度与源码哈希、逐次 runs/events、候选与证据均保存到实验目录。
