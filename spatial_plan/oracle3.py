"""Spatial oracle v3 (PRE-REGISTERED before any live call). Adds the one thing oracle v2 could not establish: which drawn element a fence-type tag's LEADER ends on.
Everything is derived from the PDF's own vector objects (never from a model): the tag diamond (0.349 pt stroke around the tag letter), its leader (0.249 pt stroke path
touching the diamond), the leader's far end, and the structure nearest that end (the heavy perimeter enclosure or an interior Type B divider stroke).
Run with the experiment interpreter. No network. No quantity, length or price is produced."""
import math, pathlib, sys
sys.path.insert(0, str(pathlib.Path.home() / "ifi-amd-inference-experiment"))
from ext import spatial2, vector_inventory          # noqa: E402

TOL_IN = 0.08                  # a leader end counts as 'on' a structure when within 0.08 sheet-inch
DIAMOND_STROKE = (0.30, 0.40); LEADER_STROKE = (0.20, 0.30); DIVIDER_STROKE = (1.0, 1.4)


class Oracle3:
    def __init__(self, pdf, cfg):
        self.o2 = spatial2.Oracle2(pdf, cfg)
        self.paths = self.o2.vectors["paths"]; self.k = self.o2.in_per_norm
        self.dividers = [p for p in self.paths if DIVIDER_STROKE[0] <= p["stroke_width_pt"] <= DIVIDER_STROKE[1] and p["h_pt"] > 50 and spatial2._in(p["rect_norm"], self.o2.crop, 0.0)]

    def close(self): self.o2.close()

    def _d(self, pt, rect):                                    # distance in sheet inches from a point to a rectangle
        dx = max(rect[0] - pt[0], 0, pt[0] - rect[2]) * self.k[0]; dy = max(rect[1] - pt[1], 0, pt[1] - rect[3]) * self.k[1]
        return math.hypot(dx, dy)

    def leader_target(self, tag):
        r = self.o2.fence_type_tags().get(tag)
        if not r: return {"tag": tag, "verdict": "TAG_NOT_FOUND"}
        tr = r[0]; cx, cy = (tr[0] + tr[2]) / 2, (tr[1] + tr[3]) / 2
        sq = [p for p in self.paths if DIAMOND_STROKE[0] <= p["stroke_width_pt"] <= DIAMOND_STROKE[1] and 18 <= p["w_pt"] <= 21 and abs(p["w_pt"] - p["h_pt"]) < 1.0]
        dia = [p for p in sq if math.hypot(((p["rect_norm"][0] + p["rect_norm"][2]) / 2 - cx) * self.k[0], ((p["rect_norm"][1] + p["rect_norm"][3]) / 2 - cy) * self.k[1]) <= 0.35]   # nearest 19.7 pt diamond within 0.35 sheet-inch of the tag text
        if not dia: return {"tag": tag, "verdict": "NO_DIAMOND_FOUND"}
        d = min(dia, key=lambda p: math.hypot(((p["rect_norm"][0] + p["rect_norm"][2]) / 2 - cx) * self.k[0], ((p["rect_norm"][1] + p["rect_norm"][3]) / 2 - cy) * self.k[1]))["rect_norm"]; dc = ((d[0] + d[2]) / 2, (d[1] + d[3]) / 2)
        near = lambda a, b, m=0.004: not (a[2] < b[0] - m or a[0] > b[2] + m or a[3] < b[1] - m or a[1] > b[3] + m)
        leaders = [p for p in self.paths if LEADER_STROKE[0] <= p["stroke_width_pt"] <= LEADER_STROKE[1] and near(p["rect_norm"], d) and spatial2._in(p["rect_norm"], self.o2.crop, 0.0)]
        if len(leaders) != 1: return {"tag": tag, "verdict": "LEADER_NOT_UNIQUE", "leaders_found": len(leaders)}
        lr = leaders[0]["rect_norm"]; corners = [(lr[0], lr[1]), (lr[0], lr[3]), (lr[2], lr[1]), (lr[2], lr[3])]
        far = max(corners, key=lambda c: math.hypot((c[0] - dc[0]) * self.k[0], (c[1] - dc[1]) * self.k[1]))
        e = self.o2.enclosure; edge = {"left": abs(far[0] - e[0]) * self.k[0], "right": abs(far[0] - e[2]) * self.k[0], "top": abs(far[1] - e[1]) * self.k[1], "bottom": abs(far[1] - e[3]) * self.k[1]}
        side = min(edge, key=edge.get); d_per = edge[side]
        d_div = min(self._d(far, p["rect_norm"]) for p in self.dividers) if self.dividers else 99.0
        if d_per <= TOL_IN and d_per <= d_div: element, detail = "perimeter_fence", {"enclosure_side": side, "distance_in": round(d_per, 3)}
        elif d_div <= TOL_IN: element, detail = "interior_divider", {"enclosure_side": "interior", "distance_in": round(d_div, 3)}
        else: element, detail = "unclear", {"nearest_perimeter_in": round(d_per, 3), "nearest_divider_in": round(d_div, 3)}
        return {"tag": tag, "verdict": "LEADER_TARGET_DERIVED", "element": element, **detail, "leader_far_end_norm": [round(far[0], 4), round(far[1], 4)], "diamond_norm": [round(x, 4) for x in d]}

    def check_type_tag_claim(self, tag, claimed_element, claimed_side=None):
        t = self.leader_target(tag)
        if t["verdict"] != "LEADER_TARGET_DERIVED": return {**t, "claim_verdict": "NOT_VERIFIABLE"}
        elt_ok = (claimed_element == t["element"]) or (claimed_element in ("top", "bottom", "left", "right") and t["element"] == "perimeter_fence" and claimed_element == t["enclosure_side"])
        side_ok = claimed_side is None or claimed_side == t["enclosure_side"]
        return {**t, "claim_verdict": "CONFIRMED_BY_VECTOR_GEOMETRY" if elt_ok and side_ok else "CONTRADICTED_BY_VECTOR_GEOMETRY"}
