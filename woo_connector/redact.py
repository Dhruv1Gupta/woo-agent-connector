"""PII handling. Default 'mask' mode: the agent sees enough to reason, not enough to leak."""
import re


def mask_email(e):
    if not e or "@" not in e:
        return ""
    local, _, dom = e.partition("@")
    return local[:1] + "***@" + dom


def mask_phone(p):
    digits = re.sub(r"\D", "", p or "")
    return ("***" + digits[-2:]) if len(digits) >= 2 else ""


def mask_name(first, last):
    first, last = (first or "").strip(), (last or "").strip()
    return (first + (" " + last[:1] + "." if last else "")).strip()


def person(addr, mode):
    """Slim a billing/shipping address block according to PII mode."""
    addr = addr or {}
    base = {
        "city": addr.get("city", ""), "state": addr.get("state", ""),
        "postcode": addr.get("postcode", ""), "country": addr.get("country", ""),
    }
    if mode == "full":
        base.update({
            "name": ("%s %s" % (addr.get("first_name", ""), addr.get("last_name", ""))).strip(),
            "email": addr.get("email", ""), "phone": addr.get("phone", ""),
            "address": ", ".join(x for x in (addr.get("address_1"), addr.get("address_2")) if x),
        })
    else:
        base.update({
            "name": mask_name(addr.get("first_name"), addr.get("last_name")),
            "email": mask_email(addr.get("email")),
            "phone": mask_phone(addr.get("phone")),
        })
    return base


def clean_text(s, limit=500):
    """Strip HTML tags and cap length for free-text fields."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]
