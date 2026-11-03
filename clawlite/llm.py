import json
import time
import urllib.error
import urllib.request
from typing import Any

from clawlite.config import LLMConfig
from clawlite.telemetry import TelemetryTracer


class LLMClient:
    """OpenAI-compatible LLM Client with prefix-cache telemetry and exponential backoff."""

    def __init__(self, config: LLMConfig, tracer: TelemetryTracer) -> None:
        self.config = config
        self.tracer = tracer

    def chat(
        self,
        actor: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        target_model = model or self.config.orchestrator_model
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_err: Exception | None = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    raw_data = resp.read().decode("utf-8")
                dt = (time.perf_counter() - t0) * 1000.0
                data = json.loads(raw_data)
                usage = data.get("usage") or {}
                self.tracer.record_llm_usage(
                    actor=actor, usage=usage, duration_ms=dt, model=target_model
                )
                raw_msg = data["choices"][0]["message"]
                clean_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": raw_msg.get("content") or "",
                }
                if raw_msg.get("tool_calls"):
                    clean_msg["tool_calls"] = raw_msg["tool_calls"]
                t_names = [tc["function"]["name"] for tc in clean_msg.get("tool_calls", [])]
                print(
                    f"   ⚡ [{actor}] LLM ({target_model}) responded in {dt:.0f}ms "
                    f"| tools={t_names or 'final_text'}",
                    flush=True,
                )
                return clean_msg
            except Exception as exc:
                last_err = exc
                time.sleep(0.8 * (attempt + 1))

        raise RuntimeError(f"LLM API call failed after 3 attempts: {last_err}")
