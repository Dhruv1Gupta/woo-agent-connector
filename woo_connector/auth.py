"""WooCommerce's built-in app-authorization flow (wc-auth) plus manual key storage.

Flow: merchant opens the authorize URL -> approves -> WooCommerce POSTs the generated
read-only consumer key/secret to our callback_url (must be HTTPS on real stores).
"""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode

from .config import DEFAULT_CRED_FILE


def build_authorize_url(store_url, callback_url, return_url, app_name="Agent Studio Connector", user_id=None):
    user_id = user_id or secrets.token_urlsafe(16)   # doubles as a CSRF/state token
    q = urlencode({"app_name": app_name, "scope": "read", "user_id": user_id,
                   "return_url": return_url, "callback_url": callback_url})
    return "%s/wc-auth/v1/authorize?%s" % (store_url.rstrip("/"), q), user_id


def save_credentials(store_url, key, secret, path=DEFAULT_CRED_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"store_url": store_url.rstrip("/"), "consumer_key": key, "consumer_secret": secret}, f)
    os.chmod(path, 0o600)
    return path


def run_callback_server(store_url, expected_user_id, port=8787, path=DEFAULT_CRED_FILE):
    """Blocks until WooCommerce delivers keys for the expected user_id, then exits."""
    state = {"done": False}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                body = {}
            ok = (body.get("user_id") == expected_user_id and body.get("consumer_key")
                  and body.get("consumer_secret") and body.get("key_permissions") == "read")
            if ok:
                save_credentials(store_url, body["consumer_key"], body["consumer_secret"], path)
                state["done"] = True
            self.send_response(200 if ok else 400)
            self.end_headers()

    srv = HTTPServer(("0.0.0.0", port), H)
    while not state["done"]:
        srv.handle_request()
    return path
