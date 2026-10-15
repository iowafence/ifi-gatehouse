# intake

**Status: implemented; not connected to the demonstration.**

- `archive.py` hardened ZIP inventory using only the standard library: the archive is never extracted to disk, sizes are counted while streaming, unsafe archives are rejected whole, and unsupported files are listed with a reason rather than dropped.
- `pdf_index.py` page inventory with source ids using PyMuPDF, an optional dependency (`requirements-pdf.txt`). Region-level citations are not provided.

No upload route exists in the API, so none of this runs in the demo. Without PyMuPDF the three PDF-indexing tests are skipped.
