"""Plans and prices for clinics, in Uzbek, Russian and English. Used by the /pricing page.

Rules behind the prices:
- Patients and staff never pay, and no plan ever blocks, delays or hides a report or an urgent flag.
- Clinics pay by the number of departments, never by the number of reports.
- Every new clinic gets the full Klinika plan free for TRIAL_DAYS, then moves to Start unless it pays.
  Its departments keep taking reports and its data is kept.

Plans are not enforced in the app yet: this is the published offer.
NOTE: have native speakers review the Uzbek and Russian wording before real use.
"""

PRICES_VERSION = "2026-11-18"
TRIAL_DAYS = 60
START_DEPARTMENTS = 3
KLINIKA_DEPARTMENTS = 15
KLINIKA_MONTH = 790_000          # UZS per month
KLINIKA_YEAR = 7_900_000         # UZS per year (2 months free)
NETWORK_FROM = 2_500_000         # UZS per month, by contract
FOUNDING_CLINICS = 10            # first private clinics that get the founding discount
FOUNDING_DISCOUNT = 50           # percent, first year


def som(n: int) -> str:
    """790000 -> '790 000' (thin, non-breaking spaces between thousands)."""
    return f"{n:,}".replace(",", " ")


# Comparison rows: (key, start, klinika, network). True = included, False = not included, str key = text cell.
ROWS = [
    ("r_departments", "v_start_dep", "v_klinika_dep", "v_unlimited"),
    ("r_channels", True, True, True),
    ("r_safety", True, True, True),
    ("r_followup", True, True, True),
    ("r_triage", "v_rules", "v_ai", "v_ai"),
    ("r_linked", False, True, True),
    ("r_actions", False, True, True),
    ("r_rca", False, False, True),
    ("r_branches", False, False, "v_soon"),
    ("r_setup", "v_self", "v_online", "v_onsite"),
    ("r_support", "v_telegram", "v_telegram", "v_priority"),
]

_TEXT = {
    "uz": {
        "title": "Narxlar",
        "intro": "Bemorlar, ularning yaqinlari va xodimlar Ovoz'dan doim bepul foydalanadi. Klinika esa bo'limlar soniga "
                 "qarab to'laydi — murojaatlar soniga emas.",
        "trial": "Har bir yangi klinika {days} kun davomida Klinika tarifini bepul oladi. Karta kerak emas.",
        "currency": "so'm", "per_month": "oyiga", "per_year": "yiliga", "network_price": "{nf} so'mdan",
        "start_name": "Start", "start_price": "Bepul", "start_for": "Kichik klinikalar uchun, muddatsiz.",
        "klinika_name": "Klinika", "klinika_for": "Ko'pchilik xususiy klinikalar uchun.",
        "klinika_year": "yoki {year} {cur} {per_year} — 2 oy bepul",
        "network_name": "Tarmoq", "network_for": "Katta klinikalar va bir nechta filiallar uchun. Shartnoma asosida.",
        "popular": "Ko'p tanlanadi",
        "cta_trial": "{days} kun bepul sinab ko'ring", "cta_start": "Bepul boshlash", "cta_contact": "Biz bilan bog'laning",
        "start_points": ["{n} tagacha bo'lim", "Veb va Telegram, ovoz yoki matn", "Shaxsiy ma'lumotlarni yashirish, "
                         "har safar rozilik", "Shoshilinch belgilar", "Kalit so'zlar bo'yicha saralash"],
        "klinika_points": ["{n} tagacha bo'lim", "Start'dagi hamma narsa", "Sun'iy intellekt bilan saralash va xolis "
                           "xulosalar", "Bemor va xodim xabarlarini bog'lash, erta ogohlantirish", "Choralar rejasi va "
                           "“Siz aytdingiz, biz qildik” ekrani"],
        "network_points": ["Cheksiz bo'limlar", "Klinika'dagi hamma narsa", "Sabablarni topishda sun'iy intellekt "
                           "yordami", "Joyida o'rnatish va xodimlarga tushuntirish", "Tezkor yordam"],
        "compare": "Tariflarni solishtirish", "feature": "Imkoniyat",
        "r_departments": "Bo'limlar (QR kodlar)", "r_channels": "Veb va Telegram, ovoz yoki matn, uz / ru / en",
        "r_safety": "Ma'lumotlarni yashirish, har safar rozilik, shoshilinch belgilar",
        "r_followup": "Kod orqali anonim savol-javob", "r_triage": "Murojaatlarni saralash",
        "r_linked": "Bog'langan muammolar va erta ogohlantirish",
        "r_actions": "Choralar rejasi va “Siz aytdingiz, biz qildik” ekrani",
        "r_rca": "Sabablarni topishda sun'iy intellekt yordami", "r_branches": "Bir hisobda bir nechta filial",
        "r_setup": "O'rnatish", "r_support": "Yordam",
        "v_start_dep": "{start} tagacha", "v_klinika_dep": "{klinika} tagacha", "v_unlimited": "Cheksiz",
        "v_rules": "Kalit so'zlar", "v_ai": "Sun'iy intellekt", "v_soon": "Tez orada",
        "v_self": "Mustaqil", "v_online": "Onlayn", "v_onsite": "Joyida",
        "v_telegram": "Telegram", "v_priority": "Tezkor", "yes": "Bor", "no": "Yo'q",
        "rules": "Biz va'da qiladigan narsalar",
        "rules_list": [
            "Hech bir tarif murojaatni to'xtatmaydi, kechiktirmaydi yoki yashirmaydi. Limitdan oshsangiz ham hamma "
            "xabarlar keladi.",
            "Murojaatlar soni uchun to'lov yo'q: ko'p fikr olgan klinika jazolanmasligi kerak.",
            "Xavfsizlik va maxfiylik har bir tarifda bor, jumladan bepul tarifda ham.",
            "To'lovni to'xtatsangiz, ma'lumotlaringiz o'chirilmaydi va QR kodlaringiz ishlashda davom etadi.",
        ],
        "faq": "Savollar",
        "faq_list": [
            ("{days} kundan keyin nima bo'ladi?",
             "Agar to'lamasangiz, klinika Start tarifiga o'tadi. Mavjud bo'limlaringiz murojaat qabul qilishda davom "
             "etadi, ma'lumotlar saqlanadi. Sun'iy intellekt tahlili, bog'langan muammolar, choralar rejasi va ekran "
             "o'chadi. Istalgan vaqtda to'lab, ularni qaytarishingiz mumkin."),
            ("Qanday to'lanadi?",
             "Shartnoma va hisob-faktura asosida bank o'tkazmasi orqali. Karta orqali to'lov keyinroq qo'shiladi."),
            ("Birinchi klinikalar uchun taklif bormi?",
             "Ha. Birinchi {founding} ta xususiy klinika birinchi yil uchun {discount}% chegirma oladi (oyiga {fprice} "
             "{cur}), buning evaziga bizga ochiq fikr bildiradi."),
            ("Bemorlar to'laydimi?", "Yo'q. Bemorlar, yaqinlari va xodimlar hech qachon to'lamaydi."),
        ],
        "print": "PDF sifatida saqlash", "version": "Narxlar sanasi",
    },
    "ru": {
        "title": "Цены",
        "intro": "Пациенты, их родственники и сотрудники пользуются Ovoz всегда бесплатно. Клиника платит по числу "
                 "отделений — а не по числу обращений.",
        "trial": "Каждая новая клиника получает тариф «Клиника» бесплатно на {days} дней. Карта не нужна.",
        "currency": "сум", "per_month": "в месяц", "per_year": "в год", "network_price": "от {nf} сум",
        "start_name": "Старт", "start_price": "Бесплатно", "start_for": "Для небольших клиник, без ограничения срока.",
        "klinika_name": "Клиника", "klinika_for": "Для большинства частных клиник.",
        "klinika_year": "или {year} {cur} {per_year} — 2 месяца бесплатно",
        "network_name": "Сеть", "network_for": "Для крупных клиник и сетей с филиалами. По договору.",
        "popular": "Чаще всего выбирают",
        "cta_trial": "{days} дней бесплатно", "cta_start": "Начать бесплатно", "cta_contact": "Связаться с нами",
        "start_points": ["До {n} отделений", "Сайт и Telegram, голосом или текстом", "Скрытие личных данных, согласие "
                         "каждый раз", "Отметки о срочном", "Сортировка по ключевым словам"],
        "klinika_points": ["До {n} отделений", "Всё из тарифа «Старт»", "Сортировка с ИИ и нейтральные резюме",
                           "Связь отзывов пациентов и сотрудников, ранние предупреждения",
                           "План мер и экран «Вы сказали — мы сделали»"],
        "network_points": ["Без ограничения отделений", "Всё из тарифа «Клиника»", "Помощь ИИ в поиске причин",
                           "Запуск на месте и инструктаж сотрудников", "Приоритетная поддержка"],
        "compare": "Сравнение тарифов", "feature": "Возможность",
        "r_departments": "Отделения (QR-коды)", "r_channels": "Сайт и Telegram, голос или текст, uz / ru / en",
        "r_safety": "Скрытие данных, согласие каждый раз, отметки о срочном",
        "r_followup": "Анонимная переписка по коду", "r_triage": "Сортировка обращений",
        "r_linked": "Связанные проблемы и ранние предупреждения",
        "r_actions": "План мер и экран «Вы сказали — мы сделали»",
        "r_rca": "Помощь ИИ в поиске причин", "r_branches": "Несколько филиалов в одном аккаунте",
        "r_setup": "Запуск", "r_support": "Поддержка",
        "v_start_dep": "до {start}", "v_klinika_dep": "до {klinika}", "v_unlimited": "Без ограничений",
        "v_rules": "Ключевые слова", "v_ai": "ИИ", "v_soon": "Скоро",
        "v_self": "Самостоятельно", "v_online": "Онлайн", "v_onsite": "На месте",
        "v_telegram": "Telegram", "v_priority": "Приоритетная", "yes": "Есть", "no": "Нет",
        "rules": "Что мы обещаем",
        "rules_list": [
            "Ни один тариф не останавливает, не задерживает и не скрывает обращения. Даже сверх лимита все сообщения "
            "доходят.",
            "Нет платы за число обращений: клиника, которая получает много отзывов, не должна платить больше.",
            "Безопасность и конфиденциальность есть в каждом тарифе, включая бесплатный.",
            "Если вы перестанете платить, данные не удаляются, а QR-коды продолжают работать.",
        ],
        "faq": "Вопросы",
        "faq_list": [
            ("Что будет через {days} дней?",
             "Если вы не оплатите, клиника перейдёт на тариф «Старт». Уже созданные отделения продолжат принимать "
             "обращения, данные сохранятся. Отключатся анализ с ИИ, связанные проблемы, план мер и экран. Их можно "
             "вернуть оплатой в любой момент."),
            ("Как оплатить?",
             "По договору и счёт-фактуре, банковским переводом. Оплата картой появится позже."),
            ("Есть ли предложение для первых клиник?",
             "Да. Первые {founding} частных клиник получают скидку {discount}% на первый год ({fprice} {cur} в месяц) "
             "в обмен на честную обратную связь."),
            ("Платят ли пациенты?", "Нет. Пациенты, родственники и сотрудники не платят никогда."),
        ],
        "print": "Сохранить как PDF", "version": "Цены от",
    },
    "en": {
        "title": "Pricing",
        "intro": "Patients, relatives and staff always use Ovoz for free. Clinics pay by the number of departments — "
                 "never by the number of reports.",
        "trial": "Every new clinic gets the Klinika plan free for {days} days. No card needed.",
        "currency": "UZS", "per_month": "per month", "per_year": "per year", "network_price": "from {nf} UZS",
        "start_name": "Start", "start_price": "Free", "start_for": "For small clinics, with no time limit.",
        "klinika_name": "Klinika", "klinika_for": "For most private clinics.",
        "klinika_year": "or {year} {cur} {per_year} — 2 months free",
        "network_name": "Network", "network_for": "For large clinics and clinics with branches. By contract.",
        "popular": "Most chosen",
        "cta_trial": "Try {days} days free", "cta_start": "Start free", "cta_contact": "Contact us",
        "start_points": ["Up to {n} departments", "Web and Telegram, voice or text", "Masking of personal details, "
                         "consent every time", "Urgent flags", "Keyword sorting"],
        "klinika_points": ["Up to {n} departments", "Everything in Start", "AI sorting and neutral summaries",
                           "Linked patient and staff reports, early warnings",
                           "Action tracker and “You said, we did” board"],
        "network_points": ["Unlimited departments", "Everything in Klinika", "AI help finding root causes",
                           "On-site setup and staff briefing", "Priority support"],
        "compare": "Compare plans", "feature": "Feature",
        "r_departments": "Departments (QR codes)", "r_channels": "Web and Telegram, voice or text, uz / ru / en",
        "r_safety": "Masking, consent every time, urgent flags",
        "r_followup": "Anonymous follow-up by case code", "r_triage": "Report sorting",
        "r_linked": "Linked problems and early warnings",
        "r_actions": "Action tracker and “You said, we did” board",
        "r_rca": "AI help finding root causes", "r_branches": "Several branches in one account",
        "r_setup": "Setup", "r_support": "Support",
        "v_start_dep": "up to {start}", "v_klinika_dep": "up to {klinika}", "v_unlimited": "Unlimited",
        "v_rules": "Keywords", "v_ai": "AI", "v_soon": "Soon",
        "v_self": "Self-serve", "v_online": "Online", "v_onsite": "On site",
        "v_telegram": "Telegram", "v_priority": "Priority", "yes": "Included", "no": "Not included",
        "rules": "What we promise",
        "rules_list": [
            "No plan ever stops, delays or hides a report. Even over a limit, every message gets through.",
            "No charge per report: a clinic that hears a lot from its patients should not pay more for it.",
            "Safety and privacy are in every plan, including the free one.",
            "If you stop paying, your data is not deleted and your QR codes keep working.",
        ],
        "faq": "Questions",
        "faq_list": [
            ("What happens after {days} days?",
             "If you don't pay, the clinic moves to Start. Your existing departments keep taking reports and your data "
             "is kept. AI analysis, linked problems, the action tracker and the board switch off. Pay at any time to get "
             "them back."),
            ("How do we pay?",
             "By contract and invoice, with a bank transfer. Card payment comes later."),
            ("Is there an offer for the first clinics?",
             "Yes. The first {founding} private clinics get {discount}% off their first year ({fprice} {cur} per "
             "month) in return for honest feedback."),
            ("Do patients pay?", "No. Patients, relatives and staff never pay."),
        ],
        "print": "Save as PDF", "version": "Prices as of",
    },
}


def text(lang: str) -> dict:
    """All pricing text for one language, with numbers filled in."""
    t = dict(_TEXT[lang])
    fill = {
        "days": TRIAL_DAYS, "n": "", "start": START_DEPARTMENTS, "klinika": KLINIKA_DEPARTMENTS,
        "year": som(KLINIKA_YEAR), "nf": som(NETWORK_FROM), "cur": t["currency"], "per_year": t["per_year"],
        "founding": FOUNDING_CLINICS, "discount": FOUNDING_DISCOUNT,
        "fprice": som(KLINIKA_MONTH * (100 - FOUNDING_DISCOUNT) // 100),
    }
    for k, v in list(t.items()):
        if isinstance(v, str):
            t[k] = v.format(**fill)
    t["start_points"] = [p.format(**{**fill, "n": START_DEPARTMENTS}) for p in t["start_points"]]
    t["klinika_points"] = [p.format(**{**fill, "n": KLINIKA_DEPARTMENTS}) for p in t["klinika_points"]]
    t["network_points"] = [p.format(**fill) for p in t["network_points"]]
    t["rules_list"] = [p.format(**fill) for p in t["rules_list"]]
    t["faq_list"] = [(q.format(**fill), a.format(**fill)) for q, a in t["faq_list"]]
    t["rows"] = [(t[key], *[(t[c] if isinstance(c, str) else c) for c in cells]) for key, *cells in ROWS]
    t["lang"] = lang
    t["klinika_month"] = som(KLINIKA_MONTH)
    t["version_date"] = PRICES_VERSION
    return t


def all_texts() -> list:
    return [text(lang) for lang in ("uz", "ru", "en")]
