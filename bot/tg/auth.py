from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType


def is_admin(update: Update, admin_ids: frozenset[int]) -> bool:
    user = update.effective_user
    return user is not None and user.id in admin_ids


def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE
