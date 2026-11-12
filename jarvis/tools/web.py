"""Web tools: search, read a page, open a page in your browser.

Everything that comes back from the web is marked as untrusted data, and
reading a page or search results "taints" the request: in trusted mode,
JARVIS then asks before changing, running or controlling anything until
your next message. A web page is the most likely place for hidden
instructions aimed at an assistant.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser

from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
MAX_DOWNLOAD = 3_000_000  # bytes read from any one page
PAGE_CHARS = 12_000  # text returned per call; ask for more with 'start'


def _check_url(url: str) -> str | None:
    """Returns a reason the URL may not be fetched, or None if it is fine."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "Only http and https web addresses are allowed."
    # Do not let a web page steer JARVIS at this computer or the home
    # network (router pages, JARVIS's own local server, and so on).
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, None)}
    except socket.gaierror:
        return f"Cannot find the site {parts.hostname}."
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return f"{parts.hostname} is an address on this computer or local network; not fetched."
    return None


class _NoLocalRedirects(urllib.request.HTTPRedirectHandler):
    """A public page must not redirect us to a local address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        problem = _check_url(newurl)
        if problem:
            raise urllib.error.URLError(f"redirect refused: {problem}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_NoLocalRedirects)


class _TextExtractor(HTMLParser):
    """Pulls the readable text out of a page, keeping headings and links."""

    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "footer", "form", "header", "aside"}
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP and tag != "head":
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.parts.append("# ")
            elif tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and tag != "head":
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        text = re.sub(r"^[-#]\s*$", "", text, flags=re.MULTILINE)  # empty bullets and headings
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def page_text(markup: str) -> tuple[str, str]:
    """HTML -> (title, readable text)."""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
    except Exception:
        pass  # keep whatever was read before the bad markup
    return parser.title.strip(), parser.text()


def _search(query: str, count: int) -> list[dict]:
    """Separate so tests can replace it. Returns dicts with title, href, body."""
    from ddgs import DDGS

    return DDGS(timeout=15).text(query, max_results=count)


@tool(
    name="web_search",
    description=(
        "Search the web. Returns titles, addresses and short summaries of the top results. "
        "Use read_page on a result to read it in full."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "count": {"type": "integer", "minimum": 1, "maximum": 15, "description": "How many results. Default 6."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Search the web for: {a['query']}",
)
def web_search(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        results = _search(args["query"], args.get("count", 6))
    except ImportError:
        return ToolResult('Web search needs one more library. Run:  pip install -e "."', is_error=True)
    except Exception as exc:
        return ToolResult(
            f"The search failed ({type(exc).__name__}: {str(exc)[:200]}). "
            "The search engines may be rate-limiting; try again in a minute.",
            is_error=True,
        )
    if not results:
        return ToolResult("No results.")
    rows = []
    for i, r in enumerate(results, 1):
        rows.append(f"{i}. {r.get('title', '').strip()}\n   {r.get('href', '')}\n   {(r.get('body') or '').strip()}")
    return ToolResult("\n".join(rows), untrusted_source=f"web search: {args['query']}", taints=True)


@tool(
    name="read_page",
    description=(
        "Fetch a web page and return its readable text. Long pages come in parts: pass 'start' to continue. "
        "Works for ordinary pages; sites that need a login or build their content with scripts may return little."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full address starting with http:// or https://"},
            "start": {"type": "integer", "minimum": 0, "description": "Character offset to continue from."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Read the web page {a['url']}",
)
def read_page(args: dict, ctx: ToolContext) -> ToolResult:
    url = args["url"].strip()
    problem = _check_url(url)
    if problem:
        return ToolResult(problem, is_error=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with _opener.open(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(MAX_DOWNLOAD)
    except urllib.error.HTTPError as exc:
        return ToolResult(f"The site answered with an error ({exc.code} {exc.reason}).", is_error=True)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return ToolResult(f"Could not reach the page ({getattr(exc, 'reason', exc)}).", is_error=True)

    if not any(kind in content_type for kind in ("html", "text", "json", "xml")) and content_type:
        return ToolResult(f"That address is a {content_type} file, not a readable page ({len(raw):,} bytes).")
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    if "html" in content_type or "<html" in body[:2000].lower():
        title, text = page_text(body)
    else:
        title, text = "", html.unescape(body)

    start = args.get("start", 0)
    chunk = text[start : start + PAGE_CHARS]
    header = f"{title}\n{url}\n\n" if title and start == 0 else ""
    more = ""
    if start + PAGE_CHARS < len(text):
        more = f"\n\n[Showing characters {start}-{start + len(chunk)} of {len(text)}. Call again with start={start + PAGE_CHARS} for more.]"
    if not text:
        chunk = "(The page has no readable text. It may need a login or build its content with scripts.)"
    return ToolResult(header + chunk + more, untrusted_source=url, taints=True)


@tool(
    name="open_url",
    description="Open a web address in the user's default browser, for them to look at. Does not return the page's content; use read_page for that.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full address starting with http:// or https://"}},
        "required": ["url"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Open {a['url']} in your browser",
)
def open_url(args: dict, ctx: ToolContext) -> ToolResult:
    url = args["url"].strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ToolResult("Only http and https web addresses can be opened.", is_error=True)
    if not webbrowser.open(url):
        return ToolResult("No browser could be opened.", is_error=True)
    return ToolResult(f"Opened {url} in the browser.")
