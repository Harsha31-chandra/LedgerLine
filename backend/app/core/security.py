"""
Security utilities for LedgerLine.

Provides cryptographic password hashing, verification, and rehash detection using
Argon2id (RFC 9106 / OWASP recommended).

SECURITY POLICY & DESIGN:
- Algorithm: Argon2id (hybrid version of Argon2 providing memory-hardness against
  GPU/ASIC cracking and side-channel timing attack resistance).
- Parameters:
    - Time cost (t): 3 iterations
    - Memory cost (m): 65,536 KiB (64 MiB)
    - Parallelism (p): 4 parallel lanes/threads
    - Salt length: 16 bytes (128 bits) generated via CSPRNG
    - Hash length: 32 bytes (256 bits) output key length
- Encoding: Standard PHC-string format ($argon2id$v=19$m=65536,t=3,p=4$...)
  ensuring salt, parameters, and version are self-contained with the hash.
- Passwords are never logged or stored in plaintext.
- Verification is fail-closed: invalid or corrupted hashes return False safely.
- Verification performs no database lookup; timing-based account enumeration protections
  (such as dummy verification for nonexistent accounts) must be implemented by the future login service layer.
- Empty passwords: Hashing an empty string is rejected with ValueError. Verification
  of empty passwords fails closed and returns False. Password complexity policy
  (minimum length, entropy) is a separate concern handled at the API schema validation layer.
"""

from typing import Final

from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# RFC 9106 recommended parameters for Argon2id
ARGON2_TIME_COST: Final[int] = 3
ARGON2_MEMORY_COST: Final[int] = 65536  # 64 MiB in KiB
ARGON2_PARALLELISM: Final[int] = 4
ARGON2_HASH_LEN: Final[int] = 32  # 256 bits
ARGON2_SALT_LEN: Final[int] = 16  # 128 bits
ARGON2_TYPE: Final[Type] = Type.ID  # Argon2id hybrid

__all__ = [
    "ARGON2_HASH_LEN",
    "ARGON2_MEMORY_COST",
    "ARGON2_PARALLELISM",
    "ARGON2_SALT_LEN",
    "ARGON2_TIME_COST",
    "ARGON2_TYPE",
    "get_hasher",
    "hash_password",
    "needs_rehash",
    "verify_password",
]

# Internal singleton hasher instance configured with RFC 9106 parameters
_default_hasher: PasswordHasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
    type=ARGON2_TYPE,
)


def get_hasher() -> PasswordHasher:
    """Return the configured default Argon2id PasswordHasher instance."""
    return _default_hasher


def hash_password(password: str, hasher: PasswordHasher | None = None) -> str:
    """Hash a plaintext password using Argon2id with a unique CSPRNG salt.

    Args:
        password: The plaintext password string to hash. Must be non-empty.
        hasher: Optional custom PasswordHasher instance (defaults to standard RFC 9106 hasher).

    Returns:
        Encoded Argon2id hash string containing parameters, salt, and key.

    Raises:
        TypeError: If password is not a string.
        ValueError: If password is empty.
    """
    if not isinstance(password, str):
        raise TypeError("Password must be a string")
    if not password:
        raise ValueError("Password cannot be empty")

    active_hasher = hasher if hasher is not None else _default_hasher
    return active_hasher.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
    hasher: PasswordHasher | None = None,
) -> bool:
    """Verify a plaintext password against a stored Argon2id hash string.

    Fails closed: returns False for mismatched passwords, malformed hashes,
    empty inputs, or non-string inputs. Never raises unhandled exceptions on invalid hashes.

    This function performs no database lookup or account existence checks.
    Protection against timing-based account enumeration must be implemented
    by the caller (the future login/authentication service).

    Args:
        plain_password: The plaintext candidate password.
        hashed_password: The stored Argon2id hash string.
        hasher: Optional custom PasswordHasher instance.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    if not plain_password or not hashed_password:
        return False

    active_hasher = hasher if hasher is not None else _default_hasher
    try:
        return active_hasher.verify(hashed_password, plain_password)
    except (InvalidHashError, VerificationError):
        return False


def needs_rehash(hashed_password: str, hasher: PasswordHasher | None = None) -> bool:
    """Determine whether an existing stored hash requires rehashing.

    Returns True if:
    - The hash was created with older, weaker, or different Argon2 parameters.
    - The hash is malformed or not an Argon2 hash.
    - The hash string is empty or invalid.

    Returns False if:
    - The hash matches the current standard Argon2id parameters.

    Args:
        hashed_password: The stored hash string to evaluate.
        hasher: Optional custom PasswordHasher instance.

    Returns:
        True if the hash should be rehashed upon next successful login, False otherwise.
    """
    if not isinstance(hashed_password, str) or not hashed_password:
        return True

    active_hasher = hasher if hasher is not None else _default_hasher
    try:
        return active_hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True
