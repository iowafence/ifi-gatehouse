#!/usr/bin/env python3
"""Build guard for the ONE recorded capture the hosted image replays: hosting/captures/f0b0571c9696_call3.json, the verbatim record of the live parse of Addendum 02.
The file is tracked in the repository. This script copies nothing: it REFUSES (non-zero exit) unless the tracked capture is byte-identical to the expected hash, names
ADDENDUM_02.pdf as its source, is the only file in hosting/captures, and the pinned sample PDF matches its SHA-256. The Dockerfile repeats the hash check at build time.
Usage: hosting/stage_capture.py   (run from anywhere; READ-ONLY)"""
import hashlib, json, pathlib, sys
NAME = "f0b0571c9696_call3.json"
CAPTURE_SHA256 = "ad91cd1e30d8c87350665a5181a7723116bd927aa96bbb3ed5748ab50f5b6fa6"
SOURCE_SHA256 = "f0b0571c9696517676320d5b7dcf02cbff214149b0db9f6147913ff15ed00aef"   # ADDENDUM_02.pdf
root = pathlib.Path(__file__).resolve().parent.parent
d = root / "hosting/captures"
src = d / NAME
b = src.read_bytes() if src.is_file() else sys.exit(f"MISSING capture: {src}")
if hashlib.sha256(b).hexdigest() != CAPTURE_SHA256: sys.exit("HASH MISMATCH: the tracked capture is not the expected file.")
if json.loads(b).get("source_sha256") != SOURCE_SHA256: sys.exit("SOURCE MISMATCH: the capture is not for ADDENDUM_02.pdf.")
if sorted(p.name for p in d.iterdir()) != [NAME]: sys.exit("EXTRA FILES in hosting/captures: only the one capture may be there (never ledger.json or another capture).")
pdf = root / "samples/public-demo/dp001/ADDENDUM_02.pdf"
if hashlib.sha256(pdf.read_bytes()).hexdigest() != SOURCE_SHA256: sys.exit("SAMPLE PDF MISMATCH: ADDENDUM_02.pdf is not at the pinned SHA-256.")
print(f"capture ok sha256={CAPTURE_SHA256}; sample PDF ok sha256={SOURCE_SHA256}")
