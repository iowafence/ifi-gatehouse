"""Validate a rate-book workbook before uploading it.   python3 -m pricing.cli validate BOOK.xlsx [--verbose] [--as-of YYYY-MM-DD]

Prints the verdict, the book's identity (id, version, hashes) and every problem as CODE + cell location. Messages are
hidden unless --verbose, because a message can quote a cell and a cell is the company's pricing. Exit status 0 = importable."""
import datetime
import pathlib
import sys

from . import ratebook as rb
from .store import loggable


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    verbose = "--verbose" in argv
    as_of = None
    for a in argv:
        if a.startswith("--as-of="):
            try:
                as_of = datetime.date.fromisoformat(a.split("=", 1)[1])
            except ValueError:
                print("--as-of must be YYYY-MM-DD")
                return 2
    if len(args) != 2 or args[0] != "validate":
        print(__doc__)
        return 2
    path = pathlib.Path(args[1])
    try:
        result = rb.import_workbook(path.read_bytes(), as_of=as_of)
    except OSError as exc:
        print(f"cannot read {path.name}: {type(exc).__name__}")
        return 2
    except rb.RateBookRejected as exc:
        print(f"REJECTED  {path.name}: {len(exc.problems)} problem(s)")
        for p in (exc.problems if verbose else loggable(exc.problems)):
            print("  " + "  ".join(f"{k}={v}" for k, v in p.items() if v is not None))
        return 1
    book, ref = result["ratebook"], rb.ref(result["ratebook"])
    print(f"ACCEPTED  {path.name}\n  book      {ref['ratebook_id']} v{ref['version']} effective {ref['effective_date']} ({book['meta']['data_classification']})")
    print(f"  content   {ref['content_sha256']}\n  labor     {ref['labor_sha256']}\n  file      {book['hashes']['file_sha256']}")
    print("  counts    " + ", ".join(f"{k}={v}" for k, v in result["report"].items()))
    for w in result["warnings"]:
        print(f"  warning   {w['code']}  {w.get('where') or ''}" + (f"  {w['message']}" if verbose else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
