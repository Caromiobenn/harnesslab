# R 公共源码依赖与禁网安装

`bn-fit-modify` 的官方参考解安装 `remotes 2.5.0` 和 `bnlearn 4.9`。
官方任务镜像已有 R、编译工具和输入数据，缺失的是公共 R 安装包。

`prepare_coding_actor_r.py` 下载固定版本的 CRAN 源码包，读取包内 DESCRIPTION
核对名称、版本并记录 SHA-256，随后在任务镜像中建立本地 source repository。
禁网探针把包安装到临时目录，实际加载并核对版本；打包只包含公共源码、索引和仓库配置，
不包含编译后的库、任务数据处理脚本或答案。模型与参考解仍需自行安装和解题。

运行环境通过 `R_PROFILE_USER` 加入本地仓库。联网组保留 CRAN 作为后备源，
禁网组使用相同缓存并关闭外部网络。`R --vanilla` 等主动忽略用户 profile 的调用仍按 R 的原有行为执行。
此配置面向使用默认仓库的 `bn-fit-modify`；其他任务若显式指定仓库 URL，需要先单独验证。

准备回执位于 `artifacts/coding-actor-r/<run>/<task>/receipt.json`，记录下载 URL、包哈希、
镜像指纹、禁网安装输出、归档哈希和实例回收结果。正式评测前仍需通过空提交与参考解的四项对照。

公开来源：[remotes](https://cran.r-project.org/package=remotes)、
[bnlearn 历史源码](https://cran.r-project.org/src/contrib/Archive/bnlearn/)。
