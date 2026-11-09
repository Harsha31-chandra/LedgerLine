"""
Unit tests verifying Argon2id password hashing, verification, rehash detection,
and security failure modes for LedgerLine.
"""

from unittest.mock import MagicMock

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import pytest

from backend.app.core.security import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LEN,
    ARGON2_TIME_COST,
    ARGON2_TYPE,
    get_hasher,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_argon2id_configuration_parameters():
    """Verify that Argon2id constants match RFC 9106 recommendations."""
    assert ARGON2_TIME_COST == 3
    assert ARGON2_MEMORY_COST == 65536  # 64 MiB
    assert ARGON2_PARALLELISM == 4
    assert ARGON2_HASH_LEN == 32
    assert ARGON2_SALT_LEN == 16
    assert ARGON2_TYPE == Type.ID

    hasher = get_hasher()
    assert hasher.time_cost == 3
    assert hasher.memory_cost == 65536
    assert hasher.parallelism == 4
    assert hasher.hash_len == 32
    assert hasher.salt_len == 16
    assert hasher.type == Type.ID


def test_successful_password_hashing():
    """Verify successful hashing produces a standard PHC-formatted Argon2id string."""
    password = "CorrectHorseBatteryStaple2026!"
    hashed = hash_password(password)

    assert isinstance(hashed, str)
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    # Verify length fits well within the 255-character database column limit
    assert len(hashed) < 255
    assert len(hashed) >= 80


def test_correct_password_verification():
    """Verify that a valid plaintext password verifies successfully against its hash."""
    password = "MySecureBankingPassword#42"
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


def test_incorrect_password_rejection():
    """Verify that incorrect passwords fail verification without raising errors."""
    password = "SuperSecretPassword123"
    hashed = hash_password(password)

    assert verify_password("WrongPassword123", hashed) is False
    assert verify_password("supersecretpassword123", hashed) is False  # Case-sensitive check
    assert verify_password("SuperSecretPassword123 ", hashed) is False  # Trailing space check


def test_different_hashes_for_same_password_due_to_unique_salts():
    """Verify that hashing the same password twice yields different hashes due to CSPRNG salts."""
    password = "IdenticalPlaintextPassword"
    hash_1 = hash_password(password)
    hash_2 = hash_password(password)

    # Hashes must differ because distinct random salts were generated
    assert hash_1 != hash_2

    # Both distinct hashes must verify the original plaintext
    assert verify_password(password, hash_1) is True
    assert verify_password(password, hash_2) is True


def test_invalid_and_malformed_hash_handling():
    """Verify that malformed or corrupted hashes fail closed safely without unhandled exceptions."""
    password = "ValidPassword123"
    valid_hash = hash_password(password)

    # 1. Arbitrary non-hash text
    assert verify_password(password, "this_is_not_a_hash") is False

    # 2. Incomplete or truncated Argon2 headers
    assert verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$") is False
    assert verify_password(password, "$argon2id$") is False

    # 3. Corrupted hash content (tampered salt/checksum)
    tampered_hash = valid_hash[:-4] + "XXXX"
    assert verify_password(password, tampered_hash) is False

    # 4. Empty string and None hashes
    assert verify_password(password, "") is False
    assert verify_password(password, None) is False  # type: ignore[arg-type]

    # 5. Non-string candidate types
    assert verify_password(None, valid_hash) is False  # type: ignore[arg-type]
    assert verify_password(12345, valid_hash) is False  # type: ignore[arg-type]
    assert verify_password(password, 12345) is False  # type: ignore[arg-type]


def test_rehash_detection_with_different_parameters():
    """Verify rehash detection flags older/weaker parameters but approves standard ones."""
    password = "PasswordForRehashTest"

    # Current standard hash must not need rehashing
    current_hash = hash_password(password)
    assert needs_rehash(current_hash) is False

    # Hasher configured with legacy/weaker parameters (e.g. OWASP minimum 19 MiB, 2 iterations)
    legacy_hasher = PasswordHasher(
        time_cost=2,
        memory_cost=19456,
        parallelism=1,
        type=Type.ID,
    )
    legacy_hash = legacy_hasher.hash(password)

    # Legacy hash must still verify successfully
    assert verify_password(password, legacy_hash) is True
    # But needs_rehash must identify that it requires an upgrade to current standard parameters
    assert needs_rehash(legacy_hash) is True


def test_rehash_detection_with_invalid_inputs():
    """Verify needs_rehash handles malformed, empty, or non-string inputs safely."""
    assert needs_rehash("garbage_hash") is True
    assert needs_rehash("") is True
    assert needs_rehash(None) is True  # type: ignore[arg-type]
    assert needs_rehash(12345) is True  # type: ignore[arg-type]


def test_unicode_password_handling():
    """Verify intentional, diverse Unicode passwords across multiple scripts, accents, and emojis."""
    unicode_passwords = [
        # Latin with accents
        "Hôtel#Crédit-naïve_2026",
        # Non-Latin: Greek
        "Σωκράτης_Banking_Pass#42",
        # Non-Latin: Japanese
        "東京Ledger_パスワード_2026",
        # Non-Latin: Devanagari with Indian Rupee symbol
        "सुरक्षित_पासवर्ड_₹50000",
        # Non-Latin: Cyrillic
        "Секретный_Пароль_123!",
        # Emoji with symbols
        "🔐SafeVault🔑Pass🛡️2026",
        # Mixed Unicode, currency symbols, and ASCII
        "Café_€99.99_naïve_µs",
    ]

    for upw in unicode_passwords:
        h = hash_password(upw)
        assert verify_password(upw, h) is True
        assert verify_password(upw + "_mismatch", h) is False


def test_long_passphrase_handling_without_truncation():
    """Verify that Argon2id supports long passphrases without the 72-byte truncation flaw of bcrypt."""
    long_base = "A" * 150
    pw1 = long_base + "SuffixOne"
    pw2 = long_base + "SuffixTwo"

    h1 = hash_password(pw1)
    assert verify_password(pw1, h1) is True
    # bcrypt would truncate both pw1 and pw2 to 72 bytes and treat them as identical;
    # Argon2id must distinguish them and reject pw2.
    assert verify_password(pw2, h1) is False


def test_empty_password_behavior():
    """Verify empty-password handling conforms to explicit fail-closed security policy."""
    # Attempting to hash an empty password must raise ValueError
    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("")

    # Attempting to hash non-string types must raise TypeError
    with pytest.raises(TypeError, match="Password must be a string"):
        hash_password(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Password must be a string"):
        hash_password(123456)  # type: ignore[arg-type]

    # Verifying an empty candidate password against any valid hash must fail closed
    valid_hash = hash_password("ValidPassword456!")
    assert verify_password("", valid_hash) is False


def test_verification_is_independent_of_user_lookup():
    """Verify that password verification operates as a pure crypto function with zero DB dependencies."""
    # Functions can be called without any active database, engine, or session
    h = hash_password("StandalonePasswordTest")
    assert verify_password("StandalonePasswordTest", h) is True
    assert verify_password("IncorrectCandidate", h) is False


def test_exception_handling_behavior():
    """Verify that documented Argon2 exceptions fail closed, while programming errors propagate."""
    # 1. Documented Argon2 exceptions fail closed safely in verify_password
    mock_hasher_mismatch = MagicMock()
    mock_hasher_mismatch.verify.side_effect = VerifyMismatchError("mismatch")
    assert verify_password("secret", "some_hash", hasher=mock_hasher_mismatch) is False

    mock_hasher_invalid = MagicMock()
    mock_hasher_invalid.verify.side_effect = InvalidHashError("invalid hash")
    assert verify_password("secret", "some_hash", hasher=mock_hasher_invalid) is False

    mock_hasher_verification = MagicMock()
    mock_hasher_verification.verify.side_effect = VerificationError("verification error")
    assert verify_password("secret", "some_hash", hasher=mock_hasher_verification) is False

    # 2. Documented InvalidHashError in needs_rehash returns True
    mock_hasher_rehash_invalid = MagicMock()
    mock_hasher_rehash_invalid.check_needs_rehash.side_effect = InvalidHashError("corrupted")
    assert needs_rehash("some_hash", hasher=mock_hasher_rehash_invalid) is True

    # 3. Unexpected programming errors (e.g. RuntimeError) are NOT swallowed
    mock_buggy_hasher = MagicMock()
    mock_buggy_hasher.verify.side_effect = RuntimeError("Unexpected internal crash")
    with pytest.raises(RuntimeError, match="Unexpected internal crash"):
        verify_password("secret", "some_hash", hasher=mock_buggy_hasher)

    mock_buggy_rehash = MagicMock()
    mock_buggy_rehash.check_needs_rehash.side_effect = RuntimeError("Unexpected internal crash")
    with pytest.raises(RuntimeError, match="Unexpected internal crash"):
        needs_rehash("some_hash", hasher=mock_buggy_rehash)
