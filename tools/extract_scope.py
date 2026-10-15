#!/usr/bin/env python3
"""Vision extraction: bid-package PDF pages -> structured scope JSON, via ANY OpenAI-compatible endpoint
(the judged path is vLLM on AMD Developer Cloud; swap by changing env vars only).

  export LLM_BASE_URL=http://<droplet-ip>:8000/v1   LLM_MODEL=<model>   LLM_API_KEY=<key>
  python3 tools/extract_scope.py plans.pdf --pages 3 6 --specs specs.pdf --spec-pages 29 144 145 146 -o scope.json

Needs poppler (pdftoppm, pdftotext). Standard library only otherwise.
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine.validate import validate_scope  # noqa: E402

SYSTEM = """You extract facts from construction bid documents into JSON for a deterministic estimating engine.
HARD RULES
1. Output ONLY one JSON object. No prose, no markdown.
2. NEVER guess. If the documents do not support a value, set "value": null and "status": "unresolved".
3. If two places in the documents state different values for the same fact, set value null, status "unresolved",
   and list BOTH in "evidence" with "stated_value" and "source_type" for each. Do not pick one.
4. Every fact is an object: {"value":..., "status": "confirmed"|"inferred"|"unresolved", "evidence":[...]}.
   "confirmed" = stated directly (needs evidence). "inferred" = you derived it (needs "inference_note" with the formula).
5. Evidence item: {"doc_id","page","sheet_label","source_type":"plan_sheet|schedule|detail|spec_section|general_note|addendum",
   "stated_value","excerpt"(<=200 chars)}.
6. NEVER output prices, costs, rates, totals, markups or labor. Quantities and specifications only.
7. Owner-selected colors/finishes that do not affect price: status "unresolved" with "price_affecting": false.
8. If a pay item or quantity table exists, copy its stated quantities into bid_structure.pay_items (stated_qty_base,
   stated_qty_alt). Do NOT adjust your own derived geometry to match the table.
TARGET SHAPE (abbreviated): {"scope_version":1,"project_ref":"...","documents":[],
 "fence_runs":[{"run_id":"FR-001","fence_type":FACT,"height_ft":FACT,"length_lf":FACT,"section_spacing_ft":FACT,
   "repeat":1,"post":{"terminal_od_in":FACT,"line_od_in":FACT},"geometry":{"closed":true,"corners":4}}],
 "gates":[{"gate_id","run_id","gate_kind":FACT,"clear_width_ft":FACT,"height_ft":FACT,"quantity":1,"transom":{"height_ft":FACT}}],
 "accessories":[{"accessory_id","kind":"windscreen|fence_guard","length_lf":FACT,"color":FACT,...}],
 "bid_structure":{"pricing_basis":"unit_price|lump_sum","pay_items":[{"item_no","description","unit","stated_qty_base","stated_qty_alt","in_engine_scope"}],
   "alternates":[{"alternate_id","label","scope_change"}],"selected_bid":{"value":null,"status":"unresolved"}},
 "global_requirements":{"core_drilling_required":FACT}}"""


def render(pdf, page, dpi):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", pdf, f"{d}/p"],
                       check=True, capture_output=True)
        f = next(x for x in sorted(os.listdir(d)) if x.endswith(".png"))
        return base64.b64encode(open(os.path.join(d, f), "rb").read()).decode()


def text_layer(pdf, page, limit=6000):
    r = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", pdf, "-"], capture_output=True, text=True)
    return re.sub(r"[ \t]{3,}", "  ", r.stdout)[:limit]


def chat(messages, base_url, model, api_key, max_tokens=8000, timeout=600, json_mode=True):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code == 400 and json_mode:   # endpoint without json_object support: retry plain
            return chat(messages, base_url, model, api_key, max_tokens, timeout, json_mode=False)
        raise


def parse_json(txt):
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    s, e = txt.find("{"), txt.rfind("}")
    return json.loads(txt[s:e + 1])


def build_content(sources, dpi):
    content = [{"type": "text", "text": "Extract the structured fence scope from these pages."}]
    for doc_id, pdf, pages in sources:
        for pg in pages:
            content.append({"type": "text", "text": f"--- doc_id={doc_id} page={pg} (text layer below, may be garbled; trust the image)\n{text_layer(pdf, pg)}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{render(pdf, pg, dpi)}"}})
    return content


def extract(sources, base_url, model, api_key, dpi=110, retries=1):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": build_content(sources, dpi)}]
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        raw = chat(messages, base_url, model, api_key)
        latency = round(time.time() - t0, 2)
        try:
            scope = parse_json(raw)
        except Exception as ex:
            last = {"error": f"unparseable JSON: {ex}", "raw": raw[:500], "latency_s": latency}
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Return ONLY the JSON object, nothing else."})
            continue
        problems = validate_scope(scope)
        last = {"scope": scope, "problems": problems, "latency_s": latency, "attempt": attempt + 1}
        if not problems:
            return last
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": "Fix these problems and return the full JSON again:\n- " + "\n- ".join(problems[:20])})
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plans"); ap.add_argument("--pages", nargs="+", type=int, required=True)
    ap.add_argument("--specs"); ap.add_argument("--spec-pages", nargs="*", type=int, default=[])
    ap.add_argument("--dpi", type=int, default=110); ap.add_argument("-o", "--out", default="scope.json")
    a = ap.parse_args()
    base, model, key = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL"), os.environ.get("LLM_API_KEY", "x")
    if not base or not model:
        sys.exit("set LLM_BASE_URL and LLM_MODEL (and LLM_API_KEY)")
    sources = [("PLANS", a.plans, a.pages)] + ([("SPECS", a.specs, a.spec_pages)] if a.specs and a.spec_pages else [])
    res = extract(sources, base, model, key, a.dpi)
    json.dump(res, open(a.out, "w"), indent=2)
    print(f"latency {res.get('latency_s')}s  attempts {res.get('attempt', '?')}  problems: {res.get('problems', res.get('error'))}")


if __name__ == "__main__":
    main()
