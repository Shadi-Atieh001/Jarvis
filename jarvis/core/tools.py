"""Tool definitions and the plugin loader.

A tool is one Python function plus a little metadata. To add a tool, drop a
file in jarvis/tools/ that uses the @tool decorator; it is picked up at the
next start. See jarvis/tools/files.py for worked examples.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .config import Settings
    from .killswitch import KillSwitch

AUTO, CONFIRM, BLOCKED = "auto", "confirm", "blocked"
TIER_ORDER = {AUTO: 0, CONFIRM: 1, BLOCKED: 2}
KINDS = ("", "read", "launch", "write", "execute", "control", "delete", "send")


def stricter(a: str, b: str) -> str:
    return a if TIER_ORDER[a] >= TIER_ORDER[b] else b


@dataclass
class ToolContext:
    """What every tool function receives alongside its arguments."""

    settings: "Settings"
    kill: "KillSwitch"
    memory: Any = None  # the MemoryStore, for the memory tools
    schedule: Any = None  # the Schedule, for the scheduling tools (window only)
    browser: Any = None  # the link to the Chrome extension, for the browser tools

    @property
    def workspace(self) -> Path:
        return self.settings.workspace

    def resolve(self, path: str) -> Path:
        """Turn a path from the model into an absolute one. Relative paths are
        taken relative to the workspace. Symlinks and '..' are resolved so a
        path cannot pretend to be inside the workspace when it is not."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    def in_workspace(self, path: Path) -> bool:
        return path == self.workspace or self.workspace in path.parents


@dataclass
class ToolResult:
    text: str
    is_error: bool = False
    # Set when the text came from somewhere JARVIS does not control (a file's
    # contents, command output, later: web pages and email). The agent wraps
    # such text so the model treats it as data, never as instructions.
    untrusted_source: str | None = None
    # True if, after seeing this, later actions in the same request should
    # need confirmation (see confirm_after_untrusted in settings.toml).
    taints: bool = False


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[[dict, ToolContext], ToolResult | str]
    tier: str | None = None  # None means: use [permissions] default
    read_only: bool = False
    # What sort of action this is. The permission mode in settings.toml
    # decides how each kind is treated:
    #   read     looks at something, changes nothing
    #   launch   opens an app or a web page for you to look at
    #   write    creates or changes files
    #   execute  runs commands or code
    #   control  moves the mouse or types for you
    #   delete   removes something
    #   send     sends or posts something to other people
    # Leave empty for a tool that should always follow its own tier.
    kind: str = ""
    # Optional: (args, ctx) -> tier, (tier, why) or (tier, why, "strict").
    # May only make a call stricter. "strict" ones apply in trusted mode too.
    escalate: Callable[[dict, ToolContext], str | None] | None = None
    # Optional: (args, ctx) -> text shown to the user when asking permission.
    describe: Callable[[dict, ToolContext], str] | None = None
    # Optional: (args, ctx) -> text checked against the blocked patterns.
    blockable_text: Callable[[dict], str] | None = None
    # True for tools that decide for themselves what is safe after untrusted
    # content has been read (the browser tools, which use approved sites).
    own_trust_rules: bool = False

    def api_definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            # Streams large inputs (file contents) as they are generated. The
            # agent validates every input against the schema before running.
            "eager_input_streaming": True,
        }


def tool(
    *,
    name: str,
    description: str,
    input_schema: dict,
    tier: str | None = None,
    read_only: bool = False,
    kind: str = "",
    escalate=None,
    describe=None,
    blockable_text=None,
    own_trust_rules: bool = False,
):
    """Register a function as a JARVIS tool."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r} for tool {name}")
    if tier is not None and tier not in TIER_ORDER:
        raise ValueError(f"Unknown tier {tier!r} for tool {name}")

    def decorator(func):
        # The loader finds tools by looking for this attribute.
        func.jarvis_tool = Tool(
            name, description, input_schema, func, tier, read_only, kind, escalate, describe, blockable_text,
            own_trust_rules,
        )
        return func

    return decorator


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, t: Tool) -> None:
        if t.name in self.tools:
            raise ValueError(f"Two tools are both named {t.name!r}")
        self.tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def api_definitions(self) -> list[dict]:
        # Sorted so the list is identical on every request (keeps the
        # prompt cache valid and the conversation history consistent).
        return [self.tools[n].api_definition() for n in sorted(self.tools)]


def load_tools(package: str = "jarvis.tools") -> ToolRegistry:
    """Import every module in the tools package and collect its tools."""
    registry = ToolRegistry()
    pkg = importlib.import_module(package)
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        for obj in vars(module).values():
            found = getattr(obj, "jarvis_tool", None)
            # Skip tools merely imported from another module.
            if isinstance(found, Tool) and getattr(obj, "__module__", None) == module.__name__:
                registry.add(found)
    return registry
