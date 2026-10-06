import argparse
import getpass
import json
import sys

from . import auth
from .client import WooClient
from .config import load_config
from .errors import WooError
from .mcp_server import serve
from .tools import Toolbox


def main(argv=None):
    ap = argparse.ArgumentParser(prog="woo_connector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the MCP stdio server")
    sub.add_parser("check", help="verify credentials and connectivity")
    sub.add_parser("spec", help="print the MCP tool specification as JSON")
    sub.add_parser("save-keys", help="paste a read-only key pair and store it (chmod 600)")
    a1 = sub.add_parser("auth-url", help="print the WooCommerce app-authorization URL")
    a1.add_argument("--store", required=True)
    a1.add_argument("--callback", required=True, help="public HTTPS URL that forwards to auth-server")
    a1.add_argument("--return-url", default="https://example.com/connected")
    a2 = sub.add_parser("auth-server", help="receive the keys WooCommerce posts back")
    a2.add_argument("--store", required=True)
    a2.add_argument("--user-id", required=True, help="the user_id printed by auth-url")
    a2.add_argument("--port", type=int, default=8787)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "save-keys":
            store = input("Store URL (https://...): ").strip()
            key = getpass.getpass("Consumer key (ck_...): ").strip()
            secret = getpass.getpass("Consumer secret (cs_...): ").strip()
            print("Saved to", auth.save_credentials(store, key, secret))
        elif args.cmd == "auth-url":
            url, uid = auth.build_authorize_url(args.store, args.callback, args.return_url)
            print("Open this URL as the store admin:\n%s\n\nuser_id (pass to auth-server): %s" % (url, uid))
        elif args.cmd == "auth-server":
            print("Waiting for WooCommerce callback on port %d ..." % args.port)
            print("Saved to", auth.run_callback_server(args.store, args.user_id, args.port))
        else:
            cfg = load_config()
            client = WooClient(cfg)
            box = Toolbox(client, cfg)
            if args.cmd == "spec":
                print(json.dumps({"tools": box.spec()}, indent=2))
            elif args.cmd == "check":
                print(json.dumps(box.call("connector_health", {}), indent=2))
            else:
                print("[woo] MCP server ready (read-only, pii=%s)" % cfg.pii_mode, file=sys.stderr)
                serve(box)
    except WooError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
