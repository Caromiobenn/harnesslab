# Native 环境中的 Python 工具运行依赖

`crack-7z-hash / rubric_evidence / public` 的官方得分为 1，但内部状态为 `grader_error`。
grader 发起两次 `read_artifact` 后，指纹命令均以 127 退出：任务镜像没有 `python3`。
该试次没有执行证据验证命令。相关原始轨迹、得分和消耗继续保留。

Native 环境已经为进程管理和提交采集上传了固定版本的 Python 3.13。新增的
`actor_python_fallback: true` prerequisite 字段让所有 harness 共享这一运行依赖：

- 启动环境时，在 controller 专属目录建立 `actor-bin/python3`，指向已校验的 Python。
- actor 阶段执行命令时，把这个目录追加到原来的 `PATH`。任务已有的 Python 保持优先。
- 文件工具、证据工具和 actor 的命令因此都能在缺少系统 Python 时找到同一个解释器。
- 网络检查、任务资源、时间预算、进程回收和 verifier 的原有依赖配置继续使用各自的流程。

这个字段默认关闭，已有 study 与 prerequisite 文件保持原值。新版本需要复制并固定自己的
prerequisite 清单，明确开启该字段，并把版本和控制测试记录写进新的实验计划。
已调用过模型的单元保持原始结果；新配置仅用于尚未启动的单元，不补跑旧单元。

单元测试实际执行 shell，检查缺少任务 Python 时使用 fallback、已有任务 Python 时保持原解释器，
并检查命令仍通过原有进程组追踪。首轮云端探测发现，供应商适配层会在命令前恢复镜像 PATH，
覆盖更外层追加的目录。因此在 `exec` 层包装原始命令，让 fallback 追加发生在镜像 PATH 恢复之后；
新增实际 shell 回归测试覆盖这一顺序。前两次无模型探测的失败记录与实例回收记录保留。

## 云端验收结果

2026-11-14，修复版本 `2a1239dd2e1aa8258bc6735765e07b4e1ac75540` 在
`crack-7z-hash` 的新云实例中完成验收。两种网络下均确认原镜像没有 `python3`，
开启 actor 阶段后使用固定的 Python 3.13.14。

- 禁网和联网各完成文件写入、读取、目录查询、glob、grep、编辑、下载和删除。
- 两侧均完成 `read_artifact` 指纹绑定、`verify_candidate` 行为检查，以及当前证据一致性检查。
- 两侧均完成提交传输哈希核验；两个探测实例全部回收。

| 网络 | 对照 | 官方得分 | 官方测试通过数 | 回收 |
| --- | --- | ---: | ---: | --- |
| 禁网 | empty | 0 | 0 / 2 | 已确认 |
| 禁网 | oracle | 1 | 2 / 2 | 已确认 |
| 联网 | empty | 0 | 0 / 2 | 已确认 |
| 联网 | oracle | 1 | 2 / 2 | 已确认 |

验收作业 `1210960` 已正常结束，四个对照实例全部回收，模型调用数为零。
原有单元测试、格式检查和 smoke 检查已通过；续跑功能版本共有 342 项测试通过。

证据位于 `tb21-actor-python-path/artifacts/setup/tb21-actor-python-acceptance-v3-20261114/acceptance.json`，
SHA-256 为 `412064f77dba45a14c4f04118066b126392d1dfbb06d2849f4458a0b0a4673cb`。
该记录包含探测结果、官方测试、实例回收记录及输入证据哈希；前两次失败探测仍独立保留。
