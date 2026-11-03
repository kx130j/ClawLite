import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpanEvent:
    span_id: str
    actor: str  # e.g., "gateway", "orchestrator", "subagent:recon", "mcp:devops", "verifier"
    event_type: str  # "llm_call", "tool_call", "hook_intercept", "verification", "compaction"
    duration_ms: float
    status: str  # "ok", "blocked", "error", "failed_check"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class TokenMetrics:
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    subagent_isolated_tokens: int = 0
    compactions_triggered: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit_rate(self) -> float:
        if self.prompt_tokens == 0:
            return 0.0
        return round((self.cached_tokens / self.prompt_tokens) * 100.0, 2)


class TelemetryTracer:
    """Tracks full Agent execution spans, token economics, and Prompt Cache efficiency."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.spans: list[SpanEvent] = []
        self.tokens = TokenMetrics()
        self._counter = 0

    def record_span(
        self,
        actor: str,
        event_type: str,
        duration_ms: float,
        status: str = "ok",
        **metadata: Any,
    ) -> SpanEvent:
        self._counter += 1
        span = SpanEvent(
            span_id=f"{self.session_id}-span-{self._counter:03d}",
            actor=actor,
            event_type=event_type,
            duration_ms=round(duration_ms, 2),
            status=status,
            metadata=metadata,
        )
        self.spans.append(span)
        return span

    def record_llm_usage(
        self, actor: str, usage: dict[str, Any], duration_ms: float, model: str
    ) -> None:
        p_tokens = int(usage.get("prompt_tokens", 0))
        c_tokens = int(usage.get("completion_tokens", 0))
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or 0)

        self.tokens.llm_calls += 1
        self.tokens.prompt_tokens += p_tokens
        self.tokens.completion_tokens += c_tokens
        self.tokens.cached_tokens += cached
        if actor.startswith("subagent:"):
            self.tokens.subagent_isolated_tokens += p_tokens + c_tokens

        self.record_span(
            actor=actor,
            event_type="llm_call",
            duration_ms=duration_ms,
            status="ok",
            model=model,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            cached_tokens=cached,
        )

    def summary_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "token_metrics": {
                "llm_calls": self.tokens.llm_calls,
                "prompt_tokens": self.tokens.prompt_tokens,
                "completion_tokens": self.tokens.completion_tokens,
                "total_tokens": self.tokens.total_tokens,
                "cached_tokens": self.tokens.cached_tokens,
                "prompt_cache_hit_rate_pct": self.tokens.cache_hit_rate,
                "subagent_isolated_tokens": self.tokens.subagent_isolated_tokens,
                "compactions_triggered": self.tokens.compactions_triggered,
            },
            "span_count": len(self.spans),
            "spans": [asdict(s) for s in self.spans],
        }

    def export_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.summary_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
