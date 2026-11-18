"""Speech-to-text. API keys stay on the server; the browser never sees them.

VoiceLab (https://docs.voicelab.uz/api/stt), used when the key starts with "vlk_":
- POST {VOICELAB_BASE}/v1/stt  (Authorization: Bearer, Idempotency-Key, form fields `audio`, `language`)
  returns a job id; GET /v1/stt/transcriptions/{id} until status is "completed"; read `transcript`.
- VoiceLab keeps transcripts and source audio by default, so the job is DELETED right after we read it.
- The key needs Speech to text = Access (write to submit and delete, read to poll).
- Accepts WebM/Opus, OGG/Opus, M4A/AAC, WAV, MP3, FLAC directly (no conversion needed).

Aisha (legacy, any other key in AISHA_API_KEY):
- POST {AISHA_BASE}/api/v1/stt/post/ with the X-Api-Key header, form fields `audio` and `language`.

Audio is held in memory / a temp file here and never stored by this app.
"""
import os
import subprocess
import tempfile
import time
import uuid

import httpx

from . import config

DEMO_TRANSCRIPTS = {
    "uz": "Kecha kechqurun soatlab hech kim kelmadi, hamshirani chaqirdim lekin javob bo'lmadi.",
    "ru": "Вчера вечером я несколько часов ждал, никто не подошёл, звонок остался без ответа.",
    "en": "Last night I waited for hours and nobody came when I pressed the call bell.",
}

LANG_CODES = {"uz": "uz", "ru": "ru", "en": "en"}

AUDIO_TYPES = {".webm": "audio/webm", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
               ".mp3": "audio/mpeg", ".flac": "audio/flac"}
POLL_TIMEOUT = 120  # seconds to wait for VoiceLab to finish one clip


def provider():
    """Which speech service is configured: "voicelab", "aisha", or False (demo transcripts)."""
    if config.VOICELAB_API_KEY:
        return "voicelab"
    if config.AISHA_API_KEY:
        return "aisha"
    return False


def _fail(msg):
    return {"text": "", "demo": False, "error": msg}


def _voicelab(audio: bytes, filename: str, lang: str):
    ext = os.path.splitext(filename or "")[1].lower() or ".webm"
    ctype = AUDIO_TYPES.get(ext, "application/octet-stream")
    auth = {"Authorization": f"Bearer {config.VOICELAB_API_KEY}"}
    with httpx.Client(base_url=config.VOICELAB_BASE, headers=auth, timeout=30) as c:
        r = c.post("/v1/stt", headers={"Idempotency-Key": str(uuid.uuid4())},
                   files={"audio": ("audio" + ext, audio, ctype)},
                   data={"language": lang, "include_speakers": "false"}, timeout=90)
        if r.status_code >= 400:
            return _fail(f"speech service error {r.status_code}")
        job = r.json()
        job_id = job.get("id")
        if not job_id:
            return _fail("speech service returned no job id")
        try:
            data, deadline = job, time.time() + POLL_TIMEOUT
            while data.get("status") not in ("completed", "failed"):
                if time.time() > deadline:
                    return _fail("speech service timed out")
                try:
                    wait = float(r.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1.0
                time.sleep(min(max(wait, 0.5), 5))
                r = c.get(f"/v1/stt/transcriptions/{job_id}")
                if r.status_code >= 400:
                    return _fail(f"speech service error {r.status_code}")
                data = r.json()
            if data.get("status") == "failed":
                return _fail("speech service could not transcribe the audio")
            text = (data.get("transcript") or "").strip()
            if not text:
                text = " ".join((s.get("text") or "").strip() for s in data.get("segments") or []).strip()
            if not text:
                return _fail("no speech recognised")
            return {"text": text, "demo": False, "error": None}
        finally:
            try:  # do not leave the transcript or audio on VoiceLab's servers
                c.delete(f"/v1/stt/transcriptions/{job_id}")
            except Exception:
                pass


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
    if provider() == "voicelab":
        try:
            return _voicelab(audio, filename, lang)
        except Exception as e:  # network, timeout, bad json
            return _fail(f"speech service unavailable ({type(e).__name__})")
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
