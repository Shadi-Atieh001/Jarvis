"""Run shell commands.

Every command asks for confirmation by default. A command that starts in the
workspace can still reach the whole machine, so there is no safe way to wave
some commands through automatically.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from jarvis.core.killswitch import Stopped, kill_tree
from jarvis.core.tools import CONFIRM, ToolContext, ToolResult, tool

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
MAX_OUTPUT = 30_000


def shell_argv(command: str) -> list[str]:
    if sys.platform == "win32":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-c", command]


def run_process(argv: list[str], cwd, timeout: int, ctx: ToolContext) -> ToolResult:
    """Run a process to completion, killing it on timeout or emergency stop.
    Shared with the code tool."""
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True  # own group, so the whole tree can be killed

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    ctx.kill.register(proc)

    # Read output on a helper thread so a chatty process cannot block us.
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()), daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        while proc.poll() is None:
            if ctx.kill.tripped:
                kill_tree(proc)
                raise Stopped()
            if time.monotonic() > deadline:
                timed_out = True
                kill_tree(proc)
                break
            time.sleep(0.05)
    finally:
        ctx.kill.unregister(proc)
    if ctx.kill.tripped:  # the stop may have killed it before we noticed
        raise Stopped()
    reader.join(timeout=5)

    output = "".join(chunks)
    if len(output) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        output = output[:half] + f"\n[... {len(output) - MAX_OUTPUT} characters cut ...]\n" + output[-half:]
    if timed_out:
        return ToolResult(f"Timed out after {timeout}s and was killed.\n{output}", is_error=True, untrusted_source="command output")
    status = f"[exit code {proc.returncode}]"
    return ToolResult(
        f"{output.rstrip()}\n{status}".strip(),
        is_error=proc.returncode != 0,
        untrusted_source="command output",
    )


@tool(
    name="run_command",
    description=(
        "Run a shell command and return its output. Runs in PowerShell on Windows, sh on macOS and Linux. "
        "The working directory defaults to the workspace. Not for interactive programs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "Working directory. Defaults to the workspace."},
            "timeout": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT, "description": f"Seconds. Default {DEFAULT_TIMEOUT}."},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    tier=CONFIRM,
    describe=lambda a, c: f"Run this command in {c.resolve(a.get('cwd') or '.')}:\n\n{a['command']}",
    blockable_text=lambda a, c: a["command"],
)
def run_command(args: dict, ctx: ToolContext) -> ToolResult:
    cwd = ctx.resolve(args.get("cwd") or ".")
    if not cwd.is_dir():
        return ToolResult(f"No such directory: {cwd}", is_error=True)
    return run_process(shell_argv(args["command"]), cwd, args.get("timeout", DEFAULT_TIMEOUT), ctx)
