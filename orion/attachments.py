"""Turns files, images, screenshots, clipboard content, tabs and windows into 'attachments'
that can be shown in the chat and handed to the brain."""
import base64
import re
from pathlib import Path

MAX_FILE_BYTES = 8_000_000        # refuse to even read files bigger than this
MAX_CHARS_FILE = 40_000           # per attachment
MAX_CHARS_TOTAL = 90_000          # per message
MAX_IMAGE_EDGE = 1568
MAX_PDF_PAGES = 40

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
            ".ini", ".cfg", ".conf", ".env", ".log", ".xml", ".html", ".htm", ".css", ".scss", ".js", ".jsx",
            ".ts", ".tsx", ".py", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
            ".sh", ".bat", ".ps1", ".sql", ".swift", ".kt", ".lua", ".r", ".tex", ".srt", ".vtt", ".gitignore"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _attachment(kind, name, **kw):
    a = {"kind": kind, "name": name, "media_type": "", "data": "", "text": "", "thumb": None, "note": ""}
    a.update(kw)
    return a


# ---------------- images ----------------
def _encode_qimage(img, prefer_jpeg):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    if max(img.width(), img.height()) > MAX_IMAGE_EDGE:
        from PySide6.QtCore import Qt
        img = img.scaled(MAX_IMAGE_EDGE, MAX_IMAGE_EDGE, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def enc(fmt, q=-1):
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, fmt, q)
        return bytes(ba.data())
    if prefer_jpeg:
        data, mt = enc("JPEG", 85), "image/jpeg"
    else:
        data, mt = enc("PNG"), "image/png"
        if len(data) > 4_500_000:
            data, mt = enc("JPEG", 80), "image/jpeg"
    return data, mt, img


def _thumb(img, edge=160):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    t = img.scaled(edge, edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    t.save(buf, "PNG")
    return bytes(ba.data())


def from_qimage(img, name="image.png", prefer_jpeg=False):
    if img is None or img.isNull():
        return _attachment("info", name, text="(the image could not be read)", note="unreadable image")
    data, mt, small = _encode_qimage(img, prefer_jpeg)
    return _attachment("image", name, media_type=mt, data=base64.b64encode(data).decode("ascii"),
                       thumb=_thumb(small), note=f"{img.width()}x{img.height()}")


def _from_image_path(path):
    from PySide6.QtGui import QImage
    img = QImage(str(path))
    return from_qimage(img, path.name, prefer_jpeg=path.suffix.lower() in (".jpg", ".jpeg"))


# ---------------- documents ----------------
def _read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PDF reading needs the pypdf package (run the installer again)."
    r = PdfReader(str(path))
    out = []
    for i, page in enumerate(r.pages[:MAX_PDF_PAGES]):
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    text = "\n\n".join(out).strip()
    extra = f"\n\n[only the first {MAX_PDF_PAGES} of {len(r.pages)} pages were read]" if len(r.pages) > MAX_PDF_PAGES else ""
    if not text:
        return None, "This PDF has no selectable text (it may be a scan). Attach screenshots of its pages instead."
    return text + extra, ""


def _read_docx(path):
    try:
        import docx
    except ImportError:
        return None, "Word files need the python-docx package (run the installer again)."
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts), ""


def _looks_textual(path):
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _decode(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", "replace")


def from_text(name, text, kind="text", note=""):
    text = text or ""
    if len(text) > MAX_CHARS_FILE:
        note = (note + " " if note else "") + f"(truncated: first {MAX_CHARS_FILE:,} of {len(text):,} characters)"
        text = text[:MAX_CHARS_FILE]
    return _attachment(kind, name, text=text, note=note)


def from_path(path):
    path = Path(path)
    if path.is_dir():
        return folder_listing(path)
    if not path.exists():
        return _attachment("info", path.name, text="(file not found)", note="missing")
    try:
        size = path.stat().st_size
    except OSError as e:
        return _attachment("info", path.name, text=f"(cannot read: {e})", note="unreadable")
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return _from_image_path(path)
    if size > MAX_FILE_BYTES:
        return _attachment("info", path.name, text=f"(file is {size / 1e6:.1f} MB, too large to read here)",
                           note="too large")
    try:
        if ext == ".pdf":
            text, err = _read_pdf(path)
        elif ext == ".docx":
            text, err = _read_docx(path)
        elif ext in TEXT_EXT or _looks_textual(path):
            text, err = _decode(path), ""
        else:
            return _attachment("info", path.name, text=f"(a {ext or 'binary'} file, {size:,} bytes; "
                               "I can't read this type yet)", note="unsupported type")
    except Exception as e:
        return _attachment("info", path.name, text=f"(could not read: {type(e).__name__}: {e})", note="error")
    if text is None:
        return _attachment("info", path.name, text=f"({err})", note="unreadable")
    return from_text(path.name, text, note=f"{size:,} bytes")


def folder_listing(path, limit=250):
    path = Path(path)
    lines, n = [], 0
    try:
        for p in sorted(path.rglob("*")):
            if any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv") for part in
                   p.relative_to(path).parts):
                continue
            n += 1
            if n > limit:
                lines.append(f"... and more (showing the first {limit})")
                break
            rel = p.relative_to(path).as_posix()
            lines.append(rel + ("/" if p.is_dir() else f"  ({p.stat().st_size:,} bytes)"))
    except OSError as e:
        lines.append(f"(could not finish reading the folder: {e})")
    return _attachment("text", path.name + "/", text=f"Folder listing of {path.name}:\n" + "\n".join(lines),
                       note=f"{min(n, limit)} entries")


def from_mime(md):
    """Attachments from drag/drop or clipboard mime data."""
    out = []
    if md is None:
        return out
    if md.hasUrls():
        for u in md.urls():
            if u.isLocalFile():
                out.append(from_path(u.toLocalFile()))
    if not out and md.hasImage():
        from PySide6.QtGui import QImage
        img = md.imageData()
        if isinstance(img, QImage):
            out.append(from_qimage(img, "pasted-image.png"))
    return out


# ---------------- handing them to the brain ----------------
def render(attachments):
    """-> (text block to append to the user's message, list of images for the model)."""
    blocks, images, budget = [], [], MAX_CHARS_TOTAL
    for a in attachments or []:
        name = a["name"].replace('"', "'")
        if a["kind"] == "image":
            images.append({"media_type": a["media_type"], "data": a["data"]})
            blocks.append(f'<attachment name="{name}" type="image">(the image is shown to you directly)</attachment>')
            continue
        body = a["text"] or ""
        if len(body) > budget:
            body = body[:max(0, budget)] + "\n[...cut: attachment limit for one message reached]"
        budget -= len(body)
        body = re.sub(r"</\s*attachment\s*>", "</ attachment>", body, flags=re.I)
        note = f' note="{a["note"]}"' if a["note"] else ""
        blocks.append(f'<attachment name="{name}" type="{a["kind"]}"{note}>\n{body}\n</attachment>')
    return "\n\n".join(blocks), images


def summary(attachments):
    return ", ".join(a["name"] for a in attachments or [])


def public_view(attachments):
    """What the UI needs to draw a sent message (no heavy data)."""
    return [{"name": a["name"], "kind": a["kind"], "thumb": a.get("thumb")} for a in attachments or []]
