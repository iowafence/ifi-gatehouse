"""Parity of web/lib/takeoff.ts (runtime) against the independently prepared reference dp001_takeoff_review.py for G3 = unresolved and 1..61 ft.
Runs the TS module with node's built-in type stripping (it has no imports). Exit 0 only if every compared value is identical."""
import json, pathlib, subprocess, sys
from decimal import Decimal as D
HOME = pathlib.Path.home()
PACK = pathlib.Path(__file__).resolve().parent / "reference"; sys.path.insert(0, str(PACK))
from dp001_takeoff_review import reconcile as ref
WS = pathlib.Path(__file__).resolve().parent.parent
js = f"""
import {{ reconcile }} from '{WS}/web/lib/takeoff.ts';
const out = {{}};
for (const s of ['base','alt']) {{
  out[s] = {{ null: reconcile(s, null) }};
  for (let g = 1; g <= 61; g += 0.5) {{ try {{ out[s][String(g)] = reconcile(s, g); }} catch (e) {{ out[s][String(g)] = {{ error: String(e.message) }}; }} }}
}}
console.log(JSON.stringify(out));
"""
tmp = WS / "dp001" / "_parity_run.mjs"; tmp.write_text(js)
res = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(tmp)], capture_output=True, text=True)
if res.returncode: print(res.stderr); sys.exit(2)
ts = json.loads(res.stdout); bad = []; n = 0
for s_ts, s_py in (("base", "base"), ("alt", "alternate_a1")):
    for key, got in ts[s_ts].items():
        g = None if key == "null" else D(key)
        try: want = ref(s_py, g)
        except ValueError:
            n += 1
            if "error" not in got: bad.append((s_ts, key, "reference rejects, TS accepts"))
            continue
        n += 1
        if "error" in got: bad.append((s_ts, key, "TS rejects: " + got["error"])); continue
        pairs = [("gross_fence_lf", got["gross"]["total"]), ("gross_type_a_lf", got["gross"]["type_a"]), ("gross_type_b_lf", got["gross"]["type_b"]),
                 ("net_type_a_lf", got["net"]["type_a"]), ("net_type_b_lf", got["net"]["type_b"]), ("net_fence_lf", got["net"]["total"]),
                 ("windscreen_south_lf", got["accessories"]["windscreen_lf"]), ("fence_guard_type_b_lf", got["accessories"]["fence_guard_lf"]),
                 ("known_gate_openings_lf", got["known_openings_lf"]), ("total_core_drill_holes", got["holes"]["total"])]
        for k, v in pairs:
            w = want[k]
            if (w is None) != (v is None) or (w is not None and abs(float(w) - float(v)) > 1e-9): bad.append((s_ts, key, k, w, v))
        if want["type_a_post_count"] is not None:
            cl = {c["id"]: c["count"] for c in got["classes"]}
            exp = {"a_line": want["type_a_post_count"]["line"], "a_terminal": want["type_a_post_count"]["corners"], "b_line": want["type_b_post_count"]["line"], "b_terminal": want["type_b_post_count"]["terminals"],
                   "g3_gate": want["type_a_post_count"]["gate_posts_unknown_size_g3"], "g12_gate": want["type_a_post_count"]["gate_posts_total"] - want["type_a_post_count"]["gate_posts_unknown_size_g3"]}
            for k, v in exp.items():
                if cl[k] != v: bad.append((s_ts, key, "class " + k, v, cl[k]))
            if [float(x) for x in want["nominal_type_a_segment_lf"]] != got["segments"]["type_a"]: bad.append((s_ts, key, "segments"))
print(json.dumps({"compared_cases": n, "mismatches": len(bad), "first": bad[:5]})); sys.exit(1 if bad else 0)
