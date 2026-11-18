"""Which plan each clinic is on, and what that plan allows. Prices and published text are in pricing.py.

A clinic's plan is worked out from three columns on `clinics`:
- trial_until: last day of the free Klinika trial (sign-up day + TRIAL_DAYS).
- plan / paid_until: a paid plan ('klinika' or 'network') and its last paid day (empty = no end date).
Paid plan still running -> that plan. Else trial still running -> Klinika (trial). Else -> Start.

Rules that never change with the plan:
- Reports are never blocked, delayed or hidden. Every active department keeps taking reports,
  even when a clinic has more departments than its plan allows (the limit only stops adding new ones).
- Masking, consent, urgent flags, the latest reports and case-code follow-up are in every plan.

Set a paid plan by hand after a payment (no online payment yet):
    python -m app.plans list
    python -m app.plans set <clinic_code> klinika --until 2027-12-31
    python -m app.plans set <clinic_code> start          (ends a paid plan)
    python -m app.plans trial <clinic_code> --days 30    (extends the trial from today)
"""
import argparse
from datetime import date, timedelta
from typing import Optional

from .pricing import KLINIKA_DEPARTMENTS, START_DEPARTMENTS, TRIAL_DAYS

PLAN_NAMES = {"start": "Start", "klinika": "Klinika", "network": "Network"}

# departments: most active departments (None = unlimited)
# ai_sorting: language-model triage and summaries (otherwise keyword rules)
# insights: recurring / linked problems, early-warning radar, action tracker, "You said, we did" board
# ai_root_cause: language-model root-cause suggestions (otherwise standard suggestions)
LIMITS = {
    "start": {"departments": START_DEPARTMENTS, "ai_sorting": False, "insights": False, "ai_root_cause": False},
    "klinika": {"departments": KLINIKA_DEPARTMENTS, "ai_sorting": True, "insights": True, "ai_root_cause": False},
    "network": {"departments": None, "ai_sorting": True, "insights": True, "ai_root_cause": True},
}
PAID = ("klinika", "network")


# Text for the plan notices on the dashboard and settings pages (uz / ru / en).
# NOTE: have native speakers review the Uzbek and Russian wording.
UI = {
    "uz": {
        "names": {"start": "Start", "klinika": "Klinika", "network": "Tarmoq"},
        "trial": "Klinika sinov muddati: {days} kun qoldi ({until} gacha).",
        "trial_after": "Keyin Ovoz Start tarifida {n} tagacha bo'lim uchun bepul qoladi va barcha murojaatlar kelishda davom etadi.",
        "start_title": "Start tarifi (bepul).",
        "start_ended": "Sinov yoki to'langan muddat tugadi.",
        "start_body": "Barcha murojaatlar kelishda davom etadi; shoshilinch va oxirgi murojaatlar ko'rinadi. Takrorlanuvchi "
                      "muammolar, erta ogohlantirish, choralar rejasi va \u201cSiz aytdingiz, biz qildik\u201d ekrani Klinika tarifida.",
        "ending": "{plan} tarifi {days} kundan keyin tugaydi ({until}).",
        "renew": "Uzaytirish uchun Ovoz jamoasiga murojaat qiling.",
        "pay": "To'lov uchun:",
        "over": "Sizda {used} ta faol bo'lim bor; {plan} tarifi {limit} tagacha ruxsat beradi. Ularning hammasi murojaat "
                "qabul qilishda davom etadi. Yangisini qo'shish uchun avval bittasini o'chiring yoki tarifni o'zgartiring.",
        "pricing": "Narxlar",
        "card_title": "Tarif", "trial_tag": "bepul sinov", "until": "{until} gacha", "no_end": "muddatsiz",
        "deps": "Bo'limlar: {used} / {limit}", "unlimited": "cheksiz", "sorting": "Saralash",
        "ai": "sun'iy intellekt", "rules": "kalit so'zlar",
        "insights": "Takrorlanuvchi muammolar, ogohlantirish, choralar, ekran", "rca": "Sabablarni topishda SI yordami",
        "yes": "bor", "no": "yo'q",
        "never": "Bemorlar va xodimlar hech qachon to'lamaydi, hech bir tarif murojaatni to'xtatmaydi.",
        "upsell_title": "Takrorlanuvchi muammolar, ogohlantirish va choralar",
        "upsell_body": "Klinika tarifida Ovoz murojaatlarni takrorlanuvchi muammolarga guruhlaydi, bemor va xodimlar bir joy "
                       "haqida aytganini bog'laydi, odatdagidan ko'p murojaat bo'lsa erta ogohlantiradi va choralarni "
                       "\u201cSiz aytdingiz, biz qildik\u201d ekranida ko'rsatadi.",
        "limit": "Tarifingiz {n} tagacha faol bo'limga ruxsat beradi. Avval bittasini o'chiring yoki tarifni o'zgartiring. "
                 "Mavjud bo'limlar murojaat qabul qilishda davom etadi.",
    },
    "ru": {
        "names": {"start": "Старт", "klinika": "Клиника", "network": "Сеть"},
        "trial": "Пробный период «Клиника»: осталось {days} дн. (до {until}).",
        "trial_after": "Потом Ovoz остаётся бесплатным на тарифе «Старт» для {n} отделений, и все обращения продолжают поступать.",
        "start_title": "Тариф «Старт» (бесплатно).",
        "start_ended": "Пробный или оплаченный период закончился.",
        "start_body": "Все обращения продолжают поступать; срочные и последние обращения видны. Повторяющиеся проблемы, "
                      "ранние предупреждения, план мер и экран «Вы сказали — мы сделали» входят в тариф «Клиника».",
        "ending": "Тариф «{plan}» заканчивается через {days} дн. ({until}).",
        "renew": "Чтобы продлить, напишите команде Ovoz.",
        "pay": "Для оплаты:",
        "over": "У вас {used} активных отделений; тариф «{plan}» позволяет {limit}. Все они продолжают принимать обращения. "
                "Чтобы добавить новое, сначала уберите одно или смените тариф.",
        "pricing": "Цены",
        "card_title": "Тариф", "trial_tag": "пробный период", "until": "до {until}", "no_end": "без срока",
        "deps": "Отделения: {used} из {limit}", "unlimited": "без ограничений", "sorting": "Сортировка",
        "ai": "ИИ", "rules": "ключевые слова",
        "insights": "Повторяющиеся проблемы, предупреждения, меры, экран", "rca": "Помощь ИИ в поиске причин",
        "yes": "есть", "no": "нет",
        "never": "Пациенты и сотрудники никогда не платят, и ни один тариф не блокирует обращения.",
        "upsell_title": "Повторяющиеся проблемы, предупреждения и меры",
        "upsell_body": "На тарифе «Клиника» Ovoz группирует обращения в повторяющиеся проблемы, связывает то, что говорят "
                       "пациенты и сотрудники об одном месте, заранее предупреждает, когда обращений больше обычного, и "
                       "показывает принятые меры на экране «Вы сказали — мы сделали».",
        "limit": "Ваш тариф позволяет {n} активных отделений. Сначала уберите одно или смените тариф. "
                 "Существующие отделения продолжают принимать обращения.",
    },
    "en": {
        "names": {"start": "Start", "klinika": "Klinika", "network": "Network"},
        "trial": "Klinika trial: {days} days left (until {until}).",
        "trial_after": "After that Ovoz stays free on Start for up to {n} departments, and every report keeps coming in.",
        "start_title": "Start plan (free).",
        "start_ended": "Your trial or paid plan has ended.",
        "start_body": "Every report still comes in, and urgent reports and the latest reports are shown. Recurring problems, "
                      "early warnings, the action tracker and the \u201cYou said, we did\u201d board are part of Klinika.",
        "ending": "{plan} plan ends in {days} days ({until}).",
        "renew": "Contact the Ovoz team to renew.",
        "pay": "To pay:",
        "over": "You have {used} active departments; the {plan} plan allows {limit}. They all keep taking reports. "
                "To add another one, remove one first or change plan.",
        "pricing": "See pricing",
        "card_title": "Plan", "trial_tag": "free trial", "until": "until {until}", "no_end": "no end date",
        "deps": "Departments: {used} of {limit}", "unlimited": "unlimited", "sorting": "Sorting",
        "ai": "AI", "rules": "keyword rules",
        "insights": "Recurring problems, early warnings, actions, board", "rca": "AI root-cause help",
        "yes": "yes", "no": "no",
        "never": "Patients and staff never pay, and no plan ever blocks a report.",
        "upsell_title": "Recurring problems, early warnings and actions",
        "upsell_body": "On Klinika, Ovoz groups reports into recurring problems, links what patients and staff say about the "
                       "same place, warns you early when a place gets more reports than usual, and shows the fixes you make "
                       "on the \u201cYou said, we did\u201d ward screen.",
        "limit": "Your plan allows {n} active departments. Remove one first, or change plan. "
                 "Existing departments keep taking reports.",
    },
}


def trial_end(start: Optional[date] = None) -> str:
    return ((start or date.today()) + timedelta(days=TRIAL_DAYS)).isoformat()


def status(row, today: Optional[date] = None) -> dict:
    """The plan in force for one clinic row (needs plan, paid_until, trial_until)."""
    today_s = (today or date.today()).isoformat()
    plan, paid_until, trial_until = row["plan"], row["paid_until"], row["trial_until"]
    if plan in PAID and (not paid_until or paid_until >= today_s):
        key, trial, until = plan, False, paid_until
    elif trial_until and trial_until >= today_s:
        key, trial, until = "klinika", True, trial_until
    else:
        key, trial, until = "start", False, None
    days_left = (date.fromisoformat(until) - date.fromisoformat(today_s)).days if until else None
    return {"key": key, "name": PLAN_NAMES[key], "trial": trial, "until": until, "days_left": days_left,
            "trial_ended": key == "start" and bool(trial_until), **LIMITS[key]}


def for_clinic(conn, clinic_id: int) -> dict:
    row = conn.execute("SELECT plan, paid_until, trial_until FROM clinics WHERE id=?", (clinic_id,)).fetchone()
    if not row:
        return status({"plan": None, "paid_until": None, "trial_until": None})
    return status(row)


def active_departments(conn, clinic_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM wards WHERE clinic_id=? AND active=1", (clinic_id,)).fetchone()[0]


def can_add_department(conn, clinic_id: int) -> bool:
    limit = for_clinic(conn, clinic_id)["departments"]
    return limit is None or active_departments(conn, clinic_id) < limit


def summary(conn, clinic_id: int) -> dict:
    """Plan plus department usage, for the settings page and the dashboard."""
    p = for_clinic(conn, clinic_id)
    p["departments_used"] = active_departments(conn, clinic_id)
    p["over_limit"] = p["departments"] is not None and p["departments_used"] > p["departments"]
    p["start_departments"] = START_DEPARTMENTS
    return p


def set_plan(conn, clinic_id: int, plan: str, until: Optional[str] = None):
    if plan not in LIMITS:
        raise ValueError(f"plan must be one of {', '.join(LIMITS)}")
    if until:
        date.fromisoformat(until)  # raises on a bad date
    if plan == "start":
        conn.execute("UPDATE clinics SET plan=NULL, paid_until=NULL WHERE id=?", (clinic_id,))
    else:
        conn.execute("UPDATE clinics SET plan=?, paid_until=? WHERE id=?", (plan, until or None, clinic_id))


def set_trial(conn, clinic_id: int, days: int):
    conn.execute("UPDATE clinics SET trial_until=? WHERE id=?",
                 ((date.today() + timedelta(days=days)).isoformat(), clinic_id))


def migrate(conn):
    """Run by init_db. Clinics from before pricing get a full trial from today; the demo clinic shows everything."""
    conn.execute("UPDATE clinics SET plan='network' WHERE slug='demo' AND plan IS NULL AND trial_until IS NULL")
    conn.execute("UPDATE clinics SET trial_until=? WHERE trial_until IS NULL", (trial_end(),))


def main(argv=None):
    from .db import db, init_db
    ap = argparse.ArgumentParser(prog="python -m app.plans", description="See or change clinic plans.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every clinic and its plan")
    s = sub.add_parser("set", help="set a paid plan after payment, or 'start' to end it")
    s.add_argument("clinic_code")
    s.add_argument("plan", choices=list(LIMITS))
    s.add_argument("--until", help="last paid day, YYYY-MM-DD (leave out for no end date)")
    t = sub.add_parser("trial", help="give a clinic a Klinika trial of N days from today")
    t.add_argument("clinic_code")
    t.add_argument("--days", type=int, default=TRIAL_DAYS)
    a = ap.parse_args(argv)
    init_db()
    with db() as conn:
        if a.cmd == "list":
            for r in conn.execute("SELECT id, slug, name FROM clinics ORDER BY slug"):
                p = summary(conn, r["id"])
                limit = "unlimited" if p["departments"] is None else p["departments"]
                left = f", {p['days_left']} days left" if p["days_left"] is not None else ""
                print(f"{r['slug']:<24} {p['name']}{' (trial)' if p['trial'] else ''}"
                      f"{' until ' + p['until'] if p['until'] else ''}{left}"
                      f" · departments {p['departments_used']}/{limit}")
            return
        r = conn.execute("SELECT id FROM clinics WHERE slug=?", (a.clinic_code.strip().lower(),)).fetchone()
        if not r:
            raise SystemExit(f"No clinic with code {a.clinic_code!r}")
        if a.cmd == "set":
            try:
                set_plan(conn, r["id"], a.plan, a.until)
            except ValueError:
                raise SystemExit(f"--until must be a date like 2027-12-31, not {a.until!r}")
        else:
            set_trial(conn, r["id"], a.days)
        p = summary(conn, r["id"])
        print(f"{a.clinic_code}: {p['name']}{' (trial)' if p['trial'] else ''}"
              f"{' until ' + p['until'] if p['until'] else ''}")


if __name__ == "__main__":
    main()
