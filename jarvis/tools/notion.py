"""Notion: search, read, create and add to pages.
Connect once with:  python -m jarvis connect notion

Notion only lets an integration see pages you have shared with it: open a
page in Notion, choose "..." > Connections, and add your JARVIS integration.
Sharing a page also shares the pages beneath it.
"""

from __future__ import annotations

import re

from jarvis.core.secrets import SecretsUnavailable
from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool
from jarvis.integrations import tokens
from jarvis.integrations.oauth import ApiError, NotConnected
from jarvis.integrations.tokens import NOTION

API = "https://api.notion.com/v1"
MAX_TEXT = 12_000
_ID_FIELD = {"type": "string", "description": "The page id from notion_search (32 letters and digits)."}


def _guard(func):
    def wrapper(args: dict, ctx: ToolContext):
        for key in ("page_id", "parent_id"):
            if key in args and not re.fullmatch(r"[0-9a-fA-F]{32}", args[key].replace("-", "")):
                return ToolResult("That is not a Notion page id. Use notion_search to find it.", is_error=True)
        try:
            return func(args, ctx)
        except (NotConnected, ApiError, SecretsUnavailable) as exc:
            return ToolResult(str(exc), is_error=True)

    wrapper.__name__ = func.__name__
    wrapper.__module__ = func.__module__
    return wrapper


def _plain(rich_text: list | None) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or [])


def _title(item: dict) -> str:
    if item.get("object") == "database":
        return _plain(item.get("title")) or "(untitled database)"
    for prop in (item.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title")) or "(untitled)"
    return "(untitled)"


_PREFIX = {
    "heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ",
    "numbered_list_item": "1. ", "quote": "> ", "callout": "> ", "toggle": "▸ ",
}


def block_text(block: dict) -> str | None:
    """One Notion block as a line of text, or None if it has none."""
    kind = block.get("type", "")
    data = block.get(kind) or {}
    if kind == "to_do":
        return f"[{'x' if data.get('checked') else ' '}] {_plain(data.get('rich_text'))}"
    if kind == "child_page":
        return f"(sub-page: {data.get('title', '')}, id {block.get('id', '').replace('-', '')})"
    if kind == "code":
        return "```\n" + _plain(data.get("rich_text")) + "\n```"
    if kind == "divider":
        return "---"
    if "rich_text" in data:
        text = _plain(data["rich_text"])
        return _PREFIX.get(kind, "") + text if text or kind == "paragraph" else None
    return None


def to_blocks(content: str) -> list[dict]:
    """Plain text with simple markers -> Notion blocks.
    '# ' '## ' '### ' headings, '- ' bullets, '[ ] ' / '[x] ' to-dos."""
    blocks = []
    for line in content.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        kind, text, extra = "paragraph", line, {}
        for marker, name in (("### ", "heading_3"), ("## ", "heading_2"), ("# ", "heading_1"), ("- ", "bulleted_list_item"), ("* ", "bulleted_list_item")):
            if line.startswith(marker):
                kind, text = name, line[len(marker):]
                break
        else:
            todo = re.match(r"\[( |x|X)\] (.*)", line)
            if todo:
                kind, text, extra = "to_do", todo.group(2), {"checked": todo.group(1) != " "}
        # Notion allows at most 2000 characters in one piece of text.
        pieces = [{"type": "text", "text": {"content": text[i : i + 2000]}} for i in range(0, len(text), 2000)]
        blocks.append({"object": "block", "type": kind, kind: {"rich_text": pieces, **extra}})
    return blocks


def _append(page_id: str, blocks: list[dict]) -> None:
    for i in range(0, len(blocks), 100):  # Notion accepts 100 blocks per request
        tokens.call(NOTION, "PATCH", f"{API}/blocks/{page_id}/children", body={"children": blocks[i : i + 100]})


@tool(
    name="notion_search",
    description="Search the user's Notion pages and databases by title. Returns each one's title and id. An empty query lists recently edited pages.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "additionalProperties": False},
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: f"Search Notion for: {a.get('query') or '(recent pages)'}",
)
@_guard
def notion_search(args: dict, ctx: ToolContext) -> ToolResult:
    body = {"page_size": 15, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    if args.get("query"):
        body["query"] = args["query"]
    results = (tokens.call(NOTION, "POST", f"{API}/search", body=body) or {}).get("results", [])
    rows = [
        f"{_title(r)}  [{r.get('object')}, id {r.get('id', '').replace('-', '')}, edited {str(r.get('last_edited_time', ''))[:10]}]"
        for r in results
    ]
    if not rows:
        return ToolResult(
            "Nothing found. Notion only shows pages that have been shared with the JARVIS integration "
            "(in Notion: open the page, '...' > Connections > add it)."
        )
    return ToolResult("\n".join(rows), untrusted_source="Notion search")


@tool(
    name="notion_read",
    description="Read the contents of a Notion page.",
    input_schema={"type": "object", "properties": {"page_id": _ID_FIELD}, "required": ["page_id"], "additionalProperties": False},
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: f"Read Notion page {a['page_id']}",
)
@_guard
def notion_read(args: dict, ctx: ToolContext) -> ToolResult:
    page_id = args["page_id"].replace("-", "")
    title = _title(tokens.call(NOTION, "GET", f"{API}/pages/{page_id}") or {})
    lines, cursor = [], None
    for _ in range(5):  # up to 500 blocks
        data = tokens.call(NOTION, "GET", f"{API}/blocks/{page_id}/children", {"page_size": 100, "start_cursor": cursor}) or {}
        for block in data.get("results", []):
            line = block_text(block)
            if line is not None:
                lines.append(line + ("  (has nested content not shown)" if block.get("has_children") and block.get("type") != "child_page" else ""))
        cursor = data.get("next_cursor")
        if not data.get("has_more"):
            break
    text = f"# {title}\n\n" + ("\n".join(lines) or "(the page is empty)")
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n[... the rest of the page is not shown]"
    return ToolResult(text, untrusted_source=f"Notion page: {title}", taints=True)


_CONTENT_HELP = "Plain text, one block per line. Start a line with '# ', '## ' or '### ' for a heading, '- ' for a bullet, '[ ] ' for a to-do."


@tool(
    name="notion_create_page",
    description="Create a new Notion page beneath an existing page.",
    input_schema={
        "type": "object",
        "properties": {
            "parent_id": {"type": "string", "description": "Id of the page to create it under (from notion_search)."},
            "title": {"type": "string"},
            "content": {"type": "string", "description": _CONTENT_HELP},
        },
        "required": ["parent_id", "title"],
        "additionalProperties": False,
    },
    tier=AUTO, kind="write",
    describe=lambda a, c: f"Create the Notion page '{a['title']}':\n\n{a.get('content', '')}",
)
@_guard
def notion_create_page(args: dict, ctx: ToolContext) -> ToolResult:
    blocks = to_blocks(args.get("content", ""))
    page = tokens.call(
        NOTION, "POST", f"{API}/pages",
        body={
            "parent": {"page_id": args["parent_id"].replace("-", "")},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": args["title"][:2000]}}]}},
            "children": blocks[:100],
        },
    )
    if len(blocks) > 100:
        _append(page["id"], blocks[100:])
    return ToolResult(f"Created '{args['title']}': {page.get('url')}")


@tool(
    name="notion_append",
    description="Add text to the end of an existing Notion page.",
    input_schema={
        "type": "object",
        "properties": {"page_id": _ID_FIELD, "content": {"type": "string", "description": _CONTENT_HELP}},
        "required": ["page_id", "content"],
        "additionalProperties": False,
    },
    tier=AUTO, kind="write",
    describe=lambda a, c: f"Add this to Notion page {a['page_id']}:\n\n{a['content']}",
)
@_guard
def notion_append(args: dict, ctx: ToolContext) -> ToolResult:
    blocks = to_blocks(args["content"])
    if not blocks:
        return ToolResult("There is nothing to add.", is_error=True)
    _append(args["page_id"].replace("-", ""), blocks)
    return ToolResult(f"Added {len(blocks)} block(s) to the page.")
