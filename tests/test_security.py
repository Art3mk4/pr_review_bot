import hashlib
import hmac

import pytest

from pr_review_bot.webhook.security import verify_signature


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.parametrize(
    "payload, sig_header, expected",
    [
        (b'{"action":"opened"}', lambda s: _sign(b'{"action":"opened"}', s), True),
        (b'{"action":"opened"}', lambda s: "sha256=0000000000000000", False),
        (b'{"action":"opened"}', lambda s: "", False),
        (b'{"action":"opened"}', lambda s: "sha1=abcdef", False),
        (b'', lambda s: _sign(b'', s), True),
    ],
)
def test_verify_signature(payload: bytes, sig_header, expected: bool) -> None:
    secret = "super-secret"
    sig = sig_header(secret) if callable(sig_header) else sig_header
    assert verify_signature(payload, sig, secret=secret) is expected


def test_verify_signature_different_secrets() -> None:
    payload = b'{"action":"opened"}'
    sig = _sign(payload, "right-secret")
    assert verify_signature(payload, sig, secret="wrong-secret") is False
