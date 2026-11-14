import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from harnesslab.coding.deepseek_adapter import (
    MultimodalChatDeepSeek,
    aliyun_deepseek_profile,
    relocate_tool_images,
)


@pytest.mark.parametrize("kind", ["image", "image_url"])
def test_images_survive_real_sdk_serialization_after_parallel_tool_results(kind):
    block = (
        {"type": "image", "base64": "aGVsbG8=", "mime_type": "image/png"}
        if kind == "image"
        else {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    )
    messages = [
        HumanMessage(content="inspect"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_file", "args": {}, "id": "image"},
                {"name": "execute", "args": {}, "id": "text"},
            ],
        ),
        ToolMessage(
            content=[{"type": "text", "text": "file contents"}, block],
            tool_call_id="image",
            additional_kwargs={"read_file_path": "/app/example.png"},
        ),
        ToolMessage(content="done", tool_call_id="text"),
    ]
    before = [message.model_dump() for message in messages]
    recorded = []

    def handler(request):
        recorded.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-v4.1-flash-1017",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "observed",
                            "reasoning_content": "reason",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    model = MultimodalChatDeepSeek(
        model="deepseek-v4.1-flash-1017",
        api_key="fixture",
        api_base="https://fixture.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = model.invoke(messages)
    wire = recorded[0]["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "tool", "user"]
    assert "aGVsbG8=" not in wire[2]["content"]
    assert wire[-1]["content"][-1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
    assert response.additional_kwargs["reasoning_content"] == "reason"
    assert response.usage_metadata["input_tokens"] == 100
    assert [message.model_dump() for message in messages] == before


def test_text_tool_json_is_preserved_and_images_do_not_cross_assistant_turns():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}
    messages = [
        ToolMessage(content=[image], tool_call_id="one"),
        AIMessage(content="next"),
        ToolMessage(
            content=[{"type": "text", "text": "literal data:image/png;base64,eA=="}],
            tool_call_id="two",
        ),
    ]
    result = relocate_tool_images(messages)
    assert [type(m).__name__ for m in result] == [
        "ToolMessage",
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    assert result[-1] is messages[-1]
    assert result[1].content[-1] == image


@pytest.mark.parametrize(
    "window,expected", [(1_048_576, 1_000_000), (1000, 1000), (None, 1_000_000)]
)
def test_provider_input_ceiling_and_media_capabilities(window, expected):
    profile = aliyun_deepseek_profile(window, 393216)
    assert profile["max_input_tokens"] == expected and profile["max_output_tokens"] == 393216
    assert profile["image_inputs"] and profile["image_tool_message"]
    assert not profile["audio_inputs"] and not profile["video_inputs"] and not profile["pdf_inputs"]
