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
    summary = desc + (" It was caught before reaching the patient (near-miss)." if near else "")
    return {"category": category, "severity": sev, "urgent": urgent, "near_miss": near, "summary": summary}


# --------------------------------------------------------------------------------------
# LLM (any OpenAI-compatible chat-completions API)
# --------------------------------------------------------------------------------------
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


def analyze(text: str, source: str, harm: str = "none", near_miss_flag: bool = False):
    """Mask, then triage. Returns dict ready to store."""
    masked = mask_text(text)
    result = rule_triage(masked, source, harm, near_miss_flag)
    llm = llm_json(_TRIAGE_SYSTEM, f"source: {source}\nreport: {masked}")
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

_RCA_SYSTEM = (
    "You help a hospital quality officer find root causes from anonymous reports. Use just-culture thinking: "
    "focus on systems and processes, never on individuals, and never assign blame. Reply with JSON only: "
    '{"summary": one sentence, "whys": [3-5 short strings forming a 5-whys chain], "fixes": [2-4 concrete, '
    "practical process fixes]}. English."
)


def rca(theme: str, unit_label: str, patient_texts, staff_summaries):
    fb = _RCA_FALLBACK.get(theme, _RCA_FALLBACK["other"])
    out = {
        "summary": f"Likely process causes behind recurring '{THEMES.get(theme, theme)}' reports in {unit_label}.",
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
    llm = llm_json(_RCA_SYSTEM, json.dumps(payload, ensure_ascii=False))
    if isinstance(llm, dict) and isinstance(llm.get("whys"), list) and isinstance(llm.get("fixes"), list):
        out["summary"] = str(llm.get("summary", out["summary"]))
        out["whys"] = [str(x) for x in llm["whys"]][:6]
        out["fixes"] = [str(x) for x in llm["fixes"]][:5]
        out["source"] = "llm"
    return out
