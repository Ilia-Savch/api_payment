import hmac


def is_valid_webhook_signature(body: bytes, signature: str, secret: bytes) -> bool:
    if len(signature) != 64:
        return False
    try:
        received = bytes.fromhex(signature)
    except ValueError:
        return False
    expected = hmac.digest(secret, body, "sha256")
    return hmac.compare_digest(expected, received)
