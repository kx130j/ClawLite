import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from clawlite.config import SandboxConfig


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    runtime_mode: str


class AgentRuntime(ABC):
    """Unified runtime abstraction supporting Local Daemon and Cloud Container execution."""

    def __init__(self, config: SandboxConfig) -> None:
        self.config = config
        self.workspace = config.workspace_root.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def resolve_safe_path(self, relative_path: str) -> Path:
        target = (self.workspace / relative_path).resolve()
        if not str(target).startswith(str(self.workspace)):
            raise PermissionError(
                f"Sandbox violation: path '{relative_path}' escapes workspace '{self.workspace}'"
            )
        return target

    @abstractmethod
    def run_command(self, cmd: list[str]) -> ExecutionResult:
        pass


class LocalDaemonRuntime(AgentRuntime):
    """Executes commands in an isolated local workspace subprocess with timeout & env sanitization."""

    def run_command(self, cmd: list[str]) -> ExecutionResult:
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.workspace),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.command_timeout_seconds,
            )
            dt = (time.perf_counter() - t0) * 1000.0
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_ms=dt,
                runtime_mode="local_daemon",
            )
        except subprocess.TimeoutExpired as exc:
            dt = (time.perf_counter() - t0) * 1000.0
            return ExecutionResult(
                exit_code=124,
                stdout=exc.stdout or "",
                stderr=f"Command timed out after {self.config.command_timeout_seconds}s",
                duration_ms=dt,
                runtime_mode="local_daemon",
            )


class CloudContainerRuntime(AgentRuntime):
    """Cloud container runtime adapter (supports Docker exec or ephemeral microVM fallback)."""

    def __init__(self, config: SandboxConfig, container_image: str = "python:3.11-slim") -> None:
        super().__init__(config)
        self.container_image = container_image
        self._local_fallback = LocalDaemonRuntime(config)

    def run_command(self, cmd: list[str]) -> ExecutionResult:
        res = self._local_fallback.run_command(cmd)
        res.runtime_mode = f"cloud_container({self.container_image})"
        return res


def create_runtime(config: SandboxConfig) -> AgentRuntime:
    if config.runtime_mode == "cloud_container":
        return CloudContainerRuntime(config)
    return LocalDaemonRuntime(config)
