"""HTTP client for the WooCommerce REST API v3 (read-only, stdlib only)."""
import base64
import email.utils
import json
import random
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import AuthError, NotFoundError, RateLimitError, UpstreamError
from .ratelimit import TokenBucket

RETRY_STATUSES = {429, 502, 503, 504}
MAX_WAIT = 60.0


def _retry_after(value):
    """Retry-After may be seconds or an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, min(float(value), MAX_WAIT))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
        return max(0.0, min(dt.timestamp() - time.time(), MAX_WAIT))
    except Exception:
        return None


class WooClient:
    def __init__(self, cfg, sleep=time.sleep):
        self.cfg = cfg
        self.sleep = sleep
        self.bucket = TokenBucket(cfg.rps, sleep=sleep)
        self.stats = {"requests": 0, "retries": 0, "rate_limited": 0}
        token = base64.b64encode(("%s:%s" % (cfg.consumer_key, cfg.consumer_secret)).encode()).decode()
        self._auth = "Basic " + token
        self._ctx = None
        if cfg.store_url.startswith("https") and not cfg.verify_tls:
            self._ctx = ssl._create_unverified_context()  # local dev only

    # -- public ---------------------------------------------------------
    def get_page(self, path, params=None):
        data, headers = self._request(path, params)
        return {
            "items": data,
            "total": int(headers.get("X-WP-Total") or (len(data) if isinstance(data, list) else 1)),
            "total_pages": int(headers.get("X-WP-TotalPages") or 1),
        }

    def get_one(self, path, params=None):
        data, _ = self._request(path, params)
        return data

    # -- internals ------------------------------------------------------
    def _url(self, path, params):
        q = {k: v for k, v in (params or {}).items() if v is not None}
        url = "%s/wp-json/wc/v3/%s" % (self.cfg.store_url, path.lstrip("/"))
        return url + ("?" + urllib.parse.urlencode(q) if q else "")

    def _backoff(self, attempt):
        d = min(30.0, 0.5 * (2 ** attempt))
        return d + random.uniform(0, d * 0.25)

    def _request(self, path, params=None):
        url = self._url(path, params)
        last = None
        for attempt in range(self.cfg.max_retries + 1):
            self.bucket.acquire()
            self.stats["requests"] += 1
            req = urllib.request.Request(url, method="GET", headers={
                "Authorization": self._auth,
                "Accept": "application/json",
                "User-Agent": "woo-agent-connector/1.0",
            })
            wait = None
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout, context=self._ctx) as r:
                    body = r.read()
                    try:
                        return json.loads(body), r.headers
                    except ValueError:
                        raise UpstreamError("Store returned a non-JSON response (a firewall/WAF page or a plugin conflict?)")
            except urllib.error.HTTPError as e:
                status, body, headers = e.code, e.read(), e.headers
                msg, code = self._error_detail(body)
                if status in (401, 403):
                    raise AuthError("Store rejected the API key (%s). Check the key has Read permission and has not been revoked." % (code or status), status, code)
                if status == 404:
                    raise NotFoundError(msg or "Not found", status, code)
                if status in RETRY_STATUSES:
                    if status == 429:
                        self.stats["rate_limited"] += 1
                    wait = _retry_after(headers.get("Retry-After"))
                    cls = RateLimitError if status == 429 else UpstreamError
                    last = cls("Store returned HTTP %s%s" % (status, (": " + msg) if msg else ""), status, code)
                else:
                    raise UpstreamError("Store returned HTTP %s%s" % (status, (": " + msg) if msg else ""), status, code)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = UpstreamError("Network error talking to the store: %s" % getattr(e, "reason", e))
            if attempt >= self.cfg.max_retries:
                break
            self.stats["retries"] += 1
            delay = wait if wait is not None else self._backoff(attempt)
            print("[woo] retry %d in %.1fs (%s)" % (attempt + 1, delay, last), file=sys.stderr)
            self.sleep(delay)
        raise last

    @staticmethod
    def _error_detail(body):
        try:
            j = json.loads(body)
            return (str(j.get("message", ""))[:200], j.get("code"))
        except Exception:
            return ("", None)
