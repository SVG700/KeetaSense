"""Telegram alerts in English and Kannada.

When a trap's recommendation changes (e.g. WAIT -> SPRAY), we build one
message per language from backend/alert_templates.yaml and send it with
python-telegram-bot. If no bot token is configured, the message is written
to the log and saved in the AlertLog table with status "logged" - the demo
never fails because Telegram is missing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import threading
from functools import lru_cache
from pathlib import Path

import yaml
from sqlmodel import Session, select

from backend import bot_store, image_quality, settings
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
        quality_text=image_quality.reasons_text((decision.get("quality") or {}).get("reasons", []), lang,
                                                only_bad=True),
    ).strip() + borderline_line(lang, trap, decision) + \
        ("\n" + line if (line := support_line(templates().get(lang) or templates()["en"], decision, lang)) else "")


def support_line(t: dict, decision: dict, lang: str) -> str | None:
    """F5: cost of spraying / release dose, localised (None if nothing to add)."""
    s = decision.get("support")
    if not s or decision.get("action") == "CHECK_TRAP":
        return None
    if s.get("predators_at_risk"):
        return t["support_harm"].format(n=s["predators_at_risk"])
    if s.get("release_count"):
        from datetime import date as _date
        return t["support_release"].format(
            n=s["release_count"], area=f"{s['area_m2']:g}",
            predator=settings.pest_display_name(s["release_class"], lang),
            date=_date.fromisoformat(s["recheck_date"]).strftime("%d-%m-%Y"))
    return None


def borderline_line(lang: str, trap: Trap, decision: dict) -> str:
    """F2: extra line when the advice could change inside the detector's count range."""
    if not decision.get("borderline") or decision.get("action") == "CHECK_TRAP":
        return ""
    u = decision["uncertainty"]
    t = templates().get(lang) or templates()["en"]
    return "\n" + t["borderline"].format(low=f"{u['pests_low']:.0f}", high=f"{u['pests_high']:.0f}",
                                         pest_name=settings.pest_display_name(trap.target_pest, lang))


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


ACK_ACTIONS = ("sprayed", "released", "not_yet")
ACTIONABLE = ("SPRAY", "RELEASE_BIOCONTROL")   # alerts that get Sprayed / Released / Not yet buttons


def ack_buttons(alert_id: int, trap_id: str, lang: str) -> list[tuple[str, str]]:
    """(label, callback data) for the alert's buttons. Data: ack|<alert id>|<trap id>|<action> (< 64 bytes)."""
    t = templates().get(lang) or templates()["en"]
    return [(t[f"button_{a}"], f"ack|{alert_id}|{trap_id}|{a}") for a in ACK_ACTIONS]


async def _send_telegram(text: str, chat_ids: list[str], buttons: list[tuple[str, str]] | None = None) -> None:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup  # lazy import
    from telegram.request import HTTPXRequest
    # short timeouts: with Wi-Fi off the attempt fails fast instead of hanging
    request = HTTPXRequest(connect_timeout=5, read_timeout=10, write_timeout=10, pool_timeout=5)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]]) \
        if buttons else None
    async with Bot(settings.telegram_token(), request=request) as bot:
        for chat_id in chat_ids:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


def _send_in_background(alert_id: int, text: str, chat_ids: list[str],
                        buttons: list[tuple[str, str]] | None = None) -> None:
    """Send on a separate thread so a slow network never blocks the API."""
    def worker():
        status, error = "sent", None
        try:
            asyncio.run(_send_telegram(text, chat_ids, buttons))
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
               lang: str, text: str, buttons: bool = False, suppressed_until: datetime | None = None) -> AlertLog:
    """Store one alert and send it to Telegram (or only log it if nobody can receive it).

    buttons: add Sprayed / Released / Not yet buttons (F4).
    suppressed_until: inside a post-action cooldown - store the alert as "suppressed", do not send it."""
    chats = recipients(trap_id, lang)
    status = "suppressed" if suppressed_until else ("pending" if chats else "logged")
    row = AlertLog(trap_id=trap_id, action=action, previous_action=previous_action, language=lang, message=text,
                   status=status, error=f"cooldown until {suppressed_until:%Y-%m-%d %H:%M}" if suppressed_until else None)
    session.add(row)
    session.commit()
    session.refresh(row)
    if suppressed_until:
        log.info("[ALERT suppressed - action cooldown until %s] (%s) %s", suppressed_until, lang, trap_id)
    elif chats:
        _send_in_background(row.id, text, chats, ack_buttons(row.id, trap_id, lang) if buttons else None)
    else:
        log.warning("[ALERT - Telegram not configured, logged only] (%s)\n%s", lang, text)
    return row


def notify_decision_change(session: Session, trap: Trap, decision: dict, previous_action: str | None,
                           cooldown_until: datetime | None = None) -> list[AlertLog]:
    """Create (and send, if configured) one alert per language.

    SPRAY / BIOCONTROL alerts get action buttons and are held back during a post-action cooldown;
    CHECK TRAP and WAIT alerts are always sent."""
    actionable = decision["action"] in ACTIONABLE
    rows = []
    for lang in languages_for(trap.id):
        if lang not in templates():
            continue
        rows.append(send_alert(session, trap.id, decision["action"], previous_action, lang,
                               render_message(lang, trap, decision), buttons=actionable,
                               suppressed_until=cooldown_until if actionable else None))
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
