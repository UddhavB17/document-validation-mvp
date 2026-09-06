"""Password hashing and policy for ``ws-d-auth`` (contracts §6)."""

from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 10

# Common passwords rejected by policy. Embedded constant covering widely
# published top-100 weak passwords (exact match, case-insensitive).
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "123456",
        "123456789",
        "12345678",
        "12345",
        "1234567",
        "1234567890",
        "qwerty",
        "abc123",
        "password1",
        "123123",
        "admin",
        "letmein",
        "welcome",
        "monkey",
        "dragon",
        "football",
        "master",
        "sunshine",
        "princess",
        "shadow",
        "michael",
        "jesus",
        "superman",
        "iloveyou",
        "trustno1",
        "starwars",
        "whatever",
        "freedom",
        "hello",
        "charlie",
        "aa123456",
        "donald",
        "password123",
        "qwerty123",
        "1q2w3e4r",
        "admin123",
        "welcome123",
        "login123",
        "changeMe1",
        "changeme",
        "p@ssw0rd",
        "passw0rd",
        "password12",
        "qwertyuiop",
        "1qaz2wsx",
        "zaq12wsx",
        "qazwsx",
        "baseball",
        "superman1",
        "batman",
        "trustno12",
        "maverick",
        "solo1234",
        "pepper123",
        "hunter123",
        "silver123",
        "golden123",
        "honor1234",
        "merlin123",
        "ginger12",
        "scooter1",
        "jordan23",
        "killer12",
        "pepper12",
        "jennifer",
        "hunter12",
        "buster12",
        "thomas12",
        "tigger12",
        "robert12",
        "george12",
        "andrew12",
        "michelle",
        "banana12",
        "computer",
        "corvette",
        "coffee12",
        "diamond1",
        "matthew1",
        "daniel12",
        "prince12",
        "william1",
        "alexander",
        "arsenal1",
        "chelsea1",
        "liverpool",
        "manutd12",
        "ranger12",
        "samsung1",
        "apple1234",
        "google12",
        "amazon12",
        "summer12",
        "winter12",
        "autumn12",
        "spring12",
        "flower12",
        "butterfly",
        "rainbow1",
        "sunshine1",
        "moonlight",
        "starlight",
        "thunder1",
        "lightning",
        "elephant",
        "monkey12",
        "tiger1234",
        "dragon12",
        "qwerty12",
    }
)


def validate_password(password: str) -> None:
    """Enforce the password policy, raising ``ValueError`` on violation."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    if password.strip().lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common; choose a less predictable password")


def hash_password(password: str) -> str:
    """Hash ``password`` with bcrypt after enforcing policy."""
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when ``password`` matches ``password_hash`` (constant-time)."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Precomputed dummy hash so failed logins for unknown emails still cost one
# bcrypt verification (constant-time failure path in ``service.authenticate``).
_DUMMY_HASH: str = bcrypt.hashpw(b"ws-d-auth-dummy-fallback", bcrypt.gensalt()).decode(
    "utf-8"
)


def dummy_verify(password: str) -> bool:
    """Run a bcrypt verification that always fails; mitigates user enumeration."""
    return verify_password(password, _DUMMY_HASH)
