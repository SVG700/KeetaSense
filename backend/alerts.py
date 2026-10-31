"""Telegram alerts in English and Kannada.

When a trap's recommendation changes (e.g. WAIT -> SPRAY), we build one
message per language from backend/alert_templates.yaml and send it with
python-telegram-bot. If no bot token is configured, the message is written
to the log and saved in the AlertLog table with status "logged" - the demo
never fails because Telegram is missing.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache
from pathlib import Path

import yaml
from sqlmodel import Session, select

from backend import bot_store, settings
from backend.db import get_engine
from backend.models import AlertLog, Trap

log = logging.getLogger("keetasense.alerts")

TEMPLATES_FILE = Path(__file__).resolve().parent / "alert_templates.yaml"


@lru_cache(maxsize=1)
def templates() -> dict:
    with open(TEMPLATES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fmt(x) -> str:
    if x is None:
        return "-"
    return f"{x:.1f}".rstrip("0").rstrip(".")


def render_message(lang: str, trap: Trap, decision: dict) -> str:
    """Fill in the template for one language."""
    t = templates()[lang]
    days = decision["degree_days"]["days_to_next_generation"]
    days_text = t["days_known"].format(days=days) if days is not None else t["days_unknown"]
    return t[decision["action"]].format(
        trap_name=trap.name,
        pest_name=settings.pest_display_name(trap.target_pest, lang),
        pests_per_day=_fmt(decision["pests_per_day"]),
        predators_per_day=_fmt(decision["predators_per_day"]),
        ratio=_fmt(decision["ratio"]),
        days_text=days_text,
        reason=decision["reason"],
    ).strip()


def telegram_configured() -> bool:
    """A bot token AND a main alert chat (TELEGRAM_CHAT_ID) are set."""
    return bool(settings.telegram_token() and settings.telegram_chat_id())


def recipients(trap_id: str, lang: str) -> list[str]:
    """Telegram chats that should get this trap's alert in this language:
    the main alert chat (for ALERT_LANGUAGES) + bot users following this trap in this language."""
    if not settings.telegram_token():
        return []
    chats = []
    if settings.telegram_chat_id() and lang in settings.alert_languages():
        chats.append(settings.telegram_chat_id())
    chats += [cid for cid, user_lang in bot_store.subscribers(trap_id) if user_lang == lang and cid not in chats]
    return chats


def languages_for(trap_id: str) -> list[str]:
    """ALERT_LANGUAGES plus every language a subscriber of this trap uses."""
    langs = list(settings.alert_languages())
    for _, lang in bot_store.subscribers(trap_id):
        if lang not in langs:
            langs.append(lang)
    return langs


async def _send_telegram(text: str, chat_ids: list[str]) -> None:
    from telegram import Bot  # lazy import
    from telegram.request import HTTPXRequest
    # short timeouts: with Wi-Fi off the attempt fails fast instead of hanging
    request = HTTPXRequest(connect_timeout=5, read_timeout=10, write_timeout=10, pool_timeout=5)
    async with Bot(settings.telegram_token(), request=request) as bot:
        for chat_id in chat_ids:
            await bot.send_message(chat_id=chat_id, text=text)


def _send_in_background(alert_id: int, text: str, chat_ids: list[str]) -> None:
    """Send on a separate thread so a slow network never blocks the API."""
    def worker():
        status, error = "sent", None
        try:
            asyncio.run(_send_telegram(text, chat_ids))
            log.info("Telegram alert %s sent to %d chat(s)", alert_id, len(chat_ids))
        except Exception as e:  # network down, wrong token, ...
            status, error = "failed", str(e)[:500]
            log.error("Telegram alert %s failed: %s", alert_id, e)
        with Session(get_engine()) as s:
            row = s.get(AlertLog, alert_id)
            if row:
                row.status, row.error = status, error
                s.add(row)
                s.commit()
    threading.Thread(target=worker, daemon=True).start()


def send_alert(session: Session, trap_id: str, action: str, previous_action: str | None,
               lang: str, text: str) -> AlertLog:
    """Store one alert and send it to Telegram (or only log it if nobody can receive it)."""
    chats = recipients(trap_id, lang)
    row = AlertLog(trap_id=trap_id, action=action, previous_action=previous_action, language=lang, message=text,
                   status="pending" if chats else "logged")
    session.add(row)
    session.commit()
    session.refresh(row)
    if chats:
        _send_in_background(row.id, text, chats)
    else:
        log.warning("[ALERT - Telegram not configured, logged only] (%s)\n%s", lang, text)
    return row


def notify_decision_change(session: Session, trap: Trap, decision: dict,
                           previous_action: str | None) -> list[AlertLog]:
    """Create (and send, if configured) one alert per language."""
    rows = []
    for lang in languages_for(trap.id):
        if lang not in templates():
            continue
        rows.append(send_alert(session, trap.id, decision["action"], previous_action, lang,
                               render_message(lang, trap, decision)))
    return rows


def notify_early_warning(session: Session, trap: Trap, warning: dict, texts: dict[str, str]) -> list[AlertLog]:
    """Early warning: a neighbouring farm crossed its threshold. Sent ONCE per (trap, neighbour).

    For these alerts, previous_action holds the neighbour's trap id (used to avoid repeats)."""
    already = session.exec(select(AlertLog).where(AlertLog.trap_id == trap.id, AlertLog.action == "EARLY_WARNING",
                                                  AlertLog.previous_action == warning["neighbour_id"])).first()
    if already:
        return []
    return [send_alert(session, trap.id, "EARLY_WARNING", warning["neighbour_id"], lang, text)
            for lang, text in texts.items() if lang in languages_for(trap.id)]
