from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import Settings
from bot.db import Database
from bot.feed import FutaminaClient
from bot.rules.over_goals import OverGoalsAlertRule, OverGoalsRuleConfig
from bot.services.alerts import AlertCollectionService
from bot.services.broadcast import BroadcastService
from bot.services.polling import FeedPollingService
from bot.services.settlement import SignalSettlementService
from bot.tg.handlers import AdminCommandHandlers, GroupMembershipHandler
from bot.tg.sender import TelegramMessageSender


def build_rule_config(settings: Settings) -> OverGoalsRuleConfig:
    return OverGoalsRuleConfig(
        min_rate=settings.rule_min_rate,
        skip_limbo=settings.rule_skip_limbo,
        next_games=settings.rule_next_games,
        min_samples=settings.rule_min_samples,
    )


def build_application(settings: Settings) -> Application:
    db = Database(settings.sqlite_path)
    feed = FutaminaClient(settings.futamina_base_url, settings.futamina_api_key)
    rule = OverGoalsAlertRule(build_rule_config(settings))

    collector = AlertCollectionService(feed, rule, db)
    app = Application.builder().token(settings.telegram_bot_token).build()
    sender = TelegramMessageSender(app.bot)
    broadcaster = BroadcastService(
        db,
        db,
        sender,
        signup_url=settings.signup_url,
        entry_cooldown_minutes=settings.entry_cooldown_minutes,
    )
    settlement = SignalSettlementService(
        db,
        feed,
        sender,
        signup_url=settings.signup_url,
    )
    polling = FeedPollingService(collector, broadcaster, settlement)

    app.bot_data["settings"] = settings
    app.bot_data["polling"] = polling

    admin = AdminCommandHandlers(db, settings.admin_telegram_ids)
    membership = GroupMembershipHandler(db)

    app.add_handler(CommandHandler("grupos", admin.grupos))
    app.add_handler(CommandHandler("pausar", admin.pausar))
    app.add_handler(CommandHandler("retomar", admin.retomar))
    app.add_handler(
        ChatMemberHandler(membership.on_my_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER)
    )
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
            membership.on_membership_service,
        )
    )

    async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await context.application.bot_data["polling"].run_once()

    app.job_queue.run_repeating(
        poll_job,
        interval=settings.poll_interval_seconds,
        first=5,
        name="feed_poll",
        job_kwargs={
            "misfire_grace_time": settings.poll_interval_seconds,
        },
    )

    return app
