import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv():
    p = BASE_DIR / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def env(key, default=""):
    return os.environ.get(key, default)


DB_PATH = env("DB_PATH", str(BASE_DIR / "data" / "clinic.db"))
CLINIC_PASSWORD = env("CLINIC_PASSWORD", "demo")
SECRET = env("SESSION_SECRET", "change-me")
K_MIN = int(env("K_MIN", "3"))
STAFF_DELAY_HOURS = float(env("STAFF_RELEASE_DELAY_HOURS", "0"))
WINDOW_DAYS = int(env("WINDOW_DAYS", "60"))

AISHA_API_KEY = env("AISHA_API_KEY")
AISHA_BASE = env("AISHA_BASE_URL", "https://back.aisha.group").rstrip("/")

LLM_BASE_URL = env("LLM_BASE_URL").rstrip("/")
LLM_API_KEY = env("LLM_API_KEY")
LLM_MODEL = env("LLM_MODEL")
