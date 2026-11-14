# 全量矩阵入队记录：2026-11-14

89 个任务、五组、联网/禁网两种条件，共 **890 个单元**，每个单元只独立运行一次。
固定 Terminal-Bench 2.1 revision `12b7565679ce5006230b820666353673a133db93`。
最后任务 `rstan-to-pystan` 的十个单元已在数组作业 `1210104` 入队，
依赖 `afterany:1209844`，保持总模型并发为 2。控制器作业申请 2 CPU、8 GiB 内存、零 GPU。
实验容器使用任务规定的资源和时限；模型通过 DeepSeek API 调用。

这是实验安排完成的记录。下述进度快照为已评分 122/890，全量评测仍在运行。

## 固定实验与结果口径

- 五组：`mini`、`deepagents_default`、`generic_retry`、`rubric_transcript`、`rubric_evidence`。
- HIGH、thinking 开启、temperature 1、top_p 0.95；输出上限 393,216 token，模型调用上限 500，actor 与 grader 共享。
- 六题试验保留 60 个单元；先前批次保留或安排 820 个单元；本次新增最后 10 个单元，尚待准备的任务数为零。
- 已调用模型的失败尝试保留。13 个缺少分数的原始提交经过不改变文件的官方重新评分，没有再次调用 actor。
- 工具调用、底层命令、token、输出字符、各阶段耗时、grader 消耗与 usage 缺失分别记录；运行适配版本单独分组。
- 官方分数来自 verifier，原始运行错误和无分数尝试的成本继续保留。

最新 study 的 SHA-256 为
`049faaec347c54fe79738bfcae9c534b74d92c911b2336e362926a7cbf1ac33d`，
路径为 `tb21-pystan-local-index/artifacts/expansions/tb21-full-image11-20261114/study.json`。
统一报告脚本可从该 study 追溯完整批次，使用方法见 [全量报告说明](coding-campaign-report.md)。

## 最后一题的原始对照验收

PyStan 最初的禁网依赖缓存探针关闭了 pip 的公网索引，但正式环境只配置了本地 find-links。
依赖安装仍可能尝试不可达的公网索引，原始参考解在 1,800 秒时限到达时仅完成约 88% 的采样，尚未输出 CSV。
修正使用已有的 `offline_local_index` 选项；联网侧仍使用正常公网索引。
两侧使用相同的公共安装包，原始任务、参考解、采样次数、资源和官方时限保持不变。

| 配置 | 网络 | 参考解 Agent 阶段耗时（秒） | 官方检查 | 得分 |
| --- | --- | ---: | --- | ---: |
| 初次验收 | public | 418.1 | 6/6 | 1 |
| 初次验收 | offline | 1811.4 | 1/6 | 0 |
| 本地索引修正 | public | 406.2 | 6/6 | 1 |
| 本地索引修正 | offline | 388.4 | 6/6 | 1 |

1811.4 秒是包含取消收尾的实际阶段耗时；配置时限仍为 1800 秒。
两次验收的空解均为 0，所有实例均已回收；首次失败完整保留。
第二次作业 `1210075` 的四项原始对照全部接受，模型调用为零，随后零模型预检 `1210103` 通过。
准备阶段允许针对环境修正重新验收；正式模型单元仍为 N1。

公共软件来源、分阶段 Python 依赖和提交捕获范围见 [PyStan 输入说明](coding-pystan-public-inputs.md)。
其他任务各自的兼容性记录继续保留在其 study 和 controls manifest 中。

## 指标核对与阶段快照

对 110 个已评分单元的较早快照中，88 条 Deep Agents 记录进行了 LangSmith 服务端读回：
官方分数、模型与工具调用、token、输出字符和耗时等已发布字段全部与本地一致，88 条 trace 均已结束。
其中固定提交重新评分的分数也与原始 trace 对应，原始运行错误和消耗未被覆盖。
首次查询因频率限制只核对 58 条；降低查询频率后补齐其余 30 条，没有重跑评测。

核对文件：`tb21-campaign-report/artifacts/coding-reports/langsmith-audit-20261114T090548Z/audit.json`，
SHA-256：`372612248dfa9ec4d895d3eb59a4372301d76c99b790fefa8027e9719da46614`。

截至 **2026-11-14 09:10:16 UTC**，完整矩阵的进度报告记录 122 个已评分单元、87 个成功，
另保留 10 次环境失败记录，共 132 次已结束尝试。已记录 24 条 usage 不完整的尝试。
这些是进行中的任务子集统计；各组及网络条件的完整比较待全量结束后汇总。
该快照新增的记录不属于前述 88 条服务端读回范围。

报告路径：`tb21-campaign-report/artifacts/coding-reports/campaign-20261114T091016Z/report.json`，
SHA-256：`c0b96c0f6174d31a922bca017a39c766d0e83711fc4bf16b4219493a47c2239d`。

本阶段的 study、对照结果、队列快照及上述报告哈希索引位于
`tb21-pystan-local-index/artifacts/coding-reports/full-matrix-release-20261114/evidence.json`，
SHA-256：`c3ae50c9cdebf683d06e33716235ba6342ab11ca26ee8ac882ef0acde4c1d005`。
原始轨迹、提交、官方测试与清理记录继续保存在各任务的 trial 目录。
