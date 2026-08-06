from backend.app import crypto


def test_encrypt_decrypt_roundtrip():
    original = "test_api_key_12345"
    encrypted = crypto.encrypt_text(original)
    assert encrypted != original
    assert crypto.decrypt_text(encrypted) == original


def test_decrypt_invalid_returns_empty():
    assert crypto.decrypt_text("!!!") == ""