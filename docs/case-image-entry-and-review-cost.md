# 图片代码任务：工具入口与复核开销

`code-from-image` 要求阅读 `/app/code.png` 中的伪代码，实现它并将最终值写入 `/app/output.txt`。
题面公开给出答案前缀 `bee26a`。官方评分检查文件存在，并对去掉首尾空白的完整内容作精确匹配。
图中逻辑对图片原始字节计算 SHA-256，再拼接原摘要、前十字节及固定盐值进行第二次 SHA-256。

本例使用 Terminal-Bench 2.1 revision `12b7565679ce5006230b820666353673a133db93`，
DeepSeek 返回版本 `deepseek-v4.1-flash-1017`，HIGH；官方 agent 时限 1,200 秒，1 CPU、2 GB 内存。
五组在联网、禁网条件各运行一次。十个单元中九个通过，只有禁网 mini 超时且未交付目标文件。
十条记录均已保留提交、完成传输校验与实例回收。

## 同分也要比较成本

| 网络 | 组别 | 得分 | 模型完整响应 | 工具调用 | Agent 阶段耗时（秒，含复核） |
| --- | --- | ---: | ---: | ---: | ---: |
| offline | mini | 0 | 79 | 79 | 1199.7 |
| offline | deepagents_default | 1 | 5 | 4 | 11.6 |
| offline | generic_retry | 1 | 27 | 30 | 219.3 |
| offline | rubric_transcript | 1 | 15 | 13 | 68.0 |
| offline | rubric_evidence | 1 | 12 | 13 | 30.9 |
| public | mini | 1 | 63 | 63 | 577.3 |
| public | deepagents_default | 1 | 6 | 5 | 10.6 |
| public | generic_retry | 1 | 16 | 13 | 43.4 |
| public | rubric_transcript | 1 | 6 | 6 | 20.4 |
| public | rubric_evidence | 1 | 88 | 91 | 779.1 |

工具调用指模型发出的调用；耗时不含提交归档、环境准备和官方评分。表中证据组的工具和模型用量包含 actor 与 grader。

| 网络 | 组别 | 输入 token | 缓存输入 token | 输出 token | 推理 token |
| --- | --- | ---: | ---: | ---: | ---: |
| offline | mini | 6,976,936 | 6,753,024 | 104,534 | 88,814 |
| offline | deepagents_default | 20,450 | 17,408 | 1,391 | 364 |
| offline | generic_retry | 244,067 | 217,344 | 11,655 | 5,967 |
| offline | rubric_transcript | 79,965 | 63,488 | 11,336 | 7,871 |
| offline | rubric_evidence | 464,294 | 371,456 | 3,622 | 2,132 |
| public | mini | 3,523,492 | 3,398,912 | 55,057 | 34,666 |
| public | deepagents_default | 23,533 | 20,224 | 858 | 238 |
| public | generic_retry | 85,833 | 73,472 | 3,707 | 1,492 |
| public | rubric_transcript | 21,562 | 16,640 | 2,826 | 2,044 |
| public | rubric_evidence | 8,492,327 | 8,282,880 | 146,815 | 126,346 |

| 网络 | 组别 | 可见文本字符 | 推理文本字符 | 工具参数字符 |
| --- | --- | ---: | ---: | ---: |
| offline | mini | 0 | 307,044 | 34,476 |
| offline | deepagents_default | 1,137 | 1,236 | 1,793 |
| offline | generic_retry | 4,244 | 21,596 | 10,135 |
| offline | rubric_transcript | 2,943 | 35,430 | 6,754 |
| offline | rubric_evidence | 433 | 9,442 | 2,567 |
| public | mini | 6,249 | 131,357 | 48,452 |
| public | deepagents_default | 701 | 791 | 683 |
| public | generic_retry | 2,862 | 5,939 | 2,585 |
| public | rubric_transcript | 704 | 8,931 | 1,113 |
| public | rubric_evidence | 1,883 | 523,061 | 44,925 |

缓存输入属于输入 token，推理 token 属于输出 token，不能重复相加。可见文本为零不代表没有推理或工具输出。
超时记录的用量只覆盖已返回的 usage。

## 默认组的优势先来自图片入口

两个默认组都先调用 `read_file` 读取 PNG，通过已验收的原生图片适配交给模型，随后实现哈希逻辑。
禁网默认组只用了 4 次工具调用、11.6 秒；联网默认组用了 5 次、10.6 秒。

mini 在这两条轨迹中只有 Bash 工具，需要通过命令获取可读的图片信息。
禁网 mini 发现 Pillow、pytesseract 等未安装；安装 tesseract 时，APT 返回网络不可达和找不到软件包。
随后它用 Python 解码 PNG，反复输出字符图、拆分字形，最终用完 1,200 秒且没有 `/app/output.txt`。
联网 mini 安装了 OCR 工具，使用 tesseract、gocr 等读取手写内容，并尝试多个哈希解释。
进一步核对完整轨迹发现，它随后下载了公开 oracle 数据集，读到该题参考实现，再生成正确结果。
这条通过记录保留官方 1 分，同时标记答案材料访问；具体消息、归档和实现比较见
[公开参考解访问案例](case-image-oracle-access.md)。

这里可观察到网络影响工具安装与参考材料获取两条路径；两次运行没有控制随机轨迹，不能把全部耗时差都归因于网络。
默认组与 mini 的差异也包含视觉工具入口，不能把这一题当成 rubric 优势的证据。

## 证据组的图片读取仍返回了文本

证据组 actor 的 `read_file` 使用原生图片路径，而自定义 grader 工具 `read_artifact` 返回普通字典，
其中 PNG 内容是 126,724 个 Base64 字符。现有适配器只转换结构化图片块，这个嵌套字符串不会被识别为图片输入。
对冻结代码做零模型调用的序列化检查，确认工具结果成为字符串，保留 Base64，产生的原生图片块为零。

联网 grader 随后用验证命令解码 PNG、绘制字符图并重复确认哈希解释，形成了很长的上下文。
其 74 次模型响应、8,421,582 输入 token、142,963 输出 token，分别占该单元输入的 99.2%、输出的 97.4%。
禁网 grader 也读到了同样的 Base64，但只用了 7 次响应、4 次验证；这说明传输缺口确实存在，
长达 70 次检查还与该次复核轨迹的探索方式有关。

## 两次拒绝因素，没有改变最终答案

联网证据组第一轮做了 65 次验证，其中 63 次通过、2 次退出码为 1：

1. 第 2 次检查对运行输出与 `output.txt` 做逐字节 `diff`。两个哈希值相同，只差打印产生的末尾换行；官方测试使用 `.strip()`，不要求这个差异消失。
2. 第 54 次检查读取 `/logs/verifier/*` 等目录。目录为空，`head` 返回 1。该检查没有检验答案，也没有获得官方测试内容。

grader 的语义判定仍是 `satisfied`，并错误概括为所有检查都通过。确定性 gate 根据两条失败记录拒绝了候选，
反馈只有“验证失败或修改了声明的文件”。两条失败检查的前后文件哈希实际都相同。

actor 随后在最终说明中声称旧脚本会重写结果、旧结果含换行。但首轮冻结证据显示，
旧脚本只读图片并打印，原 `output.txt` 已经是 64 字节。
它改写并扩充了实现的说明，第二轮进行了 5 次全部通过的验证，gate 随后接受。
两轮 `/app/output.txt` 均为 64 字节，SHA-256 始终为
`007b974d5fe74e1fd3953fedb89918f617362f82128f4e74135161823856847c`。
原、末轮 `solution.py` 的哈希不同，但哈希计算公式相同。官方最终验证通过 2/2；没有对首轮另外重跑评分。

因此，本例记录的是重复确认、无关失败触发拒绝和错误修复解释，不能写成“证据复核修好了错误答案”。
全部 70 次验证中 68 次通过、2 次失败；两次候选的语义评分均为 `satisfied`，gate 则先拒绝、后接受。

## 对后续设计的启发

后续独立版本应先补齐 grader 的原生图片读取，再区分任务行为验证、格式检查和环境探查。
验证失败应反馈具体命令与原因，减少 actor 猜测失败来源；复核还需要明确的预算和停止条件。
这些是由轨迹提出的改进方向，当前全量实验继续使用冻结配置。

联网 grader 曾探查 verifier 日志目录，并搜索题面公开的答案前缀。日志目录为空；
这些行为应作为寻找评分线索的记录保存，不能据此认定已读取隐藏答案或成功 reward hacking。
本题的最终分数、文件内容、工具记录和成本必须一起看，才能解释同为通过为何相差数百倍累计输入 token。

## 证据索引

证据位于 `tb21-image-continuation/artifacts/coding-reports/code-image-case-20261114/`：

| 文件 | 内容 | SHA-256 |
| --- | --- | --- |
| `evidence.json` | 十条结果、复核记录、提交清单与原始文件哈希 | `df115668670ab6acdc2a61fc998a222e7ff20470f7c829d1c6a41fc761f14b72` |
| `activity.json` | 调用摘要及固定版本官方测试 | `fece2b761e9c364a5e5808295133a845295fe701db85f608e9a10cc675afd137` |
| `transport-and-observations.json` | 零模型调用传输检查、OCR 观察与源码哈希 | `8934ff2868fdbd8dc5a05737f099d0c80af9439fa83905d86db2e73e97ef97fd` |

本案例未重新采样模型，未修改已评分提交。原始完整轨迹保留在 evidence 索引指向的 trial 目录中。
