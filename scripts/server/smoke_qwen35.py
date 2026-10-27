"""Require real automatic tool calls and both structured-output strategies."""

import json
from pathlib import Path

from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-required", max_retries=0)
tool = {
    "type": "function",
    "function": {
        "name": "lookup_value",
        "description": "Look up a value.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}
common = {
    "model": "Qwen3.5-9B",
    "temperature": 0,
    "max_tokens": 1024,
    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
}
response = client.chat.completions.create(
    **common,
    messages=[{"role": "user", "content": "Call lookup_value with key=alpha. Use the tool."}],
    tools=[tool],
    tool_choice="auto",
)
message = response.choices[0].message
assert message.tool_calls and message.tool_calls[0].function.name == "lookup_value", response
assert json.loads(message.tool_calls[0].function.arguments) == {"key": "alpha"}, response
schema = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}},
    "required": ["passed"],
    "additionalProperties": False,
}
structured = client.chat.completions.create(
    **common,
    messages=[{"role": "user", "content": "Return passed=true."}],
    response_format={
        "type": "json_schema",
        "json_schema": {"name": "SmokeVerdict", "schema": schema},
    },
)
assert json.loads(structured.choices[0].message.content) == {"passed": True}, structured
report = {
    "automatic_tool_call": True,
    "structured_output": True,
    "tool_response": response.model_dump(mode="json"),
    "structured_response": structured.model_dump(mode="json"),
}
Path("/mnt/harnesslab-data/runtime/model-smoke.json").write_text(json.dumps(report, indent=2))
print("MODEL_SMOKE_PASSED", flush=True)
