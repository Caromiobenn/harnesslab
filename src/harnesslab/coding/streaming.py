"""Aggregate streamed mini responses without changing its prompts, tools, or loop."""

from uuid import uuid4

from harnesslab.coding.config import save_json


def collect_completion(response, messages, stopped, logs_dir):
    import litellm

    chunks = []
    try:
        for chunk in response:
            chunks.append(chunk)
            if stopped.is_set():
                raise InterruptedError("Agent execution has ended")
        return litellm.stream_chunk_builder(chunks, messages=messages)
    except Exception as error:
        save_json(
            logs_dir / f"interrupted-stream-{uuid4().hex}.json",
            {
                "error_type": type(error).__name__,
                "usage_complete": False,
                "chunks": [chunk.model_dump() for chunk in chunks],
            },
        )
        raise
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
