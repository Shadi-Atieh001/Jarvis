"""Read documents: PDF, Word, PowerPoint and Excel files.

PDFs are read with the pypdf library. The three Office formats are zip
archives of XML, so they are read with the standard library alone.

Limits worth knowing: a scanned PDF is a set of pictures and has no text to
extract; old binary formats (.doc, .ppt, .xls) are not supported, so save
them as the modern format first.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from jarvis.core.tools import AUTO, ToolContext, ToolResult, tool
from jarvis.tools.files import _escalate_read, _outside

CHUNK = 12_000  # characters returned per call
MAX_MEMBER = 60_000_000  # largest file read from inside an Office archive
SUPPORTED = (".pdf", ".docx", ".pptx", ".xlsx")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class Unreadable(Exception):
    pass


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    info = archive.getinfo(name)
    if info.file_size > MAX_MEMBER:  # also guards against "zip bombs"
        raise Unreadable(f"{name} inside the file is too large to read.")
    return ElementTree.fromstring(archive.read(name))


def _numbered(names: list[str], pattern: str) -> list[str]:
    """Archive members matching pattern, in numeric order (slide2 before slide10)."""
    found = [(int(m.group(1)), n) for n in names if (m := re.fullmatch(pattern, n))]
    return [n for _, n in sorted(found)]


def read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Unreadable('Reading PDFs needs one more library. Run:  pip install -e "."') from None
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Unreadable("This PDF is password-protected.")
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"--- Page {number} ---\n{text}")
    except Unreadable:
        raise
    except Exception as exc:
        raise Unreadable(f"This PDF could not be read ({type(exc).__name__}).") from None
    if not pages:
        raise Unreadable(
            f"This PDF has {len(reader.pages)} page(s) but no text. It is probably a scan (pictures of pages), "
            "which cannot be read as text."
        )
    return "\n\n".join(pages)


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        body = _xml(archive, "word/document.xml").find(f"{W}body")
    lines = []
    for block in body if body is not None else []:
        if block.tag == f"{W}p":
            text = "".join(t.text or "" for t in block.iter(f"{W}t"))
            style = block.find(f"{W}pPr/{W}pStyle")
            if text.strip() and style is not None and style.get(f"{W}val", "").lower().startswith("heading"):
                text = "# " + text
            lines.append(text)
        elif block.tag == f"{W}tbl":
            for row in block.iter(f"{W}tr"):
                cells = ["".join(t.text or "" for t in cell.iter(f"{W}t")).strip() for cell in row.iter(f"{W}tc")]
                lines.append(" | ".join(cells))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def read_pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        slides = []
        for number, name in enumerate(_numbered(names, r"ppt/slides/slide(\d+)\.xml"), 1):
            paragraphs = []
            for paragraph in _xml(archive, name).iter(f"{A}p"):
                text = "".join(t.text or "" for t in paragraph.iter(f"{A}t")).strip()
                if text:
                    paragraphs.append(text)
            notes_name = f"ppt/notesSlides/notesSlide{number}.xml"
            if notes_name in names:
                notes = [
                    "".join(t.text or "" for t in p.iter(f"{A}t")).strip() for p in _xml(archive, notes_name).iter(f"{A}p")
                ]
                notes = [n for n in notes if n and not n.isdigit()]  # drop the slide-number placeholder
                if notes:
                    paragraphs.append("Speaker notes: " + " ".join(notes))
            slides.append(f"--- Slide {number} ---\n" + "\n".join(paragraphs))
    return "\n\n".join(slides)


def read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for item in _xml(archive, "xl/sharedStrings.xml").iter(f"{S}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{S}t")))
        titles = [sheet.get("name", "") for sheet in _xml(archive, "xl/workbook.xml").iter(f"{S}sheet")]
        sheets = []
        for index, name in enumerate(_numbered(names, r"xl/worksheets/sheet(\d+)\.xml")):
            rows = []
            for row in _xml(archive, name).iter(f"{S}row"):
                cells = []
                for cell in row.iter(f"{S}c"):
                    kind, value = cell.get("t"), cell.find(f"{S}v")
                    if kind == "s" and value is not None:
                        text = shared[int(value.text)] if value.text and int(value.text) < len(shared) else ""
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(f"{S}t"))
                    else:
                        text = value.text if value is not None and value.text else ""
                    cells.append(text.strip())
                if any(cells):
                    rows.append(" | ".join(cells))
            title = titles[index] if index < len(titles) else f"Sheet {index + 1}"
            sheets.append(f"--- Sheet: {title} ---\n" + "\n".join(rows))
    return "\n\n".join(sheets)


READERS = {".pdf": read_pdf, ".docx": read_docx, ".pptx": read_pptx, ".xlsx": read_xlsx}


def document_text(path: Path) -> str:
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise Unreadable(f"{path.suffix or 'That'} files are not supported. Supported: {', '.join(SUPPORTED)}.")
    try:
        return reader(path)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise Unreadable(f"{path.name} is damaged, or is not really a {path.suffix} file.") from None


@tool(
    name="read_document",
    description=(
        "Read the text of a PDF, Word (.docx), PowerPoint (.pptx) or Excel (.xlsx) file. Long documents come in "
        "parts: pass 'start' to continue. For plain text and code files use read_file instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Relative paths are inside the workspace."},
            "start": {"type": "integer", "minimum": 0, "description": "Character offset to continue from."},
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
def read_document(args: dict, ctx: ToolContext) -> ToolResult:
    path = ctx.resolve(args["path"])
    if not path.is_file():
        return ToolResult(f"No such file: {path}", is_error=True)
    try:
        text = document_text(path)
    except Unreadable as exc:
        return ToolResult(str(exc), is_error=True)
    start = args.get("start", 0)
    chunk = text[start : start + CHUNK] or "(The document has no text.)"
    more = ""
    if start + CHUNK < len(text):
        more = f"\n\n[Showing characters {start}-{start + len(chunk)} of {len(text)}. Call again with start={start + CHUNK} for more.]"
    header = f"{path.name} ({len(text):,} characters of text)\n\n" if start == 0 else ""
    return ToolResult(header + chunk + more, untrusted_source=str(path), taints=_outside(path, ctx))
