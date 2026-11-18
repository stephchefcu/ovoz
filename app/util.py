import hashlib
import hmac
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


def hash_password(password: str) -> str:
    """Salted PBKDF2-SHA256 (standard library only). Format: pbkdf2$iterations$salt$hash."""
    salt = secrets.token_hex(16)
    n = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), n).hex()
    return f"pbkdf2${n}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(n)).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(got, digest)
