import json
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import ClassVar

from harnesslab.benchmark_runner import run_benchmark_experiment
from harnesslab.config import load_benchmark_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "configs/benchmark-openai-compatible.example.yaml"


class ChatCompletionsHandler(BaseHTTPRequestHandler):
    response_content: ClassVar[str]
    requests: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.requests.append(request)
        body = json.dumps(
            {
                "id": "chatcmpl-harnesslab-test",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": request["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": self.response_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 111,
                    "completion_tokens": 37,
                    "total_tokens": 148,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_real_openai_compatible_http_path_validates_private_oracle(tmp_path: Path) -> None:
    loaded = load_benchmark_experiment(CONFIG)
    case = loaded.cases[0]
    ChatCompletionsHandler.response_content = json.dumps(
        case.evaluation.reference_submission,
        ensure_ascii=False,
    )
    ChatCompletionsHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ChatCompletionsHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        model = loaded.config.harness.model.model_copy(
            update={"base_url": f"http://localhost:{server.server_port}/v1"}
        )
        harness = loaded.config.harness.model_copy(update={"model": model})
        config = loaded.config.model_copy(update={"harness": harness})
        selected = replace(loaded, config=config, cases=(case,))

        result = run_benchmark_experiment(selected, output_root=tmp_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.summary.total_runs == 1
    assert result.summary.successful_runs == 1
    assert result.runs[0].metrics.input_tokens == 111
    assert result.runs[0].metrics.output_tokens == 37
    assert len(ChatCompletionsHandler.requests) == 1
    request = ChatCompletionsHandler.requests[0]
    assert request["model"] == "replace-with-served-model-name"
    assert request["seed"] == 42
    serialized_messages = json.dumps(request["messages"], ensure_ascii=False)
    assert "reference_submission" not in serialized_messages
    assert "validators" not in serialized_messages
