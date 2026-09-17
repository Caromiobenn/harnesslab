# HarnessLab 实验协议（预注册草案）

状态：`draft-v0.2`。本文件用于在大规模运行前冻结研究问题、任务、预算、排除规则和分析方法。当前仓库有两个结构化任务和一个文件任务；首轮 27-run 自托管探索矩阵已完成，但尚未达到本协议的正式实验门槛。

## 1. 研究问题与对比

### 主问题 P1：显式 Planning 的增量效果

- Treatment：`H2 = langchain_baseline + TodoListMiddleware`。
- Control：`H0 = langchain_baseline`。
- 主要结果：外部确定性 validator 的任务成功率。
- 次要结果：硬约束满足率、false completion、模型/工具调用、Token、延迟和 cost per success。
- 主假设：Planning 在可分解长程任务上提高成功率，但在简单任务上增加无效协调成本。

这是第一项允许做单机制因果解释的对比。除 Todo middleware 及其最小必要提示外，模型、公开任务、领域工具、Runtime、预算与 validator 必须一致。

### 次问题 P2：Deep Agents 默认 bundle 的系统效果

- Treatment：`H1 = create_deep_agent()` 的锁版本默认 bundle。
- Control：`H0 = langchain_baseline`。
- 结果同 P1。
- 允许结论：默认 bundle 的整体可靠性—成本差异。
- 禁止结论：把全部差异单独归因于子 Agent、文件工具或上下文管理。

### 后续问题 P3：专业委派的增量效果

- Treatment：`H3 = 冻结的 coordinator + specialist profiles`。
- Matched control：相同 coordinator、模型、工具和提示，但不提供 specialist 委派能力的 shadow 配置；同时与通用委派基底比较。
- 主假设：专业委派只在任务可自然分解、交接信息较小的类别中获益。

H3 在 matched control 实现和合同测试完成前不进入正式矩阵。

### 后续问题 P4：有界 Verified Execution 的增量效果

- Treatment：冻结 producer + 独立 rubric grader + 确定性 Evidence Tool + 最多一次修订。
- Control：相同 producer 直接提交。
- 主结果：false completion rate 和任务成功率。
- 代价：grader/revision 的全部 Token、调用和延迟。

Rubric grader 不是 ground truth；最终 verdict 仍由外部 validator 给出。

## 2. 实验单位

配对键定义为：

```text
pair_key =
  task_revision
  × model_revision
  × environment_fixture_digest
  × budget_policy
  × repeat
  × seed
  × fault_assignment
```

Harness variant 是 treatment，不进入 pair key。同一 pair key 下的 Harness 必须读取相同 public task、使用相同 private evaluation、从相同 fixture 创建独立环境，并获得同一总预算。

统计独立单位优先使用 `task_family`，其次使用逻辑任务，而不是把同一任务的多次 repeat 当成独立样本。

## 3. 目标任务集

第一版正式任务集目标为 15 个逻辑任务，覆盖六类能力：

| 类别 | 任务 | 核心不变量 |
|---|---|---|
| Structured | contacts normalization | 规范化、去重、稳定排序、schema |
| Structured | invoice reconciliation | Decimal 计算、逐行舍入、状态关系 |
| File | sales rollup | 输入不可修改、跨文件聚合、来源完整 |
| File | config layering | precedence、未知字段、确定性输出 |
| File | policy index | 引用覆盖、去重、来源映射 |
| Tool | procurement optimization | 硬预算、库存、供应商约束 |
| Tool | paginated ledger join | 游标完成、去重、跨源一致性 |
| Tool | refund idempotency | 恰好一次副作用、状态核验 |
| Long horizon | employee onboarding | 阶段依赖、权限、全部检查项 |
| Long horizon | incident recovery | 诊断、恢复、回滚和证据 |
| Travel | feasible day plan | 营业时间、交通时间、无重叠 |
| Travel | disruption replan | 保留约束、只修改受影响部分 |
| Travel | accessible group trip | 无障碍、成员偏好、预算与时间 |
| Code | CSV parser repair | hidden tests、兼容性、禁止范围 |
| Code | retry client repair | backoff、幂等、错误分类、测试 |

每个任务必须包含：

- 带 revision 的 public definition；
- 独立文件中的 private evaluation；
- 至少一个 reference submission；
- 一个已知错误 submission；
- validator mutation tests；
- 明确的执行预算和 workspace policy；
- 一名非任务作者的审阅记录。

正式 clean suite 为 15 个 cases。故障实验增加约 12 个 task×fault 组合；另加入至少 2 个 metamorphic variants，总计目标约 29 个 cases/Harness。报告按逻辑任务或任务族做 macro 汇总，不能把 fault variants 当成大量独立任务抬高样本量。

## 4. 故障矩阵

第一版优先实现以下确定性 fault primitives：

1. `retryable_timeout_once`；
2. `rate_limit_once`；
3. `empty_page_with_next_cursor`；
4. `duplicate_page`；
5. `schema_v2_envelope`；
6. `timeout_after_commit`；
7. `stale_read_once`；
8. `write_version_conflict`；
9. `authority_conflict`；
10. `prompt_injection_record`；
11. `action_conflict`；
12. `test_infrastructure_error`。

每个 fault 必须记录 assignment、activation、Agent detection、recovery action 和最终 external verdict。`test_infrastructure_error` 用于验证 evaluator-invalid 分类，不作为 Agent 鲁棒性失败。

## 5. 模型与运行环境

正式矩阵至少包含：

- 一个能力较强的 API 模型，作为当前系统上界；
- 一个低成本 API 模型，用于经济性比较；
- 一个研究服务器可部署的开源 instruct/tool-calling 模型，用于自托管实验。

具体 model id、revision、量化、context length 和 provider 日期必须在运行前填写并冻结。不得只记录滚动别名。

本地低显存 GPU 只用于 endpoint 与 tool-calling smoke，不进入主要质量结论。研究服务器环境必须记录：

- GPU 与驱动；
- 容器或 OS 镜像；
- CUDA、PyTorch、vLLM 版本；
- served model revision 与量化格式；
- tensor parallel、KV cache、最大上下文、并发和显存利用率；
- 服务启动参数及镜像 digest。

Provider 凭据仅通过环境变量传入，不写入 config、manifest、Trace 或 Git。

## 6. Harness treatment contract

每个 Harness 在运行前生成机器可读 contract：

```yaml
treatment_id: h2-planning-v1
base_treatment: h0-minimal-v1
framework: langchain
intended_delta:
  - TodoListMiddleware
required_capabilities:
  - write_todos
forbidden_capabilities:
  - task
  - rubric_revision
budget_policy: equal-total-v1
```

合同检查分三层：

- assignment：配置声明的 treatment；
- exposure：实际 system prompt hash、middleware、绑定工具和权限；
- uptake：运行中真实发生的 Todo、委派、Evidence 查询和修订。

主要分析按 assignment 进行。不能只保留发生 uptake 的 runs，否则会引入 treatment 后选择偏差。

## 7. 预算策略

主分析使用 `equal-total-v1`：

- actor model calls：按任务公开 limits 固定；
- domain tool calls：按任务固定；
- 总输入/输出 Token 上限：模型条件内固定；
- wall clock：按任务固定；
- provider retry：固定；
- 并发：同一批次固定；
- H4 grader/revision：计入统一总预算。

另做 `production-policy-v1` 敏感性分析：允许各 Harness 使用预先定义的生产预算，但全部成本计入。两种策略的结果不可混在同一列。

当前 v0.2 runner 已强制 actor call limit、provider request timeout 和 Unix main-thread wall deadline；domain tool budget、总 Token hard limit和跨进程强制终止仍需在正式实验前实现。

## 8. 重复、顺序与批次

- temperature 0 条件：每个 RunCell 至少 3 次，用于捕捉 provider 非确定性和 Runtime 波动；
- 非零 temperature：至少 5 次；
- Harness 顺序在每个 task/model/repeat block 内用预先记录的 seed 随机化；
- 不能让 H0 总是先跑或让某个 treatment 总是命中热缓存；
- 共享 API 限流时采用串行或隔离配额，并记录等待时间；
- 自托管批次记录服务重启点和 warm-up runs；warm-up 不进入指标。

若预算不足，优先减少 exploratory model 条件，不降低主对比的任务覆盖和配对完整性。

## 9. Outcomes

### 9.1 主指标

- `task_success`：所有 hard validators 通过；
- `category_macro_success`：先在逻辑任务内汇总，再对类别等权；
- `hard_constraint_satisfaction`；
- `false_completion_rate`。

### 9.2 鲁棒性指标

- `fault_activation_rate`；
- `fault_detection_rate`；
- `recovery_success_rate`；
- `robust_retention = success_fault / success_clean`；
- `fault_induced_failure`：clean 成功但 matched fault 失败；
- duplicate side effects、conflict resolution accuracy、retry appropriateness。

### 9.3 经济指标

- actor/grader model calls；
- domain/harness tool calls；
- input/output tokens；
- end-to-end latency；
- estimated API cost；
- `cost_per_success = all_run_cost / successful_runs`；
- 首次充分证据之后的冗余步骤。

无成功运行时 cost per success 记为不可定义/无穷，不记为 0。

## 10. Run 状态与排除规则

预定义状态：

- `completed_pass`；
- `completed_fail`；
- `execution_error`；
- `budget_exhausted`；
- `evaluator_invalid`；
- `infrastructure_invalid`。

排除只允许：

- validator 自身异常或 oracle 矛盾，并有 reference/mutation test 证据；
- 实验基础设施在 Agent 启动前失败；
- 配置 hash 与预注册条件不符；
- provider 官方确认的大范围事故，且规则对所有 treatment 对称应用。

模型输出错误、tool-call 解析错误、任务内超时、限流策略失败、预算耗尽和 Harness 崩溃均属于被测策略结果，不能事后删除。所有排除保留原 artifact、原因代码和决定者。

## 11. 统计分析

主对比 H2−H0：

1. 在每个逻辑任务内对 repeats 求平均；
2. 计算任务级配对差；
3. 在 task family 层进行 cluster bootstrap，报告 95% 区间；
4. 同时报告绝对成功率、绝对差、相对成本和配对翻转；
5. 单次完整二元配对可补充 McNemar 检验，但不以 p 值替代 effect size。

预先定义分层：

- simple vs long-horizon；
- structured/file/code/tool/travel；
- clean vs fault；
- naturally decomposable vs shared-context-heavy。

样本量不足的层只报告描述性结果和区间，不给确定性因果结论。所有事后发现的分层标为 exploratory。

Pareto 分析绘制：

- success vs tokens；
- success vs latency；
- recovery vs calls；
- false completion vs cost。

被另一配置在可靠性不低、所有主要成本不高的条件下严格支配的配置，标为 empirical dominated，但限定在本任务和模型范围内。

## 12. Judge 元评测

LLM judge 在 deterministic validator 覆盖不了的软质量层使用，不参与硬约束 ground truth。抽取的人工审计样本应覆盖：

- 每个 Harness 与模型；
- pass/fail；
- 每个主要 task category；
- fault/no-fault；
- prompt-injection cases；
- 边界分数与 judge disagreement。

至少两位标注者独立标注首批样本，冻结 rubric 后再扩展。报告：

- Accuracy、Precision、Recall；
- False Accept Rate、False Reject Rate；
- Cohen's kappa；
- 多次评分稳定性；
- judge 模型间一致性；
- 单次评分成本和延迟；
- 注入前后性能差。

Judge 不得读取 Harness label、private reference prose 或另一个 Judge 的结论，除非该条件本身是被研究的 treatment。

## 13. 结果发布门槛

一项数字进入 README、简历或技术报告主摘要前，必须同时满足：

- 任务/validator reference 与 mutation tests 全部通过；
- treatment exposure 合同检查通过；
- artifact 包含 config、lockfile、task/evaluation 和环境 hash；
- 主要 pair 完整，排除规则已应用并公布；
- 汇总脚本可从原始 `runs.jsonl` 重建表格；
- 结果包含不确定性或明确说明样本量限制；
- scripted/mock runs 没有混入真实模型结果；
- 一名独立审阅者核对至少一批典型 artifacts；
- 简历文字只陈述数据直接支持的范围。

在此之前，只能报告工程事实，例如“实现了公私分离 benchmark 协议和三种 framework adapters”，不能报告“Planning 提升 X%”。

## 14. 当前 readiness

| 条目 | 状态 | 证据/缺口 |
|---|---|---|
| API-free runner 与 artifact | ready | v0.1 smoke + tests |
| Baseline/Planning/Deep default 合同 | ready | scripted real graph tests |
| Public/private task schema | ready | v0.2 catalog |
| Independent validators | partial | 2 structured + 1 file case，仍缺任务族广度 |
| OpenAI-compatible adapter | ready | 已完成 27-run Qwen2.5-14B-AWQ server artifact |
| Model calls/request/wall timeout | partial | 已有；还缺跨进程 kill 与 token hard cap |
| 10–15 clean tasks | not ready | 当前 3 |
| Isolated workspace/domain tools | partial | 1 个 file case 已端到端运行 |
| Fault injector and activation ledger | not ready | schema 仅预留 fault rules |
| Specialist treatment | not ready | 需 matched control |
| Verified treatment | not ready | 需独立 producer/grader/evidence |
| Batch statistics/Pareto | partial | 已有 raw-run 汇总；缺 bootstrap/Pareto 与足够样本 |
| Judge meta-evaluation | not ready | 等轨迹与人工标注 |

这个表必须随实现更新。`ready` 表示已有自动测试和可运行证据，不表示研究问题已经得出结论。

## 15. 正式运行前检查表

1. 冻结本协议 revision 和 Git commit；
2. 验证所有 reference、反例和 mutation tests；
3. 生成 treatment contracts 并检查 exposure；
4. 记录模型、provider、自托管环境和 pricing snapshot；
5. 生成随机化 schedule 与 pair keys；
6. 先跑不计入结果的 endpoint/warm-up smoke；
7. 执行小规模 pilot，只允许修基础设施，不看 treatment 排名后改主指标；
8. 冻结正式 config 后批量运行；
9. 从 artifacts 重建汇总，并审计 invalid/exclusion；
10. 完成人工 failure/judge 标注；
11. 生成表格、区间、Pareto 图与典型案例；
12. 最后才撰写结论和带数字的简历表述。
