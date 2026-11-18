// "Check what will be sent": before EVERY report or reply, show exactly what the server will store
// (the masked text and every field), and send only after the person ticks "I agree".
// Needs i18n.js (t, LANG) and a global TERMS_VERSION. Nothing is saved until onAgree runs.

const reviewEsc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let _review = null;

async function previewText(text) {
  const r = await fetch("/api/preview", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }) });
  if (!r.ok) throw new Error(r.status);
  return r.json();  // {masked, date, time_bucket, terms_version}
}

// opts: { box, hide: [elements to hide while reviewing], masked, rows: () => [[label, value], ...],
//         onAgree: async () => {...}, onBack: () => {...} }
function showReview(opts) {
  _review = opts;
  opts.hide.forEach(el => el.classList.add("hidden"));
  renderReview();
  opts.box.classList.remove("hidden");
  opts.box.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderReview() {
  const o = _review;
  if (!o) return;
  const rows = o.rows();
  o.box.innerHTML = `
    <h2>${t("rv_title")}</h2>
    <label>${t("rv_msg")}</label>
    <div class="masked">${reviewEsc(o.masked)}</div>
    ${rows.length ? `<table class="rv">${rows.map(([k, v]) => `<tr><th>${reviewEsc(k)}</th><td>${reviewEsc(v)}</td></tr>`).join("")}</table>` : ""}
    <div class="note info small">${t("rv_not")}<br>${t("rv_who")}</div>
    <label class="agree"><input type="checkbox" id="rv_ok">
      <span>${t("rv_agree_pre")} <a href="${typeof PRIVACY_URL !== "undefined" ? PRIVACY_URL : "/privacy"}" target="_blank" rel="noopener">${t("rv_terms")}</a>${t("rv_agree_post")}</span></label>
    <div id="rv_err" class="note bad hidden"></div>
    <div class="row" style="margin-top:12px">
      <button id="rv_send" disabled>${t("btn_agree")}</button>
      <button class="ghost" id="rv_back">${t("btn_back")}</button>
    </div>`;
  const ok = document.getElementById("rv_ok"), send = document.getElementById("rv_send");
  ok.addEventListener("change", () => { send.disabled = !ok.checked; });
  document.getElementById("rv_back").addEventListener("click", closeReview);
  send.addEventListener("click", async () => {
    const err = document.getElementById("rv_err");
    err.classList.add("hidden");
    if (!ok.checked) { err.textContent = t("need_agree"); err.classList.remove("hidden"); return; }
    send.disabled = true; send.textContent = t("sending");
    try {
      await o.onAgree();
      _review = null;
    } catch (e) {
      err.textContent = String(e.message) === "409" ? t("terms_changed") : t("err");
      err.classList.remove("hidden");
      send.disabled = false; send.textContent = t("btn_agree");
    }
  });
}

function closeReview() {
  const o = _review;
  if (!o) return;
  _review = null;
  o.box.classList.add("hidden");
  o.hide.forEach(el => el.classList.remove("hidden"));
  if (o.onBack) o.onBack();
}

// Labels follow the language switch while the review is open (the checkbox must be ticked again).
document.addEventListener("langchange", renderReview);

function partOfDay(p) { return `${p.date}, ${t("tb_" + p.time_bucket)}`; }
function langName() { return (I18N[LANG] || I18N.en).langName; }
