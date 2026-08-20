import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def sign_payload(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith(SIGNATURE_PREFIX):
        return False
    return hmac.compare_digest(sign_payload(payload, secret), signature)
