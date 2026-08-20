from app.security import sign_payload, verify_signature


def test_matches_github_published_signature_vector() -> None:
    payload = b"Hello, World!"
    secret = "It's a Secret to Everybody"
    expected = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    assert sign_payload(payload, secret) == expected
    assert verify_signature(payload, expected, secret)


def test_rejects_missing_or_incorrect_signature() -> None:
    assert not verify_signature(b"payload", None, "secret")
    assert not verify_signature(b"payload", "sha256=bad", "secret")
