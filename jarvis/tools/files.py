"""File system tools: read, list, search, write, move, delete.

Reading is automatic, except for paths matching [permissions.sensitive].
Creating new files inside the workspace is automatic. Overwriting, deleting,
or touching anything outside the workspace asks first.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
import shutil
from pathlib import Path, PurePosixPath

from jarvis.core.config import find_settings_file
from jarvis.core.tools import AUTO, CONFIRM, ToolContext, ToolResult, tool

SETTINGS_FILE = (find_settings_file() or Path("settings.toml")).resolve()
MAX_READ_BYTES = 400_000
MAX_SEARCH_RESULTS = 200
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "$RECYCLE.BIN"}


def _is_sensitive(path: Path, ctx: ToolContext) -> bool:
    # JARVIS's own settings decide what it may do, so it must not be able
    # to rewrite them without the user seeing.
    if path in (ctx.settings.home / "overrides.json", SETTINGS_FILE):
        return True
    posix = path.as_posix()
    for pattern in ctx.settings.sensitive_paths:
        # Match both the whole path and, for "**/x/**" patterns, the folder itself.
        if PurePosixPath(posix).full_match(pattern, case_sensitive=False) or PurePosixPath(
            posix + "/x"
        ).full_match(pattern, case_sensitive=False):
            return True
    return False


def _escalate_read(key: str = "path"):
    def check(args: dict, ctx: ToolContext):
        if _is_sensitive(ctx.resolve(args.get(key) or "."), ctx):
            return CONFIRM, "this path is on the sensitive list in settings.toml", "strict"
        return None

    return check


def _outside(path: Path, ctx: ToolContext) -> bool:
    return not ctx.in_workspace(path)


# ------------------------------------------------------------------- reading


@tool(
    name="read_file",
    description="Read a text file. Returns its contents with line numbers. Use offset and limit for large files.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Relative paths are inside the workspace."},
            "offset": {"type": "integer", "minimum": 1, "description": "First line to return (1-based)."},
            "limit": {"type": "integer", "minimum": 1, "description": "Maximum number of lines to return."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    escalate=_escalate_read(),
    describe=lambda a, c: f"Read {c.resolve(a['path'])}",
)
def read_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args["path"])
    if not path.is_file():
        return ToolResult(f"No such file: {path}", is_error=True)
    if path.suffix.lower() in (".pdf", ".docx", ".pptx", ".xlsx"):
        return ToolResult(f"{path.name} is a document. Use read_document to read it.", is_error=True)
    if path.stat().st_size > MAX_READ_BYTES and "limit" not in args:
        return ToolResult(
            f"{path} is {path.stat().st_size:,} bytes. Read it in parts with offset and limit, or use search_files.",
            is_error=True,
        )
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        return ToolResult(f"{path} looks like a binary file ({len(raw):,} bytes); not shown.")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    start = args.get("offset", 1) - 1
    chunk = lines[start : start + args["limit"]] if "limit" in args else lines[start:]
    body = "\n".join(f"{start + i + 1:>5}  {line}" for i, line in enumerate(chunk))
    return ToolResult(
        body or "(empty file)",
        untrusted_source=str(path),
        # Files in the workspace are ones JARVIS made or was handed to work
        # on. Files elsewhere could be anything: downloads, attachments.
        taints=_outside(path, ctx),
    )


@tool(
    name="list_dir",
    description="List the files and folders in a directory, with sizes.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path. Defaults to the workspace."}},
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    escalate=_escalate_read(),
    describe=lambda a, c: f"List {c.resolve(a.get('path') or '.')}",
)
def list_dir(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args.get("path") or ".")
    if not path.is_dir():
        return ToolResult(f"No such directory: {path}", is_error=True)
    rows = []
    for entry in sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
        try:
            rows.append(f"{entry.name}/" if entry.is_dir() else f"{entry.name}  ({entry.stat().st_size:,} bytes)")
        except OSError:
            rows.append(f"{entry.name}  (unreadable)")
    listing = "\n".join(rows[:1000]) or "(empty)"
    if len(rows) > 1000:
        listing += f"\n... and {len(rows) - 1000} more"
    return ToolResult(f"{path}\n{listing}", untrusted_source=str(path))


@tool(
    name="search_files",
    description=(
        "Find files by name and optionally by content. 'name' is a glob such as '*.pdf' or 'report*'. "
        "'contains' is a regular expression searched inside text files. Searches subfolders."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder to search. Defaults to the workspace."},
            "name": {"type": "string", "description": "Glob for file names. Defaults to '*'."},
            "contains": {"type": "string", "description": "Regular expression to find inside files."},
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    escalate=_escalate_read(),
    describe=lambda a, c: f"Search {c.resolve(a.get('path') or '.')}",
)
def search_files(args: dict, ctx: ToolContext) -> ToolResult:
    root = ctx.resolve(args.get("path") or ".")
    if not root.is_dir():
        return ToolResult(f"No such directory: {root}", is_error=True)
    name_glob = args.get("name") or "*"
    try:
        pattern = re.compile(args["contains"]) if args.get("contains") else None
    except re.error as exc:
        return ToolResult(f"Invalid regular expression: {exc}", is_error=True)

    hits: list[str] = []
    for dirpath, dirnames, filenames in root.walk():
        ctx.kill.check()
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if not fnmatch.fnmatch(filename.lower(), name_glob.lower()):
                continue
            file = dirpath / filename
            # Never surface the contents of sensitive files through search.
            if _is_sensitive(file, ctx):
                continue
            if pattern is None:
                hits.append(str(file))
            else:
                try:
                    if file.stat().st_size > MAX_READ_BYTES:
                        continue
                    for n, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        if pattern.search(line):
                            hits.append(f"{file}:{n}: {line.strip()[:200]}")
                            if len(hits) >= MAX_SEARCH_RESULTS:
                                break
                except OSError:
                    continue
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
        if len(hits) >= MAX_SEARCH_RESULTS:
            hits.append(f"(stopped at {MAX_SEARCH_RESULTS} results; narrow the search)")
            break
    return ToolResult(
        "\n".join(hits) or "No matches.",
        untrusted_source=str(root),
        taints=pattern is not None and _outside(root, ctx),
    )


# ------------------------------------------------------------------- writing


def _escalate_write(args: dict, ctx: ToolContext):
    path = ctx.resolve(args["path"])
    if _is_sensitive(path, ctx):
        return CONFIRM, "this path is on the sensitive list in settings.toml", "strict"
    if _outside(path, ctx):
        return CONFIRM, "it writes outside the workspace"
    if path.exists():
        return CONFIRM, "it overwrites an existing file"
    return None


def _describe_write(args: dict, ctx: ToolContext) -> str:
    path = ctx.resolve(args["path"])
    new = args["content"]
    if path.is_file():
        old = path.read_text(encoding="utf-8", errors="replace")
        diff = list(
            difflib.unified_diff(old.splitlines(), new.splitlines(), "current", "new", lineterm="", n=2)
        )
        shown = "\n".join(diff[:80]) or "(no change to the text)"
        more = f"\n... {len(diff) - 80} more diff lines" if len(diff) > 80 else ""
        return f"Overwrite {path}\n\n{shown}{more}"
    preview = "\n".join(new.splitlines()[:40])
    more = "\n..." if new.count("\n") >= 40 else ""
    return f"Create {path} ({len(new):,} characters)\n\n{preview}{more}"


@tool(
    name="write_file",
    description="Create a text file, or replace an existing one, with the given content. Parent folders are created.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Relative paths are inside the workspace."},
            "content": {"type": "string", "description": "The complete new contents of the file."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    escalate=_escalate_write,
    describe=_describe_write,
)
def write_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args["path"])
    if path.is_dir():
        return ToolResult(f"{path} is a directory.", is_error=True)
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return ToolResult(f"{'Overwrote' if existed else 'Created'} {path} ({len(args['content']):,} characters).")


@tool(
    name="make_dir",
    description="Create a folder (and any missing parent folders).",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    escalate=lambda a, c: (CONFIRM, "it is outside the workspace") if _outside(c.resolve(a["path"]), c) else None,
    describe=lambda a, c: f"Create the folder {c.resolve(a['path'])}",
)
def make_dir(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args["path"])
    path.mkdir(parents=True, exist_ok=True)
    return ToolResult(f"Folder ready: {path}")


def _escalate_move(args: dict, ctx: ToolContext):
    src, dst = ctx.resolve(args["source"]), ctx.resolve(args["destination"])
    if _outside(src, ctx) or _outside(dst, ctx):
        return CONFIRM, "it moves something outside the workspace"
    if dst.exists():
        return CONFIRM, "the destination already exists"
    return None


@tool(
    name="move_file",
    description="Move or rename a file or folder. Refuses to replace an existing destination unless overwrite is true.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
            "overwrite": {"type": "boolean", "description": "Replace the destination if it exists. Default false."},
        },
        "required": ["source", "destination"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    escalate=_escalate_move,
    describe=lambda a, c: (
        f"Move {c.resolve(a['source'])}\n  to {c.resolve(a['destination'])}"
        + ("\n  REPLACING what is there now" if c.resolve(a["destination"]).exists() and a.get("overwrite") else "")
    ),
)
def move_file(args: dict, ctx: ToolContext) -> ToolResult:
    src, dst = ctx.resolve(args["source"]), ctx.resolve(args["destination"])
    if not src.exists():
        return ToolResult(f"No such file or folder: {src}", is_error=True)
    if src == ctx.workspace:
        return ToolResult("The workspace folder itself cannot be moved.", is_error=True)
    if dst.exists():
        if not args.get("overwrite"):
            return ToolResult(f"{dst} already exists. Pass overwrite=true to replace it.", is_error=True)
        if dst.is_dir():
            return ToolResult(f"{dst} is an existing folder; delete it first if you mean to replace it.", is_error=True)
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return ToolResult(f"Moved {src} to {dst}.")


def _describe_delete(args: dict, ctx: ToolContext) -> str:
    path = ctx.resolve(args["path"])
    if path.is_dir():
        count = sum(1 for p in path.rglob("*") if p.is_file())
        return f"PERMANENTLY delete the folder {path} and the {count} file(s) inside it"
    return f"PERMANENTLY delete the file {path}"


@tool(
    name="delete_file",
    description="Permanently delete a file, or a folder and everything in it (recursive must be true for folders).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "description": "Required to delete a folder that is not empty."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    tier=CONFIRM,
    kind="delete",
    describe=_describe_delete,
)
def delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args["path"])
    if not path.exists():
        return ToolResult(f"No such file or folder: {path}", is_error=True)
    if path == ctx.workspace or path in ctx.workspace.parents or path == Path.home():
        return ToolResult(f"Refusing to delete {path}: it contains the workspace or is your home folder.", is_error=True)
    if path.is_dir():
        if any(path.iterdir()) and not args.get("recursive"):
            return ToolResult(f"{path} is not empty. Pass recursive=true to delete it and its contents.", is_error=True)
        shutil.rmtree(path)
    else:
        path.unlink()
    return ToolResult(f"Deleted {path}.")
