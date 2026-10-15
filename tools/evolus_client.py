"""Evolus REST client. Env: EVOLUS_API_KEY, EVOLUS_APPLICATION_ID (EVOLUS_APP_ID accepted), EVOLUS_BASE_URL (EVOLUS_BASE accepted;
default https://api.evolus.ai/api/v1).
EVOLUS_MOCK=1 returns canned responses so the pipeline can be tested without credentials.
NOTE: endpoint path/shape taken from Evolus docs summary; confirm against /company/api-docs."""
import json, os, urllib.request

def _env(*names, default=None):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    return default


def execute_workflow(workflow_id, inputs):
    if os.environ.get("EVOLUS_MOCK") == "1":
        return {"mock": True, "workflow_id": workflow_id, "inputs": inputs}
    base = _env("EVOLUS_BASE_URL", "EVOLUS_BASE", default="https://api.evolus.ai/api/v1").rstrip("/")
    req = urllib.request.Request(f"{base}/workflows/{workflow_id}/execute", data=json.dumps(inputs).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-ApiKey": os.environ["EVOLUS_API_KEY"],
                                          "X-Application-Id": _env("EVOLUS_APPLICATION_ID", "EVOLUS_APP_ID")})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)
