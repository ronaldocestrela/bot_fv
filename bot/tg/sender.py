from __future__ import annotations

from telegram import Bot

from bot.ports import MessageSender


class TelegramMessageSender(MessageSender):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> int:
        kwargs: dict[str, object] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        message = await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return int(message.message_id)

    async def edit_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        await self._bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            **kwargs,
        )
