"""Vector geometry from the PDF itself (PDFium page objects): path bounds, stroke width, colours, dash count. Independent of any model.
Used only to CHECK spatial claims (is there a heavy line here? is this tag inside this view?). It is not a takeoff and produces no quantities."""
import ctypes
import pathlib

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .render import sha256_file


def vector_inventory(pdf_path, page_number):
    pdf_path = pathlib.Path(pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_number - 1]
        w, h = page.get_size()
        out = []
        for o in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH]):
            l, b, r, t = o.get_bounds()
            width = ctypes.c_float()
            raw.FPDFPageObj_GetStrokeWidth(o.raw, ctypes.byref(width))
            R, G, B, A = (ctypes.c_uint() for _ in range(4))
            raw.FPDFPageObj_GetStrokeColor(o.raw, R, G, B, A)
            fr, fg, fb, fa = (ctypes.c_uint() for _ in range(4))
            raw.FPDFPageObj_GetFillColor(o.raw, fr, fg, fb, fa)
            out.append({"rect_norm": [round(l / w, 5), round(1 - t / h, 5), round(r / w, 5), round(1 - b / h, 5)], "stroke_width_pt": round(width.value, 3),
                        "stroke_rgb": [R.value, G.value, B.value], "fill_alpha": fa.value, "dash_count": raw.FPDFPageObj_GetDashCount(o.raw),
                        "w_pt": round(r - l, 2), "h_pt": round(t - b, 2)})
        return {"source_document": pdf_path.name, "source_sha256": sha256_file(pdf_path), "page_number": page_number, "page_size_pt": [w, h], "position_source": "pdf_vector_objects",
                "path_object_count": len(out), "paths": out}
    finally:
        doc.close()
