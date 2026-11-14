"""Deliver image tool results as image inputs instead of serialized base64 text."""

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek


def relocate_tool_images(messages):
    """Keep tool acknowledgements together, then attach their images in a user message."""
    result, pending = [], []
    for message in messages:
        if not isinstance(message, ToolMessage) and pending:
            result.append(HumanMessage(content=pending))
            pending = []
        if not isinstance(message, ToolMessage) or not isinstance(message.content, list):
            result.append(message)
            continue
        images, content = [], []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") in ("image", "image_url"):
                images.append(block)
            else:
                content.append(block)
        if not images:
            result.append(message)
            continue
        label = message.additional_kwargs.get("read_file_path") or message.name or "tool output"
        pending.extend(
            [
                {
                    "type": "text",
                    "text": f"Image returned by {label} (tool call {message.tool_call_id}):",
                },
                *images,
            ]
        )
        content.append(
            {
                "type": "text",
                "text": "The tool's image is attached after this group of tool results.",
            }
        )
        result.append(message.model_copy(update={"content": content}))
    if pending:
        result.append(HumanMessage(content=pending))
    return result


def aliyun_deepseek_profile(context_window_tokens, max_output_tokens):
    return {
        "max_input_tokens": min(context_window_tokens or 1_000_000, 1_000_000),
        "max_output_tokens": max_output_tokens,
        "image_inputs": True,
        "image_tool_message": True,
        "audio_inputs": False,
        "video_inputs": False,
        "pdf_inputs": False,
    }


class MultimodalChatDeepSeek(ChatDeepSeek):
    """Preserve ChatDeepSeek reasoning/usage handling and its text tool compatibility."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        return super()._get_request_payload(relocate_tool_images(messages), stop=stop, **kwargs)
