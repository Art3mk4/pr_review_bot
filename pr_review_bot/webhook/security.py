from __future__ import annotations

import hashlib
import hmac


def verify_signature(payload: bytes, sig_header: str, *, secret: str) -> bool:
    """Validate a GitHub webhook HMAC-SHA256 signature."""
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", sig_header)
