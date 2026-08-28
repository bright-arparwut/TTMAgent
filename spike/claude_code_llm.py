"""PROTOTYPE (ticket #16) -- Claude Code headless as LightRAG's EXTRACT role.

EXTRACT is a batch job, so it can run on any backend (map #9 Notes). This
shells out to the `claude` binary per extraction call.

Config is stripped (`--system-prompt` replacing Claude Code's agent preamble,
no settings, no MCP, no tools) because the preamble is the dominant cost: a
two-word prompt measured 65k tokens / $0.24 on the default config, 28k / $0.17
stripped. Every call pays that floor regardless of payload.

The binary is invoked by absolute path so the user's shell alias -- which
carries --dangerously-skip-permissions -- is never picked up.
"""

import asyncio
import json
import os
import shutil

_SEARCH_PATH = "/opt/homebrew/bin:/usr/local/bin"
CLAUDE_BIN = (
    shutil.which("claude", path=_SEARCH_PATH)
    # Not a Mac (ticket #30 indexed from a Linux container): fall back to the
    # environment PATH -- shutil.which never resolves shell aliases, so the
    # --dangerously-skip-permissions alias this guard exists for stays unseen.
    or shutil.which("claude")
    or "/opt/homebrew/bin/claude"
)

# Run outside the repo so no CLAUDE.md is discovered and pulled into the prompt.
NEUTRAL_CWD = "/tmp"

DEFAULT_SYSTEM_PROMPT = (
    "You are a precise information-extraction engine. Follow the user's output "
    "format exactly. Emit only the requested output, with no preamble, no "
    "commentary, and no code fences."
)


class CostMeter:
    """Running total of what this backend actually cost, for the results file."""

    def __init__(self) -> None:
        self.calls = 0
        self.cost_usd = 0.0
        self.duration_ms = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0
        self.output_tokens = 0
        self.failures = 0

    def record(self, payload: dict) -> None:
        self.calls += 1
        self.cost_usd += payload.get("total_cost_usd") or 0.0
        self.duration_ms += payload.get("duration_ms") or 0
        usage = payload.get("usage") or {}
        self.cache_creation_tokens += usage.get("cache_creation_input_tokens") or 0
        self.cache_read_tokens += usage.get("cache_read_input_tokens") or 0
        self.output_tokens += usage.get("output_tokens") or 0

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "cost_usd": round(self.cost_usd, 4),
            "wall_seconds_summed": round(self.duration_ms / 1000, 1),
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "output_tokens": self.output_tokens,
        }


METER = CostMeter()


def build_claude_code_llm(model: str = "sonnet", timeout: int = 300):
    """An async func with LightRAG's role signature, backed by `claude -p`."""

    async def claude_code_llm(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict] | None = None,
        **kwargs,
    ) -> str:
        # LightRAG's extract prompt is delimiter-based, not JSON. Only the
        # keyword role asks for JSON, and that role stays on Gemini -- but
        # guard anyway rather than silently emitting prose.
        response_format = kwargs.get("response_format")
        wants_json = bool(response_format) or bool(kwargs.get("keyword_extraction"))

        system = system_prompt or DEFAULT_SYSTEM_PROMPT
        if wants_json:
            system += "\n\nRespond with raw JSON only. No markdown fence, no prose."

        # History is prepended as plain text: `claude -p` is single-shot and has
        # no message-array input. Extraction gleaning passes history this way.
        parts: list[str] = []
        for turn in history_messages or []:
            role = turn.get("role", "user").upper()
            parts.append(f"[{role}]\n{turn.get('content', '')}")
        parts.append(prompt)
        full_prompt = "\n\n".join(parts)

        argv = [
            CLAUDE_BIN,
            "-p",
            "--model", model,
            "--output-format", "json",
            "--allowedTools", "",
            "--max-turns", "1",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--system-prompt", system,
        ]

        env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=NEUTRAL_CWD,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(full_prompt.encode()), timeout=timeout
            )
        except TimeoutError as err:
            proc.kill()
            METER.failures += 1
            raise RuntimeError(f"claude -p timed out after {timeout}s") from err

        if proc.returncode != 0:
            METER.failures += 1
            raise RuntimeError(
                f"claude -p exited {proc.returncode}: {stderr.decode()[:400]}"
            )

        payload = json.loads(stdout.decode())
        METER.record(payload)
        if payload.get("is_error"):
            METER.failures += 1
            raise RuntimeError(f"claude -p reported error: {payload.get('result')!r}")
        return payload.get("result", "")

    return claude_code_llm
