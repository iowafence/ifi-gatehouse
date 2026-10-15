"""Server-side rate-book store. The rate book is an authenticated, server-held pricing source, never a public file.

  * root is a private directory (mode 0700) outside any served path; files are 0600 and content-addressed by sha256,
    so a name can never be attacker-chosen and there is no path to traverse;
  * put() validates the upload with the hardened importer BEFORE anything is written, and returns metadata only;
  * get() re-derives the content hash from the stored JSON, so a tampered or corrupted file is refused;
  * nothing here logs or returns rate values. Log `loggable(problems)`, never the problem messages (they can quote cells)."""
import hashlib
import json
import os
import pathlib
import re
import tempfile

from . import ratebook as rb

_HEX = re.compile(r"^[0-9a-f]{64}$")


def default_root():
    return pathlib.Path(os.environ.get("GATEHOUSE_RATEBOOK_DIR") or (pathlib.Path.home() / ".local/share/ifi-gatehouse/ratebooks"))


def loggable(problems):
    """Codes and locations only. Messages may echo cell contents, which are the company's rates."""
    return [{"code": p["code"], "where": p.get("where")} for p in problems]


class StoreError(Exception):
    pass


class RateBookStore:
    def __init__(self, root=None):
        self.root = pathlib.Path(root or default_root()).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if self.root.stat().st_mode & 0o077:
            raise StoreError("rate-book directory must not be accessible to group or others")

    def _path(self, digest, ext):
        if not _HEX.match(digest or ""):
            raise StoreError("not a content hash")
        return self.root / f"{digest}.{ext}"

    def _write(self, path, data):
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def put(self, data, *, as_of=None):
        """Validate then store. Raises RateBookRejected on any problem; nothing is written in that case."""
        result = rb.import_workbook(data, as_of=as_of)
        book = result["ratebook"]
        self._write(self._path(book["hashes"]["file_sha256"], "xlsx"), data)
        self._write(self._path(book["hashes"]["content_sha256"], "json"), rb.canonical(book).encode())
        return {"ref": rb.ref(book), "warnings": result["warnings"], "report": result["report"]}

    def get(self, content_sha256):
        path = self._path(content_sha256, "json")
        if not path.exists():
            raise StoreError("no such rate book")
        try:
            book = json.loads(path.read_bytes())
            hashes = book["hashes"]
            labor = hashlib.sha256(rb.canonical({k: book[k] for k in ("roles", "crews", "labor_tasks", "crew_options")}).encode()).hexdigest()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise StoreError("stored rate book is unreadable") from None
        recomputed = hashlib.sha256(rb.canonical(self._body_for_hash(book)).encode()).hexdigest()
        if recomputed != content_sha256 or hashes.get("content_sha256") != content_sha256 or hashes.get("labor_sha256") != labor:
            raise StoreError("stored rate book failed its integrity check")
        return book

    @staticmethod
    def _body_for_hash(book):
        return {k: v for k, v in book.items() if k != "hashes"}

    def refs(self):
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(rb.ref(self.get(p.stem)))
            except (StoreError, KeyError, ValueError):
                continue
        return out
