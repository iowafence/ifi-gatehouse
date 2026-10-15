"""The client must read the variable names documented in .env.example, and never call out in these tests."""
import json, os, unittest
from unittest import mock

from tools import evolus_client


class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"{}"


class EvolusEnv(unittest.TestCase):
    def run_call(self, env):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
            return FakeResponse()

        keys = ("EVOLUS_BASE_URL", "EVOLUS_BASE", "EVOLUS_APPLICATION_ID", "EVOLUS_APP_ID", "EVOLUS_API_KEY", "EVOLUS_MOCK")
        clean = {k: v for k, v in os.environ.items() if k not in keys}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            evolus_client.execute_workflow("wf-1", {"a": 1})
        return seen

    def test_documented_names_are_honoured(self):
        seen = self.run_call({"EVOLUS_API_KEY": "k", "EVOLUS_APPLICATION_ID": "app-1", "EVOLUS_BASE_URL": "https://example.test/api/"})
        self.assertEqual(seen["url"], "https://example.test/api/workflows/wf-1/execute")
        self.assertEqual(seen["headers"]["X-application-id"], "app-1")

    def test_legacy_names_still_work(self):
        seen = self.run_call({"EVOLUS_API_KEY": "k", "EVOLUS_APP_ID": "app-2"})
        self.assertEqual(seen["headers"]["X-application-id"], "app-2")
        self.assertTrue(seen["url"].startswith("https://api.evolus.ai/api/v1/"))


if __name__ == "__main__":
    unittest.main()
