"""Hardened, read-only .xlsx parser (stdlib only) for UNTRUSTED uploads.

Why not just open it in a spreadsheet library: the rate book is an authenticated server-side pricing source, so
everything about the file is treated as hostile until proven otherwise, and the cached results Excel stored next to
each formula must never become a price. This parser therefore
  * enforces size, member-count, expansion-ratio and path rules on the ZIP container before reading any member,
  * rejects macros, external links, embedded objects, data connections, pivot caches and DOCTYPE/ENTITY XML,
  * returns formulas as text for scanning and DOES NOT return their cached values (keep_cached=False),
  * decodes numbers as Decimal and dates from number formats, and never coerces text to numbers.
Raises WorkbookRejected with every structural problem found, not just the first."""
import datetime
import posixpath
import re
import struct
import zipfile
import zlib
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
WORKBOOK_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"

FORBIDDEN_PREFIXES = ("xl/externalLinks/", "xl/embeddings/", "xl/activeX/", "xl/ctrlProps/", "xl/macrosheets/",
                      "xl/dialogsheets/", "xl/queryTables/", "xl/pivotCache", "xl/pivotTables/", "xl/connections")
FORBIDDEN_NAME_PARTS = ("vbaproject", "oleobject", "vbadata")
UNSAFE_FORMULA = re.compile(
    r"\[|https?:|ftp:|file:|\\\\|\bWEBSERVICE\b|\bHYPERLINK\b|\bINDIRECT\b|\bEXEC\b|\bCALL\s*\(|\bREGISTER(\.ID)?\b|"
    r"\bFILTERXML\b|\bRTD\b|\bDDE\b|\bSQL\.REQUEST\b|\|\s*'", re.I)
BUILTIN_DATE_FMTS = set(range(14, 23)) | {45, 46, 47}
_DATE_TOKEN = re.compile(r"[ymdhs]", re.I)
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d{1,7})$")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[0-9:.]+Z?)?", re.ASCII)
_BIDI = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class WorkbookRejected(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(f"{p['code']}: {p['message']}" for p in problems[:5]) + (" ..." if len(problems) > 5 else ""))


class Limits:
    max_file_bytes = 5_000_000
    max_members = 200
    max_member_bytes = 20_000_000
    max_total_bytes = 60_000_000
    max_ratio = 150           # uncompressed / compressed, applied above min_ratio_bytes
    min_ratio_bytes = 1_000_000
    max_rows = 5_000
    max_cols = 100
    max_cells_per_sheet = 100_000
    max_formula_len = 2_000
    max_string_len = 2_000


class Cell:
    """kind: n number (Decimal), s string, b bool, d date (ISO str), e error, f formula-only (cached value withheld)."""
    __slots__ = ("kind", "value", "formula", "cached")

    def __init__(self, kind, value, formula=None, cached=None):
        self.kind, self.value, self.formula, self.cached = kind, value, formula, cached

    @property
    def is_formula(self):
        return self.formula is not None

    def __repr__(self):
        return f"Cell({self.kind},{self.value!r},f={self.formula!r})"


class Sheet:
    def __init__(self, name, state):
        self.name, self.state = name, state
        self.cells = {}           # (row, col) -> Cell
        self.merges = []

    def get(self, row, col):
        return self.cells.get((row, col))

    @property
    def max_row(self):
        return max((r for r, _ in self.cells), default=0)

    @property
    def max_col(self):
        return max((c for _, c in self.cells), default=0)


class Workbook:
    def __init__(self):
        self.sheets = {}          # name -> Sheet, in workbook order
        self.warnings = []


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _p(code, message, where=None):
    return {"code": code, "message": message, "where": where}


def _local(tag):
    return tag.rsplit("}", 1)[-1]


_ENC = re.compile(rb'^\s*<\?xml[^>]*?encoding\s*=\s*["\']([^"\']+)["\']', re.I)


def _xml(data, name, problems):
    """Parse one XML part. Only ASCII-compatible UTF-8 is accepted, so the DTD/ENTITY scan below cannot be bypassed by
    UTF-16/32 encoding, and the whole buffer is scanned (not a prefix), so padding cannot hide a DOCTYPE."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:8]:
        problems.append(_p("XML_ENCODING_FORBIDDEN", "only UTF-8 XML parts are accepted", name))
        return None
    m = _ENC.match(data[:300])
    if m and m.group(1).strip().lower() not in (b"utf-8", b"utf8"):
        problems.append(_p("XML_ENCODING_FORBIDDEN", "only UTF-8 XML parts are accepted", name))
        return None
    low = data.lower()
    if b"<!doctype" in low or b"<!entity" in low:
        problems.append(_p("XML_DTD_FORBIDDEN", "DOCTYPE/ENTITY declarations are not allowed", name))
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        problems.append(_p("XML_MALFORMED", f"cannot parse XML: {exc}", name))
        return None


def _container(data, lim, problems):
    if len(data) > lim.max_file_bytes:
        problems.append(_p("FILE_TOO_LARGE", f"{len(data)} bytes exceeds the {lim.max_file_bytes} byte limit"))
        return None
    if not data.startswith(b"PK\x03\x04"):
        problems.append(_p("NOT_XLSX", "file is not a ZIP/OOXML package (wrong magic bytes)"))
        return None
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        problems.append(_p("NOT_XLSX", f"corrupt ZIP container: {exc}"))
        return None
    infos = zf.infolist()
    if len(infos) > lim.max_members:
        problems.append(_p("TOO_MANY_MEMBERS", f"{len(infos)} package members exceeds {lim.max_members}"))
        return None
    seen, total = set(), 0
    for i in infos:
        n = i.filename
        low = n.lower()
        if n.startswith("/") or ".." in n.split("/") or "\\" in n or "\x00" in n or re.match(r"^[A-Za-z]:", n):
            problems.append(_p("UNSAFE_PATH", "package member path is not a plain relative path", n))
        if n in seen:
            problems.append(_p("DUPLICATE_MEMBER", "duplicate package member", n))
        seen.add(n)
        if i.flag_bits & 0x1:
            problems.append(_p("ENCRYPTED", "encrypted package members are not accepted", n))
        total += i.file_size
        if i.file_size > lim.max_member_bytes:
            problems.append(_p("MEMBER_TOO_LARGE", f"{i.file_size} bytes uncompressed", n))
        if i.file_size > lim.min_ratio_bytes and i.file_size / max(1, i.compress_size) > lim.max_ratio:
            problems.append(_p("ZIP_BOMB", "expansion ratio exceeds the limit", n))
        if any(low.startswith(p.lower()) for p in FORBIDDEN_PREFIXES) or any(x in low for x in FORBIDDEN_NAME_PARTS):
            problems.append(_p("FORBIDDEN_PART", "macros, external links, embedded objects, connections and pivot caches are not allowed", n))
    if total > lim.max_total_bytes:
        problems.append(_p("ZIP_BOMB", f"{total} bytes total uncompressed exceeds {lim.max_total_bytes}"))
    return None if problems else zf


def _read(zf, name, lim, problems):
    try:
        with zf.open(name) as fh:
            data = fh.read(lim.max_member_bytes + 1)   # headers can lie; bound the real read
    except KeyError:
        problems.append(_p("MISSING_PART", "required package part is missing", name))
        return None
    except (zipfile.BadZipFile, RuntimeError, OSError, zlib.error, EOFError, NotImplementedError, struct.error) as exc:
        problems.append(_p("NOT_XLSX", f"cannot read package part ({type(exc).__name__})", name))
        return None
    if len(data) > lim.max_member_bytes:
        problems.append(_p("MEMBER_TOO_LARGE", "member larger than its declared size", name))
        return None
    return data


def _rels(zf, path, lim, problems, warnings):
    data = _read(zf, path, lim, problems) if path in zf.namelist() else None
    out = {}
    if data is None:
        return out
    root = _xml(data, path, problems)
    if root is None:
        return out
    base = posixpath.dirname(posixpath.dirname(path))
    for r in root:
        target, mode, typ = r.get("Target", ""), r.get("TargetMode", "Internal"), r.get("Type", "")
        if mode == "External":
            if typ.endswith("/hyperlink"):
                warnings.append(_p("EXTERNAL_HYPERLINK_IGNORED", "an external hyperlink was ignored", path))
            else:
                problems.append(_p("EXTERNAL_RELATIONSHIP", f"external relationship of type {typ.rsplit('/', 1)[-1]} is not allowed", path))
            continue
        out[r.get("Id")] = posixpath.normpath(target[1:] if target.startswith("/") else posixpath.join(base, target))
    return out


def _date_styles(zf, lim, problems):
    if "xl/styles.xml" not in zf.namelist():
        return []
    data = _read(zf, "xl/styles.xml", lim, problems)
    root = _xml(data, "xl/styles.xml", problems) if data is not None else None
    if root is None:
        return []
    custom = {}
    for nf in root.iter(f"{{{MAIN_NS}}}numFmt"):
        code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", nf.get("formatCode", ""))
        custom[int(nf.get("numFmtId", "0"))] = bool(_DATE_TOKEN.search(code))
    flags = []
    xfs = root.find(f"{{{MAIN_NS}}}cellXfs")
    for xf in (xfs if xfs is not None else []):
        fid = int(xf.get("numFmtId", "0"))
        flags.append(custom.get(fid, fid in BUILTIN_DATE_FMTS))
    return flags


def _shared_strings(zf, lim, problems):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    data = _read(zf, "xl/sharedStrings.xml", lim, problems)
    root = _xml(data, "xl/sharedStrings.xml", problems) if data is not None else None
    out = []
    t_tag, r_tag = f"{{{MAIN_NS}}}t", f"{{{MAIN_NS}}}r"
    for si in (root if root is not None else []):
        parts = []
        for child in si:                       # linear: <t> and <r><t> only; phonetic runs (rPh) are skipped, never searched
            if child.tag == t_tag:
                parts.append(child.text or "")
            elif child.tag == r_tag:
                parts.extend(t.text or "" for t in child if t.tag == t_tag)
        out.append("".join(parts))
    return out


def _serial_to_date(serial, date1904):
    base = datetime.date(1904, 1, 1) if date1904 else datetime.date(1899, 12, 30)
    return (base + datetime.timedelta(days=int(serial))).isoformat()


def _sheet(zf, path, name, state, shared, date_flags, date1904, lim, problems, keep_cached, warnings_out):
    sh = Sheet(name, state)
    data = _read(zf, path, lim, problems)
    root = _xml(data, path, problems) if data is not None else None
    if root is None:
        return sh
    for col in root.iter(f"{{{MAIN_NS}}}col"):
        if col.get("hidden", "0").lower() in ("1", "true"):
            problems.append(_p("HIDDEN_COLUMN", "hidden columns are not accepted", name))
    sd = root.find(f"{{{MAIN_NS}}}sheetData")
    for mc in root.iter(f"{{{MAIN_NS}}}mergeCell"):
        sh.merges.append(mc.get("ref"))
    n = 0
    for row in (sd if sd is not None else []):
        if row.get("hidden", "0").lower() in ("1", "true"):
            problems.append(_p("HIDDEN_ROW", "hidden rows are not accepted", name))
        for c in row:
            ref = c.get("r", "")
            m = _CELL_REF.match(ref)
            if not m:
                problems.append(_p("BAD_CELL_REF", f"invalid cell reference {ref!r}", name))
                continue
            col, r = _col_index(m.group(1)), int(m.group(2))
            if (r, col) in sh.cells:
                problems.append(_p("DUPLICATE_CELL", f"cell {ref} is defined twice", name))
                continue
            if r > lim.max_rows or col > lim.max_cols:
                problems.append(_p("SHEET_TOO_LARGE", f"cell {ref} is outside the {lim.max_rows}x{lim.max_cols} limit", name))
                continue
            n += 1
            if n > lim.max_cells_per_sheet:
                problems.append(_p("SHEET_TOO_LARGE", "too many cells", name))
                return sh
            f = c.find(f"{{{MAIN_NS}}}f")
            v = c.find(f"{{{MAIN_NS}}}v")
            t = c.get("t", "n")
            s_idx = int(c.get("s", "0") or 0)
            is_date = s_idx < len(date_flags) and date_flags[s_idx]
            vtext = v.text if v is not None and v.text is not None else None
            if f is not None:
                ftext = (f.text or "").strip()
                if f.get("t") in ("dataTable",) or len(ftext) > lim.max_formula_len:
                    problems.append(_p("UNSAFE_FORMULA", "data-table or oversized formula", f"{name}!{ref}"))
                if ftext and UNSAFE_FORMULA.search(ftext):
                    problems.append(_p("UNSAFE_FORMULA", "formula references an external resource or an unsafe function", f"{name}!{ref}"))
                if t == "e":
                    warnings_out.append(_p("FORMULA_SHOWS_ERROR", "a computed cell holds an error in the file (ignored; Python recomputes everything)", f"{name}!{ref}"))
                cached = vtext if keep_cached else None
                sh.cells[(r, col)] = Cell("f", None, ftext or "<shared>", _decode(t, cached, c, shared, is_date, date1904, name, ref, problems) if keep_cached else None)
                continue
            if t == "inlineStr":
                is_ = c.find(f"{{{MAIN_NS}}}is")
                text = "".join(x.text or "" for x in is_.iter(f"{{{MAIN_NS}}}t")) if is_ is not None else ""
                sh.cells[(r, col)] = Cell("s", text)
                continue
            if vtext is None:
                continue
            cell = _decode(t, vtext, c, shared, is_date, date1904, name, ref, problems)
            if cell is not None:
                sh.cells[(r, col)] = cell
    return sh


def _decode(t, vtext, c, shared, is_date, date1904, name, ref, problems):
    if vtext is None:
        return None
    if t == "s":
        try:
            return Cell("s", shared[int(vtext)])
        except (ValueError, IndexError):
            problems.append(_p("BAD_SHARED_STRING", "shared string index out of range", f"{name}!{ref}"))
            return None
    if t in ("str", "inlineStr"):
        return Cell("s", vtext)
    if t == "b":
        return Cell("b", vtext.strip() == "1")
    if t == "e":
        return Cell("e", vtext)
    if t == "d":
        try:
            if not _ISO_DATE.fullmatch(vtext.strip()):
                raise ValueError
            return Cell("d", datetime.date.fromisoformat(vtext.strip()[:10]).isoformat())
        except ValueError:
            problems.append(_p("BAD_DATE", f"invalid ISO date {vtext!r}", f"{name}!{ref}"))
            return None
    if not _NUMBER.fullmatch(vtext.strip(" \t\r\n")):
        problems.append(_p("BAD_NUMBER", "numeric cell is not plain ASCII decimal notation", f"{name}!{ref}"))
        return None
    try:
        d = Decimal(vtext.strip())
    except InvalidOperation:
        problems.append(_p("BAD_NUMBER", f"unparseable numeric value {vtext!r}", f"{name}!{ref}"))
        return None
    if not d.is_finite():
        problems.append(_p("BAD_NUMBER", "non-finite number", f"{name}!{ref}"))
        return None
    if is_date:
        try:
            return Cell("d", _serial_to_date(d, date1904))
        except (OverflowError, ValueError):
            problems.append(_p("BAD_DATE", f"date serial {vtext} out of range", f"{name}!{ref}"))
            return None
    return Cell("n", d)


def read_workbook(data, limits=None, keep_cached=False):
    """Parse bytes of an .xlsx into a Workbook. Raises WorkbookRejected listing every structural problem found.
    Whatever a hostile file does to the parser, the caller sees WorkbookRejected, never a raw exception."""
    try:
        return _read_workbook(data, limits, keep_cached)
    except WorkbookRejected:
        raise
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError, OverflowError, UnicodeError,
            zipfile.BadZipFile, ET.ParseError, MemoryError, zlib.error, EOFError, NotImplementedError, struct.error,
            OSError, RuntimeError, LookupError) as exc:
        raise WorkbookRejected([_p("MALFORMED_WORKBOOK", f"the workbook could not be parsed safely ({type(exc).__name__})")]) from None


def _read_workbook(data, limits, keep_cached):
    lim = limits or Limits()
    problems, warnings = [], []
    zf = _container(data, lim, problems)
    if zf is None:
        raise WorkbookRejected(problems)
    names = set(zf.namelist())
    ct = _read(zf, "[Content_Types].xml", lim, problems)
    ctroot = _xml(ct, "[Content_Types].xml", problems) if ct is not None else None
    if ctroot is not None:
        types = [o.get("ContentType", "") for o in ctroot]
        if any("macroEnabled" in t or "vbaProject" in t for t in types):
            problems.append(_p("MACROS_FORBIDDEN", "macro-enabled workbooks are not accepted"))
        if not any(o.get("PartName") == "/xl/workbook.xml" and o.get("ContentType") == WORKBOOK_CT for o in ctroot):
            problems.append(_p("NOT_XLSX", "/xl/workbook.xml is not a plain .xlsx workbook part"))
    wbdata = _read(zf, "xl/workbook.xml", lim, problems) if "xl/workbook.xml" in names else None
    if wbdata is None:
        problems.append(_p("MISSING_PART", "xl/workbook.xml is missing"))
        raise WorkbookRejected(problems)
    wbroot = _xml(wbdata, "xl/workbook.xml", problems)
    if wbroot is None or problems:
        raise WorkbookRejected(problems)
    if wbroot.find(f"{{{MAIN_NS}}}externalReferences") is not None:
        problems.append(_p("EXTERNAL_LINKS", "workbook declares external references"))
    for dn in wbroot.iter(f"{{{MAIN_NS}}}definedName"):
        if UNSAFE_FORMULA.search(dn.text or ""):
            problems.append(_p("UNSAFE_FORMULA", f"defined name {dn.get('name')!r} points outside the workbook", "xl/workbook.xml"))
    pr = wbroot.find(f"{{{MAIN_NS}}}workbookPr")
    date1904 = pr is not None and pr.get("date1904", "false").lower() in ("1", "true")
    rels = _rels(zf, "xl/_rels/workbook.xml.rels", lim, problems, warnings)
    shared = _shared_strings(zf, lim, problems)
    date_flags = _date_styles(zf, lim, problems)
    wb = Workbook()
    wb.warnings = warnings
    used_parts = set()
    sheets_el = wbroot.find(f"{{{MAIN_NS}}}sheets")
    for s in (sheets_el if sheets_el is not None else []):
        name, state = s.get("name", ""), s.get("state", "visible")
        path = rels.get(s.get(f"{{{REL_NS}}}id"))
        if name in wb.sheets:
            problems.append(_p("DUPLICATE_SHEET", "duplicate sheet name", name))
            continue
        if path is None or path not in names:
            problems.append(_p("MISSING_PART", "sheet part not found", name))
            continue
        if path in used_parts:
            problems.append(_p("DUPLICATE_SHEET_PART", "two sheets point at the same worksheet part", name))
            continue
        used_parts.add(path)
        wb.sheets[name] = _sheet(zf, path, name, state, shared, date_flags, date1904, lim, problems, keep_cached, warnings)
        # per-sheet relationships: external hyperlinks are ignored with a warning, anything else external is rejected
        srel = posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels")
        if srel in names:
            _rels(zf, srel, lim, problems, warnings)
    if problems:
        raise WorkbookRejected(problems)
    return wb


def check_text(cell):
    """Return a problem code if a string cell is unsafe to carry (control chars, formula-injection lead), else None."""
    if cell.kind != "s":
        return None
    s = cell.value
    if len(s) > Limits.max_string_len:
        return "TEXT_TOO_LONG"
    if _CTRL.search(s):
        return "CONTROL_CHARACTERS"
    if _BIDI.search(s):
        return "INVISIBLE_CHARACTERS"
    if s[:1] in ("=", "@", "\t", "\r", "+") or (s[:1] == "-" and not s[1:2].isdigit() and s[1:2] != " "):
        return "FORMULA_LIKE_TEXT"
    return None
