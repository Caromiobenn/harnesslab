# Harness 消融与因果归因

消融实验不是“把几种 Agent 配置各跑一次，然后比较柱状图”。它要回答的是一个反事实问题：**对于同一个任务、模型、环境和预算，如果只改变某个 Harness 机制，结果会怎样变化？**

阅读完本文，应当能够解释：

- treatment、对照和 treatment fidelity 分别是什么；
- 为什么 HarnessLab 的五类配置不是一条天然可作因果归因的阶梯；
- 怎样用配对运行控制任务难度和环境差异；
- 哪些常见变化会构成混杂；
- 如何从运行证据判断“配置了机制”和“实际使用了机制”；
- 当前离线实验为什么只能证明合同，而不能证明 planning 有效。

## 1. 从“配置比较”到“因果问题”

设任务为 (t)，Harness treatment 为 (h)。同一个任务在两种 treatment 下有两个潜在结果：

\[
Y_t(h_1),\quad Y_t(h_0)
\]

单任务的 treatment effect 是：

\[
\tau_t = Y_t(h_1)-Y_t(h_0)
\]

但一次真实运行只能观察其中一个潜在结果。我们通过让同一个任务在两个条件下分别运行、固定其他因素，并在任务集合上汇总配对差值，近似回答这个反事实问题。

在 HarnessLab 中，结果不只有成功与否。不同 (Y) 会形成不同结论：

- (Y^{success})：外部 validator 是否通过；
- (Y^{cost})：总 Token 或估算费用；
- (Y^{latency})：端到端延迟；
- (Y^{false\ completion})：是否出现虚假完成；
- (Y^{recovery})：故障触发后是否恢复成功。

所以“Planning 有效”不是一个完整结论。更准确的形式是：

> 在固定模型、任务版本、工具、预算和故障条件下，显式 planning 相对 minimal baseline 对长程任务成功率的平均配对差为多少，同时增加了多少调用、Token 和延迟。

## 2. 什么是 Treatment Fidelity

Treatment fidelity 表示：实验标签、实际实现和运行时暴露是否一致。

如果一项实验标记为 `single_agent`，但框架默认注入了通用子 Agent，那么标签与实际 treatment 不一致。即使代码无报错、结果可复现，因果解释仍然错误。

应把 fidelity 分成三层。

### 2.1 Assignment：配置声称分配了什么

manifest 中应有机器可读的 treatment contract，例如：

```yaml
treatment:
  id: h2-explicit-planning-v1
  base: h0-minimal-v1
  intended_delta:
    - TodoListMiddleware
  required_tools:
    - sum_numbers
    - write_todos
  forbidden_tools:
    - task
  max_revision_rounds: 0
```

这描述实验者的意图，但仍不能证明框架照此构建。

### 2.2 Exposure：Agent 实际能接触什么

启动后要捕获：

- 最终 system prompt 的 hash 和受控 diff；
- 绑定的工具名、schema 与权限；
- middleware 的有序清单及版本；
- backend、文件系统和网络能力；
- 子 Agent profile、模型和可见上下文；
- grader、Evidence Tool 和修订上限；
- 模型、采样参数、上下文窗口与预算。

例如 HarnessLab 当前在 `harness_configured` 事件和 diagnostics 中记录 framework、planning、bound tools 和 todos。这是 fidelity 证据的起点。更成熟的实现还需把 middleware 和工具 schema 规范化后写入 manifest，并对禁止能力做合同测试。

### 2.3 Uptake：Agent 是否实际使用机制

配置 Todo 工具不代表 Agent 调用了它；提供子 Agent 不代表发生了委派；配置 validator 不代表触发了修订。因此 Trace 还要记录实际 uptake：

- Todo 创建、更新和完成次数；
- `task` 调用、目标 specialist、交接内容和返回采用情况；
- Evidence Tool 查询与 revision round；
- 上下文压缩或文件卸载实际触发次数。

这里有一个重要统计陷阱：主要效果应优先按**分配的 treatment** 统计，也就是类似 intention-to-treat 的分析。只保留“确实用了 planning”的样本，会把模型是否愿意规划这一选择带来的偏差混入结果。

Uptake 更适合解释机制：

```text
分配了 Planning 但没有调用 Todo
  -> 不是把该 run 从 Planning 组删除
  -> 而是记录为 treatment assigned、uptake absent
```

## 3. HarnessLab 五类配置的严格边界

这五类配置既包含单机制消融，也包含一个现实工程 bundle。必须先承认这一点，才能避免过度归因。

| ID | 报告名称 | 唯一允许新增的核心能力 | 必须固定或禁用 | 可以回答的问题 |
|---|---|---|---|---|
| H0 | Minimal baseline | LangChain `create_agent` + 领域工具 | 无 Todo、无子 Agent、无文件管理增强、无 grader/revision | 最小工具 Agent 的基线表现 |
| H1 | Deep Agents default | 锁定版本的 `create_deep_agent()` 默认 bundle | 不再显式添加 planning、specialist 或项目自定义 verifier | 默认工程 bundle 相对 H0 的整体效果 |
| H2 | Explicit planning | H0 + `TodoListMiddleware` | 模型、领域工具、prompt 主体、backend、预算策略与 H0 一致 | 显式 Todo 机制的增量效果 |
| H3 | Specialist subagents | 在冻结的 Deep Agents 基底上，把通用委派条件替换或扩展为预注册 specialist profiles | 无 rubric revision；每个 specialist 的模型、工具和上下文边界固定 | 专业化委派相对匹配委派基底的效果 |
| H4 | Verified execution | 冻结的 producer + 独立 rubric、确定性 Evidence Tool、固定最大修订轮数 | producer 本身不变；禁止无限查询和无限修订 | 有界运行时验收的增量效果 |

### 3.1 H0：真正的最小基线

H0 的价值是提供可解释起点。它只包含完成任务必须的领域工具。例如 `sum_numbers` 只绑定 `sum_numbers`，不应因为框架方便而额外暴露 `task`、文件编辑或 Todo 工具。

“单 Agent”描述的是实际拓扑，不是类名。使用名为 Deep Agent 的构造器并不能自动得到单 Agent。

### 3.2 H1：默认 Deep Agents 是 bundle anchor

在本项目锁定的 Deep Agents 0.7.x 边界下，默认构造会带来通用子 Agent 等多项机制。它适合作为“开箱即用工程方案”与 H0 比较，但：

\[
H1-H0 = \text{framework + prompt + tools + context management + delegation + ...}
\]

所以不能把 H1 与 H0 的差异单独称为“子 Agent 效果”或“上下文压缩效果”。它测量的是 bundle effect。

### 3.3 H2：目前最干净的单因素对比

H2 应严格定义为 H0 只增加 Todo middleware。系统提示可能需要加入最小使用说明，但其 diff 必须被记录；领域工具、输入、模型和 backend 不应顺便变化。

当前 `offline-baseline.yaml` 与 `offline-planning.yaml` 已采用这个结构：都走 LangChain adapter，planning 条件仅额外加入 `TodoListMiddleware`。不过 scripted model 被预先写成必定调用 `write_todos`，所以它只验证中间件合同，不估计真实模型在 Planning treatment 下的行为效果。

### 3.4 H3：专业子 Agent 的比较基底

H3 不能简单与 H0 相减后宣称“委派的效果”，因为二者还可能相差框架、提示、内置文件工具和上下文策略。

要回答不同问题，需要不同对照：

- **默认 bundle vs minimal**：比较 H1 与 H0，结论只到 bundle；
- **专业化 vs 通用委派**：比较 H3 与 H1，前提是 H3 只改变 subagent profiles；
- **有委派 vs 无委派**：建立一个 H3-shadow，在相同 coordinator 栈中禁用 `task` 能力，其他工具与提示保持匹配。

内部 shadow control 不一定成为 README 的第六个产品配置，但应存在于因果实验矩阵中。

还要记录 specialist 的输入边界。若它直接读取完整主 Agent 上下文，而对照只能看到精简任务，结果同时受到额外信息量影响。

### 3.5 H4：Verified 不是“换了一个更强 Agent”

H4 的 producer 必须显式冻结，例如：

```text
H4[producer=H0, grader=G1, evidence=E1, max_revision=1]
```

其匹配对照就是同一个 H0 producer，不经过 grader/revision。若 H4 同时换更强模型、增加搜索工具并放宽预算，就无法归因于验收闭环。

H4 还应把三种子条件分开：

1. self-check；
2. independent rubric grader；
3. grader + deterministic Evidence Tool + bounded revision。

这几项可以作为 H4 内部实验，而不是把它们混成一个无法解释的标签。

## 4. 什么必须保持不变

为了把差异归因给目标 treatment，以下变量原则上应在一个配对对比中冻结。

### 4.1 模型条件

- provider 与 model revision；
- temperature、top-p、reasoning effort 等采样参数；
- 最大输出 Token；
- tool calling 模式；
- 同一时段可能发生的 provider 模型漂移。

模型名相同不一定代表 revision 相同。若 provider 只提供滚动别名，应记录运行日期和响应 metadata，并把跨日期结果视为潜在批次效应。

### 4.2 任务与环境

- public task revision；
- private oracle 和 validator version；
- 输入 fixture 与 workspace image digest；
- 可用领域工具及其 schema；
- 网络与凭据权限；
- 故障注入 schedule；
- 冷/热缓存状态。

机制导致的下游状态变化是 mediator，不应被“修正掉”。例如 planning 使对话更长，这是 treatment 的一部分；但两组一开始就有不同上下文窗口，则是混杂。

### 4.3 停止与预算策略

至少冻结：

- 最大模型调用数；
- 最大工具调用数；
- 最大输入/输出 Token；
- 墙钟超时；
- 重试与 backoff；
- H4 最大修订轮数；
- 子 Agent 并发上限。

预算公平没有唯一答案，应报告两种视角：

1. **等资源比较**：所有 treatment 共用总预算，回答单位资源下谁更可靠；
2. **策略比较**：每种配置使用预先定义的生产策略，回答整个方案上线时的可靠性—成本权衡。

不能在看完失败后临时只给某一组增加步骤数。若 Verified 的额外修订是其设计组成，应在策略比较中计入其全部成本；在等资源比较中，则必须从统一总预算中消耗。

## 5. 配对实验怎样运行

### 5.1 RunCell 的配对键

建议用以下字段唯一标识可配对单元：

```text
pair_key =
  task_revision
  × model_revision
  × environment_fixture
  × budget_policy
  × repeat
  × seed
  × fault_assignment
```

同一 `pair_key` 下依次产生 H0、H1……的结果。Harness 是被比较维度，不进入 pair key。

### 5.2 随机化运行顺序

始终按 H0→H1→H2 的顺序执行会让配置和时间混杂：API 负载、限流、网络、模型滚动更新以及机器温度都可能随时间变化。

可以在每个任务块内用固定随机种子打乱 Harness 顺序，或采用平衡 Latin square。并行运行能缩短时间差，但如果共享 CPU、速率限制或服务状态，也会产生相互干扰；并行资源必须隔离。

### 5.3 重复不能冒充独立任务

同一个任务重复 20 次提供的是该任务上的随机性信息，不等于新增 20 个独立任务。统计汇总时：

- 先在 `task_id` 内汇总 repeats；
- 再在任务层做 bootstrap 或置信区间；
- 保留类别分层，例如 file/code/tool/long-horizon；
- 不把 30 个任务 × 5 次重复当成 150 个完全独立样本。

若任务共享同一模板，只替换了数字，也可能形成 task family 聚类。更稳妥的 bootstrap 单元是独立任务族。

### 5.4 随机 seed 的真实含义

seed 只有在模型/provider 和工具真正消费它时才有效。HarnessLab 当前 manifest 明确记录：scripted offline model 是确定性的，`requested_seed` 存在，但 `effective=False`。

对不保证确定性的 API，即使传相同 seed，也不能假设两次输出逐 Token 对齐。配对仍能控制任务条件，但需要多次重复并报告不确定性。

## 6. 常见混杂以及怎样识别

| 混杂来源 | 典型错误 | 改进方式 |
|---|---|---|
| Prompt | Planning 组获得更多领域提示 | 只加入机制必要说明，保存 prompt diff |
| 工具 | Subagent 组顺便多了搜索工具 | 对齐领域工具；机制工具单独列出 |
| 模型 | Grader 组 producer 也换成更强模型 | 冻结 producer，单独记录 grader 模型 |
| 预算 | Verified 组可无限修订 | 预注册统一总预算或明确策略预算 |
| Runtime | 一组可访问宿主 Shell，另一组在沙箱 | 对齐 backend 和权限 |
| 顺序 | baseline 总是先跑、后续命中缓存 | 随机或平衡顺序，隔离缓存 |
| 任务 | 不同配置分配到不同难度任务 | 同任务配对；无法配对时随机分层分配 |
| Validator | 每组使用不同判分器 | 所有组使用同一外部 oracle/validator |
| 重试 | 工具异常只在某组自动重试 | 固定 retry policy，Trace 中记录每次尝试 |
| 版本 | 依赖升级改变默认 middleware | 锁版本、记录源 commit、做能力合同测试 |

一个实用判断问题是：

> 如果结果变好，除了目标机制之外，还有没有另一项同时变化且足以解释改善？

若答案是“有”，该实验仍可作为系统配置比较，但不应写成单机制因果结论。

## 7. 分析 Treatment Effect

### 7.1 成功率使用任务内配对差

对每个任务，先计算两组在 repeats 上的平均成功率，再求差：

\[
d_t = \bar{Y}_{t,H2} - \bar{Y}_{t,H0}
\]

总体平均效果为：

\[
\widehat{ATE} = \frac{1}{|T|}\sum_{t \in T} d_t
\]

同时报告任务级 bootstrap 置信区间。单次、二元且完整配对的数据也可以用 McNemar 检验，但 p 值不能替代 effect size 和区间。

不要只报告两组独立 success rate 而丢掉配对信息。相同任务上的 0→1 与 1→0 翻转，往往比总平均更能说明机制在哪些任务上帮助或伤害。

### 7.2 成本也要配对

对成功率提升伴随的成本，至少报告：

\[
\Delta C = \bar{C}_{treatment} - \bar{C}_{control}
\]

以及：

\[
\text{Cost per Success}
=
\frac{\text{全部运行总成本}}{\text{成功运行数}}
\]

“每提升 1 个百分点成功率的增量成本”可以用于同一任务分布上的配置比较，但当成功率没有提升或区间跨零时，不应给出误导性的正数结论。

### 7.3 分层效果比一个总数更有价值

Planning 很可能对三步长程任务有益，却在一次工具调用任务上只增加开销。预先定义分层：

- 简单 vs 长程；
- 可自然分解 vs 强共享上下文；
- 文件、代码、结构化输出、工具操作；
- 正常工具 vs 故障注入；
- 短上下文 vs 长上下文。

分层应在看结果前定义，并保留每层任务数与区间。事后挑出几项获益任务，只能作为探索性案例，不能冒充预注册主结论。

## 8. 故障注入中的特殊因果问题

假设 fault schedule 指定“第一次调用支付工具返回超时”。某个 Harness 可能根本没调用支付工具，因此故障没有激活。

应同时报告：

- fault assignment：该 run 被分配到什么扰动；
- fault activation：触发条件是否实际发生；
- detection：Agent 是否观察或识别异常；
- recovery：最终外部 validator 是否通过。

主分析可以按 assignment 进行，回答整个策略面对故障环境的效果；条件性恢复分析只在已激活且有恢复机会的 runs 中计算，并明确这不是随机子集，可能受 treatment 自身行为影响。

不能悄悄丢弃“因为 Agent 走了另一条路径而未触发”的样本。避开脆弱工具本身可能就是一种有效策略。

## 9. HarnessLab 当前实验的正确解读

当前三条 framework 配置提供了宝贵但有限的证据：

```text
offline-baseline     -> create_agent + sum_numbers
offline-planning     -> 上述条件 + TodoListMiddleware
offline-deepagents   -> create_deep_agent 默认 bundle + sum_numbers
```

scripted model 在 planning 组被明确编排为：

```text
write_todos(in_progress)
-> sum_numbers
-> write_todos(completed)
-> final output
```

因此若三组都通过 exact match，可以得出的结论是：

- adapters 能构造对应 framework graph；
- Todo middleware 的工具调用和状态更新合同能跑通；
- Deep Agents 默认 tool loop 能完成该固定脚本；
- trace、validator 和 artifact 路径连通。

不能得出的结论是：

- Planning 提高了成功率；
- Deep Agents 默认比 minimal Agent 更可靠；
- 子 Agent 对求和任务有帮助；
- 多出的模型调用在真实 API 上值得其成本。

行为实验必须让真实模型根据同一 public task 自主决定是否规划、调用什么工具以及何时停止。

## 10. 一份实验前登记模板

在运行昂贵实验前，可以冻结以下内容：

```yaml
question: "Explicit Todo planning 是否提高长程文件任务成功率？"
contrast: "H2 - H0"
primary_outcome: "external_validator_pass"
secondary_outcomes:
  - total_tokens
  - duration_ms
  - cost_per_success
unit_of_analysis: "task_family"
task_revisions: "suite-v1 manifest hash"
models: ["provider/model@revision"]
budget_policy: "equal-total-v1"
repeats: 5
order: "blocked randomized, seed=..."
exclusions:
  - "evaluator_invalid only"
fidelity_checks:
  - "H0 forbids write_todos/task"
  - "H2 requires write_todos schema hash ..."
analysis:
  - "task-family paired mean difference"
  - "cluster bootstrap 95% CI"
```

预登记不是为了形式感，而是防止看到结果后更换主指标、排除不利任务或改变 treatment 定义。

## 11. 面试中怎样讲清楚

可以这样回答：

> 我先为每个 Harness 写 treatment contract，区分配置分配、实际能力暴露和运行时 uptake。五类配置中，minimal baseline 与显式 planning 是干净的单因素对比；Deep Agents default 是现实 bundle，只能报告整体效果；specialist 和 verified 都需要各自的 matched shadow control。实验按任务 revision、模型 revision、环境、预算、seed 和 fault assignment 配对，在任务块内随机化配置顺序，并以任务族为统计单位做配对差和 cluster bootstrap。这样可以避免把默认中间件、额外工具、预算或运行顺序误当成目标机制效果。

如果继续追问“为什么不只看成功率”，应补充：Harness 的收益必须与调用、Token、延迟、false completion 和故障恢复一起报告；否则提高可靠性的机制可能在简单任务上不经济。

## 12. 自测问题

1. 为什么 H1 Deep Agents default 与 H0 的差不能直接称为“子 Agent 效果”？
2. 配置里出现 `write_todos` 和 Trace 中实际调用它，分别属于 fidelity 的哪一层？
3. 为什么只分析 Planning 组中“真的写了 Todo”的运行会产生偏差？
4. H2 的 prompt 多了一页领域知识，而 H0 没有。即使其他代码相同，是否仍是 planning 单因素消融？
5. 同一任务重复 20 次为何不等于 20 个独立任务？
6. Verified 配置多一次 grader 调用，等预算比较和策略比较应怎样处理？
7. 若 provider 不保证 seed 确定性，配对设计是否失去价值？
8. 某个 fault 被分配但因 Agent 避开该工具而未激活，应不应该删除该 run？
9. 当前 scripted Planning 组成功，为什么不构成 Planning 有效的证据？
10. H3 specialist 比 H1 default 更好时，最准确的 treatment 解释是什么？

### 答案要点

1. H1 同时改变框架默认提示、工具、上下文管理和通用委派等多项机制，只能归因为 bundle。
2. 前者是 exposure，实际调用是 uptake；配置文件本身最初属于 assignment。
3. 是否采用 planning 是模型行为，会与任务难度和模型把握相关；条件筛选破坏原分配对比。
4. 不是。额外领域知识本身足以解释改善；prompt diff 应限制为启用机制所必需的部分。
5. 它们共享任务内容和难度，只估计同一任务上的随机波动；独立分析单位仍接近一个任务或任务族。
6. 等预算时 grader 从共同总预算中消耗；策略比较可给预定义额外预算，但全部成本必须计入。
7. 不会。配对仍控制任务、环境和批次差异，只是需要 repeats 和不确定性区间，不能期待逐 Token 对齐。
8. 不应。主分析按 fault assignment 保留；另报 activation 和条件性恢复，避免 treatment-induced selection。
9. 调用序列由 fixture 预先合成，测到的是 middleware 合同，而不是模型自主规划的因果效果。
10. 在其他默认能力冻结时，是“专业化 profiles 相对通用委派”的效果；不是笼统的“有子 Agent 相对无子 Agent”。
