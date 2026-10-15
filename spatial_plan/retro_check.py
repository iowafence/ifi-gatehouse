"""Applies the pre-registered oracle v3 RETROSPECTIVELY to the stored response of run spatial_c101_live_002 (type-tag claims A and B). Not part of that run's original scoring."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from oracle3 import Oracle3
HERE = pathlib.Path(__file__).resolve().parent.parent; EXP = HERE / "amd_experiment"
cfg = json.loads((EXP / "experiments/c101_base_plan_crop_ansi_b_v2.json").read_text())
raw = json.loads((EXP / "runs_v2/dp001_ansi_b_v2_drawings/62ab61d7f255/spatial_c101_live_002/stage1_raw_response.json").read_text())
obj = json.loads(raw["content"]); o = Oracle3(HERE / "dp001/documents/DP001_Drawings_IFB_Rev0_ANSI_B.pdf", cfg); out = []
try:
    for a in obj["visual_associations"]:
        if a["kind"] == "fence_type_tag": out.append({"model_claim": a, **o.check_type_tag_claim(a["label"], a["enclosure_side"])})
finally: o.close()
print(json.dumps(out, indent=1))
