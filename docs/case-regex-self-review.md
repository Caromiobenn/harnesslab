# 普通自我复查增加成本，但提交内容没有改变

六题 HIGH、每格独立运行一次的离线实验中，`regex-log / generic_retry` 的官方判分为 1。该组先生成答案，再执行两轮自我复查，共产生三个候选完成消息。首次生成后的实际文件读回与最终归档逐字节相同：`/app/regex.txt`，296 字节，SHA-256 为 `6e0818ff07b2c1d29235d01b17b5eaab43de4d4685ef75031cba4da6cf505257`。

| 阶段 | 模型调用 | 输入 token | 输出 token |
| --- | ---: | ---: | ---: |
| 首次完成 | 5 | 26,113 | 15,932 |
| 后续两轮复查 | 13 | 134,940 | 46,156 |
| 总计 | 18 | 161,053 | 62,088 |

首次完成消息到最后完成消息相隔 269.48 秒。两轮复查占总输出 token 的 74.34%，包括读取文件、检查边界情况、随机测试和性能测试；最终交付内容没有变化。这里的输出 token 按服务端 usage 统计，包含其报告的推理输出，不能等同于用户看到的文字长度。

该例说明固定追加自我复查可以增加测试覆盖与信心，也可能付出显著成本而不改变提交。这一例没有显示出官方正确率收益：原始文件和最终文件相同，只有最终状态接受了官方判分。跨组比较仍要以同一任务、同一网络条件的完整记录为准；单次结果不推断总体显著性。

证据目录：`artifacts/coding-cases/regex-self-review/`，包含 `evidence.json` 与 `verified.json`。

原始 trial：`artifacts/coding/jobs/tb21-high-offline-20261114b-regex-log-generic_retry-0/regex-log__kufmabY`。核验依据是 `agent/events.jsonl` 的首次 `write_file`、`agent/messages.json` 中工具调用 `call_2f0dfc3c71094833932ec4ab` 的实际读回、以及 `agent/submission/regex.txt` 的归档哈希。阶段边界来自第 21、54、75 行的候选完成消息。
