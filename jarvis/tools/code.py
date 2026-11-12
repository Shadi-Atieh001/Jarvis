"""Run Python scripts in the workspace.

"Sandboxed" here means: scripts live in the workspace folder, run with the
workspace as their working directory, and are killed on timeout or emergency
stop. It is NOT an isolated virtual machine; a script can still do anything
your user account can. That is why running one asks for confirmation by
default, with the code shown to you first.
"""

from __future__ import annotations

import sys
from datetime import datetime

from jarvis.core.tools import CONFIRM, ToolContext, ToolResult, tool
from jarvis.tools.shell import MAX_TIMEOUT, run_process

DEFAULT_TIMEOUT = 120


def _script_text(args: dict, ctx: ToolContext) -> str:
    if args.get("code") is not None:
        return args["code"]
    path = ctx.resolve(args.get("path") or "")
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _describe(args: dict, ctx: ToolContext) -> str:
    code = _script_text(args, ctx)
    lines = code.splitlines()
    shown = "\n".join(lines[:60]) + (f"\n... {len(lines) - 60} more lines" if len(lines) > 60 else "")
    what = f"the script {ctx.resolve(args['path'])}" if args.get("path") else "this Python code"
    extra = f" with arguments {args['args']}" if args.get("args") else ""
    return f"Run {what}{extra} in the workspace:\n\n{shown}"


@tool(
    name="run_python",
    description=(
        "Run Python in the workspace and return its output. Give either 'path' (a script inside the workspace) "
        "or 'code' (saved to the workspace's scratch folder, then run). Use this to write, test and debug scripts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Script to run. Must be inside the workspace."},
            "code": {"type": "string", "description": "Python source to run instead of a file."},
            "args": {"type": "array", "items": {"type": "string"}, "description": "Command-line arguments."},
            "timeout": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT, "description": f"Seconds. Default {DEFAULT_TIMEOUT}."},
        },
        "additionalProperties": False,
    },
    tier=CONFIRM,
    kind="execute",
    describe=_describe,
    blockable_text=_script_text,
)
def run_python(args: dict, ctx: ToolContext) -> ToolResult:
    if (args.get("path") is None) == (args.get("code") is None):
        return ToolResult("Give exactly one of 'path' or 'code'.", is_error=True)

    if args.get("code") is not None:
        scratch = ctx.workspace / "scratch"
        scratch.mkdir(exist_ok=True)
        script = scratch / f"run_{datetime.now():%Y%m%d_%H%M%S_%f}.py"
        script.write_text(args["code"], encoding="utf-8")
    else:
        script = ctx.resolve(args["path"])
        if not ctx.in_workspace(script):
            return ToolResult(f"{script} is outside the workspace. Copy it in first, or use run_command.", is_error=True)
        if not script.is_file():
            return ToolResult(f"No such file: {script}", is_error=True)

    argv = [sys.executable, str(script), *args.get("args", [])]
    return run_process(argv, ctx.workspace, args.get("timeout", DEFAULT_TIMEOUT), ctx)
