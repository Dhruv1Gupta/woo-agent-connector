"""Minimal MCP server over stdio (newline-delimited JSON-RPC 2.0). No third-party deps."""
import json
import sys

from . import __version__
from .errors import WooError
from .tools import Toolbox

PROTOCOL = "2024-11-05"


def _ok(i, result):
    return {"jsonrpc": "2.0", "id": i, "result": result}


def _err(i, code, msg):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": msg}}


def handle(toolbox, msg):
    """Return a response dict, or None for notifications."""
    method, i, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        return _ok(i, {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "woocommerce-readonly", "version": __version__}})
    if method == "ping":
        return _ok(i, {})
    if method == "tools/list":
        return _ok(i, {"tools": toolbox.spec()})
    if method == "tools/call":
        try:
            out = toolbox.call(params.get("name"), params.get("arguments"))
            return _ok(i, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                           "isError": False})
        except WooError as e:   # expected, agent-readable failures
            return _ok(i, {"content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}],
                           "isError": True})
        except Exception as e:  # never leak a stack trace or secrets to the model
            print("[woo] internal error: %r" % e, file=sys.stderr)
            return _ok(i, {"content": [{"type": "text", "text": "InternalError: the connector failed unexpectedly."}],
                           "isError": True})
    if i is None:               # notification (e.g. notifications/initialized)
        return None
    return _err(i, -32601, "Method not found: %s" % method)


def serve(toolbox, stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps(_err(None, -32700, "Parse error")) + "\n")
            stdout.flush()
            continue
        resp = handle(toolbox, msg)
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
