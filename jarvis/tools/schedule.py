"""Scheduling tools: reminders and recurring tasks.

Creating a scheduled item counts as a "write": automatic in trusted mode,
but it asks if JARVIS has just read a web page or email, so that hidden
instructions cannot plant a task that runs later when nobody is watching.
"""

from __future__ import annotations

from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool
from jarvis.scheduler.store import DAYS, describe_when, format_items


def _schedule(ctx: ToolContext):
    if ctx.schedule is None:
        raise RuntimeError("Scheduling is only available in the JARVIS window, not in terminal chat.")
    return ctx.schedule


def _describe(args: dict, ctx: ToolContext) -> str:
    when = f"once at {args['at']}" if args.get("at") else f"at {args.get('daily_at')} " + (
        "on " + ", ".join(args["days"]) if args.get("days") else "every day"
    )
    what = "Remind you" if args.get("kind") == "reminder" else "Carry out this request unattended"
    return f"Schedule '{args.get('title')}' ({when}).\n{what}:\n\n{args.get('text')}"


@tool(
    name="schedule_add",
    description=(
        "Schedule something for later. kind 'reminder' simply tells the user 'text' at the time. kind 'task' "
        "carries out 'text' as a request at the time (for example a daily briefing). Give either 'at' for a "
        "single date and time, or 'daily_at' for a repeating time of day, optionally limited to certain 'days'. "
        "Times are the user's local time; work them out from <current_time>."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short name, e.g. 'Call Layla'."},
            "kind": {"type": "string", "enum": ["reminder", "task"]},
            "text": {"type": "string", "description": "For a reminder: what to say. For a task: the request to carry out."},
            "at": {"type": "string", "description": "One-off: ISO date and time, e.g. 2026-11-13T18:00."},
            "daily_at": {"type": "string", "description": "Repeating: time of day as HH:MM, e.g. 08:00."},
            "days": {"type": "array", "items": {"type": "string", "enum": list(DAYS)}, "description": "With daily_at: only on these days."},
        },
        "required": ["title", "kind", "text"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    describe=_describe,
)
def schedule_add(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        item = _schedule(ctx).add(args["title"], args["kind"], args["text"], args.get("at"), args.get("daily_at"), args.get("days"))
    except (ValueError, RuntimeError) as exc:
        return ToolResult(str(exc), is_error=True)
    return ToolResult(f"Scheduled #{item['id']} '{item['title']}': {describe_when(item)}.")


@tool(
    name="schedule_list",
    description="List everything that is scheduled: reminders, recurring tasks and the morning briefing.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: "List what is scheduled",
)
def schedule_list(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        return ToolResult(format_items(_schedule(ctx).items()))
    except RuntimeError as exc:
        return ToolResult(str(exc), is_error=True)


@tool(
    name="schedule_remove",
    description="Cancel a scheduled item by its number (from schedule_list).",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "integer", "minimum": 1}},
        "required": ["id"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    describe=lambda a, c: f"Cancel scheduled item #{a['id']}",
)
def schedule_remove(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        removed = _schedule(ctx).remove(args["id"])
    except RuntimeError as exc:
        return ToolResult(str(exc), is_error=True)
    return ToolResult(f"Cancelled #{args['id']}." if removed else f"There is no scheduled item #{args['id']}.", is_error=not removed)
