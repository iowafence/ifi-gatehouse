#!/usr/bin/env python3
"""Stage the ONE recorded capture the hosted image replays: f0b0571c9696_call3.json, the verbatim record of the live parse of Addendum 02.
Copies exactly that file, byte for byte, into hosting/staged/captures/ (git-ignored). Never copies ledger.json or any other file from the captures folder.
Refuses unless the capture's hash and its recorded source document hash both match. READ-ONLY toward the source.
Usage: hosting/stage_capture.py [CAPTURE_DIR=~/ifi-gatehouse-live-captures]"""
import hashlib, json, pathlib, sys
NAME = "f0b0571c9696_call3.json"
CAPTURE_SHA256 = "ad91cd1e30d8c87350665a5181a7723116bd927aa96bbb3ed5748ab50f5b6fa6"
SOURCE_SHA256 = "f0b0571c9696517676320d5b7dcf02cbff214149b0db9f6147913ff15ed00aef"   # ADDENDUM_02.pdf
root = pathlib.Path(__file__).resolve().parent.parent
src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "~/ifi-gatehouse-live-captures").expanduser() / NAME
b = src.read_bytes() if src.is_file() else sys.exit(f"MISSING capture: {src}")
if hashlib.sha256(b).hexdigest() != CAPTURE_SHA256: sys.exit("HASH MISMATCH: capture is not the expected file. Nothing written.")
if json.loads(b).get("source_sha256") != SOURCE_SHA256: sys.exit("SOURCE MISMATCH: capture is not for ADDENDUM_02.pdf. Nothing written.")
out = root / "hosting/staged/captures" / NAME
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b); out.chmod(0o644)
print(f"staged {out} sha256={CAPTURE_SHA256}")
