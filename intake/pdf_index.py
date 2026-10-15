"""PDF page inventory using PyMuPDF (optional dependency, see requirements-pdf.txt).

Produces page counts and page text with source ids so later extraction can cite document/page. Region-level
citations and 200-dpi crops are a separate step and are not claimed here.
"""
from .archive import IntakeError

MAX_PAGES = 500
MAX_PAGE_CHARS = 30_000


def available():
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False


def _mod():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz
            return fitz
        except ImportError:
            raise IntakeError("PDF indexing is unavailable: PyMuPDF is not installed")


def index_pdf(name, raw, doc_id):
    mu = _mod()
    try:
        pdf = mu.open(stream=raw, filetype="pdf")
    except Exception:
        raise IntakeError(f"{name} cannot be opened as a PDF")
    try:
        if pdf.needs_pass or pdf.is_encrypted:
            raise IntakeError(f"{name} is encrypted")
        if pdf.page_count < 1:
            raise IntakeError(f"{name} has no pages")
        if pdf.page_count > MAX_PAGES:
            raise IntakeError(f"{name} has too many pages")
        pages = []
        for i, page in enumerate(pdf):
            text = page.get_text()
            pages.append({"page": i + 1, "source_id": f"{doc_id}:p{i + 1}", "chars": len(text),
                          "text": text[:MAX_PAGE_CHARS], "truncated": len(text) > MAX_PAGE_CHARS,
                          "width_pt": round(page.rect.width, 1), "height_pt": round(page.rect.height, 1)})
        return {"doc_id": doc_id, "filename": name, "pages": pages}
    finally:
        pdf.close()


def index_documents(inv):
    """inv is the result of archive.inventory(). doc_id is derived from the content hash, not the filename."""
    by_name = {e["filename"]: e for e in inv["entries"]}
    return [index_pdf(n, raw, by_name[n]["sha256"][:16]) for n, raw in inv["documents"]]
