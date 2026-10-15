"""Source text and positions come from the PDF itself (PDFium text layer), never from a model.

text_inventory(pdf, page) returns every text line with its normalized page rectangle (origin top-left, 0-1), plus hashes of the text layer so a later run
can prove it used the same source. A page with no text layer reports `has_text_layer: False`; nothing here pretends to read an image.
"""
import hashlib
import pathlib

import pypdfium2 as pdfium

from .render import sha256_file


def text_inventory(pdf_path, page_number):
    pdf_path = pathlib.Path(pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError(f"page {page_number} outside 1..{len(doc)}")
        page = doc[page_number - 1]
        w, h = page.get_size()
        tp = page.get_textpage()
        text = tp.get_text_range()
        lines, start = [], 0
        for raw in text.split("\n"):
            seg = raw.rstrip("\r")
            n = len(raw) + 1
            if seg.strip():
                xs0, ys0, xs1, ys1 = [], [], [], []
                for i in range(start, start + len(seg)):
                    if text[i].isspace():
                        continue
                    l, b, r, t = tp.get_charbox(i)
                    xs0.append(l); ys0.append(b); xs1.append(r); ys1.append(t)
                if xs0:
                    lines.append({"text": seg.strip(), "rect_norm": [round(min(xs0) / w, 5), round(1 - max(ys1) / h, 5), round(max(xs1) / w, 5), round(1 - min(ys0) / h, 5)]})
            start += n
        return {"source_document": pdf_path.name, "source_sha256": sha256_file(pdf_path), "page_number": page_number, "page_size_pt": [w, h],
                "has_text_layer": bool(lines), "line_count": len(lines), "text_layer_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "position_source": "pdf_text_layer", "lines": lines}
    finally:
        doc.close()


def word_inventory(pdf_path, page_number):
    """Whitespace-separated tokens with their own PDF-derived rectangles (normalized, origin top-left). For locating tags such as G1/G2/G3 and detail callouts."""
    pdf_path = pathlib.Path(pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_number - 1]
        w, h = page.get_size()
        tp = page.get_textpage()
        text = tp.get_text_range()
        words, i, n = [], 0, len(text)
        while i < n:
            if text[i].isspace():
                i += 1
                continue
            j = i
            while j < n and not text[j].isspace():
                j += 1
            boxes = [tp.get_charbox(k) for k in range(i, j)]
            words.append({"text": text[i:j], "rect_norm": [round(min(b[0] for b in boxes) / w, 5), round(1 - max(b[3] for b in boxes) / h, 5),
                                                            round(max(b[2] for b in boxes) / w, 5), round(1 - min(b[1] for b in boxes) / h, 5)]})
            i = j
        return {"source_document": pdf_path.name, "source_sha256": sha256_file(pdf_path), "page_number": page_number, "position_source": "pdf_text_layer", "words": words}
    finally:
        doc.close()
