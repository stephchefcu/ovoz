// Voice recording -> /api/transcribe -> fills the text box so the person can check and edit it.
// The audio is sent to OUR server only (never directly to the speech service) and is not kept.
function setupRecorder(opts) {
  const { button, status, textarea } = opts;
  const MAX_MS = 90000;
  let rec = null, chunks = [], timer = null, stream = null;

  function setStatus(msg, kind) {
    status.textContent = msg || "";
    status.className = "note " + (kind || "info") + (msg ? "" : " hidden");
  }
  function reset() {
    button.classList.remove("live");
    button.textContent = t("voice_start");
    button.disabled = false;
    if (timer) clearTimeout(timer);
    if (stream) stream.getTracks().forEach(tr => tr.stop());
    stream = null;
  }

  async function start() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setStatus(t("voice_nomic"), "warn");
      return;
    }
    const mimes = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    const mime = mimes.find(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
    rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    chunks = [];
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      const type = rec.mimeType || "audio/webm";
      const blob = new Blob(chunks, { type });
      reset();
      button.disabled = true;
      setStatus(t("voice_wait"), "info");
      const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
      const fd = new FormData();
      fd.append("audio", blob, "voice." + ext);
      fd.append("lang", LANG);
      try {
        const r = await fetch("/api/transcribe", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok || j.error || !j.text) {
          setStatus(t("voice_fail"), "warn");
        } else {
          textarea.value = (textarea.value ? textarea.value.trim() + " " : "") + j.text;
          textarea.focus();
          setStatus(j.demo ? t("voice_demo") : t("voice_check"), j.demo ? "warn" : "ok");
        }
      } catch (e) {
        setStatus(t("voice_fail"), "warn");
      }
      button.disabled = false;
    };
    rec.start();
    button.classList.add("live");
    button.textContent = t("voice_stop");
    setStatus(t("voice_rec") + " " + t("voice_max"), "info");
    timer = setTimeout(() => { if (rec && rec.state === "recording") rec.stop(); }, MAX_MS);
  }

  button.addEventListener("click", () => {
    if (rec && rec.state === "recording") { rec.stop(); } else { start(); }
  });
  document.addEventListener("langchange", () => {
    if (!button.classList.contains("live")) button.textContent = t("voice_start");
  });
  button.textContent = t("voice_start");  // the page language was applied before this listener existed
  setStatus("");
}
