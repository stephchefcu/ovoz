"""AI pipeline: mask personal details, triage (category / severity / urgency), neutral summary,
and root-cause help.

Design rules
- Personal details are masked with regexes BEFORE any text is stored or sent to an LLM.
- If an OpenAI-compatible LLM is configured (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL) it is used;
  otherwise a keyword-rule fallback (Uzbek Latin/Cyrillic, Russian, English) keeps everything working offline.
- The AI only suggests. It never assigns blame to a person.
"""
import json
import re

import httpx

from . import config

# --------------------------------------------------------------------------------------
# Taxonomy
# --------------------------------------------------------------------------------------
CATEGORIES = {
    "handover": ("continuity", "Shift handover",
                 "Information was lost or unclear when care passed between shifts or staff."),
    "waiting": ("continuity", "Waiting / no response",
                "Patients waited a long time or calls for help were not answered."),
    "staffing": ("continuity", "Staffing",
                 "Too few staff were available to cover the ward."),
    "medication": ("medication", "Medication",
                   "A medicine was given late, to the wrong patient, or at the wrong dose."),
    "diagnosis": ("diagnosis", "Tests / diagnosis",
                  "A test, result or diagnosis was delayed, missed or mixed up."),
    "hygiene": ("hygiene", "Hygiene / infection",
                "Cleanliness or infection-control standards were not met."),
    "falls": ("physical_safety", "Falls / physical safety",
              "A patient fell or was put at risk by the environment or equipment."),
    "equipment": ("facilities", "Equipment / facilities",
                  "Equipment or facilities were broken, missing or unsuitable."),
    "behavior": ("communication", "Staff behavior",
                 "A patient felt treated rudely or without respect."),
    "communication": ("communication", "Information / communication",
                      "Patients or relatives were not given clear information."),
    "pain": ("pain_care", "Pain management", "Pain was not addressed in time."),
    "privacy": ("privacy", "Privacy / confidentiality",
                "Patient privacy or confidentiality was not respected."),
    "billing": ("billing", "Billing / payments",
                "Unclear charges or requests for informal payments."),
    "food": ("facilities", "Food / comfort", "Food, water, heating or comfort problems."),
    "other": ("other", "Other", "Other concern."),
}

THEMES = {
    "continuity": "Care continuity & responsiveness",
    "medication": "Medication safety",
    "diagnosis": "Tests & diagnosis",
    "hygiene": "Hygiene & infection control",
    "physical_safety": "Falls & physical safety",
    "facilities": "Equipment, food & facilities",
    "communication": "Communication & respect",
    "pain_care": "Pain care",
    "privacy": "Privacy",
    "billing": "Billing & payments",
    "other": "Other",
}

# --------------------------------------------------------------------------------------
# Text normalisation (Uzbek Latin + Cyrillic, Russian, English)
# --------------------------------------------------------------------------------------
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'",
    "ҳ": "h",
}


def _norm_apos(s: str) -> str:
    return re.sub(r"[‘’ʻʼ`´]", "'", s)


def _translit(s: str) -> str:
    return "".join(_CYR2LAT.get(ch, ch) for ch in s)


def _variants(text: str):
    low = _norm_apos(text.lower())
    return low, _translit(low)


# --------------------------------------------------------------------------------------
# Masking
# --------------------------------------------------------------------------------------
_TITLES = (
    r"doctor|dr\.?|nurse|sister|mr\.?|mrs\.?|ms\.?|shifokor|vrach|hamshira|opa|aka|xola|buva|"
    r"medsestra|sestra|doktor|feldsher|врач|доктор|медсестра|сестра|санитарка|заведующ\w+|"
    r"шифокор|ҳамшира|ака|ока|опа"
)
_NAME = r"[A-ZА-ЯЎҚҒҲ][a-zа-яёўқғҳ'’ʻ‘-]{2,}"


_COMMON_NAMES = (
    "Aziz Azizbek Aziza Dilnoza Dilshod Dilfuza Gulnara Gulnoza Gulchehra Gulbahor Malika Madina Munisa Nodira "
    "Nargiza Nigora Sevara Shahnoza Zilola Zulfiya Feruza Farhod Jasur Jamshid Sardor Bobur Otabek Rustam "
    "Sherzod Timur Ulugbek Akmal Alisher Anvar Bahrom Botir Davron Eldor Hamid Ilhom Islom Kamola Komil Laylo "
    "Lola Mohira Muhabbat Nilufar Oybek Rahim Saida Sanjar Sitora Shoira Svetlana Elena Olga Natalya Tatyana "
    "Irina Marina Anna Maria Mariya Aleksandr Alexander Sergey Dmitry Andrey Ivan Nikolay Vladimir Yuri Sasha "
    "Азиз Азиза Дилноза Дилшод Гульнара Гулноза Малика Мадина Нодира Саида Светлана Елена Ольга Наталья "
    "Татьяна Ирина Марина Анна Мария Александр Сергей Дмитрий Андрей Иван Николай Владимир Юрий Фарход "
    "Жасур Рустам Тимур Улугбек Акмал Алишер Сардор Бобур Отабек Шерзод Лола Нилуфар Зулфия Феруза Шахноза"
).split()
def _stems(names):
    out = set()
    for n in names:
        out.add(n)
        if len(n) >= 5 and n[-1] in "аяaи":
            out.add(n[:-1])  # Гульнара -> Гульнар (so Гульнары, Гульнаре, Гульнару match)
    return sorted(out, key=len, reverse=True)


_NAMES_RE = re.compile(r"\b(?:" + "|".join(map(re.escape, _stems(_COMMON_NAMES))) + r")[а-яёa-z']{0,4}\b")
_PATRONYMIC_RE = re.compile(r"\b[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|ична|ич)\b|\b[A-Z][a-z']+\s+(?:o'g'li|o‘g‘li|qizi)\b")

_MASK_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?:\+?998[\s-]?)?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}"), "[PHONE]"),
    (re.compile(r"\b\d{9,}\b"), "[ID]"),
    (re.compile(r"\b\d{5,8}\b"), "[ID]"),
    (re.compile(r"\b([01]?\d|2[0-3])[:.][0-5]\d\b"), "[TIME]"),
    # clock times written with words: 7am, 7 p.m. / "soat 7" (at 7 o'clock; "2 soat" = 2 hours stays) / "в 7 утра"
    (re.compile(r"\b(?:1[0-2]|0?\d)\s?(?:[ap]\.?m\.?)(?=\W|$)", re.I), "[TIME]"),
    (re.compile(r"\b(soat)\s+(?:[01]?\d|2[0-3])\b", re.I), r"\1 [TIME]"),
    (re.compile(r"(?<!\w)(в|к|около)\s+(?:[01]?\d|2[0-3])\s+(?:утра|вечера|ночи|дня|час(?:а|ов)?)(?!\w)", re.I), r"\1 [TIME]"),
    (re.compile(r"(?i)\b(room|ward|палата|палате|палату|xona|xonada|xonaga|койка|bed)\s*(№|#|no\.?)?\s*\d+\b"),
     "[ROOM]"),
]


def mask_text(text: str) -> str:
    out = text.strip()
    # titles + names first (so "Dr. Karimov" does not leave a surname behind)
    title_re = re.compile(rf"\b((?i:{_TITLES}))\s+({_NAME})(?:\s+{_NAME})?")
    out = title_re.sub(lambda m: f"{m.group(1)} [NAME]", out)
    out = _NAMES_RE.sub("[NAME]", out)
    out = _PATRONYMIC_RE.sub("[NAME]", out)
    for pat, repl in _MASK_PATTERNS:
        out = pat.sub(repl, out)
    # "I am Aziz", "my name is Aziz", "меня зовут Азиз", "ismim Aziz"
    out = re.sub(rf"\b((?i:my name is|i am|i'm|меня зовут|ismim|mening ismim))\s+{_NAME}", r"\1 [NAME]", out)
    return re.sub(r"\s+", " ", out)


# --------------------------------------------------------------------------------------
# Rule-based triage fallback
# --------------------------------------------------------------------------------------
_KEYWORDS = {
    "handover": ["handover", "hand-over", "hand over", "shift change", "passed on", "smena almash", "topshir",
                 "передач", "передал", "при смене", "смену"],
    "waiting": ["waited", "waiting", "nobody came", "no one came", "ignored", "call bell", "for hours",
                "kutdim", "kutdik", "kelmadi", "hech kim", "soatlab", "e'tibor bermad", "chaqirdim",
                "ждал", "никто не подош", "не пришел", "не пришла", "часами", "звонок", "игнор", "не подходил"],
    "staffing": ["short-staffed", "understaffed", "not enough nurses", "not enough staff", "one nurse",
                 "xodim yetishmay", "hamshira yetishmay", "kam xodim", "bitta hamshira",
                 "не хватает", "мало персонал", "одна медсестра", "одна санитарка"],
    "medication": ["medicine", "medication", "dose", "wrong drug", "drip", "injection", "pills", "tablet",
                   "dori", "ukol", "tomchi", "kapelnitsa", "dozasi", "tabletka",
                   "лекарств", "укол", "капельниц", "дозу", "дозировк", "таблетк", "препарат"],
    "diagnosis": ["test result", "x-ray", "xray", "scan", "diagnos", "blood test", "lab result",
                  "tahlil", "rentgen", "tashxis", "natija", "uzi",
                  "анализ", "рентген", "диагноз", "узи", "результат"],
    "hygiene": ["dirty", "unclean", "infection", "hygiene", "bed sheets", "toilet", "smell", "cockroach",
                "iflos", "tozalik", "toza emas", "infeksiya", "hojatxona", "choyshab", "hid ",
                "грязн", "антисанитар", "инфекц", "гигиен", "туалет", "запах", "простын", "тараканы"],
    "falls": ["fell", "fall ", "falls", "slipped", "bed rail", "wheelchair",
              "yiqil", "sirpan", "qulab", "упал", "скольз", "поскольз", "перил"],
    "equipment": ["broken", "not working", "equipment", "monitor", "oxygen", "elevator", "no light",
                  "buzuq", "ishlamaydi", "jihoz", "kislorod", "chiroq",
                  "сломан", "не работает", "оборудован", "кислород", "лифт", "нет света"],
    "behavior": ["rude", "shouted", "yelled", "disrespect", "insult",
                 "qo'pol", "baqir", "haqorat", "hurmat qilmad", "do'q",
                 "груб", "накричал", "кричал", "хамств", "оскорб"],
    "communication": ["no one explained", "didn't explain", "did not explain", "not told", "unclear",
                      "tushuntirmad", "aytmad", "ma'lumot bermad", "tushunarsiz",
                      "не объяснил", "не сказал", "не объясн", "непонятно", "ничего не говор"],
    "pain": ["pain", "painkiller", "in agony", "og'riq", "og'riyap", "боль", "болит", "обезбол"],
    "privacy": ["privacy", "curtain", "exposed", "confidential", "maxfiy", "shaxsiy hayot", "pardasiz",
                "hammaning oldida", "приватност", "конфиденц", "ширм", "при всех", "разгласил"],
    "billing": ["bribe", "paid extra", "informal payment", "asked for money", "bill ", "pul so'rad",
                "pora", "to'lov", "qo'shimcha pul", "взятк", "деньги", "доплат", "заплатил", "просили деньги"],
    "food": ["food", "meal", "water", "cold room", "heating", "blanket",
             "ovqat", "suv yo'q", "sovuq", "isitish", "ko'rpa",
             "еда", "питан", "воды нет", "холодно", "отоплен", "одеял"],
}

_URGENT = [
    "bleeding", "not breathing", "can't breathe", "cannot breathe", "unconscious", "chest pain", "seizure",
    "collapsed", "died", "death", "qon ketish", "nafas ol", "nafas olmay", "hushidan ketdi",
    "ko'krak og'riq", "tutqanoq", "vafot", "o'ldi", "o'lim", "кровотеч", "не дышит", "задыха",
    "без сознания", "боль в груди", "судорог", "умер", "смерть", "потерял сознание", "потеряла сознание",
]
_HARM = ["death", "died", "o'lim", "vafot", "смерть", "умер", "blood", "qon", "кров", "icu", "reanim",
         "реанимац", "wrong patient", "noto'g'ri bemor", "не тому пациенту", "wrong dose", "overdose",
         "передоз"]
_NEAR = ["almost", "nearly", "just in time", "close call", "caught it", "caught before",
         "чуть не", "едва не", "вовремя заметил", "вовремя заметила", "заметили вовремя", "заметил вовремя",
         "заметила вовремя", "oz qoldi", "yaxshiyamki",
         "o'z vaqtida payqa", "payqab qoldim"]
_BASE_SEV = {"medication": 3, "diagnosis": 3, "falls": 3, "pain": 3, "hygiene": 2}


def _hits(text, words):
    """Keyword stems that start at a word boundary (so "o'lim" does not match inside "bo'limida")."""
    low, lat = _variants(text)
    found = []
    for w in words:
        pat = re.compile(r"(?<!\w)" + re.escape(w))
        if pat.search(low) or pat.search(lat):
            found.append(w)
    return found


# ---- privacy check before sending: details that can identify a person even after masking -----------
_RISKY = [
    re.compile(r"(?<!\w)(?:the only|only one|the one)\s+\w+(?:\s+\w+)?", re.I),
    re.compile(r"(?<!\w)единственн\w*\s+\w+", re.I),
    re.compile(r"(?<!\w)одн[аи]\s+(?:на|во|в)\s+\w+", re.I),
    re.compile(r"(?<!\w)(?:yagona|faqat bitta)\s+\w+", re.I),
    re.compile(r"(?<!\w)\d{1,3}\s?(?:years? old|y\.o\.|yosh\w*|лет|год\w*)(?!\w)", re.I),           # ages
    re.compile(r"(?<!\w)\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?!\w)"),                                # exact dates
    re.compile(r"(?<!\w)(?:bed|krovat|койк\w*|joy)\s*(?:no\.?|№|#)?\s*\d+", re.I),                  # bed numbers
]


def privacy_flags(masked: str, limit: int = 5) -> list:
    """Phrases that may still identify someone (unique roles, ages, exact dates, bed numbers).
    Shown to the reporter before sending, so they can remove them. Nothing is changed automatically."""
    found = []
    for pat in _RISKY:
        for m in pat.finditer(masked or ""):
            s = m.group(0).strip(" ,.;:")
            if s and s.lower() not in (f.lower() for f in found):
                found.append(s)
    return found[:limit]


_BRIBE = ["bribe", "informal payment", "asked for money", "paid extra", "pora", "pul so'rad", "qo'shimcha pul",
          "взятк", "просили деньги", "доплат"]


def mentions_bribery(masked: str) -> bool:
    return bool(_hits(masked, _BRIBE))


def rule_triage(masked: str, source: str, harm: str = "none", near_miss_flag: bool = False):
    scores = {c: len(_hits(masked, kws)) for c, kws in _KEYWORDS.items()}
    best = max(scores, key=lambda c: scores[c])
    category = best if scores[best] > 0 else "other"
    urgent = bool(_hits(masked, _URGENT))
    sev = _BASE_SEV.get(category, 2)
    if _hits(masked, _HARM):
        sev += 2
    near = near_miss_flag or bool(_hits(masked, _NEAR))
    if near:
        sev -= 1
    if harm == "serious":
        sev = max(sev, 4)
    elif harm == "minor":
        sev = max(sev, 3)
    if urgent:
        sev = max(sev, 4)
    sev = max(1, min(5, sev))
    desc = CATEGORIES[category][2]
    summary = desc + (NEAR_MISS_SUFFIX if near else "")
    return {"category": category, "severity": sev, "urgent": urgent, "near_miss": near, "summary": summary}


# --------------------------------------------------------------------------------------
# LLM (any OpenAI-compatible chat-completions API)
# --------------------------------------------------------------------------------------
NEAR_MISS_SUFFIX = " It was caught before reaching the patient (near-miss)."


def is_rule_summary(summary: str) -> bool:
    """True if the summary is only the category's standard sentence (no AI model wrote it), so it says nothing
    about what actually happened."""
    return any(summary in (d, d + NEAR_MISS_SUFFIX) for _, _, d in CATEGORIES.values())


def llm_enabled() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL)


def llm_json(system: str, user: str, timeout: float = 25.0):
    if not llm_enabled():
        return None
    try:
        r = httpx.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            json={
                "model": config.LLM_MODEL,
                "temperature": 0.1,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
        return json.loads(content)
    except Exception:
        return None


_TRIAGE_SYSTEM = (
    "You triage anonymous hospital safety and feedback reports written in Uzbek, Russian or English. "
    "The text is already masked. Reply with JSON only, keys: "
    f"category (one of {list(CATEGORIES)}), severity (integer 1-5, 5 = most serious), urgent (bool: immediate "
    "danger such as bleeding, not breathing, unconscious), near_miss (bool: error caught before harm), "
    "summary (ONE neutral English sentence: no names, no exact times or dates, no job titles, no blame, "
    "describe the process problem only)."
)


def analyze(text: str, source: str, harm: str = "none", near_miss_flag: bool = False, use_llm: bool = True):
    """Mask, then triage. Returns dict ready to store.
    use_llm=False (the clinic's plan has no AI sorting): keyword rules only; masking and urgent flags are the same."""
    masked = mask_text(text)
    result = rule_triage(masked, source, harm, near_miss_flag)
    llm = llm_json(_TRIAGE_SYSTEM, f"source: {source}\nreport: {masked}") if use_llm else None
    if isinstance(llm, dict) and llm.get("category") in CATEGORIES:
        try:
            result["category"] = llm["category"]
            result["severity"] = max(1, min(5, int(llm.get("severity", result["severity"]))))
            result["urgent"] = bool(llm.get("urgent", result["urgent"])) or result["urgent"]
            result["near_miss"] = bool(llm.get("near_miss", result["near_miss"])) or near_miss_flag
            if isinstance(llm.get("summary"), str) and llm["summary"].strip():
                result["summary"] = llm["summary"].strip()
            if harm == "serious":
                result["severity"] = max(result["severity"], 4)
            if result["urgent"]:
                result["severity"] = max(result["severity"], 4)
        except Exception:
            pass
    result["theme"] = CATEGORIES[result["category"]][0]
    result["masked"] = masked
    return result


# --------------------------------------------------------------------------------------
# Root-cause assistant
# --------------------------------------------------------------------------------------
_RCA_FALLBACK = {
    "continuity": {
        "whys": [
            "Reports describe care being delayed, calls going unanswered or information being lost around shift changes.",
            "Why? Handover between shifts is likely informal and not structured, so key details are dropped.",
            "Why? There may be no standard checklist or protected time for handover, and night cover is thin.",
            "Why? Staffing and workload are probably not matched to patient numbers at those hours.",
        ],
        "fixes": [
            "Introduce a short structured handover checklist (for example SBAR) at every shift change.",
            "Review night-shift staffing against patient load and adjust.",
            "Set a call-bell response target and track it weekly on the ward.",
        ],
    },
    "medication": {
        "whys": [
            "Reports describe medicines given late, at the wrong dose or to the wrong patient.",
            "Why? Checks before giving a medicine may depend on memory rather than a fixed step.",
            "Why? Similar-looking drugs, unclear orders or interruptions make mix-ups likelier.",
        ],
        "fixes": [
            "Add a two-person check for high-risk medicines.",
            "Label and separate look-alike drugs; keep a protected, interruption-free preparation time.",
            "Make medication orders legible and standard (printed or electronic).",
        ],
    },
    "diagnosis": {
        "whys": [
            "Reports describe tests or results that were delayed, missed or mixed up.",
            "Why? There may be no single tracking list for ordered tests and returned results.",
            "Why? Responsibility for following up a result is unclear between teams.",
        ],
        "fixes": [
            "Keep a daily list of pending tests with a named owner for each result.",
            "Add a patient-identity double check on samples and result slips.",
        ],
    },
    "hygiene": {
        "whys": [
            "Reports describe cleanliness or infection-control problems.",
            "Why? Cleaning schedules and supplies may not match ward use.",
            "Why? Responsibility for checks is unclear and not audited.",
        ],
        "fixes": [
            "Publish a cleaning schedule per ward and check it with a simple daily sign-off.",
            "Ensure soap, hand rub and gloves are always stocked; audit hand hygiene monthly.",
        ],
    },
    "physical_safety": {
        "whys": [
            "Reports describe falls or physical hazards.",
            "Why? Floors, bed rails or lighting may be unsafe, or patients at risk are not identified.",
        ],
        "fixes": [
            "Do a fall-risk check on admission and mark high-risk patients.",
            "Fix hazards found in a ward safety walk-round (wet floors, lighting, broken rails).",
        ],
    },
    "facilities": {
        "whys": [
            "Reports describe broken equipment or poor food and comfort.",
            "Why? Faults are not reported quickly or repairs take too long.",
        ],
        "fixes": [
            "Create a simple fault-reporting log with a repair deadline and owner.",
            "Check heating, water and meal delivery weekly and report on it.",
        ],
    },
    "communication": {
        "whys": [
            "Reports describe patients feeling disrespected or poorly informed.",
            "Why? Staff workload leaves little time to explain, and there is no simple standard for it.",
        ],
        "fixes": [
            "Agree a short standard for explaining care to patients and relatives at each shift.",
            "Share patient feedback with the ward team regularly, focusing on the process, not individuals.",
        ],
    },
    "pain_care": {
        "whys": [
            "Reports describe pain not being addressed in time.",
            "Why? Pain may not be assessed routinely, or the person who can give pain relief is hard to reach.",
        ],
        "fixes": ["Add a routine pain check to regular observation rounds and record it."],
    },
    "privacy": {
        "whys": [
            "Reports describe privacy or confidentiality not being respected.",
            "Why? Screens or private spaces may be lacking, or discussing patients in public areas is habitual.",
        ],
        "fixes": ["Provide screens or a private space for examinations and discussions; remind teams of the rules."],
    },
    "billing": {
        "whys": [
            "Reports describe unclear charges or requests for informal payments.",
            "Why? Patients may not know the official prices or whom to ask.",
        ],
        "fixes": ["Display official prices clearly and give patients a written breakdown of any charges."],
    },
    "other": {
        "whys": ["Reports do not share a clear common theme."],
        "fixes": ["Review the individual reports and look for a pattern with the ward team."],
    },
}

# Theme names and rule-based root-cause suggestions in Uzbek and Russian (English is above).
# NOTE: have a native speaker review this wording before real use.
THEMES_I18N = {
    "uz": {
        "continuity": "Parvarish uzluksizligi va tezkorlik", "medication": "Dori xavfsizligi",
        "diagnosis": "Tahlillar va tashxis", "hygiene": "Gigiyena va infeksiya nazorati",
        "physical_safety": "Yiqilish va jismoniy xavfsizlik", "facilities": "Jihozlar, ovqat va sharoit",
        "communication": "Muloqot va hurmat", "pain_care": "Og'riqni davolash", "privacy": "Maxfiylik",
        "billing": "To'lovlar", "other": "Boshqa",
    },
    "ru": {
        "continuity": "Непрерывность ухода и отклик", "medication": "Безопасность лекарств",
        "diagnosis": "Анализы и диагностика", "hygiene": "Гигиена и инфекционный контроль",
        "physical_safety": "Падения и физическая безопасность", "facilities": "Оборудование, питание и условия",
        "communication": "Общение и уважение", "pain_care": "Обезболивание", "privacy": "Конфиденциальность",
        "billing": "Оплата", "other": "Другое",
    },
}

_RCA_SUMMARY = {
    "en": "Likely process causes behind recurring '{theme}' reports in {unit}.",
    "uz": "{unit} bo'yicha takrorlanuvchi «{theme}» murojaatlarining ehtimoliy jarayon sabablari.",
    "ru": "Вероятные причины в процессах, стоящие за повторяющимися обращениями «{theme}» в {unit}.",
}

_RCA_FALLBACK_I18N = {
    "uz": {
        "continuity": {
            "whys": [
                "Murojaatlarda parvarish kechikishi, chaqiruvlarga javob berilmasligi yoki smena almashganda ma'lumot yo'qolishi aytilgan.",
                "Nega? Smenalar o'rtasida topshirish norasmiy va tartibsiz bo'lishi mumkin, shuning uchun muhim tafsilotlar tushib qoladi.",
                "Nega? Topshirish uchun standart ro'yxat yoki ajratilgan vaqt yo'q, tungi smenada xodim kam bo'lishi mumkin.",
                "Nega? O'sha soatlarda xodimlar soni va ish hajmi bemorlar soniga mos kelmasligi mumkin.",
            ],
            "fixes": [
                "Har bir smena almashinuvida qisqa tartibli topshirish ro'yxatini joriy qiling (masalan, SBAR).",
                "Tungi smenadagi xodimlar sonini bemorlar soniga qarab qayta ko'rib chiqing.",
                "Chaqiruv tugmasiga javob berish vaqti uchun maqsad belgilang va uni har hafta bo'limda kuzating.",
            ],
        },
        "medication": {
            "whys": [
                "Murojaatlarda dori kechikib, noto'g'ri dozada yoki boshqa bemorga berilgani aytilgan.",
                "Nega? Dori berishdan oldingi tekshiruv qat'iy qadamga emas, xotiraga tayanishi mumkin.",
                "Nega? Bir-biriga o'xshash dorilar, tushunarsiz buyurtmalar yoki chalg'ishlar xatoni ko'paytiradi.",
            ],
            "fixes": [
                "Yuqori xavfli dorilar uchun ikki kishilik tekshiruvni joriy qiling.",
                "O'xshash dorilarni belgilab, alohida saqlang; tayyorlash uchun chalg'itilmaydigan vaqt ajrating.",
                "Dori buyurtmalarini aniq va standart qiling (bosma yoki elektron).",
            ],
        },
        "diagnosis": {
            "whys": [
                "Murojaatlarda tahlil yoki natijalar kechikkani, yo'qolgani yoki aralashib ketgani aytilgan.",
                "Nega? Buyurilgan tahlillar va kelgan natijalar uchun yagona kuzatuv ro'yxati bo'lmasligi mumkin.",
                "Nega? Natijani kuzatish kimning vazifasi ekani jamoalar o'rtasida aniq emas.",
            ],
            "fixes": [
                "Kutilayotgan tahlillarning kundalik ro'yxatini yuriting, har bir natija uchun mas'ul shaxsni belgilang.",
                "Namunalar va natija varaqalarida bemor shaxsini ikki marta tekshirishni qo'shing.",
            ],
        },
        "hygiene": {
            "whys": [
                "Murojaatlarda tozalik yoki infeksiya nazorati muammolari aytilgan.",
                "Nega? Tozalash jadvali va vositalar bo'limning ehtiyojiga mos kelmasligi mumkin.",
                "Nega? Tekshiruv uchun mas'uliyat aniq emas va nazorat qilinmaydi.",
            ],
            "fixes": [
                "Har bir bo'lim uchun tozalash jadvalini e'lon qiling va kunlik imzo bilan tekshiring.",
                "Sovun, antiseptik va qo'lqoplar doim bo'lishini ta'minlang; qo'l gigiyenasini har oy tekshiring.",
            ],
        },
        "physical_safety": {
            "whys": [
                "Murojaatlarda yiqilish yoki jismoniy xavflar aytilgan.",
                "Nega? Pol, karavot panjaralari yoki yoritish xavfli bo'lishi, xavf ostidagi bemorlar aniqlanmasligi mumkin.",
            ],
            "fixes": [
                "Qabul paytida yiqilish xavfini baholang va yuqori xavfli bemorlarni belgilang.",
                "Bo'limni xavfsizlik nuqtai nazaridan aylanib chiqib, topilgan xavflarni bartaraf eting (ho'l pol, yoritish, singan panjara).",
            ],
        },
        "facilities": {
            "whys": [
                "Murojaatlarda buzilgan jihozlar yoki ovqat va sharoit yomonligi aytilgan.",
                "Nega? Nosozliklar tez xabar qilinmaydi yoki ta'mirlash uzoq davom etadi.",
            ],
            "fixes": [
                "Ta'mirlash muddati va mas'uli ko'rsatilgan oddiy nosozliklar jurnalini yarating.",
                "Isitish, suv va ovqat yetkazilishini har hafta tekshiring va hisobot bering.",
            ],
        },
        "communication": {
            "whys": [
                "Murojaatlarda bemorlar hurmatsizlik yoki ma'lumot yetishmasligini his qilgani aytilgan.",
                "Nega? Xodimlarning ish yuki tushuntirishga vaqt qoldirmaydi va buning oddiy standarti yo'q.",
            ],
            "fixes": [
                "Har smenada bemor va qarindoshlarga parvarishni tushuntirishning qisqa standartini kelishib oling.",
                "Bemorlar fikrini bo'lim jamoasi bilan muntazam baham ko'ring: shaxslarga emas, jarayonga e'tibor bering.",
            ],
        },
        "pain_care": {
            "whys": [
                "Murojaatlarda og'riqqa o'z vaqtida e'tibor berilmagani aytilgan.",
                "Nega? Og'riq muntazam baholanmasligi yoki og'riq qoldiruvchi bera oladigan xodimni topish qiyin bo'lishi mumkin.",
            ],
            "fixes": ["Muntazam ko'rik paytida og'riqni tekshirishni qo'shing va qayd eting."],
        },
        "privacy": {
            "whys": [
                "Murojaatlarda maxfiylik hurmat qilinmagani aytilgan.",
                "Nega? To'siqlar yoki alohida joy yetishmasligi yoki bemorlarni ochiq joyda muhokama qilish odat bo'lib qolgan bo'lishi mumkin.",
            ],
            "fixes": ["Ko'rik va suhbatlar uchun to'siq yoki alohida joy ajrating; jamoalarga qoidalarni eslating."],
        },
        "billing": {
            "whys": [
                "Murojaatlarda tushunarsiz to'lovlar yoki norasmiy to'lov so'ralgani aytilgan.",
                "Nega? Bemorlar rasmiy narxlarni yoki kimdan so'rashni bilmasligi mumkin.",
            ],
            "fixes": ["Rasmiy narxlarni ko'rinadigan joyga osib qo'ying va har qanday to'lov uchun yozma tafsilot bering."],
        },
        "other": {
            "whys": ["Murojaatlarda aniq umumiy mavzu yo'q."],
            "fixes": ["Murojaatlarni alohida ko'rib chiqing va bo'lim jamoasi bilan qonuniyat izlang."],
        },
    },
    "ru": {
        "continuity": {
            "whys": [
                "В обращениях говорится о задержках в уходе, вызовах без ответа или потере информации при смене.",
                "Почему? Передача смены, вероятно, неформальная и без структуры, поэтому важные детали теряются.",
                "Почему? Нет стандартного чек-листа или выделенного времени на передачу, ночью мало персонала.",
                "Почему? Численность персонала и нагрузка в эти часы, вероятно, не соответствуют числу пациентов.",
            ],
            "fixes": [
                "Ввести короткий структурированный чек-лист передачи смены (например, SBAR).",
                "Пересмотреть численность ночной смены с учётом числа пациентов.",
                "Установить норматив времени ответа на вызов и еженедельно отслеживать его в отделении.",
            ],
        },
        "medication": {
            "whys": [
                "В обращениях говорится о лекарствах, выданных с опозданием, в неверной дозе или не тому пациенту.",
                "Почему? Проверка перед выдачей лекарства может зависеть от памяти, а не от обязательного шага.",
                "Почему? Похожие препараты, неясные назначения или отвлечения повышают риск ошибки.",
            ],
            "fixes": [
                "Ввести двойную проверку двумя сотрудниками для препаратов высокого риска.",
                "Маркировать и хранить отдельно похожие препараты; выделить время на подготовку без отвлечений.",
                "Сделать назначения разборчивыми и стандартными (печатными или электронными).",
            ],
        },
        "diagnosis": {
            "whys": [
                "В обращениях говорится о задержанных, пропущенных или перепутанных анализах и результатах.",
                "Почему? Может не быть единого списка назначенных анализов и полученных результатов.",
                "Почему? Неясно, какая команда отвечает за отслеживание результата.",
            ],
            "fixes": [
                "Вести ежедневный список ожидаемых анализов с ответственным за каждый результат.",
                "Добавить двойную проверку личности пациента на пробах и бланках результатов.",
            ],
        },
        "hygiene": {
            "whys": [
                "В обращениях говорится о проблемах с чистотой или инфекционным контролем.",
                "Почему? График уборки и расходные материалы могут не соответствовать нагрузке отделения.",
                "Почему? Ответственность за проверки неясна и не контролируется.",
            ],
            "fixes": [
                "Вывесить график уборки для каждого отделения и проверять его ежедневной подписью.",
                "Обеспечить постоянный запас мыла, антисептика и перчаток; ежемесячно проверять гигиену рук.",
            ],
        },
        "physical_safety": {
            "whys": [
                "В обращениях говорится о падениях или физических опасностях.",
                "Почему? Пол, поручни кроватей или освещение могут быть небезопасны, а пациенты из группы риска не выявляются.",
            ],
            "fixes": [
                "Оценивать риск падения при поступлении и отмечать пациентов высокого риска.",
                "Устранять опасности, найденные при обходе отделения (мокрый пол, освещение, сломанные поручни).",
            ],
        },
        "facilities": {
            "whys": [
                "В обращениях говорится о сломанном оборудовании или плохом питании и условиях.",
                "Почему? О неисправностях сообщают не сразу, или ремонт занимает слишком много времени.",
            ],
            "fixes": [
                "Завести простой журнал неисправностей со сроком ремонта и ответственным.",
                "Еженедельно проверять отопление, воду и доставку питания и отчитываться об этом.",
            ],
        },
        "communication": {
            "whys": [
                "В обращениях говорится, что пациенты чувствовали неуважение или им не хватало информации.",
                "Почему? Нагрузка оставляет мало времени на объяснения, и для этого нет простого стандарта.",
            ],
            "fixes": [
                "Согласовать короткий стандарт объяснения ухода пациентам и родственникам в каждую смену.",
                "Регулярно обсуждать отзывы пациентов с командой отделения, фокусируясь на процессе, а не на людях.",
            ],
        },
        "pain_care": {
            "whys": [
                "В обращениях говорится, что боль не снимали вовремя.",
                "Почему? Боль может не оцениваться регулярно, или сотрудника, который может дать обезболивающее, трудно найти.",
            ],
            "fixes": ["Добавить оценку боли в регулярные обходы и записывать её."],
        },
        "privacy": {
            "whys": [
                "В обращениях говорится о несоблюдении конфиденциальности.",
                "Почему? Может не хватать ширм или отдельного помещения, или обсуждать пациентов при посторонних стало привычкой.",
            ],
            "fixes": ["Обеспечить ширмы или отдельное место для осмотров и бесед; напомнить командам правила."],
        },
        "billing": {
            "whys": [
                "В обращениях говорится о непонятных счетах или просьбах о неофициальной оплате.",
                "Почему? Пациенты могут не знать официальных цен или к кому обратиться.",
            ],
            "fixes": ["Чётко вывесить официальные цены и выдавать пациентам письменную расшифровку любых платежей."],
        },
        "other": {
            "whys": ["У обращений нет явной общей темы."],
            "fixes": ["Рассмотреть обращения по отдельности и поискать закономерность вместе с командой отделения."],
        },
    },
}

_RCA_SYSTEM = (
    "You help a hospital quality officer find root causes from anonymous reports. Use just-culture thinking: "
    "focus on systems and processes, never on individuals, and never assign blame. Reply with JSON only: "
    '{"summary": one sentence, "whys": [3-5 short strings forming a 5-whys chain], "fixes": [2-4 concrete, '
    "practical process fixes]}. Write in {language}."
)
_LANG_NAMES = {"en": "English", "uz": "Uzbek (Latin script)", "ru": "Russian"}


def theme_name(theme: str, lang: str = "en") -> str:
    return THEMES_I18N.get(lang, {}).get(theme) or THEMES.get(theme, theme)


def rca(theme: str, unit_label: str, patient_texts, staff_summaries, lang: str = "en", use_llm: bool = True):
    """Root-cause suggestions. use_llm=False (plan without AI root-cause help): standard suggestions per theme."""
    lang = lang if lang in _RCA_SUMMARY else "en"
    rules = _RCA_FALLBACK_I18N.get(lang, _RCA_FALLBACK)
    fb = rules.get(theme, rules["other"])
    out = {
        "summary": _RCA_SUMMARY[lang].format(theme=theme_name(theme, lang), unit=unit_label),
        "whys": fb["whys"],
        "fixes": fb["fixes"],
        "source": "rules",
    }
    payload = {
        "theme": THEMES.get(theme, theme),
        "unit": unit_label,
        "patient_reports": patient_texts[:8],
        "staff_summaries": staff_summaries[:8],
    }
    llm = (llm_json(_RCA_SYSTEM.replace("{language}", _LANG_NAMES[lang]), json.dumps(payload, ensure_ascii=False))
           if use_llm else None)
    if isinstance(llm, dict) and isinstance(llm.get("whys"), list) and isinstance(llm.get("fixes"), list):
        out["summary"] = str(llm.get("summary", out["summary"]))
        out["whys"] = [str(x) for x in llm["whys"]][:6]
        out["fixes"] = [str(x) for x in llm["fixes"]][:5]
        out["source"] = "llm"
    return out
