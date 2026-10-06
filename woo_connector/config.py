"""Configuration: env vars first, then ~/.woo_connector/credentials.json."""
import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import ConfigError

DEFAULT_CRED_FILE = os.path.join(os.path.expanduser("~"), ".woo_connector", "credentials.json")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Config:
    store_url: str
    consumer_key: str
    consumer_secret: str
    pii_mode: str = "mask"      # "mask" (default) | "full"
    rps: float = 5.0            # client-side requests/second ceiling
    max_retries: int = 5
    timeout: float = 15.0
    verify_tls: bool = True


def _validate_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ConfigError("WOOCOMMERCE_URL must look like https://shop.example.com")
    if p.scheme == "http" and p.hostname not in LOCAL_HOSTS:
        raise ConfigError("Refusing plain http for a non-local store: credentials would be sent unencrypted.")
    return url.rstrip("/")


def load_config(env=None, cred_file=None):
    env = os.environ if env is None else env
    cred_file = cred_file or env.get("WOO_CREDENTIALS_FILE") or DEFAULT_CRED_FILE
    file_data = {}
    if os.path.exists(cred_file):
        with open(cred_file) as f:
            file_data = json.load(f)

    url = env.get("WOOCOMMERCE_URL") or file_data.get("store_url")
    key = env.get("WOOCOMMERCE_CONSUMER_KEY") or file_data.get("consumer_key")
    secret = env.get("WOOCOMMERCE_CONSUMER_SECRET") or file_data.get("consumer_secret")
    if not (url and key and secret):
        raise ConfigError(
            "Missing credentials. Set WOOCOMMERCE_URL / WOOCOMMERCE_CONSUMER_KEY / "
            "WOOCOMMERCE_CONSUMER_SECRET, or run: python -m woo_connector save-keys")

    pii = env.get("WOO_PII_MODE", "mask").lower()
    if pii not in ("mask", "full"):
        raise ConfigError("WOO_PII_MODE must be 'mask' or 'full'")
    try:
        return Config(
            store_url=_validate_url(url),
            consumer_key=key,
            consumer_secret=secret,
            pii_mode=pii,
            rps=float(env.get("WOO_RPS", "5")),
            max_retries=int(env.get("WOO_MAX_RETRIES", "5")),
            timeout=float(env.get("WOO_TIMEOUT", "15")),
            verify_tls=env.get("WOO_INSECURE_SKIP_TLS_VERIFY", "0") != "1",
        )
    except ValueError as e:
        raise ConfigError("Invalid numeric setting: %s" % e)
