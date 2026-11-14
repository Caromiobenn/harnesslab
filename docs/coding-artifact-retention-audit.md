# 已完成试次的文件保存与指标核验

2026-11-14 10:21:46 UTC 的固定报告含 144 个已评分单元，109 个通过；890 单元的完整评测仍在运行。
本轮检查这 144 个单元的实际文件，核对提交校验值、官方分数和指标字段，并读取 LangSmith 核对
四个 Deep Agents 组的记录。核验不调用模型，也不重新采样。

## 保存核验结果

| 项目 | 核验结果 |
| --- | --- |
| 原生轨迹 | 144/144 非空，已计算 SHA-256；mini 使用 `mini-trajectory.json`，Deep Agents 使用 `events.jsonl` |
| 提交清单 | 144/144 存在 |
| 提交文件 | 104 份归档、31 份单文件；文件长度和 SHA-256 均与提交清单一致 |
| 未生成目标文件 | 9 条；8 条 Raman 的 Deep Agents 试次、1 条联网 mini 的 WAL 试次，官方评分均为 0 |
| 增量归档的初始状态 | 84/84 与清单记录一致；其余归档采用早期的完整目录格式 |
| 官方结果 | 144/144 与汇总分数一致；其中 13 条采用此前已保存提交的零模型调用重新评分结果 |
| 官方测试报告 | 144/144 存在，报告中的测试数均大于 0 |
| 实例回收记录 | 144/144 已验证 |

9 条“未生成目标文件”来自结束时保存的缺失记录，不是归档文件在保存后丢失。
对归档的核验读取原文件计算哈希，没有解压执行其中代码，也没有重建或替换提交。

增量归档清单中的 `baseline_sha256` 使用 `json.dumps(baseline, sort_keys=True)` 后的字节计算，
与 `capture_delta` 的规则一致。初始状态文件本身的字节哈希另外保存；两种哈希的用途不同。

## 指标字段和用量完整性

144 条试次均包含非负的模型响应数、工具调用数、环境命令数、Agent 阶段耗时、总耗时、
输入/输出/缓存/推理 token，以及可见文本、推理文本和工具参数字符数。
缓存 token 不超过输入总量，推理 token 不超过输出总量。

字段存在与 API 用量是否完整分别统计：

| 用量状态 | 试次数 | 分析时的处理 |
| --- | ---: | --- |
| `complete` | 90 | 完整性检查通过 |
| `partial` | 24 | 保留已收到的 usage，标明不完整 |
| `not_reported` | 30 | 有观测指标，但不能由缺失的完整性状态推断用量完整 |

因此，token 汇总描述已观测用量；对比报告同时保留完整性状态和缺失分母。
这与 [同题成本对比](coding-paired-comparisons.md) 使用相同口径。

## LangSmith 与配对报告

本快照含 114 条 Deep Agents 记录、30 条 mini 记录。四个 Deep Agents 组的 **114/114** 条记录
均已在 LangSmith 结束，得分和消耗字段与本地记录一致；核验同时比较反馈的缩放分数和原始数值。
本次复用了 110 条此前已核验且本地来源未变的记录，另对新增 4 条进行了远端读取。

配对报告覆盖 114 个 harness 比较和 72 个联网/禁网比较，按实际运行配置分为 38 个比较组。
各比较只使用两侧都有分数的同题单元，同一基线可能参与不同的比较，不能跨比较重复累计成本。

## 冻结证据

以下路径位于服务器的 `artifacts/worktrees/` 下；核验报告、汇总及 CSV 均另外备份到本地。
原始大文件继续保存在各试次目录，逐项核验报告记录了它们的完整路径和哈希。

| 文件 | SHA-256 |
| --- | --- |
| `tb21-campaign-report/artifacts/coding-reports/campaign-20261114T102146Z/report.json` | `4c63775540619e4e52acce4e3d743f14b18bfe4f56183156f878a47e504c3d5f` |
| `tb21-campaign-report/artifacts/coding-reports/artifact-audit-canonical-20261114T102802Z/audit.json` | `1c6eb5c01011aa025f97e2257fc3f0b09ad2e6383258d442f04c561dcbfbe395` |
| `tb21-campaign-report/artifacts/coding-reports/langsmith-audit-20261114T102250Z/audit.json` | `bd7f2e0a2cca193e40a33282fa71aecbed724d1f8f580566e0eaac5668316c2b` |
| `tb21-paired-report/artifacts/coding-reports/paired-report144-20261114/pairs.json` | `bb3d6f737582f6de04ff68ab055de9b22847c3cdf2ace2bc388e04216ddb9ac9` |

后续完成更多单元时，在新快照上追加核验；本页保留这一次检查的明确范围。
