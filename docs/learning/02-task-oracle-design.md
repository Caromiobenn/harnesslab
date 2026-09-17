# 任务、Oracle 与不可见验收边界

Harness Evaluation 的可信度，首先取决于任务定义，而不是 Agent 框架。一个任务如果把答案泄露给 Agent、无法由外部证据判定，或者让不同运行共享残留状态，那么再精细的 Trace 和统计分析也只是在测量一个失真的对象。

阅读完本文，应当能够解释：

- 公开任务、私有 oracle、hidden evidence 和 validator 各自承担什么职责；
- 为什么 oracle 不等于一份标准答案，hidden test 也不等于 oracle 的全部；
- no-leak 边界应该覆盖哪些通道；
- 如何为每个 RunCell 创建隔离、可复现、可审计的工作区；
- HarnessLab 当前已经保证什么，还有哪些只是目标设计。

## 1. 先定义四种不同的东西

### 1.1 Public Task：Agent 被允许知道的问题

公开任务是 Agent 的输入契约，通常包括：

- 自然语言 instruction；
- 允许使用的输入数据；
- 输出路径、格式和公开约束；
- 可用工具的公开 schema；
- 必要时，少量用于说明格式的公开示例。

它应该包含完成任务所需的信息，但不应包含判分捷径。在 HarnessLab 中，`AgentTaskView` 是这层的显式数据模型：

```python
AgentTaskView(
    id="smoke.sum-numbers",
    category="tool_use",
    instruction="Add the supplied numbers.",
    input={"numbers": [19, 23]},
    tags=["smoke"],
)
```

`render_user_prompt()` 只序列化这几个公开字段。任务的 `expected` 和 `validators` 不在这个对象里。

公开任务不是越模糊越难、越好。若“输出一个报告”没有规定路径、格式和必须覆盖的字段，失败可能来自任务歧义，而不是 Agent 能力。好的公开任务让行为要求清楚，但把具体判分实例保留在评测侧。

### 1.2 Private Oracle：评测者对正确性的可执行定义

Oracle 回答的是：

> 在这个固定任务实例和环境中，什么外部事实足以支持“成功”？

它可能是一个值，也可能是一组关系或状态约束：

| 任务 | 私有 oracle 的可能形式 | 不充分的替代物 |
|---|---|---|
| 结构化输出 | JSON Schema、字段关系、允许误差 | “看起来像 JSON” |
| 文件处理 | 必需文件、内容约束、来源对应关系 | Agent 声称已写文件 |
| 代码修改 | hidden tests、静态规则、禁止改动范围 | 最终消息说测试通过 |
| 工具操作 | 最终服务状态、幂等键、审计记录 | 工具返回一条成功文本 |
| 行程规划 | 时间不重叠、预算上限、地理可达性 | LLM 主观打高分 |

因此，oracle 不必等于唯一的 golden answer。一个旅行计划可能有许多正确答案，此时 oracle 更适合表示“总价不超过预算、全部必选地点出现、交通时间可行”等关系约束。

Oracle 还必须说明容差和规范化规则。例如金额是精确到分还是允许汇率误差，字符串是否忽略 Unicode 规范化，集合是否关心顺序。若这些规则只存在于作者脑中，validator 就不可复现。

### 1.3 Hidden Evidence：Agent 不可见的判定材料

Hidden evidence 是 validator 用来计算 verdict、但 Agent 在运行时不能读取的材料，例如：

- 隐藏测试用例；
- 数据库预期终态；
- 受保护的参考文件或快照；
- 私有约束参数；
- 人工标注的允许答案集合；
- 故障注入器实际触发的 ground-truth 记录。

它和 oracle 的关系是：oracle 定义“正确是什么”，hidden evidence 提供“怎样观察并证明它”。例如代码任务的 oracle 是一组功能和安全不变量，hidden tests 是其中一种观测手段。

不能把“hidden”理解成靠保密制造难度。隐藏的目的，是避免 Agent 针对验收样例投机，并保持执行线和评测线独立。公开任务仍应完整描述用户真正要求的行为。

### 1.4 Validator：从证据到 Verdict 的程序

Validator 是评测函数：

\[
V(\text{submission},\ \text{side effects},\ \text{hidden evidence})
\rightarrow (\text{verdict},\ \text{score},\ \text{diagnostics})
\]

一个成熟的 validator 不只返回布尔值，还应返回：

- 每项 check 是否通过；
- 失败的机器可读代码；
- 支撑判定的证据摘要；
- validator 自身的版本；
- 无法判定时的 `invalid`，而不是武断地记为失败。

HarnessLab v0.1 的 `exact_match` 是最小实现。v0.2 已增加 JSON Schema、canonical JSON、联系人规范化和发票 Decimal 对账等独立 validator，并用 mutation tests 验证典型错误会被拒绝。这仍只覆盖结构化任务，不足以替代文件 diff、hidden tests 或服务终态检查。

## 2. 两条数据流必须分开

可信的运行有执行线和评测线：

```text
                         执行线
Public Task ──> Harness ──> Model / Tools ──> Submission + Side Effects
                    │                │
                    └──────── Trace / Usage

                         评测线
Private Oracle + Hidden Evidence + Snapshot ──> External Validator ──> Verdict
```

关键不变量是：**评测线可以读取执行线的产物，执行线不能反向读取私有评测材料。**

HarnessLab 当前通过投影实现最小边界：

```python
task = TaskDefinition(..., expected={"sum": 42}, validators=[...])
request = HarnessRequest(task=task.agent_view(), scripted_fixture=task.offline_fixture)
```

`HarnessRequest.task` 的静态类型是 `AgentTaskView`，正常代码路径拿不到 `expected`。manifest 保存公开定义与私有评测定义的 SHA-256；私有 check 详情只在 Agent 结束后的 evaluator artifact 中出现，不进入模型请求。

但要准确理解这个保证：runner 仍在同一 Python 进程中加载完整 `TaskDefinition`，随后再创建公开投影。这是良好的接口隔离和防误用设计，**不是对恶意代码的安全边界**。真实代码任务应进一步把 Agent Runtime 和 validator 放进不同进程或容器，并使用不同的文件挂载与凭据。

## 3. No-leak 不是“Prompt 里没有答案”

泄漏面远大于最终 user prompt。至少要检查以下通道。

### 3.1 直接数据泄漏

- `expected`、rubric 私有阈值或 hidden test 内容被序列化进消息；
- Harness 接收到完整任务对象，而不是最小公开视图；
- 调试日志或异常堆栈打印私有路径和答案；
- validator diagnostics 在修订前直接回传给 Agent。

### 3.2 文件系统泄漏

- hidden tests 与工作区一起挂载；
- `.git` 历史、patch、备份文件或编辑器缓存保留参考答案；
- 任务模板使用诸如 `solution_42.json` 的可猜文件名；
- 前一个 run 的正确输出留在共享目录；
- Agent 可以遍历宿主机或 artifact 目录。

### 3.3 工具与服务泄漏

- 搜索工具可以查询私有评测数据库；
- 错误消息包含预期值，例如“expected 42, got 41”；
- 测试工具把隐藏断言源码完整返回；
- 缓存键包含答案或任务标签；
- 共用账号让 Agent 能看到其他运行产生的对象。

### 3.4 间接和统计泄漏

- 给 Agent 无限次提交，并逐项返回 hidden check 的通过情况；
- 任务 ID、样例顺序或分支名与答案稳定相关；
- 同一 hidden set 长期公开排行榜，允许反复拟合；
- Verified Agent 的 Evidence Tool 实际成为逐字符 oracle。

运行时验收并不要求把最终 oracle 暴露给 Agent。Evidence Tool 可以返回可行动但有界的信息，例如“输出缺少两个必填字段”，而不是直接给出字段的期望内容；还应限制查询次数和修订轮数。

### 3.5 No-leak 的可验证合同

只在文档里写“不会泄漏”不够。应建立自动检查：

1. 对传给模型的所有消息和工具 observation 做捕获测试；
2. 为私有字段放置唯一 canary，断言消息、工作区和工具返回中均不存在；
3. 枚举 Agent 可见文件树，确认 hidden mount 不可见；
4. 检查模型可调用工具的权限清单；
5. 分别保存 public hash、private evaluation hash 和完整定义 hash；
6. 在 Trace 导出前进行密钥与隐私字段脱敏。

当前 `diagnostics["oracle_fields_visible"] = False` 只是一条实现侧声明。更强的证据是测试真实捕获到的 prompt 与工具输入，并用 canary 证明敏感值未出现。诊断字段可以辅助审计，不能自证安全。

## 4. Hidden Validation 怎样设计才公平

### 4.1 先写能力不变量，再写测试样例

如果先写几个 hidden examples，再把“通过这些 examples”当成能力定义，很容易得到脆弱 benchmark。更稳健的顺序是：

1. 写出用户真正关心的不变量；
2. 为每个不变量设计一个或多个观测方法；
3. 加入边界值、反例和等价输入；
4. 检查测试是否错误排除了其他合法解；
5. 由第二位审阅者独立验证任务和 oracle。

以文件报告任务为例：

```text
公开要求：读取 inbox/ 下的订单，生成 out/summary.json。

私有不变量：
  I1 只统计状态为 paid 的订单；
  I2 total 等于逐项金额之和；
  I3 order_ids 不重不漏；
  I4 不得修改 inbox/；
  I5 输出满足公开 schema。
```

此时 validator 应检查关系和文件 diff，而不是要求输出字节级等于一份参考 JSON。否则字段顺序等无关差异会制造 false reject。

### 4.2 区分硬约束和软质量

硬约束适合确定性检查：文件存在、schema、测试、预算、时间冲突、API 终态。软质量如措辞、解释清晰度，可能需要 rubric 或人工判断。

推荐的判定顺序是：

```text
安全/副作用硬门槛
        ↓
功能与结构硬门槛
        ↓
软质量评分
```

危险副作用发生时，不应让一项很高的文风分把总分“平均回通过”。报告应保留每个 check，而不是只保存一个聚合分数。

### 4.3 校准 validator，而不是默认它正确

Validator 也是软件，也会有 false accept 和 false reject。上线任务集前应准备一小组人工确认的：

- 明确正确答案；
- 典型错误答案；
- 合法但形式不同的答案；
- 恶意投机答案；
- validator 本身异常的输入。

对这些样本做 mutation test 很有效：删除必填字段、交换金额、重复 ID、修改禁止目录，确认每种错误至少被一个 check 捕获。如果一个 check 永远不会失败，它可能没有真的约束任何东西。

## 5. 工作区隔离是实验条件，不只是安全措施

### 5.1 为什么每个 RunCell 都需要新环境

复用工作区会引入多种污染：

- 后运行的 Agent 读取前一运行的答案；
- 一次依赖安装让后续配置意外获益；
- 未清理的临时文件改变工具搜索结果；
- 共享服务对象导致 ID 冲突或副作用累积；
- 并行任务互相修改同一个文件；
- validator 看到的不是该 run 单独造成的终态。

这既是泄漏问题，也是因果混杂。若 Planning 总是第二个运行，它可能因为 baseline 已经生成缓存而显得更快。

### 5.2 推荐的目录和挂载模型

每个 run 至少分开四类内容：

```text
run-cell/
├── input/       # 只读：该任务公开 fixture
├── work/        # 可写：Agent 唯一工作目录
├── submission/  # 可写或最终原子提交：待验证产物
└── trace/       # Agent 不可读、collector 可写

validator-only/
├── oracle/      # 私有规则与参考状态
└── hidden/      # hidden tests / evidence
```

真实隔离还需要：

- 为每个 run 从同一只读镜像或 fixture hash 创建新副本；
- 限制可写路径、网络、进程、CPU、内存和墙钟时间；
- Agent 与 validator 使用不同身份和凭据；
- validator 在 Agent 进程退出或权限撤销后运行；
- 保存运行前快照、运行后快照以及结构化 diff；
- 即使超时或崩溃，也保留已落盘的 Trace 和副作用证据；
- 结束后销毁工作区，不把其状态复用给下一 run。

“固定 seed”不能替代隔离。seed 控制的是部分随机性，工作区残留属于未记录状态。

### 5.3 副作用任务要验证终态，而不是返回值

考虑退款工具返回超时：服务端可能已成功创建退款，只是响应丢失。Agent 再次调用后可能产生两笔退款。若 validator 只检查最终消息或第二次响应，就会漏掉严重错误。

这类任务需要：

1. 在隔离服务 fixture 中记录所有写操作；
2. 以业务主键和幂等键检查最终状态；
3. 将“恰好一笔正确退款”设为 oracle；
4. 把重复副作用作为硬失败；
5. 在 Trace 中关联工具尝试和服务端审计事件。

## 6. HarnessLab 例子：从冒烟题到可信文件题

### 6.1 当前 `sum_numbers` 能证明什么

当前任务把 `[19, 23]` 作为公开输入，mock tool 返回 `{"sum": 42}`，外部 `exact_match` 使用私有 `expected` 验证。这个闭环证明：

- 公开投影能生成不含 `expected` 的 prompt；
- runner 能在 Harness 返回后调用 validator；
- run、trace、summary 和私有定义 hash 能保存下来；
- 错误输出会成为 validation failure，而不是 execution error。

它不能证明：

- 真实模型会自己选择正确工具和参数；
- 当前进程隔离足以抵抗恶意 Agent；
- exact match 能覆盖复杂任务；
- scripted model 的成功率具有行为意义。

尤其要注意，offline fixture 会指导 scripted model 生成固定工具调用。它服务于框架合同测试，不应进入真实模型质量统计。

### 6.2 一个未来文件任务的边界草图

可以把任务包拆成：

```text
tasks/report-007/public.yaml
tasks/report-007/public-input/...
tasks/report-007/private/oracle.yaml
tasks/report-007/private/hidden-tests/...
```

`public.yaml` 说明输入目录、输出 schema 和禁止联网；`oracle.yaml` 定义必需记录集合、数值关系和不可修改路径；hidden validator 在 Agent 完成后读取 submission 与文件 diff。

artifact 中保存的不是 oracle 明文，而是：

```json
{
  "task_revision": "report-007@sha256:...",
  "public_sha256": "...",
  "private_evaluation_sha256": "...",
  "workspace_image_digest": "sha256:...",
  "validator_version": "file-report-v2"
}
```

这样既能证明不同 Harness 面对同一任务版本，又不把私有材料混入模型上下文。

## 7. 一套可执行的任务审查清单

在把任务加入正式实验前，逐项回答：

### 任务有效性

- 公开要求是否足以让合格执行者理解目标？
- 成功条件是否对应真实用户价值，而非表面格式？
- 是否允许多个合理解？若允许，validator 是否误用 exact match？
- 难度来自目标能力，还是来自歧义、冷知识或偶然环境问题？

### Oracle 与 validator

- 每个硬约束是否至少有一个可执行 check？
- 是否记录容差、规范化和聚合规则？
- 是否测试过合法变体、典型错误和投机输出？
- validator 故障能否和 Agent 失败分开统计？

### No-leak

- 模型消息、工具、文件树、错误、缓存是否都做过 canary 检查？
- Evidence Tool 的反馈是否泄露最终答案？
- Agent 是否能读取 artifact、其他 run 或 validator 路径？
- Trace 是否在导出前脱敏？

### 隔离与复现

- 每个 run 是否从同一个 fixture digest 创建全新环境？
- 输入是否只读，写入是否限制在显式路径？
- 是否保存初态、终态和副作用 diff？
- 超时、崩溃和清理失败是否仍可审计？

## 8. 面试中怎样讲清楚

可以这样概括：

> 我把任务分成 Agent 可见的 public view 和 evaluator-only 的 private oracle。Oracle 不是简单标准答案，而是成功必须满足的外部不变量；hidden tests 只是观测这些不变量的证据。当前 runner 只把公开投影传给 Harness，完成后再由外部 validator 检查 submission。结构化任务已有独立文件和 hash 边界；文件与代码任务还会为每个 RunCell 创建独立工作区，并由不同权限检查文件 diff 或服务终态。No-leak 也不只查 prompt，还覆盖工具错误、文件挂载、缓存、Trace 和可反复查询的 Evidence Tool。同进程数据投影不是安全沙箱，因此正式代码任务必须升级到进程或容器隔离。

这段回答同时表达了三个重要判断：成功由外部事实定义；评测器本身需要验证；工程隔离是实验设计的一部分。

## 9. 自测问题

1. 为什么 `expected` 不一定是一份唯一的参考输出？
2. hidden tests 与 private oracle 有什么区别？
3. 公开任务说明了输出 schema，是否构成答案泄漏？
4. 为什么 `oracle_fields_visible=False` 不能单独证明 no-leak？
5. Agent 看不到 hidden test 文件，但测试失败消息返回完整预期值，边界是否仍然成立？
6. 为什么在四个 Harness 间轮流复用同一个工作目录会损害因果解释？
7. 退款 API 超时后，为什么只检查工具返回值不足以判断任务成功？
8. 当前 `sum_numbers` 的 scripted fixture 为什么不应进入 Agent 能力结论？
9. 对多解旅行规划使用字节级 golden answer，会造成哪类 evaluator 错误？
10. Validator 自己崩溃时，应记为 task failure、execution error，还是 evaluator invalid？为什么？

### 答案要点

1. 很多任务有多个合法解；oracle 更一般地表示必须满足的关系、状态和约束。
2. Oracle 定义正确性，hidden tests 是用来观测其中部分不变量的私有证据。
3. 通常不构成。Schema 是用户要求的一部分；具体字段值或隐藏边界样例才应保持私有。
4. 它是被测实现自己写出的声明；应捕获真实消息、文件和工具通道，并用 canary 测试。
5. 不成立。错误反馈本身成为泄漏通道，尤其在允许反复修订时。
6. 缓存、文件和副作用残留会同时影响后续条件，使 treatment 与运行顺序混杂。
7. 超时不代表服务端未执行；应验证最终业务状态、调用审计和幂等性。
8. 调用序列由 fixture 合成，测到的是框架和工具合同，而不是模型决策能力。
9. 会把形式不同但满足全部约束的合法解误判，产生 false reject。
10. 应单列 evaluator invalid。没有可靠 verdict 时，不能把基础设施故障伪装成 Agent 失败。
