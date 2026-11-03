import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv_if_present()


@dataclass
class LLMConfig:
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "CLAWLITE_BASE_URL", "https://discovery-api.intern-ai.org.cn/v1"
        )
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("CLAWLITE_API_KEY", "")
    )
    orchestrator_model: str = field(
        default_factory=lambda: os.getenv(
            "CLAWLITE_ORCHESTRATOR_MODEL", "Atria-Dawn"
        )
    )
    subagent_model: str = field(
        default_factory=lambda: os.getenv(
            "CLAWLITE_SUBAGENT_MODEL", "qwen3.8-27b"
        )
    )
    temperature: float = 0.1
    timeout_seconds: int = 90


@dataclass
class SandboxConfig:
    runtime_mode: str = "local_daemon"  # "local_daemon" | "cloud_container"
    workspace_root: Path = field(default_factory=lambda: Path.cwd())
    max_output_chars: int = 3500
    command_timeout_seconds: int = 15
    blocked_patterns: list[str] = field(
        default_factory=lambda: [
            "rm -rf",
            "del /f /s /q",
            "format ",
            "DROP TABLE",
            "SHUTDOWN",
            ".env.production",
            "/etc/shadow",
        ]
    )


@dataclass
class ClawLiteConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    max_orchestrator_steps: int = 10
    max_subagent_steps: int = 5
    max_verification_retries: int = 3
    context_compaction_threshold_chars: int = 12000
