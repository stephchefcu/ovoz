"""Synthetic demo data. ALL texts are invented; never put real patient data in a demo.

Run:  python -m app.seed

Planted story: on Surgery ward A, patients complain about nobody coming at night while staff report
handover gaps and thin night cover. Different words, same cause -> the dashboard links them.
Other places have only one-sided noise, and two tiny groups show the small-group privacy rule.
"""
import random
import secrets
from datetime import date, datetime, timedelta, timezone

from . import ai, analytics, clinics, config
from .db import db, init_db
from .util import hash_code

DEMO_CODE = "DEMO-2345"

WARDS = [
    ("Surgery ward A", "Surgery department"),
    ("Surgery ward B", "Surgery department"),
    ("Therapy ward", "Therapy department"),
    ("Maternity ward", "Maternity department"),
    ("Pediatric ward", "Pediatrics department"),
    ("Emergency department", "Emergency department"),
]

# Department names shown to patients and staff in their language (English name -> (Uzbek, Russian)).
WARD_NAMES = {
    "Surgery ward A": ("Jarrohlik bo'limi A", "Хирургическое отделение А"),
    "Surgery ward B": ("Jarrohlik bo'limi B", "Хирургическое отделение Б"),
    "Therapy ward": ("Terapiya bo'limi", "Терапевтическое отделение"),
    "Maternity ward": ("Tug'ruq bo'limi", "Родильное отделение"),
    "Pediatric ward": ("Pediatriya bo'limi", "Педиатрическое отделение"),
    "Emergency department": ("Shoshilinch yordam bo'limi", "Отделение неотложной помощи"),
}


def fill_ward_translations(conn):
    """Add Uzbek / Russian names to the demo wards where they are missing (keeps codes, so QR codes stay valid)."""
    for name, (uz, ru) in WARD_NAMES.items():
        conn.execute("UPDATE wards SET name_uz=COALESCE(name_uz, ?), name_ru=COALESCE(name_ru, ?) WHERE name=?",
                     (uz, ru, name))

# (source, ward, lang, text, days_ago_range or 'recent')
STORY = [
    # --- patients, Surgery ward A: nobody came at night -------------------------------------
    ("patient", "Surgery ward A", "uz", "Kechasi soatlab hech kim kelmadi, hamshirani chaqirdim, javob bo'lmadi.", "recent"),
    ("patient", "Surgery ward A", "uz", "Tunda og'riq bor edi, qo'ng'iroq qildim lekin hech kim kelmadi, juda uzoq kutdim.", "recent"),
    ("patient", "Surgery ward A", "ru", "Ночью никто не подошёл, звонок игнорировали несколько часов.", "recent"),
    ("patient", "Surgery ward A", "ru", "Палата 12: ночью не пришли на вызов, ждали часами. Медсестра Гульнара потом извинилась, телефон 90 123 45 67.", "recent"),
    ("patient", "Surgery ward A", "uz", "Кечаси соатлаб ҳеч ким келмади, ҳамшира чақирдим, жавоб бўлмади.", "recent"),
    ("patient", "Surgery ward A", "en", "Nobody came for hours last night when I pressed the call bell.", "recent"),
    ("patient", "Surgery ward A", "ru", "Ночью ждал медсестру очень долго, никто не пришёл, пришлось звать соседей.", "older"),
    ("patient", "Surgery ward A", "uz", "Smena almashganda hamshiralar mening dorilarim haqida bir-biriga aytmagan, ertalab yana so'rashdi.", "older"),
    ("patient", "Surgery ward A", "ru", "При смене дежурных врач не знал, что мне уже делали укол; пришлось объяснять заново.", "older"),
    ("patient", "Surgery ward A", "uz", "Kechasi kutdim, hech kim kelmadi, ertalab smena almashgach keldi.", "older"),
    # --- staff, Surgery ward A: handover gaps, thin night cover -------------------------------
    ("staff", "Surgery ward A", "ru", "Передача смены прошла в спешке, ночная смена не получила информацию об анализах на утро; заметили вовремя.", "recent", {"near_miss": True}),
    ("staff", "Surgery ward A", "uz", "Smena almashishda bemorning ukol vaqti haqida ma'lumot topshirilmadi, yaxshiyamki ertalab payqadik.", "recent", {"near_miss": True}),
    ("staff", "Surgery ward A", "ru", "Ночью на два поста осталась одна медсестра, часть вызовов осталась без ответа, не хватает персонала.", "older", {"harm": "minor"}),
    ("staff", "Surgery ward A", "en", "Handover notes were incomplete again at shift change; the night team did not know about a patient's allergy.", "older", {"near_miss": True}),
    ("staff", "Surgery ward A", "uz", "Tunda bitta hamshira ikki postga qaraydi, chaqiruvlarga ulgurmaydi, xodim yetishmaydi.", "older", {}),
    # --- one-sided noise ---------------------------------------------------------------------
    ("patient", "Therapy ward", "uz", "Hojatxona iflos, hid keladi, tozalik yo'q.", "older"),
    ("patient", "Therapy ward", "ru", "В туалете грязно, запах, давно не убирали.", "older"),
    ("patient", "Therapy ward", "ru", "Простыни грязные, инфекции боимся, гигиена на низком уровне.", "older"),
    ("patient", "Therapy ward", "uz", "Palatada tozalik yo'q, choyshab almashtirilmadi.", "older"),
    ("patient", "Therapy ward", "en", "The toilet was dirty and nobody cleaned it for days.", "older"),
    ("patient", "Maternity ward", "ru", "Просили деньги за палату сверху, цену не назвали.", "older"),
    ("patient", "Maternity ward", "uz", "Qo'shimcha pul so'rashdi, narxini aytishmadi.", "older"),
    ("patient", "Maternity ward", "en", "We were asked for extra money and nobody could show us the official prices.", "older"),
    ("patient", "Pediatric ward", "ru", "В палате холодно, одеял не хватает, отопление не работает.", "older"),
    ("patient", "Pediatric ward", "uz", "Bolalar bo'limida sovuq, ko'rpa yetmaydi.", "older"),
    ("patient", "Pediatric ward", "ru", "Ребёнку принесли холодную еду, воды нет.", "older"),
    ("patient", "Emergency department", "ru", "У мужа сильная боль в груди, долго никто не подходил.", "recent"),
    ("patient", "Emergency department", "uz", "Otamning nafasi qiyin bo'lib qoldi, uzoq vaqt hech kim kelmadi.", "recent"),
    ("patient", "Emergency department", "ru", "Врач накричал на нас и говорил грубо.", "older"),
    ("patient", "Emergency department", "uz", "Shifokor qo'pol gapirdi, hurmat qilmadi.", "older"),
    # --- tiny groups: shown only after roll-up (small-group privacy rule) -------------------------
    ("patient", "Surgery ward B", "uz", "Ovqat sovuq keldi.", "older"),
    ("patient", "Surgery ward B", "ru", "Не объяснили, как принимать лекарства после выписки.", "older"),
    ("staff", "Maternity ward", "ru", "Таблетка почти была выдана не тому пациенту, заметили при проверке.", "older", {"near_miss": True}),
]


def _bucket(rng, story_night):
    return "night" if story_night else rng.choice(["morning", "afternoon", "afternoon", "night"])


def seed(reset: bool = True):
    init_db()
    rng = random.Random(42)
    with db() as conn:
        if reset:
            # Only the demo clinic is reset; other clinics' data is never touched.
            old = clinics.by_slug(conn, "demo")
            if old:
                conn.execute("DELETE FROM case_messages WHERE case_hash IN "
                             "(SELECT case_hash FROM reports WHERE clinic_id=?)", (old["id"],))
                for t in ("actions", "reports", "wards"):
                    conn.execute(f"DELETE FROM {t} WHERE clinic_id=?", (old["id"],))
        demo = clinics.by_slug(conn, "demo")
        cid = demo["id"] if demo else clinics.create(conn, config.CLINIC_NAME or "Demo clinic", "demo",
                                                     config.CLINIC_PASSWORD, config.CLINIC_CONTACT)
        codes = {}
        for name, unit in WARDS:
            code = secrets.token_urlsafe(6)
            codes[name] = code
            conn.execute("INSERT INTO wards (code, name, unit, clinic_id) VALUES (?,?,?,?)", (code, name, unit, cid))
        fill_ward_translations(conn)

        demo_done = False
        for item in STORY:
            source, ward, lang, text, when = item[:5]
            opts = item[5] if len(item) > 5 else {}
            res = ai.analyze(text, source, opts.get("harm", "none"), opts.get("near_miss", False))
            days = rng.randint(0, 4) if when == "recent" else rng.randint(6, 40)
            created = (date.today() - timedelta(days=days)).isoformat()
            night = ward == "Surgery ward A" and source == "patient" and res["category"] == "waiting"
            if not demo_done and source == "patient" and ward == "Surgery ward A":
                code, demo_done = DEMO_CODE, True
            else:
                code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
            conn.execute(
                "INSERT INTO reports (source, ward_code, text_masked, summary, category, theme, severity, urgent, "
                "near_miss, rating, lang, created_day, time_bucket, release_at, case_hash, clinic_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (source, codes[ward], res["masked"], res["summary"], res["category"], res["theme"], res["severity"],
                 int(res["urgent"]), int(res["near_miss"]), rng.randint(1, 2) if source == "patient" else None, lang,
                 created, _bucket(rng, night), "2000-01-01T00:00:00", hash_code(code), cid),
            )
            if code == DEMO_CODE:
                conn.execute("INSERT INTO case_messages (case_hash, sender, body, created_day) VALUES (?,?,?,?)",
                             (hash_code(code), "clinic",
                              "Thank you for telling us. Do you remember roughly which part of the night this happened? "
                              "Is it still a problem?", date.today().isoformat()))

        today = date.today()
        conn.execute(
            "INSERT INTO actions (theme, scope_unit, title, cause, owner, due, public_text, status, created_day, done_day, "
            "clinic_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("continuity", "Surgery department", "Introduce a short structured handover checklist at every shift change.",
             "Handover between shifts was informal.", "Head nurse, Surgery",
             (today - timedelta(days=10)).isoformat(),
             "A structured handover checklist is now used at every shift change.", "done",
             (today - timedelta(days=24)).isoformat(), (today - timedelta(days=12)).isoformat(), cid),
        )
        conn.execute(
            "INSERT INTO actions (theme, scope_unit, title, cause, owner, due, public_text, status, created_day, "
            "clinic_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("continuity", "Surgery department", "Review night-shift staffing against patient load.",
             "Night cover is thin.", "Deputy director", (today + timedelta(days=7)).isoformat(),
             "Night staffing is being reviewed.", "open", today.isoformat(), cid),
        )
    return codes


if __name__ == "__main__":
    codes = seed()
    print("Seeded demo data.")
    print(f"Demo case code (has a clinic question waiting): {DEMO_CODE}")
    print("Demo clinic: code demo, password = CLINIC_PASSWORD from .env (a new demo clinic only)")
    for name, code in codes.items():
        print(f"  {name}: /r/{code}")
