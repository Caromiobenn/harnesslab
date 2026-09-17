# Qwen2.5-14B-AWQ 首轮真实模型实验

状态：`exploratory_complete`。执行时间：2026-09-17。机器：2 × RTX 4090 24GB，实际推理使用 GPU 0。完整复现步骤见 [服务器实验复现手册](server-reproduction.md)，机器可读摘要见 [`results/qwen2.5-14b-awq-20260917/summary.yaml`](../results/qwen2.5-14b-awq-20260917/summary.yaml)。

## 1. 实验到底比较了什么

同一个 `Qwen/Qwen2.5-14B-Instruct-AWQ`、同一组公开任务、同一私有 validator、temperature 0 和相同 seed 下比较：

- `langchain_baseline`：最小 `create_agent()`；
- `langchain_planning`：在 baseline 上增加 `TodoListMiddleware`；
- `deepagents_default`：Deep Agents 0.7.14 默认 bundle。

任务为联系人规范化、发票核对、文件销售汇总。每个 task × harness 重复 3 次，共 27 runs；9/9 个配对键完整。Reference submissions 在运行前全部通过 private validators。服务 smoke 还确认 vLLM 能把 Qwen 的调用解析成 OpenAI API 的结构化 `tool_calls`。

## 2. 主结果

| Harness | 成功 | Validation fail | Execution error | 平均模型调用 | 平均工具调用 | 平均输入/输出 tokens | 平均延迟 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0/9 | 9 | 0 | 1.00 | 0.00 | 600 / 184 | 2.68s |
| Planning | 3/9 | 3 | 3 | 2.00 | 4.33 | 4,727 / 1,386 | 24.60s |
| Deep Agents default | 0/9 | 9 | 0 | 3.67 | 4.00 | 11,512 / 1,898 | 28.16s |

Planning 的 3 次成功全部来自发票任务：

| Task | Baseline | Planning | Deep Agents default |
|---|---:|---:|---:|
| contacts normalize | 0/3 | 0/3 | 0/3 |
| invoice reconcile | 0/3 | 3/3 | 0/3 |
| sales rollup | 0/3 | 0/3（3 次 execution error） | 0/3 |

24 次 graph 正常结束的运行中，有 21 次被外部 validator 判错。因此，“Agent 正常结束”在这批运行中的 false-completion 比例是 21/24（87.5%）；若以全部 27 runs 为分母则是 77.8%。这正是把执行完成与任务成功分开的价值。

## 3. 失败画像

### 3.1 联系人：局部规则正确，跨重复项合并失败

三种 harness 都规范化了 email、姓名空白和大部分电话/标签，但都漏掉重复联系人第二条记录中的 `newsletter` 标签。Baseline 还把姓名全部小写；planning 与 Deep Agents 保留了姓名大小写，却把 Bob 电话的前导 `0` 丢掉。输出满足 JSON schema，却不满足语义 oracle，是典型的“格式通过、任务失败”。

### 3.2 发票：Planning 修复了排序，Deep bundle 引入状态错误

Baseline 的金额、税、余额和状态都正确，但输出行仍按 `B, A`，违反明确的按 id 排序要求。Planning 通过 Todo 过程后返回 `A, B`，三次均完全通过。Deep Agents 也正确排序和计算，却把有付款且余额为正的状态写成 `unpaid`，因此三次失败。

这只能说明在这个发票 case 上 planning treatment 与成功共同出现；只有一个逻辑任务，不能推广成 planning 的总体因果优势。

### 3.3 文件任务：三种 harness 暴露三类不同故障

- Baseline：模型输出了字面量 `<tool_call>` 文本，API parser 未把该批多调用转成结构化调用；实际工具调用为 0，输出文件不存在。
- Planning：一次响应并行发出 12 个调用，既写入了虚构数值，也读取不存在的 `/input/orders1.json` 或 `/input/orders2.json`。并行调用中的写入已经产生副作用，随后 `FileNotFoundError` 使 run 成为 execution error。
- Deep Agents：实际执行 11 次工具调用且未修改输入，但最终文件包含字面量 `\\n`、schema 不符且金额错误；graph 仍报告完成，private validator 拒绝提交。

Planning 案例还说明“run error”不等于“没有副作用”：错误发生前 `/output/summary.json` 已被写入。对真实工具系统，异常后的状态快照和幂等设计不可省略。

## 4. 成本解释

Planning 相比 baseline 平均延迟约 9.2 倍，Deep Agents 约 10.5 倍。Deep Agents 平均输入 token 约为 baseline 的 19.2 倍，但本矩阵没有获得额外成功。这个数字仅描述当前 3-task/Qwen 条件，不是框架的普遍效率排名。

Planning 的平均 token 被低估：三个文件 run 在异常路径上没有拿到 provider usage，artifact 中记录为 0。模型调用、工具调用、延迟和错误仍被保留，因此不能用这里的 planning token 均值做精确成本结论。

## 5. 可复现性证据

- 模型 5 个关键文件均有 SHA-256，保存在服务器和本地 ignored artifact 的 `model-sha256.txt`；
- 运行时 `src/ + benchmarks/ + configs/ + uv.lock + pyproject.toml` 共 69 个文件的组合哈希为 `ff79ebe8bc7459553012cef489ffe8257ac9e4ae531eefb6777295f32138d111`，当时服务器与 WSL 一致；
- 实验后修复了异常路径 token trace 与矩阵不中断调度；当前同范围代码哈希为 `3d90aece908407e4f9d2508cdfb2a343346b19465811f47620b4bc66b7a621a9`，不回写既有 immutable artifacts；
- comparison JSON 哈希为 `bfad96513510b02a61f2d7d11dfaf7908f774ebab478441a87303f279345cc79`；
- 三组 raw `runs.jsonl` 哈希记录在机器可读摘要中；
- 每组 artifact 含 manifest、events、runs、summary 和每个文件任务的初始/最终 workspace snapshot；
- 原始 artifacts 同时保存在服务器 `/mnt/harnesslab-data/artifacts/server` 与本地 `artifacts/server`（Git 忽略）。

## 6. 能说与不能说的结论

可以说：真实 14B 自托管链路、三种框架 treatment、公私分离验证、workspace 快照、usage/trace 和跨 artifact 汇总已端到端运行；Planning 在发票任务上把 0/3 提高到 3/3，同时在文件任务出现 3/3 execution errors。

不能说：Planning 总体优于 baseline，或 Deep Agents 总体无效。原因是只有 3 个逻辑任务、单一模型、固定运行顺序和单一量化条件；Deep Agents 还是 bundle，不支持单机制归因。下一批应优先扩充任务族、随机化 treatment 顺序，并修复异常路径 token 计量，而不是根据这 27 runs 调参追榜。
