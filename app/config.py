import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DOTENV_PATH = BASE_DIR / ".env"
_EXTERNAL = set(os.environ)  # set outside .env (shell, tests): these always win over the file


def _read_dotenv(p: Path) -> dict:
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _load_dotenv():
    if not DOTENV_PATH.exists():
        return
    for k, v in _read_dotenv(DOTENV_PATH).items():
        os.environ.setdefault(k, v)


_load_dotenv()


def env(key, default=""):
    return os.environ.get(key, default)


DB_PATH = env("DB_PATH", str(BASE_DIR / "data" / "clinic.db"))
CLINIC_PASSWORD = env("CLINIC_PASSWORD", "demo")
SECRET = env("SESSION_SECRET", "change-me")
K_MIN = int(env("K_MIN", "3"))
STAFF_DELAY_HOURS = float(env("STAFF_RELEASE_DELAY_HOURS", "0"))
WINDOW_DAYS = int(env("WINDOW_DAYS", "60"))

# Speech-to-text. VoiceLab keys start with "vlk_"; one pasted into AISHA_API_KEY is picked up too.
_aisha_or_vlk = env("AISHA_API_KEY")
VOICELAB_API_KEY = env("VOICELAB_API_KEY") or (_aisha_or_vlk if _aisha_or_vlk.startswith("vlk_") else "")
VOICELAB_BASE = env("VOICELAB_BASE_URL", "https://api.voicelab.uz").rstrip("/")
AISHA_API_KEY = "" if _aisha_or_vlk.startswith("vlk_") else _aisha_or_vlk
AISHA_BASE = env("AISHA_BASE_URL", "https://back.aisha.group").rstrip("/")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = env("TELEGRAM_BOT_USERNAME").lstrip("@")  # optional; found from the token if empty

# If set, new clinics must enter this code to sign up (stops strangers creating clinics on a public demo).
SIGNUP_CODE = env("SIGNUP_CODE")

# Shown in the Terms & Privacy text. PUBLIC_URL lets the bot link to the /privacy page (optional).
CLINIC_NAME = env("CLINIC_NAME")
CLINIC_CONTACT = env("CLINIC_CONTACT")
PUBLIC_URL = env("PUBLIC_URL").rstrip("/")

# Shown on /pricing for the Network plan, e.g. a Telegram username or phone (optional).
SALES_CONTACT = env("SALES_CONTACT")

# Claude (Anthropic) for AI sorting, summaries and root-cause help. OFF until ANTHROPIC_API_KEY is set in .env.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")

_DOTENV_SEEN = {"mtime": None}


def refresh_ai_keys() -> bool:
    """Pick up ANTHROPIC_API_KEY / CLAUDE_MODEL pasted into .env while Ovoz runs: no restart needed.
    Cheap (one file-time check); values set in the real environment are never overridden. True if anything changed."""
    global ANTHROPIC_API_KEY, CLAUDE_MODEL
    try:
        mtime = DOTENV_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if mtime == _DOTENV_SEEN["mtime"]:
        return False
    first = _DOTENV_SEEN["mtime"] is None
    _DOTENV_SEEN["mtime"] = mtime
    vals = _read_dotenv(DOTENV_PATH) if mtime is not None else {}
    changed = False
    if "ANTHROPIC_API_KEY" not in _EXTERNAL and vals.get("ANTHROPIC_API_KEY", "") != ANTHROPIC_API_KEY:
        ANTHROPIC_API_KEY, changed = vals.get("ANTHROPIC_API_KEY", ""), True
    if "CLAUDE_MODEL" not in _EXTERNAL and (vals.get("CLAUDE_MODEL") or "claude-sonnet-5-5") != CLAUDE_MODEL:
        CLAUDE_MODEL, changed = vals.get("CLAUDE_MODEL") or "claude-sonnet-5-5", True
    return changed and not first

LLM_BASE_URL = env("LLM_BASE_URL").rstrip("/")
LLM_API_KEY = env("LLM_API_KEY")
LLM_MODEL = env("LLM_MODEL")
