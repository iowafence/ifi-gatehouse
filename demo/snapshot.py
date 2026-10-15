"""Evidence and source snapshot. Read-only except for writing demo/DEMO_SNAPSHOT_MANIFEST.json.
  python3 demo/snapshot.py            write the manifest (hashes of tracked application source, the frozen AMD evidence and key assets)
  python3 demo/snapshot.py --verify   recompute and compare with the committed manifest and with the frozen evidence manifests; exit 0 only if nothing drifted
Paths are repository-relative. No network, no AMD client."""
import hashlib, json, pathlib, sys
H = hashlib.sha256; HERE = pathlib.Path(__file__).resolve().parent; WS = HERE.parent
EXP = WS / "amd_experiment"
SKIP = {"node_modules", ".next", "__pycache__", "evidence", "demo", "documents"}
SRC_DIRS = ("web/app", "web/lib", "web/package.json", "web/next.config.ts", "dp001", "api", "engine", "pricing", "intake", "amd_bridge", "spatial_plan", "amd_experiment/ext", "harness", "e2e", "run")
def h(p): return H(pathlib.Path(p).read_bytes()).hexdigest()
def tree(root, parts):
    out = {}
    for part in parts:
        base = root / part
        files = [base] if base.is_file() else sorted(base.rglob("*")) if base.exists() else []
        for p in files:
            if p.is_file() and not (set(p.relative_to(root).parts) & SKIP) and p.suffix not in (".pyc", ".log") and not p.name.startswith("e2e_state_") and p.name != "tsconfig.tsbuildinfo":
                out[p.relative_to(root).as_posix()] = h(p)
    return out
def frozen():
    out = {}
    for n in ("FROZEN_TEST001.json", "FROZEN_TEST002.json"):
        m = json.loads((EXP / "runs_v2" / n).read_text())
        for rel, hh in m["files"].items(): out["experiment/" + rel] = {"expected": hh, "actual": h(EXP / rel)}
    m = json.loads((WS / "spatial_plan/FROZEN_TEST003.json").read_text())
    for rel, hh in m["files"].items(): out["spatial_plan/" + rel] = {"expected": hh, "actual": h(WS / rel)}
    return out
def build():
    fr = frozen()
    key = {"dp001/ai_findings.json": h(WS / "dp001/ai_findings.json"),
           "workbook": h(WS / "samples/public-demo/reference_pricing_workbook_v2_3_0.fictional.xlsx"),
           "source_pdf_ansi_b": h(WS / "samples/public-demo/dp001/DP001_Drawings_IFB_Rev0_ANSI_B.pdf"),
           "LIVE_CALLS_DISABLED": h(EXP / "LIVE_CALLS_DISABLED")}
    return {"frozen_amd_evidence_all_match": all(v["expected"] == v["actual"] for v in fr.values()), "frozen_files_checked": len(fr), "key_hashes": key, "source_files": tree(WS, SRC_DIRS)}
if __name__ == "__main__":
    m = build(); out = HERE / "DEMO_SNAPSHOT_MANIFEST.json"
    if "--verify" in sys.argv:
        old = json.loads(out.read_text())
        d = {"manifest_vs_current": sorted(k for k in set(old["source_files"]) | set(m["source_files"]) if old["source_files"].get(k) != m["source_files"].get(k)),
             "frozen_amd_evidence_all_match": m["frozen_amd_evidence_all_match"], "key_hashes_equal": old["key_hashes"] == m["key_hashes"]}
        print(json.dumps(d, indent=1)); sys.exit(1 if d["manifest_vs_current"] or not d["frozen_amd_evidence_all_match"] or not d["key_hashes_equal"] else 0)
    out.write_text(json.dumps(m, indent=1)); print(json.dumps({"written": out.name, "files": len(m["source_files"]), "frozen_all_match": m["frozen_amd_evidence_all_match"], "frozen_files_checked": m["frozen_files_checked"]}, indent=1))
