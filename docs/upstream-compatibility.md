# Upstream compatibility notes

Reviewed on 2026-09-16 for the initial HarnessLab scaffold.

## Pinned references

- Deep Agents package: `0.7.14`.
- Deep Agents source used for API review: commit
  `ded0f1187f6bf81e2f679ea7b16ead7760d775a6`.
- Datawhale `deepagents-in-action` tutorial reviewed at commit
  `02796122ce7f73afbef866cae85822f65377f7f4`.

The tutorial is a learning reference, not this repository's code skeleton. Its chapters use
several Deep Agents 0.7.x patch versions, so examples must be checked against the package
version locked here. Tutorial prose is licensed CC BY-NC-SA and should not be copied into
this project.

## Deep Agents 0.7.x experiment constraints

- `model` must be supplied explicitly to `create_deep_agent`.
- Planning is not a default: `TodoListMiddleware` must be added explicitly.
- A bare Deep Agent still includes a general-purpose subagent and `task` tool. It is not a
  valid single-agent baseline unless that profile is disabled.
- Backend factories were removed; pass a concrete backend instance.
- Filesystem and local-shell backends default to virtual path semantics.
- Rubric and dynamic-subagent APIs are version-sensitive and need adapter contract tests.

Planned ablation labels therefore remain distinct:

1. minimal LangChain `create_agent` baseline;
2. default Deep Agents harness;
3. explicit planning;
4. explicit specialist subagents;
5. rubric/evidence verification with bounded revision.

This taxonomy is deliberate: hidden default middleware or subagents would otherwise make
the measured treatment different from the label used in the report.

## Primary sources

- <https://pypi.org/project/deepagents/0.7.14/>
- <https://github.com/langchain-ai/deepagents/tree/ded0f1187f6bf81e2f679ea7b16ead7760d775a6>
- <https://docs.langchain.com/oss/python/deepagents/overview>
- <https://github.com/datawhalechina/deepagents-in-action/tree/02796122ce7f73afbef866cae85822f65377f7f4>
