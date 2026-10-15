"""Render one PDF page to PNG with pypdfium2 (BSD-3 / Apache-2.0; PDFium), and expose the page's own text layer for evidence checks.

The page image and the text layer come from the same file, whose SHA-256 is recorded before anything is sent anywhere.
"""
import hashlib
import pathlib

import pypdfium2 as pdfium


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_page(pdf_path, page_number, dpi, out_png, region=None):
    """page_number is 1-based. Returns metadata including the document hash, the page size in points and the image size in pixels."""
    pdf_path = pathlib.Path(pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError(f"page {page_number} outside 1..{len(doc)}")
        page = doc[page_number - 1]
        w_pt, h_pt = page.get_size()
        img = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
        full_px = list(img.size)
        if region:
            x0, y0, x1, y1 = region
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("region must be normalized x0<x1, y0<y1 within 0-1")
            img = img.crop((round(x0 * img.size[0]), round(y0 * img.size[1]), round(x1 * img.size[0]), round(y1 * img.size[1])))
        out_png = pathlib.Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_png, format="PNG", optimize=True)
        return {"source_document": pdf_path.name, "source_sha256": sha256_file(pdf_path), "page_number": page_number, "page_count": len(doc),
                "page_size_pt": [w_pt, h_pt], "dpi": dpi, "image_px": list(img.size), "full_page_px_at_dpi": full_px, "region_norm_page": list(region) if region else None, "image_file": out_png.name,
                "image_sha256": sha256_file(out_png), "image_bytes": out_png.stat().st_size, "renderer": f"pypdfium2 {pdfium.version.PYPDFIUM_INFO}"}
    finally:
        doc.close()


class PdfiumPageText:
    """Text layer of one page. `find_rects(quote)` returns bounding boxes (normalized to the page, origin top-left) of every occurrence."""

    def __init__(self, pdf_path, page_number):
        self.doc = pdfium.PdfDocument(str(pdf_path))
        self.page = self.doc[page_number - 1]
        self.w, self.h = self.page.get_size()
        self.tp = self.page.get_textpage()
        self.text = self.tp.get_text_range()

    def _lines(self):
        """(normalized text, rect) for each text-layer line; rects are normalized to the page, origin top-left."""
        if getattr(self, "_line_cache", None) is None:
            from .validator import norm
            lines, start = [], 0
            for raw in self.text.split("\n"):
                seg = raw.rstrip("\r")
                n = len(raw) + 1
                idx = [i for i in range(start, start + len(seg)) if not self.text[i].isspace()]
                if idx:
                    boxes = [self.tp.get_charbox(i) for i in idx]
                    lines.append((norm(seg), [min(b[0] for b in boxes) / self.w, 1 - max(b[3] for b in boxes) / self.h, max(b[2] for b in boxes) / self.w, 1 - min(b[1] for b in boxes) / self.h]))
                start += n
            self._line_cache = lines
        return self._line_cache

    def _rects_from_lines(self, quote, max_window=10):
        """Fallback when PDFium's own search cannot match (en dashes, wrapped hyphens): the quote must equal whole consecutive text-layer lines."""
        from .validator import norm
        q = norm(quote)
        L = self._lines()
        out = []
        for i in range(len(L)):
            acc = ""
            for j in range(i, min(len(L), i + max_window)):
                acc = norm(acc + " " + L[j][0]) if acc else L[j][0]
                if q in acc and len(acc) - len(q) <= 8 and acc.startswith(L[i][0][:1]):   # whole lines, allowing a short note-number prefix or trailing punctuation
                    rs = [L[k][1] for k in range(i, j + 1)]
                    out.append([min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)])
                    break
                if len(acc) > len(q) + 8:
                    break
        return out

    def find_rects(self, quote):
        out = self._find_rects_search(quote)
        return out or self._rects_from_lines(quote)

    def _find_rects_search(self, quote):
        out = []
        if not quote.strip():
            return out
        searcher = self.tp.search(quote, match_case=False, match_whole_word=False)
        while True:
            hit = searcher.get_next()
            if not hit:
                break
            start, count = hit
            xs0, ys0, xs1, ys1 = [], [], [], []
            for i in range(start, start + count):
                l, b, r, t = self.tp.get_charbox(i)
                xs0.append(l); ys0.append(b); xs1.append(r); ys1.append(t)
            out.append([min(xs0) / self.w, 1 - max(ys1) / self.h, max(xs1) / self.w, 1 - min(ys0) / self.h])
        return out

    def close(self):
        self.doc.close()
