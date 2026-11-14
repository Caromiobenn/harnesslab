# Streaming transport for long reasoning responses

The first full-scope task exposed five request timeouts in completed Deep Agents
trials on 2026-11-14. Each had already received three or four model responses;
the next non-streaming request exceeded the 240-second HTTP read timeout while
waiting for response headers. Those attempted cells and their submissions are
retained. Pending first-batch units were held before changing the runtime.

`response_transport` now accepts `non_streaming` (the existing default) or
`streaming`. The choice is recorded in the experiment configuration. Streaming
uses the same HIGH setting, sampling parameters, output cap, model-call budget,
task deadline, and zero-retry policy. It changes delivery: the 240-second read
timeout bounds an interval without received data rather than requiring the
entire generation to finish before the first response arrives. Model reasoning
can therefore continue beyond 240 seconds while data keeps arriving, subject
to the unchanged task deadline. This is a declared transport amendment, not an
identical execution setting to the pilot.

Deep Agents uses the SDK's native streaming and explicitly requests trailing
usage. Mini retains its native prompt, tool parser, and agent loop; its streamed
chunks are aggregated using LiteLLM's response builder before reaching that
parser. Both paths retain reasoning content, tool arguments, cache usage, and
the final token counters. Partial interrupted generations are saved separately
and are not counted as completed model responses. They may have billable tokens
whose total is unavailable if the provider's final usage chunk was not received.
Receiving another chunk after the task deadline stops consumption and closes
the stream; no partial tool call is executed.

Deterministic tests exercise real DeepSeek SDK SSE decoding and the real mini
parser, including fragmented tool arguments, reasoning fragments, trailing
usage, connection interruption, and cancellation. Live transport acceptance
uses separate non-benchmark prompts; it must not resample an attempted task.
Existing frozen studies keep their original source and non-streaming setting.
Future streaming cohorts require a new plan recording this amendment and
excluding every previously attempted cell.

References:

- [Alibaba Cloud streaming and usage](https://www.alibabacloud.com/help/en/model-studio/stream)
- [Alibaba Cloud thinking requests](https://help.aliyun.com/en/model-studio/deep-thinking)
- [ChatDeepSeek streaming](https://reference.langchain.com/python/langchain-deepseek/chat_models/ChatDeepSeek)
