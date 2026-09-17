# 从 Agent Demo 到 Harness Evaluation

本文讨论 HarnessLab 真正想评测的对象：不是“模型能不能说出一个看起来合理的答案”，而是**一个模型在特定 Harness、Runtime、工具环境和预算约束下，能否可靠地完成任务**。

阅读完本文，应当能够解释：

- Framework、Runtime、Harness 分别解决什么问题；
- 为什么 Agent 停止运行或声称完成，不等于任务成功；
- HarnessLab 的实验对象、证据链和边界是什么；
- 为什么离线 mock 测试通过，还不能推出真实 Agent 有效。

## 1. 三个容易混用的概念

### 1.1 Framework：构建系统的通用积木

Framework 提供复用抽象和编程接口，例如状态图、消息、工具、middleware、checkpoint 和事件流。LangGraph、LangChain Agents 都属于这一层。

Framework 回答的是：

> 我可以用哪些抽象来组装一个 Agent 系统？

它类似 Web 开发中的应用框架。框架支持路由，并不代表某个应用的路由设计正确；同样，框架支持子 Agent，也不代表子 Agent 一定提高成功率。

### 1.2 Runtime：一次运行如何真正发生

Runtime 是代码执行时的环境和语义，包括：

- 状态如何读取、合并和持久化；
- 模型调用和工具调用如何调度；
- 文件位于内存、宿主机还是沙箱；
- 超时、重试、并发和中断如何处理；
- 一次调用失败后，哪些状态已经产生副作用；
- Trace 事件何时发出、能否在崩溃后保留。

Runtime 回答的是：

> 这套 Agent 逻辑在什么环境中、按什么执行规则运行？

同一段 Agent 代码放在无限权限宿主 Shell 和受限临时工作区中，测到的不是同一个系统。Runtime 因而也是实验条件的一部分，而不是无关的部署细节。

### 1.3 Harness：围绕模型塑造行为的控制层

Harness 是包在模型周围、直接影响其行为的一组机制。典型组成包括：

- 系统提示和输出契约；
- 可见工具及权限；
- planning/Todo middleware；
- 文件系统卸载与上下文压缩；
- 子 Agent 委派和上下文隔离；
- Rubric、Evidence Tool 和有界修订；
- 模型调用、工具调用、Token 和时间预算。

Harness 回答的是：

> 在不重新训练模型的情况下，我们怎样组织模型的工作，并约束、观察和验证它？

HarnessLab 中的 `single`、`planning`、`subagent`、`verified` 等配置，都是不同 Harness treatment。它们不是四个不同的基础模型。

### 1.4 三者不是三个互斥的软件包

一个具体组件可能跨越边界。例如 middleware 是 Framework 提供的扩展点；某个 Todo middleware 是 Harness 机制；middleware 在状态中合并 Todo 的方式又属于 Runtime 语义。因此，分类的目的不是给每个类贴唯一标签，而是弄清实验中**改变了什么**。

| 概念 | 主要问题 | HarnessLab 示例 | 是否应当记录在实验清单中 |
|---|---|---|---|
| Framework | 用什么抽象构建 | LangChain `create_agent`、LangGraph 状态图 | 是，记录版本 |
| Runtime | 一次运行怎样执行 | backend、临时工作区、超时、事件持久化 | 是，记录配置与版本 |
| Harness | 怎样组织和约束模型 | planning、subagent、rubric、工具权限 | 是，这是主要 treatment |
| Model | 谁在做语言推理 | provider、model id、temperature | 是，这是能力条件 |
| Evaluator | 谁判定任务是否通过 | hidden tests、约束求解器、确定性 validator | 是，但不得进入 Agent 可见上下文 |

## 2. Harness Evaluation 到底在评测什么

一次运行结果可以写成：

\[
Y = f(M, H, T, E, B, R)
\]

其中：

- \(M\)：模型及其采样参数；
- \(H\)：Harness 配置；
- \(T\)：任务；
- \(E\)：工具、数据和工作区环境；
- \(B\)：调用次数、Token、时间等预算；
- \(R\)：随机性与故障注入条件。

因此，看到一个结果变好时，不能自动说“这个 Harness 有效”。只有当模型、任务、环境、预算等条件得到控制，并且主要变化确实是目标 Harness 机制时，结果才支持相应解释。

例如，比较以下两项并不能纯粹回答“子 Agent 是否有效”：

1. minimal Agent，只拥有两个领域工具；
2. Deep Agents 默认配置，同时多了文件工具、上下文压缩、通用子 Agent和不同提示。

这项比较仍有工程意义，但 treatment 是一个**组合包**。结论只能是“该 Deep Agents bundle 在这些任务上如何”，不能把差异单独归因给子 Agent。

HarnessLab 的评测单元应明确写成：

```text
RunCell =
  task_revision
  × model_revision
  × harness_variant
  × environment_fixture
  × budget
  × seed_or_repeat
  × fault_variant
```

同一个单元的输入、配置和输出证据必须能在 artifact 中定位，而不能只留下终端截图。

## 3. 为什么“完成”不等于“成功”

### 3.1 完成是控制流状态，成功是外部事实

Agent 完成通常只意味着以下某件事发生了：

- 模型返回了最终消息；
- 状态图到达结束节点；
- Agent 输出“任务已完成”；
- 达到最大步骤数后停止；
- 某个自检模型给出“通过”。

这些都描述系统如何停止，不能证明现实状态满足任务要求。任务成功必须由独立证据判定。

几个 HarnessLab 场景：

- 结构化输出：返回了一段 JSON，但字段类型或金额计算错误；
- 文件任务：报告文本看似完整，但输出文件没写到规定路径；
- 代码任务：Agent 说“已修复”，隐藏测试仍失败；
- 旅行任务：行程格式正确，但两段活动时间重叠，且预算超限；
- 有副作用的工具任务：退款接口超时后盲目重试，最终文本说成功，实际创建了两笔退款。

这些运行都可能正常结束，却不应记为成功。

### 3.2 声明状态与验证结果是两个轴

| Agent 是否声明完成 | 外部 Validator 是否通过 | 含义 |
|---|---|---|
| 是 | 是 | 经验证的成功 |
| 是 | 否 | **False completion**，最危险的误放行 |
| 否 | 是 | 结果可能已满足条件，但 Agent 状态判断或停止策略有问题 |
| 否 | 否 | 显式失败或未完成 |

False completion rate 可以定义为：

\[
\text{FCR} =
\frac{\#(\text{declared complete} \land \text{validator failed})}
{\#(\text{declared complete})}
\]

分母必须写清楚。有些报告把它除以全部运行数，那是另一个指标，不能混用。

### 3.3 自检也不是最终真值

让同一个 Agent 再读一遍答案，可能提高质量，但它仍可能重复原来的错误。独立 Rubric grader 也只是 Harness 内的一个判断组件，可能被模糊表述或提示注入误导。

因此 HarnessLab 需要两条分开的线：

```text
执行线：Public Task -> Harness -> Agent/Tools -> Submission + Side Effects
                                  |
                                  +-> Trace / Usage

评测线：Private Oracle + Hidden Evidence -> External Validator -> Verdict
```

Verified Agent 可以在执行线中使用公开 Evidence Tool 并修订，但最终 verdict 仍来自评测线。否则“Agent 自己认为通过”会被循环地当成成功定义。

## 4. 三层证据缺一不可

### 4.1 结果证据：任务是否真的完成

结果层包括：

- Task Success Rate；
- 硬约束满足率；
- hidden test pass rate；
- false completion rate；
- 故障条件下的恢复成功率。

这是主结论所在的层。没有结果证据，工具调用很漂亮也只是过程展示。

### 4.2 过程证据：系统为什么成功或失败

过程层包括：

- 调用了哪些工具，参数和返回类型是什么；
- 是否重复调用、遗漏分页或无效重试；
- Todo 是否真正更新，而不只是工具存在；
- 子 Agent 接到了什么任务，返回结果是否被主 Agent采用；
- 首次得到充分证据后是否仍产生冗余步骤；
- 失败发生在哪个阶段。

过程证据用于诊断机制，不应替代结果证据。例如“调用过 planning 工具”并不证明计划有用。

### 4.3 经济证据：可靠性提升是否值得

经济层包括 Token、调用次数、延迟和成本。一个 Harness 即使成功率更高，也可能在简单任务上增加不必要的协调成本。

常用指标为：

\[
\text{Cost per Success} =
\frac{\text{全部运行总成本}}{\text{成功运行数}}
\]

不要只计算“成功样本的平均成本”，因为失败消耗同样是部署成本。若没有成功运行，该指标应报告为不可定义或无穷，而不是零。

## 5. HarnessLab 的最小可信闭环

一个可用于结论的运行至少需要以下链条：

1. 读取带 revision 的公开任务和私有评测定义；
2. 为本次运行创建全新、隔离的工具状态与工作区；
3. 只把公开任务视图交给 Harness；
4. 在固定预算内执行并增量保存 Trace；
5. 保存最终输出和可审计副作用；
6. 由外部 Validator 读取私有 oracle 进行判定；
7. 记录模型、Harness、任务、环境和依赖的可复现清单；
8. 将结果、过程和经济指标共同汇总。

当前的 `smoke.sum-numbers` 与三条 scripted framework 路径只验证基础设施和框架合同：mock tool 返回 `{"sum": 42}`，external validator 判定通过，并生成事件与 summary。v0.2 又加入了公私分离结构化任务和 OpenAI-compatible 真实模型入口。它们能证明 schema、runner、存储、provider adapter 和 validator 串得起来；在真实模型矩阵尚未运行前，仍不能证明 planning 或 subagent 有效。

这种边界说明很重要：**合同测试证明实现没有明显断线；行为实验才评估 Agent 能力。**

## 6. 面试中怎样讲清楚

可以用下面这段结构化表述：

> Framework 是构建 Agent 的通用抽象，Runtime 规定一次运行的执行环境和状态语义，Harness 则是围绕模型的提示、工具、规划、委派、上下文管理和验收机制。HarnessLab 不把模型结束或自称完成当成成功，而是让 Agent 只看到公开任务，由外部确定性 validator 根据私有 oracle 检查输出和副作用。实验固定模型、任务、工具环境和预算，只改变目标 Harness treatment，同时记录成功率、过程 Trace 与成本，从而判断机制何时有效、何时只是增加开销。

如果面试官继续追问，应主动补充两个限制：

- Deep Agents 默认配置是多机制 bundle，不能把整体差异归因于一个组件；
- 任务集规模和模型选择限制结论的外推范围，重复运行不能替代更多独立任务。

## 7. 自测问题

1. LangGraph 提供了状态图，所以“使用 LangGraph”是否本身就是一个 Harness treatment？为什么？
2. 两个 Agent 使用同一模型，但一个可访问宿主 Shell，另一个只能访问临时工作区，这是否仍是公平比较？
3. 模型输出“所有测试通过”，为什么不能直接把 run 标为成功？
4. Rubric grader 给出满分后，为什么还需要外部 validator？
5. 一个子 Agent 配置成功率更高，但平均成本提高三倍，应怎样报告，而不是简单说它更好？
6. 离线 fake model 工具调用测试究竟证明了什么，又没有证明什么？
7. 为什么 Deep Agents 默认配置可以作为工程方案比较，却不一定能作为“子 Agent 单因素”实验？
8. False completion rate 的分母是什么？如果改成全部运行数，指标含义发生了什么变化？

### 答案要点

1. Framework 只是能力底座；只有具体启用、禁用或配置某种机制，并定义对照条件，才构成 treatment。
2. 不公平。Runtime 和权限面发生变化，结果同时受到工具能力与安全边界影响。
3. 那是未经验证的模型声明；需要读取真实输出、文件、测试或副作用状态。
4. grader 仍是被测 Harness 的一部分，会犯错；外部 validator 才定义实验 ground truth。
5. 同时报成功率、成本、延迟和 cost per success，并按任务复杂度分析 Pareto 权衡。
6. 它证明 API/tool loop 合同可运行；不证明模型有决策能力，也不产生真实效果结论。
7. 默认配置同时引入文件系统、压缩、patch 和通用子 Agent，存在多重混杂。
8. 标准定义以“声明完成”的运行作分母，衡量完成声明的可信度；除以全部运行则衡量全部运行中的假完成发生率。
