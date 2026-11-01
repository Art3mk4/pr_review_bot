from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, sig_header: str, *, secret: str) -> bool:
    """Validate a GitHub webhook HMAC-SHA256 signature."""
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = f"sha256={hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()}"
    # Compare as bytes: compare_digest() on str raises TypeError for non-ASCII
    # characters, and WSGI header values may contain them (PEP 3333, latin-1),
    # which would turn a crafted signature into a 500 instead of a 403.
    return hmac.compare_digest(expected.encode("utf-8"), sig_header.encode("utf-8"))
