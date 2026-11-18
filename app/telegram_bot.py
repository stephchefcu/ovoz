"""Telegram bot: anonymous reports by voice message or text, in Uzbek, Russian or English.

Run:  python -m app.telegram_bot        (needs TELEGRAM_BOT_TOKEN in .env; get one from @BotFather)

It asks Telegram for new messages (long polling), so it needs no public address and runs next to the web app.

Privacy:
- Nothing about the person is stored: no chat id, username, phone or audio. Only the masked report text goes to the
  database, exactly like the web form (app/reports.py).
- The conversation in progress (language, ward, draft text) is kept in memory for up to 30 minutes, then forgotten.
- Rate limits use a hash of the chat id, in memory only.
- Telegram itself knows who sent a message; the bot says so at the start.
- Logs never contain message text or the bot token.
"""
import hashlib
import html
import sys
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

import httpx

from . import ai, analytics, clinics, config, reports, terms, voice
from .db import db, init_db

SESSION_TTL = 30 * 60
MAX_VOICE_SECONDS = 180
MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram's download limit for bots

# NOTE: please have a native speaker review the Uzbek and Russian wording before real use.
T = {
    "uz": {
        "emergency": "⚠️ Bu favqulodda xizmat emas. Shoshilinch yordam uchun hamshirani chaqiring.",
        "who": "Siz kimsiz?",
        "btn_patient": "🧑 Men bemorman",
        "btn_staff": "🩺 Men xodimman",
        "btn_case": "🔎 Murojaatimni tekshirish",
        "ward": "Qaysi bo'lim?",
        "rate": "Xizmat qanday edi?",
        "btn_skip": "O'tkazib yuborish",
        "ask_text": "🎤 Ovozli xabar yuboring yoki yozing: nima bo'ldi?\nBir xabarda — bitta muammo, 3 daqiqagacha.",
        "ask_text_staff": "🎤 Nima bo'lganini aytib bering — ovozli xabar yoki matn.\nKichik hodisalar va oldi olingan xatolar eng muhimi. Kim aybdorligini yozish shart emas: biz odamlarni emas, tizimni tuzatamiz.\n\n⚠️ Bemor hozir xavf ostida bo'lsa, darhol harakat qiling yoki qo'ng'iroq qiling. Bu bot o'rganish uchun.",
        "transcribing": "⏳ Matnga aylantirilmoqda…",
        "too_long": "Ovozli xabar juda uzun (3 daqiqagacha). Qisqaroq yuboring yoki yozing.",
        "voice_fail": "Ovozni matnga aylantirib bo'lmadi. Iltimos, yozib yuboring.",
        "voice_demo": "(Demo rejim: ovoz xizmati ulanmagan, namunaviy matn qo'yildi.)",
        "confirm_hint": "Tuzatish kerak bo'lsa, to'g'ri matnni yozing yoki yangi ovozli xabar yuboring.",
        "btn_cancel": "✖ Bekor qilish",
        "cancelled": "Bekor qilindi. Qaytadan boshlash uchun /start bosing.",
        "done": "✅ <b>Rahmat! Murojaatingiz qabul qilindi.</b>\n\nSizning kodingiz (saqlab qo'ying):\n<code>{code}</code>\n\nShifoxona savol bersa, uni shu yerda /case orqali ko'rasiz. Yana murojaat: /start",
        "done_urgent": "⚠️ Siz shoshilinch holat haqida yozdingiz. Hozir yordam kerak bo'lsa, hamshirani chaqiring.",
        "too_short": "Iltimos, kamida bir necha so'z yozing.",
        "slow_down": "Juda ko'p xabar. Birozdan keyin qayta urinib ko'ring.",
        "err": "Xatolik. Iltimos, qayta urinib ko'ring.",
        "case_ask": "Murojaat kodingizni yuboring (masalan, ABCD-2345).",
        "c_notfound": "Bunday kod topilmadi. Tekshirib, qayta yuboring.",
        "c_none": "Hozircha xabar yo'q. Keyinroq qayta tekshiring.",
        "c_clinic": "Shifoxona",
        "c_you": "Siz",
        "btn_reply": "✍️ Javob yozish",
        "reply_ask": "Javobingizni yozing.",
        "reply_text_only": "Iltimos, javobni matn bilan yozing.",
        "c_sent": "✅ Javob yuborildi.",
        "start_first": "Boshlash uchun /start bosing.",
        "review_title": "📋 <b>Aynan shu yuboriladi:</b>",
        "rv_msg": "Xabar (ism va raqamlar yashirilgan)",
        "rv_ward": "Bo'lim",
        "rv_role": "Siz",
        "role_patient": "bemor yoki yaqini",
        "role_staff": "xodim",
        "rv_rating": "Baho",
        "rv_none": "ko'rsatilmagan",
        "rv_type": "Turi",
        "rv_date": "Sana",
        "tb_morning": "ertalab",
        "tb_afternoon": "kunduzi",
        "tb_night": "kechasi",
        "rv_staffdate": "rahbariyat faqat haftani ko'radi",
        "rv_lang": "Til",
        "rv_not": "🚫 Yuborilmaydi: ismingiz, telefon raqamingiz, Telegram akkauntingiz, ovoz yozuvi (matnga aylantirilgach darhol o'chiriladi).",
        "rv_who": "👀 Faqat shifoxonaning sifat bo'yicha mas'ullari ko'radi.",
        "rv_agree": "«Roziman, yuborish» tugmasini bosib, yuqoridagi ma'lumot yuborilishiga hamda Foydalanish shartlari va maxfiylik siyosatiga rozilik bildirasiz: /privacy",
        "btn_agree": "✅ Roziman, yuborish",
        "ask_clinic": "🏥 Qaysi klinika? Bo'limdagi QR-kodni skanerlang yoki klinika kodini yozing (QR-kod ostida, masalan: demo).",
        "clinic_notfound": "Bunday klinika kodi topilmadi. QR-kod ostidagi kodni tekshirib, qayta yozing.",
        "rv_clinic": "Klinika",
        "btn_relative": "👪 Men bemorning yaqiniman",
        "btn_help": "🆘 Hozir yordam kerak",
        "trust": "🔒 <b>Ismingiz va Telegram ID'ingiz saqlanmaydi. Shifoxonada hech kim kim yozganini ko'ra olmaydi.</b>",
        "privacy_more": "Maxfiylik qanday himoyalanadi: /privacy",
        "max_privacy": "Telegram akkauntisiz yozmoqchimisiz? Veb-shakl: {url}",
        "f_good": "🙂 Yaxshi",
        "f_ok": "😐 O'rtacha",
        "f_bad": "🙁 Yomon",
        "help_now": "🆘 <b>Hozir hamshirani chaqirish tugmasini bosing yoki 103 ga qo'ng'iroq qiling.</b>\nBu bot favqulodda xizmat emas. Shifoxonaga ham xabar berish uchun nima bo'layotganini qisqacha yozing yoki ovozli xabar yuboring.",
        "help_type": "Qisqacha yozing yoki ayting: nima bo'lyapti?",
        "role_relative": "bemorning yaqini",
        "rv_urgent": "🆘 Shoshilinch deb belgilangan",
        "rv_flags": "⚠️ <b>Bu sizni yoki boshqa odamni tanitishi mumkin:</b>",
        "rv_flags_hint": "Olib tashlash uchun tuzatilgan matnni yuboring.",
        "serious_note": "⚠️ Bu jiddiy holatga o'xshaydi. Iltimos, rasmiy kanal orqali ham xabar bering: shifoxonaning sifat bo'limi yoki Sog'liqni saqlash vazirligi ishonch telefoni 1003.",
        "bribe_note": "Pora yoki norasmiy to'lov haqida korrupsiyaga qarshi 1203 liniyasiga ham murojaat qilishingiz mumkin.",
    },
    "ru": {
        "emergency": "⚠️ Это не служба экстренной помощи. При срочной необходимости позовите медсестру.",
        "who": "Кто вы?",
        "btn_patient": "🧑 Я пациент",
        "btn_staff": "🩺 Я сотрудник",
        "btn_case": "🔎 Проверить обращение",
        "ward": "Какое отделение?",
        "rate": "Как вас обслужили?",
        "btn_skip": "Пропустить",
        "ask_text": "🎤 Отправьте голосовое сообщение или напишите, что произошло.\nОдна проблема — одно сообщение, до 3 минут.",
        "ask_text_staff": "🎤 Просто расскажите, что произошло — голосом или текстом.\nМелочи и предотвращённые ошибки важнее всего. Не нужно писать, кто виноват: мы исправляем систему, а не ищем виноватых.\n\n⚠️ Если пациент в опасности прямо сейчас — действуйте или звоните. Этот бот — для обучения.",
        "transcribing": "⏳ Преобразуем в текст…",
        "too_long": "Голосовое слишком длинное (до 3 минут). Запишите короче или напишите текстом.",
        "voice_fail": "Не удалось преобразовать голос в текст. Пожалуйста, напишите.",
        "voice_demo": "(Демо-режим: сервис голоса не подключён, вставлен пример текста.)",
        "confirm_hint": "Если нужно исправить, отправьте исправленный текст или новое голосовое.",
        "btn_cancel": "✖ Отменить",
        "cancelled": "Отменено. Чтобы начать заново, нажмите /start.",
        "done": "✅ <b>Спасибо! Ваше обращение принято.</b>\n\nВаш код (сохраните):\n<code>{code}</code>\n\nЕсли клиника задаст вопрос, посмотрите его здесь через /case. Новое обращение: /start",
        "done_urgent": "⚠️ Вы сообщили о срочной ситуации. Если помощь нужна сейчас, позовите медсестру.",
        "too_short": "Пожалуйста, напишите хотя бы несколько слов.",
        "slow_down": "Слишком много сообщений. Попробуйте немного позже.",
        "err": "Ошибка. Пожалуйста, попробуйте ещё раз.",
        "case_ask": "Отправьте код обращения (например, ABCD-2345).",
        "c_notfound": "Такой код не найден. Проверьте и отправьте ещё раз.",
        "c_none": "Пока сообщений нет. Загляните позже.",
        "c_clinic": "Клиника",
        "c_you": "Вы",
        "btn_reply": "✍️ Ответить",
        "reply_ask": "Напишите ваш ответ.",
        "reply_text_only": "Пожалуйста, напишите ответ текстом.",
        "c_sent": "✅ Ответ отправлен.",
        "start_first": "Нажмите /start, чтобы начать.",
        "review_title": "📋 <b>Будет отправлено ровно это:</b>",
        "rv_msg": "Сообщение (имена и номера скрыты)",
        "rv_ward": "Отделение",
        "rv_role": "Вы",
        "role_patient": "пациент или родственник",
        "role_staff": "сотрудник",
        "rv_rating": "Оценка",
        "rv_none": "не указана",
        "rv_type": "Тип",
        "rv_date": "Дата",
        "tb_morning": "утро",
        "tb_afternoon": "день",
        "tb_night": "ночь",
        "rv_staffdate": "руководство видит только неделю",
        "rv_lang": "Язык",
        "rv_not": "🚫 Не отправляется: ваше имя, телефон, аккаунт Telegram, голосовая запись (удаляется сразу после перевода в текст).",
        "rv_who": "👀 Увидит только служба качества клиники.",
        "rv_agree": "Нажимая «Согласен(на), отправить», вы соглашаетесь на отправку данных выше и с Условиями использования и конфиденциальности: /privacy",
        "btn_agree": "✅ Согласен(на), отправить",
        "ask_clinic": "🏥 Какая клиника? Отсканируйте QR-код в отделении или напишите код клиники (под QR-кодом, например: demo).",
        "clinic_notfound": "Клиника с таким кодом не найдена. Проверьте код под QR-кодом и напишите ещё раз.",
        "rv_clinic": "Клиника",
        "btn_relative": "👪 Я родственник пациента",
        "btn_help": "🆘 Нужна помощь СЕЙЧАС",
        "trust": "🔒 <b>Ваше имя и Telegram ID не сохраняются. Никто в больнице не может увидеть, кто это написал.</b>",
        "privacy_more": "Как защищена анонимность: /privacy",
        "max_privacy": "Не хотите использовать аккаунт Telegram? Веб-форма: {url}",
        "f_good": "🙂 Хорошо",
        "f_ok": "😐 Нормально",
        "f_bad": "🙁 Плохо",
        "help_now": "🆘 <b>Сейчас нажмите кнопку вызова медсестры или позвоните 103.</b>\nЭтот бот — не экстренная служба. Чтобы сообщить и клинике, коротко напишите или скажите голосом, что происходит.",
        "help_type": "Коротко напишите или скажите: что происходит?",
        "role_relative": "родственник пациента",
        "rv_urgent": "🆘 Отмечено как срочное",
        "rv_flags": "⚠️ <b>Это может выдать вас или другого человека:</b>",
        "rv_flags_hint": "Чтобы убрать, отправьте исправленный текст.",
        "serious_note": "⚠️ Похоже на серьёзный случай. Пожалуйста, сообщите и через официальный канал: служба качества клиники или горячая линия Минздрава 1003.",
        "bribe_note": "О взятках и неофициальных платежах можно также сообщить на линию по борьбе с коррупцией 1203.",
    },
    "en": {
        "emergency": "⚠️ This is not an emergency service. For urgent help, call a nurse.",
        "who": "Who are you?",
        "btn_patient": "🧑 I am a patient",
        "btn_staff": "🩺 I am staff",
        "btn_case": "🔎 Check my report",
        "ward": "Which ward?",
        "rate": "How was your care?",
        "btn_skip": "Skip",
        "ask_text": "🎤 Send a voice message or type what happened.\nOne problem per message, up to 3 minutes.",
        "ask_text_staff": "🎤 Just tell us what happened, by voice or text.\nSmall things and near-misses matter most. No need to say who is to blame: we fix systems, not people.\n\n⚠️ If a patient is in danger right now, act or call now. This bot is for learning.",
        "transcribing": "⏳ Turning your voice into text…",
        "too_long": "That voice message is too long (up to 3 minutes). Record a shorter one or type instead.",
        "voice_fail": "We could not turn the voice into text. Please type instead.",
        "voice_demo": "(Demo mode: no speech service connected, sample text inserted.)",
        "confirm_hint": "To correct it, send the corrected text or a new voice message.",
        "btn_cancel": "✖ Cancel",
        "cancelled": "Cancelled. Send /start to begin again.",
        "done": "✅ <b>Thank you! Your report was received.</b>\n\nYour code (keep it):\n<code>{code}</code>\n\nIf the clinic asks a question, check it here with /case. New report: /start",
        "done_urgent": "⚠️ You mentioned an urgent situation. If you need help right now, please call a nurse.",
        "too_short": "Please write at least a few words.",
        "slow_down": "Too many messages. Please try again a little later.",
        "err": "Something went wrong. Please try again.",
        "case_ask": "Send your report code (for example ABCD-2345).",
        "c_notfound": "That code was not found. Check it and send it again.",
        "c_none": "No messages yet. Please check again later.",
        "c_clinic": "Clinic",
        "c_you": "You",
        "btn_reply": "✍️ Reply",
        "reply_ask": "Type your reply.",
        "reply_text_only": "Please type your reply as text.",
        "c_sent": "✅ Reply sent.",
        "start_first": "Send /start to begin.",
        "review_title": "📋 <b>Exactly this will be sent:</b>",
        "rv_msg": "Message (names and numbers hidden)",
        "rv_ward": "Ward",
        "rv_role": "You are",
        "role_patient": "patient or relative",
        "role_staff": "staff member",
        "rv_rating": "Rating",
        "rv_none": "not given",
        "rv_type": "Type",
        "rv_date": "Date",
        "tb_morning": "morning",
        "tb_afternoon": "afternoon",
        "tb_night": "night",
        "rv_staffdate": "managers see only the week",
        "rv_lang": "Language",
        "rv_not": "🚫 Not sent: your name, phone number, Telegram account, voice recording (deleted as soon as it is turned into text).",
        "rv_who": "👀 Only the clinic's quality team will see it.",
        "rv_agree": "By tapping “I agree, send” you agree to sending the information above and to the Terms of use and privacy: /privacy",
        "btn_agree": "✅ I agree, send",
        "ask_clinic": "🏥 Which clinic? Scan the QR code in the department, or type the clinic code (under the QR code, e.g. demo).",
        "clinic_notfound": "No clinic with that code. Check the code under the QR code and type it again.",
        "rv_clinic": "Clinic",
        "btn_relative": "👪 I am a relative",
        "btn_help": "🆘 Someone needs help NOW",
        "trust": "🔒 <b>Your name and Telegram ID are not saved. Nobody in the hospital can see who wrote this.</b>",
        "privacy_more": "How your privacy is protected: /privacy",
        "max_privacy": "Prefer not to use your Telegram account? Web form: {url}",
        "f_good": "🙂 Good",
        "f_ok": "😐 OK",
        "f_bad": "🙁 Bad",
        "help_now": "🆘 <b>Press the nurse call button now, or call 103.</b>\nThis bot is not an emergency service. To also tell the clinic, briefly type or say what is happening.",
        "help_type": "Briefly type or say: what is happening?",
        "role_relative": "relative",
        "rv_urgent": "🆘 Marked urgent",
        "rv_flags": "⚠️ <b>This might identify you or someone else:</b>",
        "rv_flags_hint": "To remove it, send the corrected text.",
        "serious_note": "⚠️ This sounds serious. Please also report it through the official channel: the clinic's quality unit or the Ministry of Health hotline 1003.",
        "bribe_note": "For bribes or informal payments you can also call the anti-corruption line 1203.",
    },
}

LANG_NAMES = {"uz": "O'zbekcha", "ru": "Русский", "en": "English"}
FACES = {"good": 5, "ok": 3, "bad": 1}   # three big buttons instead of five stars
FACE_LABEL = {5: "f_good", 3: "f_ok", 1: "f_bad"}
AUDIO_EXT = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
             "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/flac": ".flac"}


class TelegramError(Exception):
    pass


class TelegramApi:
    """Minimal Bot API client. Error messages never include the token (it is part of every URL)."""

    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"
        self._http = httpx.Client(timeout=30)

    def call(self, method: str, _http_timeout: float = 30, **params):
        # (named _http_timeout so it never clashes with Telegram's own "timeout" parameter of getUpdates)
        try:
            r = self._http.post(f"{self._base}/{method}", json=params, timeout=_http_timeout)
            data = r.json()
        except Exception as e:
            raise TelegramError(f"{method}: {type(e).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', 'error')}")
        return data["result"]

    def download(self, file_id: str) -> bytes:
        info = self.call("getFile", file_id=file_id)
        try:
            r = self._http.get(f"{self._files}/{info['file_path']}", timeout=60)
            r.raise_for_status()
        except Exception as e:
            raise TelegramError(f"download: {type(e).__name__}") from None
        return r.content


@dataclass
class Session:
    lang: str = "uz"
    # lang -> role -> ward -> detail -> text -> confirm | case_code -> case_view -> case_reply -> reply_confirm
    step: str = "lang"
    clinic_id: Optional[int] = None   # set by the QR deep link (/start w_<ward> or c_<clinic>) or a typed clinic code
    clinic_name: str = ""
    clinic_slug: str = ""
    mode: str = ""        # "patient" (department QR), "staff" (staff-room QR) or "" (clinic link / typed code)
    source: str = ""      # patient or staff
    reporter: str = ""    # patient / relative / staff
    urgent: bool = False  # "Someone needs help NOW"
    ward: str = ""
    rating: Optional[int] = None
    draft: str = ""
    case_code: str = ""
    touched: float = field(default_factory=time.time)


def _kb(rows):
    """Inline keyboard from rows of (label, callback_data)."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def _guess_lang(user: dict) -> str:
    code = (user or {}).get("language_code", "") or ""
    return "ru" if code.startswith("ru") else "en" if code.startswith("en") else "uz"


class Bot:
    def __init__(self, api):
        self.api = api
        self.sessions = {}
        self._sessions_lock = threading.Lock()
        self._chat_locks = defaultdict(threading.Lock)
        self._rate = defaultdict(deque)

    # ---- state helpers --------------------------------------------------------------------
    def _session(self, chat_id) -> Optional[Session]:
        with self._sessions_lock:
            now = time.time()
            for cid in [c for c, s in self.sessions.items() if now - s.touched > SESSION_TTL]:
                del self.sessions[cid]
            s = self.sessions.get(chat_id)
            if s:
                s.touched = now
            return s

    def _new_session(self, chat_id, lang="uz") -> Session:
        with self._sessions_lock:
            s = self.sessions[chat_id] = Session(lang=lang)
            return s

    def _end(self, chat_id):
        with self._sessions_lock:
            self.sessions.pop(chat_id, None)

    def _limited(self, chat_id, bucket, limit, window=600) -> bool:
        key = hashlib.sha256(f"{config.SECRET}:{chat_id}:{bucket}".encode()).hexdigest()
        q, now = self._rate[key], time.time()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False

    def send(self, chat_id, text, keyboard=None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard:
            params["reply_markup"] = keyboard
        return self.api.call("sendMessage", **params)

    # ---- dispatch -------------------------------------------------------------------------
    def handle_update(self, update: dict):
        if "callback_query" in update:
            cq = update["callback_query"]
            msg = cq.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("type") != "private":
                return
            try:
                self.api.call("answerCallbackQuery", callback_query_id=cq["id"])
                self.api.call("editMessageReplyMarkup", chat_id=chat["id"], message_id=msg["message_id"],
                              reply_markup={"inline_keyboard": []})
            except TelegramError:
                pass
            with self._chat_locks[chat["id"]]:
                self.on_button(chat["id"], cq.get("data", ""), cq.get("from"))
        elif "message" in update:
            msg = update["message"]
            chat = msg.get("chat") or {}
            if chat.get("type") != "private":
                return
            with self._chat_locks[chat["id"]]:
                self.on_message(chat["id"], msg)

    # ---- messages -------------------------------------------------------------------------
    def on_message(self, chat_id, msg):
        text = (msg.get("text") or "").strip()
        if text.startswith("/start") or text.startswith("/help"):
            return self.start(chat_id, msg.get("from"), text)
        s = self._session(chat_id)
        if text.startswith("/privacy") or text.startswith("/terms"):
            self.send(chat_id, terms.terms_html(s.lang if s else _guess_lang(msg.get("from")), self._clinic(s)))
            if s and s.step == "confirm":  # put the review card back so they can agree or cancel
                return self.ask_confirm(chat_id, s)
            if s and s.step == "reply_confirm":
                return self.ask_reply_confirm(chat_id, s)
            return None
        if text.startswith("/case"):
            s = s or self._new_session(chat_id, _guess_lang(msg.get("from")))
            s.step = "case_code"
            return self.send(chat_id, T[s.lang]["case_ask"])
        if not s:
            return self.send(chat_id, T[_guess_lang(msg.get("from"))]["start_first"])
        t = T[s.lang]

        if s.step == "case_code" and text:
            return self.show_case(chat_id, s, text)
        if s.step == "clinic" and text:
            with db() as conn:
                c = clinics.by_slug(conn, text.split()[0])
            if not c:
                return self.send(chat_id, t["clinic_notfound"])
            s.clinic_id, s.clinic_name, s.clinic_slug = c["id"], c["name"], c["slug"]
            return self.ask_role(chat_id, s)
        if s.step in ("case_reply", "reply_confirm"):
            if not text:
                return self.send(chat_id, t["reply_text_only"])
            s.draft = text[:2000]
            return self.ask_reply_confirm(chat_id, s)
        if s.step in ("text", "confirm"):
            audio = msg.get("voice") or msg.get("audio")
            if audio:
                return self.on_voice(chat_id, s, audio)
            if text:
                if len(text) < 5:
                    return self.send(chat_id, t["too_short"])
                s.draft = text[:3000]
                return self.ask_confirm(chat_id, s)
            # a photo, sticker etc.: repeat the question instead of losing their place
            return self.send(chat_id, t["ask_text_staff" if s.source == "staff" else "ask_text"])
        if s.step == "case_code":
            return self.send(chat_id, t["case_ask"])
        if s.step == "clinic":
            return self.send(chat_id, t["ask_clinic"])
        return self.send(chat_id, t["start_first"])

    def on_voice(self, chat_id, s, audio):
        t = T[s.lang]
        if (audio.get("duration") or 0) > MAX_VOICE_SECONDS or (audio.get("file_size") or 0) > MAX_FILE_BYTES:
            return self.send(chat_id, t["too_long"])
        if self._limited(chat_id, "stt", 20):
            return self.send(chat_id, t["slow_down"])
        self.send(chat_id, t["transcribing"])
        try:
            data = self.api.download(audio["file_id"])
        except TelegramError:
            return self.send(chat_id, t["voice_fail"])
        ext = AUDIO_EXT.get((audio.get("mime_type") or "audio/ogg").split(";")[0], ".ogg")
        result = voice.transcribe(data, "voice" + ext, s.lang)  # audio is discarded inside
        del data
        if result.get("error") or not result.get("text"):
            return self.send(chat_id, t["voice_fail"])
        s.draft = result["text"][:3000]
        return self.ask_confirm(chat_id, s, demo=result.get("demo"))

    def _agree_line(self, t, s=None):
        line = t["rv_agree"]
        if config.PUBLIC_URL:
            line += f"\n{config.PUBLIC_URL}/privacy" + (f"?c={s.clinic_slug}" if s and s.clinic_slug else "")
        return line

    def ask_confirm(self, chat_id, s, demo=False):
        """Show EXACTLY what will be stored (masked text and every field) and ask for agreement, every time."""
        t = T[s.lang]
        s.step = "confirm"
        masked = ai.mask_text(s.draft)
        with db() as conn:
            w = reports.get_ward(conn, s.ward)
        now = analytics.local_now()
        when = f"{t['rv_date']}: {now.date().isoformat()}, {t['tb_' + analytics.time_bucket(now)]}"
        if s.source == "staff":
            when += f" ({t['rv_staffdate']})"
        fields = [f"{t['rv_clinic']}: {html.escape(s.clinic_name or '—', quote=False)}",
                  f"{t['rv_ward']}: {html.escape(reports.ward_name(w, s.lang) if w else '—', quote=False)}",
                  f"{t['rv_role']}: {t['role_' + (s.reporter or s.source)]}"]
        if s.source == "patient" and not s.urgent:
            fields.append(f"{t['rv_rating']}: {t[FACE_LABEL[s.rating]] if s.rating in FACE_LABEL else t['rv_none']}")
        if s.urgent:
            fields.append(t["rv_urgent"])
        fields += [when, f"{t['rv_lang']}: {LANG_NAMES[s.lang]}"]
        parts = [t["review_title"], f"<b>{t['rv_msg']}:</b>\n<i>{html.escape(masked, quote=False)}</i>"]
        flags = ai.privacy_flags(masked)
        if flags:  # privacy check: point out details that may still identify someone
            parts.append(t["rv_flags"] + "\n" + "\n".join("• " + html.escape(f, quote=False) for f in flags)
                         + "\n" + t["rv_flags_hint"])
        parts += ["\n".join(fields), f"{t['rv_not']}\n{t['rv_who']}",
                  t["confirm_hint"] + ("\n" + t["voice_demo"] if demo else ""), self._agree_line(t, s)]
        return self.send(chat_id, "\n\n".join(parts), _kb([[(t["btn_agree"], "send")], [(t["btn_cancel"], "cancel")]]))

    def ask_reply_confirm(self, chat_id, s):
        """Replies to the clinic get the same check-and-agree step."""
        t = T[s.lang]
        s.step = "reply_confirm"
        parts = [t["review_title"], f"<b>{t['rv_msg']}:</b>\n<i>{html.escape(ai.mask_text(s.draft), quote=False)}</i>",
                 f"{t['rv_not']}\n{t['rv_who']}", self._agree_line(t)]
        return self.send(chat_id, "\n\n".join(parts), _kb([[(t["btn_agree"], "reply_send")], [(t["btn_cancel"], "cancel")]]))

    # ---- buttons --------------------------------------------------------------------------
    def on_button(self, chat_id, data, user):
        s = self._session(chat_id)
        if data.startswith("lang:"):
            lang = data.split(":", 1)[1]
            lang = lang if lang in T else "uz"
            if s and s.step == "lang":
                s.lang = lang  # keep the clinic / department that came with the QR link
            else:
                s = self._new_session(chat_id, lang)
            return self.ask_role(chat_id, s) if s.clinic_id else self.ask_clinic(chat_id, s)
        if not s:
            return self.send(chat_id, T[_guess_lang(user)]["start_first"])
        t = T[s.lang]

        if data == "role:case":
            s.step = "case_code"
            return self.send(chat_id, t["case_ask"])
        if data in ("role:patient", "role:relative", "role:staff", "role:help") and s.step == "role" and s.clinic_id:
            if data == "role:staff":
                if s.mode == "patient":  # a patient QR code never opens the staff form
                    return None
                s.source = s.reporter = "staff"
                s.ward = ""
                return self.ask_ward(chat_id, s)
            s.source = "patient"
            s.reporter = "relative" if data == "role:relative" else "patient"
            if data == "role:help":
                s.urgent = True
                self.send(chat_id, t["help_now"])  # what to do right now comes first
                if s.ward:
                    s.step = "text"
                    return None
                return self.ask_ward(chat_id, s)
            return self.ask_detail(chat_id, s) if s.ward else self.ask_ward(chat_id, s)
        if data.startswith("ward:") and s.step == "ward":
            code = data.split(":", 1)[1]
            with db() as conn:
                if not reports.ward_exists(conn, code, s.clinic_id):  # only this clinic's departments
                    return self.send(chat_id, t["err"])
            s.ward = code
            if s.source == "staff":
                s.step = "text"
                return self.send(chat_id, t["ask_text_staff"])  # staff never choose a category or severity
            if s.urgent:
                s.step = "text"
                return self.send(chat_id, t["help_type"])
            return self.ask_detail(chat_id, s)
        if data.startswith("rate:") and s.step == "detail":
            s.rating = FACES.get(data.split(":", 1)[1])
            s.step = "text"
            return self.send(chat_id, t["ask_text"])
        if data == "send" and s.step == "confirm":
            return self.submit(chat_id, s)
        if data == "cancel":
            self._end(chat_id)
            return self.send(chat_id, t["cancelled"])
        if data == "reply" and s.step == "case_view":
            s.step = "case_reply"
            return self.send(chat_id, t["reply_ask"])
        if data == "reply_send" and s.step == "reply_confirm":
            if self._limited(chat_id, "case", 15):
                return self.send(chat_id, t["slow_down"])
            with db() as conn:
                ok = reports.add_reporter_reply(conn, s.case_code, s.draft)
            self._end(chat_id)
            return self.send(chat_id, t["c_sent"] if ok else t["c_notfound"])
        # stale or out-of-order button: ignore quietly

    # ---- flows ----------------------------------------------------------------------------
    def start(self, chat_id, user, text=""):
        """/start, or a deep link from a clinic's QR code:
        w_<ward code> = patient/relative form for that department, s_<clinic code> = staff form,
        c_<clinic code> = choose patient, relative or staff."""
        self._end(chat_id)
        s = self._new_session(chat_id, _guess_lang(user))
        payload = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        with db() as conn:
            if payload.startswith("w_"):
                w = reports.get_ward(conn, payload[2:])
                if w:
                    s.ward = w["code"]
                    c = clinics.get(conn, w["clinic_id"])
                else:
                    c = None
            elif payload.startswith(("c_", "s_")):
                c = clinics.by_slug(conn, payload[2:])
            else:
                c = None
        if c:
            s.clinic_id, s.clinic_name, s.clinic_slug = c["id"], c["name"], c["slug"]
            s.mode = "patient" if s.ward else ("staff" if payload.startswith("s_") else "")
        langs = [("O'zbekcha", "lang:uz"), ("Русский", "lang:ru"), ("English", "lang:en")]
        head = f"🏥 <b>{html.escape(c['name'], quote=False)}</b>\n\n" if c else ""
        return self.send(chat_id, head + "Tilni tanlang · Выберите язык · Choose a language", _kb([langs]))

    def _clinic(self, s) -> Optional[dict]:
        if not s or not s.clinic_id:
            return None
        with db() as conn:
            return clinics.get(conn, s.clinic_id)

    def ask_clinic(self, chat_id, s):
        s.step = "clinic"
        return self.send(chat_id, T[s.lang]["ask_clinic"])

    def ask_detail(self, chat_id, s):
        """Patients: three big buttons (good / OK / bad), or skip."""
        t = T[s.lang]
        s.step = "detail"
        faces = [(t["f_good"], "rate:good"), (t["f_ok"], "rate:ok"), (t["f_bad"], "rate:bad")]
        return self.send(chat_id, t["rate"], _kb([faces, [(t["btn_skip"], "rate:skip")]]))

    def ask_ward(self, chat_id, s):
        t = T[s.lang]
        s.step = "ward"
        with db() as conn:
            wards = reports.ward_list(conn, s.clinic_id)
        if not wards:
            return self.send(chat_id, t["err"])
        return self.send(chat_id, t["ward"],
                         _kb([[(reports.ward_name(w, s.lang), "ward:" + w["code"])] for w in wards]))

    def _web_link(self, s) -> str:
        """The same form on the web, without a Telegram account (maximum privacy)."""
        if not config.PUBLIC_URL or not s.clinic_slug:
            return ""
        if s.mode == "patient" and s.ward:
            return f"{config.PUBLIC_URL}/r/{s.ward}"
        if s.mode == "staff":
            return f"{config.PUBLIC_URL}/c/{s.clinic_slug}/staff"
        return f"{config.PUBLIC_URL}/c/{s.clinic_slug}"

    def ask_role(self, chat_id, s):
        """First screen: trust message, then who is speaking (3 taps to a report)."""
        t = T[s.lang]
        head = f"🏥 <b>{html.escape(s.clinic_name, quote=False)}</b>\n\n" if s.clinic_name else ""
        intro = [head + t["trust"], t["privacy_more"]]
        if self._web_link(s):
            intro.append(t["max_privacy"].format(url=self._web_link(s)))
        self.send(chat_id, "\n".join(intro) + "\n\n" + t["emergency"])
        if s.mode == "staff":  # staff-room QR: straight to the department
            s.source = s.reporter = "staff"
            return self.ask_ward(chat_id, s)
        s.step = "role"
        rows = [[(t["btn_patient"], "role:patient")], [(t["btn_relative"], "role:relative")]]
        if s.mode != "patient":
            rows.append([(t["btn_staff"], "role:staff")])
        rows += [[(t["btn_help"], "role:help")], [(t["btn_case"], "role:case")]]
        return self.send(chat_id, t["who"], _kb(rows))

    def submit(self, chat_id, s):
        t = T[s.lang]
        if self._limited(chat_id, "report", 6):
            return self.send(chat_id, t["slow_down"])
        try:
            with db() as conn:
                res = reports.save_report(conn, s.source, s.ward, s.draft, s.lang, s.rating,
                                          terms_version=terms.TERMS_VERSION, reporter=s.reporter or None,
                                          urgent=s.urgent)
        except Exception as e:
            print(f"report not saved: {type(e).__name__}", file=sys.stderr)
            return self.send(chat_id, t["err"])
        self._end(chat_id)
        self.send(chat_id, t["done"].format(code=res["case_code"]))
        if res["urgent"]:
            self.send(chat_id, t["done_urgent"])
        if res["serious"] and (s.source == "staff" or not res["urgent"]):
            self.send(chat_id, t["serious_note"])  # never replaces the official reporting channel
        if res["bribery"]:
            self.send(chat_id, t["bribe_note"])

    def show_case(self, chat_id, s, code):
        t = T[s.lang]
        if self._limited(chat_id, "case", 15):
            return self.send(chat_id, t["slow_down"])
        with db() as conn:
            msgs = reports.case_messages(conn, code)
        if msgs is None:
            return self.send(chat_id, t["c_notfound"])
        s.case_code, s.step = code, "case_view"
        if not msgs:
            return self.send(chat_id, t["c_none"])
        lines = [f"<b>{t['c_clinic'] if m['sender'] == 'clinic' else t['c_you']}</b> · {html.escape(m['created_day'], quote=False)}\n"
                 f"{html.escape(m['body'], quote=False)}" for m in msgs]
        return self.send(chat_id, "\n\n".join(lines), _kb([[(t["btn_reply"], "reply")]]))

    # ---- polling loop ---------------------------------------------------------------------
    def run_forever(self):
        offset, pool = None, ThreadPoolExecutor(max_workers=4)
        while True:
            try:
                params = {"timeout": 50, "allowed_updates": ["message", "callback_query"]}
                if offset is not None:
                    params["offset"] = offset
                updates = self.api.call("getUpdates", _http_timeout=70, **params)
            except TelegramError as e:
                print(f"polling error: {e}", file=sys.stderr)
                time.sleep(3)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                pool.submit(self._safe_handle, u)

    def _safe_handle(self, update):
        try:
            self.handle_update(update)
        except Exception as e:  # never print message contents
            print(f"update failed: {type(e).__name__}", file=sys.stderr)


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env (create a bot with @BotFather in Telegram).")
    init_db()
    api = TelegramApi(config.TELEGRAM_BOT_TOKEN)
    try:
        me = api.call("getMe")
    except TelegramError as e:
        sys.exit(f"Telegram rejected the token ({e}). Check TELEGRAM_BOT_TOKEN in .env.")
    api.call("deleteWebhook")
    for lang, desc in (("", ("Start a new anonymous report", "Check a report by its code", "Terms of use and privacy")),
                       ("ru", ("Новое анонимное обращение", "Проверить обращение по коду",
                               "Условия использования и конфиденциальность")),
                       ("uz", ("Yangi anonim murojaat", "Murojaatni kod bo'yicha tekshirish",
                               "Foydalanish shartlari va maxfiylik"))):
        params = {"commands": [{"command": "start", "description": desc[0]}, {"command": "case", "description": desc[1]},
                               {"command": "privacy", "description": desc[2]}]}
        if lang:
            params["language_code"] = lang
        try:
            api.call("setMyCommands", **params)
        except TelegramError:
            pass
    print(f"Bot @{me.get('username')} is running. Speech: {voice.provider() or 'demo transcripts'}. Ctrl+C to stop.")
    try:
        Bot(api).run_forever()
    except KeyboardInterrupt:
        print("Bot stopped.")


if __name__ == "__main__":
    main()
