"""Telegram bot message logic and per-subscriber alert routing (no internet needed)."""
import pytest

from backend import alerts, bot_store, telegram_bot


@pytest.mark.parametrize("text", ["Can I spray today?", "spray", "/spray", "ಇಂದು ಸಿಂಪಡಿಸಬಹುದೇ?",
                                  "क्या आज छिड़काव करूँ?", "इन्दु स्प्रे?", "இன்று தெளிக்கலாமா?"])
def test_spray_questions_in_four_languages(text):
    assert telegram_bot.intent(text) == "spray"


def test_status_and_help_intents():
    assert telegram_bot.intent("/status") == "status"
    assert telegram_bot.intent("ಸ್ಥಿತಿ") == "status"
    assert telegram_bot.intent("hello") == "help"


def fake_fetch(trap_id, lang):
    return {"spray_answer": f"SPRAY-ANSWER {trap_id} {lang}", "rendered": {"text": f"STATUS {trap_id} {lang}"}}


def test_reply_uses_the_live_advisory_in_the_users_language():
    user = {"lang": "ta", "trap_id": "T3-hesaraghatta"}
    assert telegram_bot.reply_to("இன்று தெளிக்கலாமா?", user, fake_fetch) == "SPRAY-ANSWER T3-hesaraghatta ta"
    assert telegram_bot.reply_to("/status", user, fake_fetch) == "STATUS T3-hesaraghatta ta"


def test_reply_without_trap_offline_and_help():
    assert "/trap" in telegram_bot.reply_to("spray", {"lang": "hi", "trap_id": None}, fake_fetch)
    assert telegram_bot.reply_to("spray", {"lang": "en", "trap_id": "T1"}, lambda t, l: None) == \
        telegram_bot.MESSAGES["en"]["offline"]
    assert telegram_bot.reply_to("hi", {"lang": "kn", "trap_id": "T1"}, fake_fetch) == telegram_bot.MESSAGES["kn"]["help"]


def test_every_bot_language_has_every_message():
    for lang, msgs in telegram_bot.MESSAGES.items():
        assert set(msgs) == set(telegram_bot.MESSAGES["en"]), lang


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("KEETA_DB_PATH", str(tmp_path / "x.db"))
    return tmp_path


def test_bot_store_and_alert_routing(store, monkeypatch):
    bot_store.update(111, lang="hi", trap_id="T3-hesaraghatta")
    bot_store.update(222, lang="ta", trap_id="T3-hesaraghatta")
    bot_store.update(333, lang="hi", trap_id="T1-polyhouse")
    assert bot_store.get(111) == {"lang": "hi", "trap_id": "T3-hesaraghatta"}

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    assert alerts.recipients("T3-hesaraghatta", "hi") == []          # no token: nobody

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("ALERT_LANGUAGES", "en,kn")
    assert alerts.recipients("T3-hesaraghatta", "hi") == ["111"]
    assert alerts.recipients("T3-hesaraghatta", "en") == ["999"]
    assert alerts.languages_for("T3-hesaraghatta") == ["en", "kn", "hi", "ta"]
    assert alerts.languages_for("T5-chikkajala") == ["en", "kn"]
