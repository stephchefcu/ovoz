"""Speech-to-text via VoiceLab (Aisha AI).

- The API key stays on the server (X-Api-Key header); the browser never sees it.
- Endpoint used: POST {AISHA_BASE}/api/v1/stt/post/  with form fields `audio` (file) and `language`.
  Short clips only (synchronous). For longer audio use the asynchronous v2 endpoints from the docs.
- Audio is held in memory / a temp file and deleted immediately. It is never stored.
- VERIFY in the official docs: accepted formats, size/duration limits, and the exact response field names.
  The parser below tries common field names and falls back to the first string it finds.
"""
import os
import subprocess
import tempfile

import httpx

from . import config

DEMO_TRANSCRIPTS = {
    "uz": "Kecha kechqurun soatlab hech kim kelmadi, hamshirani chaqirdim lekin javob bo'lmadi.",
    "ru": "Вчера вечером я несколько часов ждал, никто не подошёл, звонок остался без ответа.",
    "en": "Last night I waited for hours and nobody came when I pressed the call bell.",
}

LANG_CODES = {"uz": "uz", "ru": "ru", "en": "en"}


def _extract_text(data):
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("transcript", "text", "result", "transcription", "data"):
            if key in data:
                got = _extract_text(data[key])
                if got:
                    return got
        for v in data.values():
            got = _extract_text(v)
            if got:
                return got
    if isinstance(data, list):
        parts = [p for p in (_extract_text(x) for x in data) if p]
        return " ".join(parts)
    return ""


def _to_wav(src_path: str) -> str:
    dst = src_path + ".wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "16000", dst],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
    )
    return dst


def _post(path: str, filename: str, lang: str):
    with open(path, "rb") as f:
        r = httpx.post(
            f"{config.AISHA_BASE}/api/v1/stt/post/",
            headers={"X-Api-Key": config.AISHA_API_KEY, "Accept-Language": "en"},
            files={"audio": (filename, f)},
            data={"language": LANG_CODES.get(lang, "uz")},
            timeout=60,
        )
    return r


def transcribe(audio: bytes, filename: str, lang: str):
    """Returns {"text": str, "demo": bool, "error": str|None}."""
    lang = lang if lang in LANG_CODES else "uz"
    if not config.AISHA_API_KEY:
        return {"text": DEMO_TRANSCRIPTS[lang], "demo": True, "error": None}

    suffix = os.path.splitext(filename or "")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    paths = [tmp.name]
    try:
        tmp.write(audio)
        tmp.close()
        r = _post(tmp.name, os.path.basename(tmp.name), lang)
        if r.status_code >= 400 and suffix != ".wav":
            # Browser formats (webm/ogg/mp4) may be refused: convert to 16 kHz mono wav and retry.
            try:
                wav = _to_wav(tmp.name)
                paths.append(wav)
                r = _post(wav, "audio.wav", lang)
            except Exception:
                pass
        if r.status_code >= 400:
            return {"text": "", "demo": False, "error": f"speech service error {r.status_code}"}
        text = _extract_text(r.json()).strip()
        if not text:
            return {"text": "", "demo": False, "error": "no speech recognised"}
        return {"text": text, "demo": False, "error": None}
    except Exception as e:  # network, timeout, bad json
        return {"text": "", "demo": False, "error": f"speech service unavailable ({type(e).__name__})"}
    finally:
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
