#!/usr/bin/env python3
"""Stage the authentic Evolus execution evidence into release_evidence/ so the hosted image carries it (a host has no mounts). BYTE-EXACT copies only.
READ-ONLY toward every source: nothing is modified, renamed or deleted. A destination file that already exists and differs is never overwritten (stops and says so).
Every file must equal the sha256 recorded in LOOM's independent reports and pinned in web/lib/audit-manifest.ts, or nothing is written.
Usage: hosting/stage_release_evidence.py [TRACES=~/gatehouse-flight-traces] [CASES=~/gatehouse-evolus-cases] [LOOM_DIR=evidence/independent_rechecks]"""
import hashlib, pathlib, shutil, sys
root = pathlib.Path(__file__).resolve().parent.parent
traces = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "~/gatehouse-flight-traces").expanduser()
cases = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "~/gatehouse-evolus-cases").expanduser()
loom = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else root / "evidence/independent_rechecks").expanduser()
dst = root / "release_evidence"
EXPECT = {  # name -> sha256, from LOOM's re-check reports and the release manifest
 ("traces", "GH-TRACE-06b4b6d525133f8a.json"): "5aa339ec1bf7022ba98b505ba4ae6776c47aa9605870df24286ed21c0fe9bef8",
 ("traces", "GH-TRACE-2b2a7a1397a9599b.json"): "8cd25c9761ed13528a067e42c69feaa49e6b4f2d0889ac0b23ddd7dd2020d6bd",
 ("cases", "GH-CASE-5131630cf9d1.json"): "6e4319bc30b9f45092515492b6a4c99996856dc750e49236c73da45021984701",
 ("cases", "GH-CASE-b661ad38637b.json"): "7f7f5001a90639eb4b2cb210462384bf146cfa60b8a444eb2ca98168f341ed7b",
 ("cases", "GH-RUN-e5bbcecef551.json"): "7a4cc958f821f18ce4679a6fee428148c91c39de6ce9eaa3e27c50725fef70c4",
 ("loom", "LOOM-GH-RUN-e5bbcecef551-remediation-recheck.md"): "d6040e169d374b03f3b8336f4d255d31fd892ee08bcb7b201d3273b26aeabf05",
 ("loom", "LOOM-GH-RUN-e5bbcecef551-9aaa104-recheck.md"): "9ea27800330a4c954654358d37bd626b7333ec6934b65d8d7ddf4e69a0f3d414",
 ("loom", "LOOM-GH-RUN-e5bbcecef551-9b0a22f-spotcheck.md"): "c18af41ecc38d0eadc3d7388062558af977682702eec36ca64f7cc226f379aaa"}
SRC = {"traces": traces, "cases": cases, "loom": loom}
sha = lambda b: hashlib.sha256(b).hexdigest()
plan = []
for (kind, name), want in EXPECT.items():
    b = (SRC[kind] / name).read_bytes() if (SRC[kind] / name).exists() else sys.exit(f"MISSING source: {SRC[kind] / name}")
    if sha(b) != want: sys.exit(f"HASH MISMATCH {name}: source {sha(b)} != expected {want}. Nothing written.")
    out = dst / kind / name
    if out.exists() and sha(out.read_bytes()) != want: sys.exit(f"REFUSING to overwrite differing {out}")
    plan.append((out, b))
for out, b in plan:
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists(): out.write_bytes(b)
    out.chmod(0o644)
lines = "".join(f"{want}  {kind}/{name}\n" for (kind, name), want in sorted(EXPECT.items(), key=lambda kv: kv[0]))
(dst / "SHA256SUMS").write_text(lines); print(f"staged {len(plan)} files into {dst}; SHA256SUMS written"); print(lines, end="")
