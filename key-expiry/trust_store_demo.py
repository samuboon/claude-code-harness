# -*- coding: utf-8 -*-
"""Point key_expiry at the certificates your own machine already trusts.

    python trust_store_demo.py

There is no better demonstration corpus than the trust store, because you did not put
it there, you have never read it, and it is real. On Windows this reads the ROOT store
through `ssl.enum_certificates`; elsewhere it reads OpenSSL's default CA bundle.

Nothing is written to disk and nothing leaves the machine. An expired root is not a
hole in your machine - an expired certificate simply cannot validate anything. The
point is narrower and worse: the dates were sitting there in plain text the whole time.

Standard library only.
"""
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import key_expiry as ke  # noqa: E402


def load():
    """-> (list of DER certificates, where they came from)."""
    if hasattr(ssl, "enum_certificates"):
        try:
            return [c for c, _enc, _trust in ssl.enum_certificates("ROOT")], "the Windows ROOT store"
        except Exception:
            pass
    path = ssl.get_default_verify_paths().openssl_cafile
    if not path or not Path(path).exists():
        print("No trust store found to read. Point key_expiry.py at a .pem bundle instead.")
        return [], ""
    data = Path(path).read_bytes()
    return [m for m in ke.PEM_RE.finditer(data)], path


def main():
    certs, where = load()
    if not certs:
        return 2
    now = datetime.now(timezone.utc)
    days = []
    unreadable = 0
    for c in certs:
        try:
            der = c if isinstance(c, bytes) else None
            if der is None:                      # a PEM match from the bundle
                import base64
                import re
                der = base64.b64decode(re.sub(rb"[^A-Za-z0-9+/=]", b"", c.group(1)), validate=True)
            days.append(ke.days_left(ke.cert_not_after(der), now))
        except Exception:
            unreadable += 1
    days.sort()
    expired = [d for d in days if d < 0]
    print("%d certificates in %s, read on %s" % (len(days), where, now.date()))
    print("  already expired : %d%s" % (len(expired),
          ("  (oldest by %d days)" % -expired[0]) if expired else ""))
    print("  expiring in 90  : %d" % len([d for d in days if 0 <= d <= 90]))
    print("  unreadable here : %d" % unreadable)
    if days:
        print("  soonest still valid: %s days" % next((d for d in days if d >= 0), "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
