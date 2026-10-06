"""End-to-end demo against the bundled fake store: starts it, runs the MCP server over
stdio exactly as an agent runtime would, and walks through a realistic support flow.

    python scripts/demo.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.mock_woo import KEY, SECRET, MockWoo  # noqa: E402


def main():
    mock = MockWoo().start()
    env = dict(os.environ, WOOCOMMERCE_URL=mock.url, WOOCOMMERCE_CONSUMER_KEY=KEY,
               WOOCOMMERCE_CONSUMER_SECRET=SECRET, WOO_CREDENTIALS_FILE="/nonexistent", PYTHONPATH=ROOT)
    p = subprocess.Popen([sys.executable, "-m", "woo_connector", "serve"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=ROOT)
    n = [0]

    def rpc(method, params=None):
        n[0] += 1
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())["result"]

    def call(tool, **args):
        r = rpc("tools/call", {"name": tool, "arguments": args})
        text = r["content"][0]["text"]
        print("\n>>> %s(%s)%s" % (tool, ", ".join("%s=%r" % kv for kv in args.items()), "  [ERROR]" if r["isError"] else ""))
        return text if r["isError"] else json.loads(text)

    print("initialize ->", rpc("initialize", {"protocolVersion": "2024-11-05"})["serverInfo"])
    print("tools:", [t["name"] for t in rpc("tools/list")["tools"]])

    print(call("connector_health"))
    o = call("search_orders", query="1007")["items"][0]
    print("Found order %s status=%s total=%s %s | customer=%s <%s>" % (
        o["number"], o["status"], o["total"], o["currency"], o["billing"]["name"], o["billing"]["email"]))
    sku = o["line_items"][0]["sku"]
    prod = call("search_products", sku=sku)["items"][0]
    print("Item %s stock: %s (%s)" % (prod["sku"], prod["stock_quantity"], prod["stock_status"]))
    low = call("list_low_stock_products", threshold=5)
    print("Low stock:", [(x["sku"], x["stock_quantity"]) for x in low["items"]], "| scanned", low["products_scanned"])
    inj = call("get_order", order_id=1003)
    print("Customer note (sanitised, flagged untrusted):", repr(inj["customer_note"]), inj["untrusted_text_fields"])
    print(call("get_order", order_id=999999))
    print(call("list_orders", per_page=500))

    mock.inject = [(429, {"Retry-After": "1"})]
    print("\n(simulating a 429 with Retry-After: 1 ...)")
    print("recovered:", call("get_order", order_id=1001)["id"])
    p.stdin.close()
    p.wait(timeout=5)
    mock.stop()


if __name__ == "__main__":
    main()
