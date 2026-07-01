import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class CodexChatClient:
    """OpenAI-chat-compatible wrapper backed by local Codex CLI."""

    def __init__(
        self,
        *,
        codex_exe: str | None = None,
        cwd: str | None = None,
        model_name: str | None = None,
        sandbox: str = "read-only",
        timeout_sec: int = 1800,
        ignore_user_config: bool = True,
    ):
        self.codex_exe = codex_exe or discover_codex_exe()
        self.cwd = cwd or os.getcwd()
        self.model_name = model_name
        self.sandbox = sandbox
        self.timeout_sec = timeout_sec
        self.ignore_user_config = ignore_user_config
        self.chat = SimpleNamespace(completions=_CodexCompletions(self))


class _CodexCompletions:
    def __init__(self, owner: CodexChatClient):
        self.owner = owner

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        **_: Any,
    ):
        del model, response_format, temperature, max_tokens

        with tempfile.TemporaryDirectory(prefix="dv_codex_") as tmpdir:
            output_path = Path(tmpdir) / "response.txt"
            prompt = build_codex_prompt(messages)
            cmd = [self.owner.codex_exe, "exec"]
            if self.owner.ignore_user_config:
                cmd.append("--ignore-user-config")
            cmd.extend(["--cd", self.owner.cwd, "--sandbox", self.owner.sandbox])
            if self.owner.model_name:
                cmd.extend(["--model", self.owner.model_name])
            cmd.extend(["--output-last-message", str(output_path), "-"])

            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.owner.timeout_sec,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Codex CLI 调用失败\n"
                    f"returncode={result.returncode}\n"
                    f"stdout={result.stdout[-4000:]}\n"
                    f"stderr={result.stderr[-4000:]}"
                )
            if not output_path.exists():
                raise RuntimeError(
                    "Codex CLI 未生成 --output-last-message 文件\n"
                    f"stdout={result.stdout[-4000:]}\n"
                    f"stderr={result.stderr[-4000:]}"
                )

            content = normalize_json_response(output_path.read_text(encoding="utf-8"))
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )


def build_codex_prompt(messages: list[dict[str, str]]) -> str:
    rendered = []
    for message in messages:
        role = message.get("role", "user").upper()
        content = message.get("content", "")
        rendered.append(f"【{role}】\n{content}")

    return (
        "你是 dv-spec2testplan-agent 的本地 Codex CLI 大模型后端。\n"
        "严格要求：只完成下面给定的 JSON 生成任务；不要修改仓库文件；不要运行 shell 命令；"
        "最终回复必须是一个 JSON 对象，不要输出 Markdown、解释文字或代码块。\n\n"
        + "\n\n".join(rendered)
    )


def normalize_json_response(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    start = content.find("{")
    if start == -1:
        raise ValueError(f"Codex 输出不是 JSON 对象: {content[:500]}")

    decoder = json.JSONDecoder()
    parsed, end = decoder.raw_decode(content[start:])
    if not isinstance(parsed, dict):
        raise ValueError("Codex 输出 JSON 顶层不是对象")
    return content[start:start + end]


def discover_codex_exe() -> str:
    configured = os.getenv("DV_CODEX_EXE")
    if configured and Path(configured).exists():
        return configured

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if candidate.exists():
            return str(candidate)

    which_codex = shutil.which("codex")
    if which_codex:
        return which_codex

    raise FileNotFoundError("找不到 Codex CLI。请确认 Codex 已安装，或设置 DV_CODEX_EXE。")
