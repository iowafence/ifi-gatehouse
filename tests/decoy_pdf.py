"""Decoy addendum PDFs for tests. Hand-written minimal PDF 1.4, one text line per page row. Every decoy is stamped DECOY and is
never the real Addendum 02 (which is not in the package). Values here are test data, not project facts."""


def make_pdf(pages):
    """pages: list of list-of-lines. Returns bytes of a valid PDF that pdftotext can read."""
    objs, kids = [], []
    n = 3 + 2 * len(pages)
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    for i in range(len(pages)):
        kids.append(f"{4 + 2 * i} 0 R")
    objs.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        body = "BT /F1 11 Tf 40 740 Td 16 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream".encode())
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs):
        offs.append(len(out))
        out += f"{i + 1} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


G3_LINE = "ITEM 1 GATE G3: THE CLEAR OPENING WIDTH IS 14 FEET (DECOY TEST VALUE)"
G2_LINE = "ITEM 2 GATE G2: CLEAR OPENING IS 12 FEET, DOUBLE LEAF, AS REVISED BY ADDENDUM 01"


def decoy(*lines, extra_pages=()):
    return make_pdf([["DECOY ADDENDUM NO. 02 - SYNTHETIC TEST FIXTURE - NOT THE REAL DOCUMENT", *lines], *extra_pages])
