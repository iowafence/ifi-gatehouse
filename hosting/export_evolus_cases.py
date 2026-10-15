#!/usr/bin/env python3
"""Copy ANVIL 2's persisted review cases (and the run records they reference) into a world-readable drop directory for the Flight Recorder.
READ-ONLY toward the source: nothing in the source directory is modified, renamed or deleted (its files are mode 0600, which the container user cannot read).
Copies are byte-exact and verified by sha256. An existing destination file that differs from the source is never overwritten (the script stops and says so).
Usage: hosting/export_evolus_cases.py [SOURCE=~/ifi-gatehouse-evolus/evolus_runs] [DEST=~/gatehouse-evolus-cases]"""
import hashlib, json, os, pathlib, re, shutil, sys

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "~/ifi-gatehouse-evolus/evolus_runs").expanduser()
dst = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "~/gatehouse-evolus-cases").expanduser()
sha = lambda b: hashlib.sha256(b).hexdigest()
cases = sorted((src / "cases").glob("GH-CASE-*.json"))
if not cases: sys.exit(f"no cases found under {src}/cases")
want = {c: c.name for c in cases}
for c in cases:
    try: rid = json.loads(c.read_bytes())["run_id"]
    except Exception: sys.exit(f"{c.name}: unreadable or no run_id; not exporting")
    if not re.fullmatch(r"GH-RUN-[0-9a-f]{12}", str(rid)): sys.exit(f"{c.name}: bad run_id")
    r = src / f"{rid}.json"
    if r.exists(): want[r] = r.name
dst.mkdir(parents=True, exist_ok=True)
for s, name in want.items():
    data = s.read_bytes(); d = dst / name
    if d.exists():
        if d.read_bytes() != data: sys.exit(f"REFUSING: {d} exists and differs from {s}; not overwriting")
        print(f"unchanged {name}"); continue
    tmp = dst / f".w-{name}"; tmp.write_bytes(data); os.chmod(tmp, 0o644); os.replace(tmp, d)
    assert sha(d.read_bytes()) == sha(data), "verification failed"
    print(f"copied    {name}  sha256 {sha(data)}")
