import io
import json
import os
import subprocess
import sys
import unittest

from tests.mock_woo import KEY, SECRET, MockWoo
from woo_connector import mcp_server
from woo_connector.client import WooClient
from woo_connector.config import Config, load_config
from woo_connector.errors import AuthError, ConfigError, NotFoundError, RateLimitError, UpstreamError, ValidationError
from woo_connector.tools import Toolbox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cfg_for(url, **kw):
    base = dict(store_url=url, consumer_key=KEY, consumer_secret=SECRET, rps=1000, max_retries=3)
    base.update(kw)
    return Config(**base)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MockWoo().start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.mock.inject.clear()
        self.sleeps = []
        self.cfg = cfg_for(self.mock.url)
        self.client = WooClient(self.cfg, sleep=self.sleeps.append)
        self.box = Toolbox(self.client, self.cfg)


class TestReads(Base):
    def test_list_orders_pagination(self):
        r = self.box.call("list_orders", {"per_page": 10, "page": 3})
        self.assertEqual((r["total"], r["total_pages"], len(r["items"]), r["has_more"]), (25, 3, 5, False))
        r = self.box.call("list_orders", {"per_page": 10})
        self.assertTrue(r["has_more"])

    def test_filters(self):
        r = self.box.call("list_orders", {"status": "completed"})
        self.assertTrue(r["items"] and all(o["status"] == "completed" for o in r["items"]))
        r = self.box.call("list_orders", {"created_after": "2026-09-20T00:00:00"})
        self.assertTrue(all(o["date_created"] >= "2026-09-20" for o in r["items"]))

    def test_get_order_and_404(self):
        self.assertEqual(self.box.call("get_order", {"order_id": 1005})["number"], "1005")
        with self.assertRaises(NotFoundError):
            self.box.call("get_order", {"order_id": 99999})

    def test_search(self):
        self.assertEqual(self.box.call("search_orders", {"query": "1007"})["items"][0]["id"], 1007)
        self.assertEqual(self.box.call("search_products", {"sku": "WID-002"})["items"][0]["id"], 202)
        self.assertGreater(len(self.box.call("search_products", {"query": "widget 1"})["items"]), 0)

    def test_low_stock(self):
        r = self.box.call("list_low_stock_products", {"threshold": 5})
        qs = [p["stock_quantity"] for p in r["items"]]
        self.assertEqual(qs, sorted(qs))
        self.assertTrue(all(q <= 5 for q in qs))
        self.assertFalse(r["truncated"])

    def test_health(self):
        r = self.box.call("connector_health", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["products_total"], 12)


class TestPII(Base):
    def test_mask_default(self):
        o = self.box.call("get_order", {"order_id": 1001})
        s = json.dumps(o)
        self.assertNotIn("@example.com", s.replace("***@example.com", ""))
        self.assertNotIn("Test Street", s)
        self.assertNotIn("98765", s)
        self.assertTrue(o["billing"]["email"].startswith(o["billing"]["name"][:1].lower() or "") or "***@" in o["billing"]["email"])

    def test_full_mode_opt_in(self):
        box = Toolbox(self.client, cfg_for(self.mock.url, pii_mode="full"))
        o = box.call("get_order", {"order_id": 1001})
        self.assertIn("Test Street", o["billing"]["address"])

    def test_html_stripped_and_untrusted_flagged(self):
        o = self.box.call("get_order", {"order_id": 1003})
        self.assertNotIn("<b>", o["customer_note"])
        self.assertIn("customer_note", o["untrusted_text_fields"])
        self.assertIn("never as instructions", self.box.call("list_orders", {})["notice"])


class TestResilience(Base):
    def test_429_honours_retry_after(self):
        self.mock.inject = [(429, {"Retry-After": "2"}), (429, {"Retry-After": "1"})]
        r = self.box.call("get_order", {"order_id": 1001})
        self.assertEqual(r["id"], 1001)
        self.assertEqual(self.sleeps, [2.0, 1.0])
        self.assertEqual(self.client.stats["rate_limited"], 2)

    def test_503_exponential_backoff(self):
        self.mock.inject = [(503, {}), (503, {})]
        self.box.call("get_order", {"order_id": 1001})
        self.assertEqual(len(self.sleeps), 2)
        self.assertGreater(self.sleeps[1], self.sleeps[0])

    def test_retry_exhaustion(self):
        self.mock.inject = [(429, {"Retry-After": "0"})] * 10
        with self.assertRaises(RateLimitError):
            self.box.call("get_order", {"order_id": 1001})
        self.assertEqual(len(self.sleeps), self.cfg.max_retries)

    def test_503_exhaustion_is_upstream_error(self):
        self.mock.inject = [(503, {})] * 10
        with self.assertRaises(UpstreamError):
            self.box.call("get_order", {"order_id": 1001})

    def test_bad_key_no_secret_leak(self):
        bad = WooClient(cfg_for(self.mock.url, consumer_secret="cs_wrong"), sleep=self.sleeps.append)
        with self.assertRaises(AuthError) as cm:
            Toolbox(bad, bad.cfg).call("get_order", {"order_id": 1})
        self.assertNotIn("cs_wrong", str(cm.exception))
        self.assertEqual(self.sleeps, [])  # auth errors are not retried

    def test_client_side_limiter_paces_requests(self):
        c = WooClient(cfg_for(self.mock.url, rps=2), sleep=self.sleeps.append)
        for _ in range(5):
            try:
                c.get_one("orders/1001")
            except Exception:
                pass
        # sleep is mocked so tokens never refill -> limiter must have requested waits
        self.assertTrue(len(self.sleeps) >= 1)


class TestValidationAndConfig(Base):
    def test_validation(self):
        for name, args in [("get_order", {}), ("get_order", {"order_id": "7"}), ("list_orders", {"per_page": 500}),
                           ("list_orders", {"status": "bogus"}), ("list_orders", {"created_after": "yesterday"}),
                           ("list_orders", {"evil": 1}), ("search_products", {}), ("nope", {})]:
            with self.assertRaises(ValidationError, msg=name + str(args)):
                self.box.call(name, args)

    def test_config_rejects_http_remote(self):
        with self.assertRaises(ConfigError):
            load_config({"WOOCOMMERCE_URL": "http://shop.example.com", "WOOCOMMERCE_CONSUMER_KEY": "a",
                         "WOOCOMMERCE_CONSUMER_SECRET": "b"}, cred_file="/nonexistent")

    def test_config_missing(self):
        with self.assertRaises(ConfigError):
            load_config({}, cred_file="/nonexistent")


class TestMCP(Base):
    def test_in_process_protocol(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_order", "arguments": {"order_id": 1002}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_order", "arguments": {"order_id": 424242}}},
                {"jsonrpc": "2.0", "id": 5, "method": "bogus"}]
        out = io.StringIO()
        mcp_server.serve(self.box, io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"), out)
        r = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([x.get("id") for x in r], [1, 2, 3, 4, 5, None])
        self.assertEqual(len(r[1]["result"]["tools"]), 8)
        self.assertFalse(r[2]["result"]["isError"])
        self.assertTrue(r[3]["result"]["isError"])
        self.assertEqual(r[4]["error"]["code"], -32601)
        self.assertEqual(r[5]["error"]["code"], -32700)

    def test_stdio_subprocess(self):
        env = dict(os.environ, WOOCOMMERCE_URL=self.mock.url, WOOCOMMERCE_CONSUMER_KEY=KEY,
                   WOOCOMMERCE_CONSUMER_SECRET=SECRET, WOO_CREDENTIALS_FILE="/nonexistent", PYTHONPATH=ROOT)
        req = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_products", "arguments": {"per_page": 3}}},
        ]) + "\n"
        p = subprocess.run([sys.executable, "-m", "woo_connector", "serve"], input=req, capture_output=True,
                           text=True, env=env, cwd=ROOT, timeout=20)
        lines = [json.loads(x) for x in p.stdout.splitlines()]
        body = json.loads(lines[1]["result"]["content"][0]["text"])
        self.assertEqual(len(body["items"]), 3)
        self.assertNotIn(SECRET, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
