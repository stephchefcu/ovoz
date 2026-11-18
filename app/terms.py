"""Terms of use and privacy notice, in Uzbek, Russian and English.

Used by the /privacy page, the bot's /privacy command and the "check what will be sent" step.
Every report stores TERMS_VERSION, so it is clear which text the person agreed to.
Bump TERMS_VERSION whenever the meaning of the text changes.

NOTE: draft text for a hackathon MVP. Have a lawyer and native speakers review it before real use
(personal-data law in Uzbekistan, where data is stored, and the clinic's own complaint procedures).
"""
from . import config

TERMS_VERSION = "2026-11-18"

_CLINIC = {"uz": "shifoxona", "ru": "клиника", "en": "the clinic"}
_CONTACT = {"uz": "shifoxona ma'muriyatiga murojaat qiling", "ru": "обратитесь в администрацию клиники",
            "en": "ask the clinic's administration"}


def clinic(lang: str) -> str:
    return config.CLINIC_NAME or _CLINIC[lang]


def contact(lang: str) -> str:
    return config.CLINIC_CONTACT or _CONTACT[lang]


# Each language: title, intro, then sections of (heading, [bullets]). {clinic} and {contact} are filled in.
_TEXT = {
    "uz": {
        "title": "Foydalanish shartlari va maxfiylik",
        "intro": "Ovoz orqali bemorlar, ularning yaqinlari va {clinic} xodimlari muammolar haqida ovoz yoki matn bilan "
                 "anonim xabar beradi, shifoxona esa ularni tuzatadi.",
        "sections": [
            ("Bu favqulodda xizmat emas", [
                "Shoshilinch yordam kerak bo'lsa, hamshirani chaqiring yoki 103 ga qo'ng'iroq qiling.",
            ]),
            ("Nima yuboriladi va saqlanadi", [
                "Xabaringiz matni — ismlar, telefon va hujjat raqamlari, vaqt va xona raqamlari avtomatik yashirilgandan keyin.",
                "Bo'lim nomi.",
                "Siz kimsiz: bemor (yoki yaqini) yoki xodim.",
                "Bahoingiz (bemorlar) yoki zarar darajasi (xodimlar), agar tanlasangiz.",
                "Til, sana (faqat kun) va kun qismi (ertalab, kunduzi yoki kechasi).",
                "Qaysi shartlarga rozi bo'lganingiz (shu matnning versiyasi).",
            ]),
            ("Nima saqlanmaydi", [
                "Ismingiz, telefon raqamingiz, Telegram akkauntingiz, qurilmangiz, IP manzilingiz, xona raqamingiz.",
                "Ovoz yozuvi: faqat matnga aylantirish uchun VoiceLab xizmatiga yuboriladi va darhol o'chiriladi "
                "(VoiceLab'da ham).",
            ]),
            ("Yashirish avtomatik — u xato qilishi mumkin", [
                "Iltimos, o'zingizning yoki boshqalarning ismini va sizni yoki boshqa odamni tanitadigan tafsilotlarni yozmang.",
                "Yuborishdan oldin har safar aynan nima yuborilishini ko'rasiz va rozilik berasiz.",
            ]),
            ("Kim ko'radi", [
                "Faqat {clinic}ning sifat va xavfsizlik bo'yicha vakolatli xodimlari.",
                "Xodimlar xabarlari rahbariyatga faqat neytral qisqa mazmun va hafta ko'rinishida ko'rsatiladi, aniq kun emas.",
                "Xabarlar juda kam bo'lgan joylar birlashtiriladi, shunda hech kimni ajratib bo'lmaydi.",
                "Xabarlar faqat davolash sifati va xavfsizlikni yaxshilash uchun ishlatiladi va shu ish uchun kerak "
                "bo'lgancha saqlanadi.",
            ]),
            ("Murojaat kodingiz", [
                "Kod — xabaringizga yagona bog'lanish. Biz kodning o'zini emas, faqat shifrlangan ko'rinishini saqlaymiz.",
                "Kodni bilgan har kim shifoxona savollarini o'qiy va javob bera oladi, shuning uchun uni boshqalarga bermang.",
            ]),
            ("Biz foydalanadigan xizmatlar", [
                "VoiceLab — ovozni matnga aylantirish uchun.",
                "Telegram — agar botdan foydalansangiz. Telegram'ning o'z maxfiylik siyosati amal qiladi va Telegram "
                "xabar qaysi akkauntdan kelganini biladi.",
                "Ushbu xizmatni ishlatadigan hosting va tarmoq provayderlari.",
            ]),
            ("Qoidalar", [
                "Haqqoniy yozing, bir xabarda bitta muammo.",
                "Tahdid, haqorat va boshqa odamlarning shaxsiy ma'lumotlari taqiqlanadi; bunday xabarlar o'chirilishi mumkin.",
                "Ovoz rasmiy shikoyat kanallarining o'rnini bosmaydi va xabar yuborish rasmiy shikoyat hisoblanmaydi.",
            ]),
            ("Sizning tanlovingiz", [
                "Xabar yuborish ixtiyoriy. Yuborishdan oldin istalgan payt to'xtatishingiz mumkin.",
                "Biz kim yuborganini bilmaymiz, shuning uchun xabarni faqat kod orqali topish mumkin. Kod bilan uni "
                "o'chirishni so'rashingiz mumkin: {contact}.",
            ]),
        ],
        "version": "Versiya",
    },
    "ru": {
        "title": "Условия использования и конфиденциальность",
        "intro": "Через Ovoz пациенты, их близкие и сотрудники учреждения «{clinic}» анонимно, голосом или текстом, "
                 "сообщают о проблемах, а клиника их исправляет.",
        "sections": [
            ("Это не служба экстренной помощи", [
                "Если нужна срочная помощь, позовите медсестру или позвоните 103.",
            ]),
            ("Что отправляется и хранится", [
                "Текст вашего сообщения — после автоматического скрытия имён, номеров телефонов и документов, времени и номеров палат.",
                "Название отделения.",
                "Кто вы: пациент (или родственник) или сотрудник.",
                "Ваша оценка (пациенты) или степень вреда (сотрудники), если вы их выбрали.",
                "Язык, дата (только день) и часть суток (утро, день или ночь).",
                "Какую версию этих условий вы приняли.",
            ]),
            ("Что не хранится", [
                "Ваше имя, телефон, аккаунт Telegram, устройство, IP-адрес, номер палаты.",
                "Голосовая запись: отправляется в сервис VoiceLab только для перевода в текст и сразу удаляется "
                "(в том числе у VoiceLab).",
            ]),
            ("Скрытие автоматическое — оно может ошибаться", [
                "Пожалуйста, не пишите своё имя или имена других людей и детали, по которым можно узнать вас или кого-то ещё.",
                "Перед каждой отправкой вы видите, что именно будет отправлено, и даёте согласие.",
            ]),
            ("Кто это видит", [
                "Только уполномоченные сотрудники службы качества и безопасности учреждения «{clinic}».",
                "Сообщения сотрудников руководство видит только как нейтральное краткое содержание и неделю, без точного дня.",
                "Места с очень малым числом сообщений объединяются, чтобы никого нельзя было выделить.",
                "Сообщения используются только для улучшения качества и безопасности помощи и хранятся, пока нужны для этой работы.",
            ]),
            ("Ваш код обращения", [
                "Код — единственная связь с вашим сообщением. Мы храним не сам код, а только его зашифрованный вид.",
                "Любой, у кого есть код, может читать вопросы клиники и отвечать, поэтому не передавайте его другим.",
            ]),
            ("Сервисы, которые мы используем", [
                "VoiceLab — для перевода голоса в текст.",
                "Telegram — если вы пользуетесь ботом. Действует политика конфиденциальности Telegram, и Telegram знает, "
                "с какого аккаунта пришло сообщение.",
                "Хостинг и сетевые провайдеры, на которых работает этот сервис.",
            ]),
            ("Правила", [
                "Пишите честно, одна проблема — одно сообщение.",
                "Угрозы, оскорбления и чужие личные данные запрещены; такие сообщения могут быть удалены.",
                "Ovoz не заменяет официальные каналы жалоб, и сообщение не является официальной жалобой.",
            ]),
            ("Ваш выбор", [
                "Отправка сообщения добровольна. До отправки вы можете остановиться в любой момент.",
                "Мы не знаем, кто отправил сообщение, поэтому найти его можно только по коду. С кодом вы можете попросить "
                "удалить сообщение: {contact}.",
            ]),
        ],
        "version": "Версия",
    },
    "en": {
        "title": "Terms of use and privacy",
        "intro": "With Ovoz, patients, relatives and staff of {clinic} report problems anonymously, by voice or text, "
                 "so the clinic can fix them.",
        "sections": [
            ("This is not an emergency service", [
                "If you need urgent help, call a nurse or dial 103.",
            ]),
            ("What is sent and stored", [
                "The text of your message, after names, phone and ID numbers, times and room numbers are hidden automatically.",
                "The ward or department.",
                "Who you are: a patient (or relative) or a staff member.",
                "Your rating (patients) or the level of harm (staff), if you choose one.",
                "Your language, the date (day only) and the part of the day (morning, afternoon or night).",
                "Which version of these terms you agreed to.",
            ]),
            ("What is not stored", [
                "Your name, phone number, Telegram account, device, IP address or room number.",
                "Voice recordings: sent to the VoiceLab speech-to-text service only to turn them into text, then deleted "
                "straight away (at VoiceLab too).",
            ]),
            ("Hiding details is automatic, and it can miss things", [
                "Please do not include your own name, other people's names, or details that could identify you or someone else.",
                "Before every report you see exactly what will be sent, and you agree to it.",
            ]),
            ("Who sees reports", [
                "Only authorised quality and safety staff of {clinic}.",
                "Managers see staff reports only as neutral summaries with the week, not the exact day.",
                "Places with very few reports are combined, so no one can be singled out.",
                "Reports are used only to improve care and safety, and kept for as long as that work needs them.",
            ]),
            ("Your case code", [
                "The code is the only link to your report. We store only a scrambled form of it, not the code itself.",
                "Anyone with the code can read the clinic's questions and reply, so do not share it.",
            ]),
            ("Services we use", [
                "VoiceLab, to turn voice into text.",
                "Telegram, if you use the bot. Telegram's own privacy policy applies, and Telegram knows which account "
                "sent a message.",
                "The hosting and network providers that run this service.",
            ]),
            ("Rules", [
                "Report honestly, one problem per report.",
                "No threats, insults or other people's personal data; such reports may be removed.",
                "Ovoz does not replace official complaint channels, and a report is not an official complaint.",
            ]),
            ("Your choice", [
                "Sending a report is voluntary. You can stop at any time before you send.",
                "We do not know who sent a report, so it can only be found with its code. With the code you can ask for "
                "it to be deleted: {contact}.",
            ]),
        ],
        "version": "Version",
    },
}


def terms(lang: str) -> dict:
    """The full text for one language with the clinic name and contact filled in."""
    lang = lang if lang in _TEXT else "uz"
    src = _TEXT[lang]
    fill = {"clinic": clinic(lang), "contact": contact(lang)}
    return {
        "lang": lang,
        "title": src["title"],
        "intro": src["intro"].format(**fill),
        "sections": [(h, [b.format(**fill) for b in items]) for h, items in src["sections"]],
        "version_label": src["version"],
        "version": TERMS_VERSION,
    }


def terms_html(lang: str) -> str:
    """Telegram-ready version (HTML parse mode)."""
    import html
    t = terms(lang)
    parts = [f"<b>{html.escape(t['title'], quote=False)}</b>", html.escape(t["intro"], quote=False)]
    for heading, items in t["sections"]:
        parts.append(f"<b>{html.escape(heading, quote=False)}</b>\n" + "\n".join("• " + html.escape(i, quote=False) for i in items))
    parts.append(f"<i>{t['version_label']}: {t['version']}</i>")
    return "\n\n".join(parts)
