"""Memory tools: remember, recall, forget.

Saving a memory counts as a "write": in trusted mode it runs without asking,
except after JARVIS has read a web page or outside file, when it asks. That
stops a page planting false "facts" for later.
"""

from __future__ import annotations

from jarvis.core.tools import AUTO, CONFIRM, ToolContext, ToolResult, tool
from jarvis.memory.store import KINDS


@tool(
    name="remember",
    description=(
        "Save a lasting fact for future conversations: the user's preferences, people in their life, their "
        "projects, or other durable facts. Write one self-contained sentence. Do not save passwords, keys, "
        "one-off details of the current task, or anything that came from a web page or document."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "One self-contained sentence, e.g. 'The user's sister is called Layla.'"},
            "kind": {"type": "string", "enum": list(KINDS)},
        },
        "required": ["text", "kind"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    describe=lambda a, c: f"Remember ({a.get('kind', 'fact')}): {a['text']}",
)
def remember(args: dict, ctx: ToolContext) -> ToolResult:
    memory_id = ctx.memory.remember(args["text"], args["kind"])
    return ToolResult(f"Remembered as #{memory_id}.")


@tool(
    name="recall",
    description=(
        "Search long-term memory: saved facts, and past conversations with the user. Use it when the user refers "
        "to something from before that is not in the current conversation."
    ),
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look for."}},
        "required": ["query"],
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Search memory for: {a['query']}",
)
def recall(args: dict, ctx: ToolContext) -> ToolResult:
    facts = ctx.memory.search(args["query"], limit=8)
    past = ctx.memory.search_exchanges(args["query"])
    lines = []
    if facts:
        lines.append("Saved facts:")
        lines += [f"  #{m['id']} [{m['kind']}] {m['text']}" for m in facts]
    if past:
        lines.append("Past conversations:")
        for e in past:
            lines.append(f"  {e['time'][:16].replace('T', ' ')}  User: {e['user_text'][:300]}")
            lines.append(f"                    JARVIS: {e['reply_text'][:500]}")
    return ToolResult("\n".join(lines) or "Nothing relevant is remembered.")


@tool(
    name="forget",
    description="Delete one saved memory by its number (from recall, or shown in the remembered context).",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "integer", "minimum": 1}},
        "required": ["id"],
        "additionalProperties": False,
    },
    tier=CONFIRM,
    kind="delete",
    describe=lambda a, c: "Forget memory #%d: %s" % (
        a["id"],
        next((m["text"] for m in c.memory.all() if m["id"] == a["id"]), "(no such memory)"),
    ),
)
def forget(args: dict, ctx: ToolContext) -> ToolResult:
    if ctx.memory.forget(args["id"]):
        return ToolResult(f"Forgot memory #{args['id']}.")
    return ToolResult(f"There is no memory #{args['id']}.", is_error=True)
