"""Single-PDF addendum intake: safety checks, SHA-256, per-page text, and verification that a cited excerpt is on the cited page.

Standard library plus the system `pdftotext` (or PyMuPDF if installed). The PDF is never executed and never written anywhere but a
private temp file that is removed immediately. Everything the client says (name, type, size) is untrusted. Fail closed: if no text
extractor is available the upload is refused, never accepted unread."""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile

from .archive import IntakeError

MAX_PDF_BYTES = 10_000_000
MAX_PAGES = 60
MAX_PAGE_CHARS = 30_000
MIN_EXCERPT, MAX_EXCERPT = 12, 400
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "′": "'", "″": '"',
                         "–": "-", "—": "-", "−": "-", " ": " "})


class AddendumRefused(IntakeError):
    """The upload is refused. `code` is a stable machine code; the message is safe to show."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def norm(s):
    return re.sub(r"\s+", " ", str(s).translate(_QUOTES)).strip().lower()


def safe_name(name):
    base = os.path.basename(str(name or "").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:100].strip()
    return base or "addendum.pdf"


def _pdftotext_pages(raw):
    exe = shutil.which("pdftotext")
    if not exe:
        raise AddendumRefused("PDF_TEXT_UNAVAILABLE", "no PDF text extractor is installed; the upload cannot be read, so it is refused")
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        try:
            out = subprocess.run([exe, "-raw", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise AddendumRefused("INVALID_PDF", "the PDF took too long to read")
    finally:
        os.unlink(path)
    if out.returncode != 0:
        raise AddendumRefused("INVALID_PDF", "the file cannot be read as a PDF (damaged, encrypted or not a PDF)")
    parts = out.stdout.decode("utf-8", "replace").split("\f")
    if parts and parts[-1].strip() == "":
        parts.pop()
    return parts


def read_pdf(raw, filename=""):
    """Validate and index one uploaded PDF. Returns {sha256, size, filename, pages:[{page,text}]} or raises AddendumRefused."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) == 0:
        raise AddendumRefused("INVALID_PDF", "the upload is empty")
    if len(raw) > MAX_PDF_BYTES:
        raise AddendumRefused("TOO_LARGE", f"the PDF is larger than the {MAX_PDF_BYTES // 1_000_000} MB limit")
    raw = bytes(raw)
    if not raw.lstrip(b"\x00 \t\r\n")[:5] == b"%PDF-" or b"%%EOF" not in raw[-2048:]:
        raise AddendumRefused("INVALID_PDF", "the file is not a complete PDF")
    pages = _pdftotext_pages(raw)
    if not pages:
        raise AddendumRefused("INVALID_PDF", "the PDF has no pages")
    if not any(t.strip() for t in pages):
        raise AddendumRefused("NO_TEXT_LAYER", "the PDF has no text layer to read (a scan or image-only file); it cannot be verified, so it is refused")
    if len(pages) > MAX_PAGES:
        raise AddendumRefused("TOO_LARGE", f"the PDF has more than {MAX_PAGES} pages")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "filename": safe_name(filename),
            "pages": [{"page": i + 1, "text": t[:MAX_PAGE_CHARS]} for i, t in enumerate(pages)]}


def excerpt_on_page(pages, page, excerpt):
    """True only when the excerpt (whitespace/case/quote-normalised) occurs on exactly the cited page."""
    if not (isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= len(pages)):
        return False
    if not isinstance(excerpt, str) or not (MIN_EXCERPT <= len(excerpt.strip()) <= MAX_EXCERPT):
        return False
    return norm(excerpt) in norm(pages[page - 1]["text"])
