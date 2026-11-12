"""GitHub: your repositories, issues, pull requests, notifications and files.
Connect once with:  python -m jarvis connect github

Issue and file contents are untrusted data (anyone can write an issue).
Anything that posts publicly (a new issue, a comment) always asks first.
"""

from __future__ import annotations

import base64
import re

from jarvis.core.secrets import SecretsUnavailable
from jarvis.core.tools import AUTO, CONFIRM, ToolContext, ToolResult, tool
from jarvis.integrations import tokens
from jarvis.integrations.oauth import ApiError, NotConnected
from jarvis.integrations.tokens import GITHUB

API = "https://api.github.com"
REPO = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
MAX_TEXT = 12_000
_REPO_FIELD = {"type": "string", "description": "The repository as owner/name, e.g. octocat/hello-world."}


def _guard(func):
    def wrapper(args: dict, ctx: ToolContext):
        if "repo" in args and not re.fullmatch(REPO, args["repo"]):
            return ToolResult("Give the repository as owner/name.", is_error=True)
        try:
            return func(args, ctx)
        except (NotConnected, ApiError, SecretsUnavailable) as exc:
            return ToolResult(str(exc), is_error=True)

    wrapper.__name__ = func.__name__
    wrapper.__module__ = func.__module__
    return wrapper


def _cut(text: str) -> str:
    text = text or ""
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"\n[... {len(text) - MAX_TEXT} more characters not shown]"


@tool(
    name="github_repos",
    description="List the user's GitHub repositories, most recently updated first.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: "List your GitHub repositories",
)
@_guard
def github_repos(args: dict, ctx: ToolContext) -> ToolResult:
    repos = tokens.call(GITHUB, "GET", f"{API}/user/repos", {"sort": "pushed", "per_page": 30}) or []
    rows = [
        f"{r['full_name']}{' (private)' if r.get('private') else ''}: {r.get('description') or 'no description'}"
        f"  [{r.get('open_issues_count', 0)} open, pushed {str(r.get('pushed_at', ''))[:10]}]"
        for r in repos
    ]
    return ToolResult("\n".join(rows) or "No repositories.", untrusted_source="GitHub repositories")


@tool(
    name="github_issues",
    description="List issues and pull requests in a GitHub repository.",
    input_schema={
        "type": "object",
        "properties": {"repo": _REPO_FIELD, "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Default open."}},
        "required": ["repo"],
        "additionalProperties": False,
    },
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: f"List issues in {a['repo']}",
)
@_guard
def github_issues(args: dict, ctx: ToolContext) -> ToolResult:
    items = tokens.call(GITHUB, "GET", f"{API}/repos/{args['repo']}/issues", {"state": args.get("state", "open"), "per_page": 30}) or []
    rows = [
        f"#{i['number']} [{'PR' if 'pull_request' in i else 'issue'}, {i['state']}] {i['title']}"
        f"  (by {i['user']['login']}, {i.get('comments', 0)} comments)"
        for i in items
    ]
    return ToolResult("\n".join(rows) or "None.", untrusted_source=f"GitHub {args['repo']}", taints=True)


@tool(
    name="github_read",
    description="Read one issue or pull request in full, with its comments.",
    input_schema={
        "type": "object",
        "properties": {"repo": _REPO_FIELD, "number": {"type": "integer", "minimum": 1}},
        "required": ["repo", "number"],
        "additionalProperties": False,
    },
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: f"Read {a['repo']}#{a['number']}",
)
@_guard
def github_read(args: dict, ctx: ToolContext) -> ToolResult:
    base = f"{API}/repos/{args['repo']}/issues/{args['number']}"
    issue = tokens.call(GITHUB, "GET", base)
    comments = tokens.call(GITHUB, "GET", f"{base}/comments", {"per_page": 30}) or [] if issue.get("comments") else []
    parts = [
        f"{'Pull request' if 'pull_request' in issue else 'Issue'} #{issue['number']}: {issue['title']}",
        f"State: {issue['state']}. Opened by {issue['user']['login']} on {str(issue.get('created_at', ''))[:10]}.",
        "",
        issue.get("body") or "(no description)",
    ]
    for c in comments:
        parts += ["", f"--- Comment by {c['user']['login']} on {str(c.get('created_at', ''))[:10]} ---", c.get("body") or ""]
    return ToolResult(_cut("\n".join(parts)), untrusted_source=f"GitHub {args['repo']}#{args['number']}", taints=True)


@tool(
    name="github_file",
    description="Read a file, or list a folder, in a GitHub repository.",
    input_schema={
        "type": "object",
        "properties": {
            "repo": _REPO_FIELD,
            "path": {"type": "string", "description": "Path within the repository. Empty for the top folder."},
            "ref": {"type": "string", "description": "Branch, tag or commit. Default: the default branch."},
        },
        "required": ["repo"],
        "additionalProperties": False,
    },
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: f"Read {a['repo']}/{a.get('path', '')}",
)
@_guard
def github_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = (args.get("path") or "").strip("/")
    if ".." in path.split("/"):
        return ToolResult("That is not a path inside the repository.", is_error=True)
    data = tokens.call(GITHUB, "GET", f"{API}/repos/{args['repo']}/contents/{path}", {"ref": args.get("ref")})
    source = f"GitHub {args['repo']}/{path}"
    if isinstance(data, list):
        rows = [f"{e['name']}/" if e["type"] == "dir" else f"{e['name']}  ({e.get('size', 0):,} bytes)" for e in data]
        return ToolResult("\n".join(rows) or "(empty)", untrusted_source=source)
    if data.get("encoding") != "base64" or not data.get("content"):
        return ToolResult(f"{path} is too large or is not a text file ({data.get('size', 0):,} bytes).", is_error=True)
    raw = base64.b64decode(data["content"])
    if b"\x00" in raw[:4096]:
        return ToolResult(f"{path} is a binary file ({len(raw):,} bytes).", is_error=True)
    return ToolResult(_cut(raw.decode("utf-8", errors="replace")), untrusted_source=source, taints=True)


@tool(
    name="github_notifications",
    description="List the user's unread GitHub notifications.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: "Check your GitHub notifications",
)
@_guard
def github_notifications(args: dict, ctx: ToolContext) -> ToolResult:
    items = tokens.call(GITHUB, "GET", f"{API}/notifications", {"per_page": 30}) or []
    rows = [f"{n['repository']['full_name']}: {n['subject']['title']}  ({n['subject']['type']}, {n['reason']})" for n in items]
    return ToolResult("\n".join(rows) or "No unread notifications.", untrusted_source="GitHub notifications", taints=True)


@tool(
    name="github_create_issue",
    description="Open a new issue in a GitHub repository. The user is shown it and must approve, since it is posted publicly.",
    input_schema={
        "type": "object",
        "properties": {"repo": _REPO_FIELD, "title": {"type": "string"}, "body": {"type": "string"}},
        "required": ["repo", "title"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="send",
    describe=lambda a, c: f"Open this issue in {a['repo']}:\n\n{a['title']}\n\n{a.get('body', '')}",
)
@_guard
def github_create_issue(args: dict, ctx: ToolContext) -> ToolResult:
    issue = tokens.call(GITHUB, "POST", f"{API}/repos/{args['repo']}/issues", body={"title": args["title"], "body": args.get("body", "")})
    return ToolResult(f"Opened issue #{issue['number']}: {issue.get('html_url')}")


@tool(
    name="github_comment",
    description="Post a comment on an issue or pull request. The user is shown it and must approve, since it is posted publicly.",
    input_schema={
        "type": "object",
        "properties": {"repo": _REPO_FIELD, "number": {"type": "integer", "minimum": 1}, "body": {"type": "string"}},
        "required": ["repo", "number", "body"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="send",
    describe=lambda a, c: f"Post this comment on {a['repo']}#{a['number']}:\n\n{a['body']}",
)
@_guard
def github_comment(args: dict, ctx: ToolContext) -> ToolResult:
    comment = tokens.call(GITHUB, "POST", f"{API}/repos/{args['repo']}/issues/{args['number']}/comments", body={"body": args["body"]})
    return ToolResult(f"Comment posted: {comment.get('html_url')}")
