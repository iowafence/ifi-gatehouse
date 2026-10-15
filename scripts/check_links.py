#!/usr/bin/env python3
"""Fail if a relative Markdown link in a tracked .md file points at a path that does not exist."""
import pathlib, re, subprocess, sys

root = pathlib.Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
files = subprocess.check_output(["git", "ls-files", "*.md"], text=True, cwd=root).split()
bad = 0
for f in files:
    text = (root / f).read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        path = (root / f).parent / target.split("#")[0]
        if not path.exists():
            print(f"BROKEN LINK in {f}: {target}", file=sys.stderr)
            bad = 1
sys.exit(bad)
