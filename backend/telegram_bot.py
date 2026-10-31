"""KeetaSense Telegram bot - for farmers who will never open a dashboard.

    python -m backend.telegram_bot          (the launcher starts it automatically
                                             when TELEGRAM_BOT_TOKEN is set in .env)

What a farmer can do (in English, Kannada, Hindi or Tamil):
  /start   choose language and trap (buttons)
  /status  today's advisory for my trap: action, counts, forecast, warnings
  /spray   or just type "Can I spray today?" / "ಇಂದು ಸಿಂಪಡಿಸಬಹುದೇ?" /
           "क्या आज छिड़काव करूँ?" / "இன்று தெளிக்கலாமா?"
           -> answered from the LIVE trap data, decision and weather forecast
  /lang    change language          /trap    change trap
They also receive alerts for their trap (decision changes, early warnings).

The bot only talks to the KeetaSense backend over HTTP (KEETA_API_URL, default
http://127.0.0.1:8000), so it can run on the same laptop or anywhere else.
It needs internet to reach Telegram; the rest of the demo never depends on it.
"""
from __future__ import annotations

import logging
import os

import requests

from backend import bot_store, settings

log = logging.getLogger("keetasense.bot")

API = os.environ.get("KEETA_API_URL", "http://127.0.0.1:8000").rstrip("/")
LANG_BUTTONS = {"en": "English", "kn": "ಕನ್ನಡ", "hi": "हिन्दी", "ta": "தமிழ்"}

# Words that mean "spray" in each language (lower-case; Indian scripts match as substrings)
SPRAY_WORDS = ["spray", "pesticide", "ಸಿಂಪಡ", "ಸ್ಪ್ರೇ", "छिड़काव", "छिडकाव", "स्प्रे", "தெளி", "ஸ்ப்ரே"]
STATUS_WORDS = ["status", "today", "report", "ಸ್ಥಿತಿ", "ವರದಿ", "स्थिति", "रिपोर्ट", "நிலை", "அறிக்கை"]

MESSAGES = {
    "en": {"welcome": "Welcome to KeetaSense! Choose your language:", "choose_trap": "Which trap is yours?",
           "saved": "Saved. Ask me \"Can I spray today?\" any time, or send /status.",
           "no_trap": "First choose your trap: /trap",
           "help": "Ask \"Can I spray today?\", or send /status for today's advice. /lang changes the language, /trap the trap.",
           "offline": "The KeetaSense server cannot be reached right now. Please try again later."},
    "kn": {"welcome": "ಕೀಟಸೆನ್ಸ್‌ಗೆ ಸ್ವಾಗತ! ನಿಮ್ಮ ಭಾಷೆ ಆರಿಸಿ:", "choose_trap": "ನಿಮ್ಮ ಬಲೆ ಯಾವುದು?",
           "saved": "ಉಳಿಸಲಾಗಿದೆ. \"ಇಂದು ಸಿಂಪಡಿಸಬಹುದೇ?\" ಎಂದು ಯಾವಾಗ ಬೇಕಾದರೂ ಕೇಳಿ, ಅಥವಾ /status ಕಳುಹಿಸಿ.",
           "no_trap": "ಮೊದಲು ನಿಮ್ಮ ಬಲೆಯನ್ನು ಆರಿಸಿ: /trap",
           "help": "\"ಇಂದು ಸಿಂಪಡಿಸಬಹುದೇ?\" ಎಂದು ಕೇಳಿ, ಅಥವಾ ಇಂದಿನ ಸಲಹೆಗೆ /status ಕಳುಹಿಸಿ. /lang ಭಾಷೆ ಬದಲಿಸಲು, /trap ಬಲೆ ಬದಲಿಸಲು.",
           "offline": "ಕೀಟಸೆನ್ಸ್ ಸರ್ವರ್ ಈಗ ಲಭ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ."},
    "hi": {"welcome": "कीटसेंस में आपका स्वागत है! अपनी भाषा चुनें:", "choose_trap": "आपका ट्रैप कौन सा है?",
           "saved": "सहेज लिया गया। कभी भी पूछें \"क्या आज छिड़काव करूँ?\", या /status भेजें।",
           "no_trap": "पहले अपना ट्रैप चुनें: /trap",
           "help": "पूछें \"क्या आज छिड़काव करूँ?\", या आज की सलाह के लिए /status भेजें। /lang से भाषा, /trap से ट्रैप बदलें।",
           "offline": "कीटसेंस सर्वर अभी उपलब्ध नहीं है। कृपया बाद में कोशिश करें।"},
    "ta": {"welcome": "கீடசென்ஸுக்கு வரவேற்கிறோம்! உங்கள் மொழியைத் தேர்ந்தெடுக்கவும்:", "choose_trap": "உங்கள் பொறி எது?",
           "saved": "சேமிக்கப்பட்டது. \"இன்று தெளிக்கலாமா?\" என்று எப்போது வேண்டுமானாலும் கேளுங்கள், அல்லது /status அனுப்புங்கள்.",
           "no_trap": "முதலில் உங்கள் பொறியைத் தேர்ந்தெடுக்கவும்: /trap",
           "help": "\"இன்று தெளிக்கலாமா?\" என்று கேளுங்கள், அல்லது இன்றைய ஆலோசனைக்கு /status அனுப்புங்கள். /lang மொழியை மாற்ற, /trap பொறியை மாற்ற.",
           "offline": "கீடசென்ஸ் சர்வரை இப்போது அணுக முடியவில்லை. பின்னர் முயற்சிக்கவும்."},
}
# (Kannada / Hindi / Tamil bot messages are machine-drafted - have a native speaker check them.)


# ---------------------------------------------------------------------------
# Pure message logic (tested without Telegram)
# ---------------------------------------------------------------------------
def intent(text: str) -> str:
    t = (text or "").strip().lower()
    if t.startswith("/spray") or any(w in t for w in SPRAY_WORDS):
        return "spray"
    if t.startswith("/status") or any(w in t for w in STATUS_WORDS):
        return "status"
    return "help"


def fetch_advisory(trap_id: str, lang: str, timeout: float = 10) -> dict | None:
    try:
        r = requests.get(f"{API}/api/advisory/{trap_id}", params={"lang": lang}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.warning("Backend not reachable for the bot: %s", e)
        return None


def reply_to(text: str, user: dict, fetch=fetch_advisory) -> str:
    lang = user.get("lang", "en")
    msg = MESSAGES.get(lang, MESSAGES["en"])
    kind = intent(text)
    if kind == "help":
        return msg["help"]
    if not user.get("trap_id"):
        return msg["no_trap"]
    adv = fetch(user["trap_id"], lang)
    if adv is None:
        return msg["offline"]
    return adv["spray_answer"] if kind == "spray" else adv["rendered"]["text"]


# ---------------------------------------------------------------------------
# Telegram plumbing
# ---------------------------------------------------------------------------
def main() -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                              filters)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = settings.telegram_token()
    if not token:
        raise SystemExit("[bot] TELEGRAM_BOT_TOKEN is not set in .env - create a bot with @BotFather first.")

    def lang_keyboard():
        return InlineKeyboardMarkup([[InlineKeyboardButton(v, callback_data=f"lang:{k}")
                                      for k, v in LANG_BUTTONS.items()]])

    def trap_keyboard():
        return InlineKeyboardMarkup([[InlineKeyboardButton(t["name"], callback_data=f"trap:{t['id']}")]
                                     for t in settings.traps_config()])

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(MESSAGES["en"]["welcome"] + "\n" + " / ".join(
            m["welcome"] for k, m in MESSAGES.items() if k != "en"), reply_markup=lang_keyboard())

    async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = bot_store.get(update.effective_chat.id)
        await update.message.reply_text(MESSAGES[user["lang"]]["welcome"], reply_markup=lang_keyboard())

    async def trap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = bot_store.get(update.effective_chat.id)
        await update.message.reply_text(MESSAGES[user["lang"]]["choose_trap"], reply_markup=trap_keyboard())

    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        kind, value = q.data.split(":", 1)
        chat = q.message.chat.id
        if kind == "lang":
            user = bot_store.update(chat, lang=value)
            if not user.get("trap_id"):
                await q.message.reply_text(MESSAGES[value]["choose_trap"], reply_markup=trap_keyboard())
                return
        else:
            user = bot_store.update(chat, trap_id=value)
        await q.message.reply_text(MESSAGES[user["lang"]]["saved"])

    async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = bot_store.get(update.effective_chat.id)
        await update.message.reply_text(reply_to(update.message.text, user))

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("trap", trap_cmd))
    app.add_handler(CommandHandler(["status", "spray", "help"], text))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    log.info("KeetaSense bot running (backend %s). Press Ctrl+C to stop.", API)
    app.run_polling()


if __name__ == "__main__":
    main()
