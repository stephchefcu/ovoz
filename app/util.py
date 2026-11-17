import hashlib
import secrets

from . import config

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_case_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def hash_code(code: str) -> str:
    """Only this hash is stored, so a database leak does not reveal anyone's case code."""
    clean = code.strip().upper().replace(" ", "")
    if "-" not in clean and len(clean) == 8:
        clean = f"{clean[:4]}-{clean[4:]}"
    return hashlib.sha256((config.SECRET + clean).encode()).hexdigest()
