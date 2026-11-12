from __future__ import annotations

import logging

from telegram import Chat, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from bot.ports import GroupRepository
from bot.tg.auth import is_admin, is_private_chat

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = frozenset(
    {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }
)
_INACTIVE_STATUSES = frozenset(
    {
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED,
    }
)


def membership_is_active(status: str, *, is_member: bool | None = None) -> bool | None:
    """True se o bot está no grupo, False se saiu, None se o status for desconhecido.

    Em supergrupo o bot pode entrar como ``restricted`` com ``is_member=True``
    em vez de ``member``. Esse caso também conta como ativo.
    """
    normalized = str(status)
    if normalized in _ACTIVE_STATUSES:
        return True
    if normalized == ChatMemberStatus.RESTRICTED:
        return bool(is_member)
    if normalized in _INACTIVE_STATUSES:
        return False
    return None


def _is_target_chat(chat: Chat) -> bool:
    """Grupo, supergrupo ou canal. Canal chega com type=channel, não supergroup."""
    return str(chat.type) in {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL}


class AdminCommandHandlers:
    def __init__(self, groups: GroupRepository, admin_ids: frozenset[int]) -> None:
        self._groups = groups
        self._admin_ids = admin_ids

    async def grupos(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allow(update):
            return
        rows = self._groups.list_groups()
        if not rows:
            await update.message.reply_text("Nenhum grupo cadastrado.")
            return
        lines = []
        for row in rows:
            status = "ativo" if row["active"] else "pausado"
            title = row["title"] or "(sem nome)"
            lines.append(f"{row['chat_id']} — {title} [{status}]")
        await update.message.reply_text("Grupos:\n" + "\n".join(lines))

    async def pausar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allow(update, deny_message=True):
            return
        if not context.args:
            await update.message.reply_text("Uso: /pausar <chat_id>")
            return
        chat_id = await self._parse_chat_id(update, context)
        if chat_id is None:
            return
        if self._groups.set_group_active(chat_id, False):
            await update.message.reply_text(f"Grupo {chat_id} pausado.")
        else:
            await update.message.reply_text(f"Grupo {chat_id} nao encontrado.")

    async def retomar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._allow(update, deny_message=True):
            return
        if not context.args:
            await update.message.reply_text("Uso: /retomar <chat_id>")
            return
        chat_id = await self._parse_chat_id(update, context)
        if chat_id is None:
            return
        if self._groups.set_group_active(chat_id, True):
            await update.message.reply_text(f"Grupo {chat_id} retomado.")
        else:
            await update.message.reply_text(f"Grupo {chat_id} nao encontrado.")

    async def _allow(self, update: Update, *, deny_message: bool = False) -> bool:
        if not is_private_chat(update):
            return False
        if is_admin(update, self._admin_ids):
            return True
        if deny_message and update.message:
            await update.message.reply_text("Acesso negado.")
        return False

    @staticmethod
    async def _parse_chat_id(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        try:
            return int(context.args[0])
        except (ValueError, IndexError, TypeError):
            await update.message.reply_text("chat_id invalido.")
            return None


class GroupMembershipHandler:
    def __init__(self, groups: GroupRepository) -> None:
        self._groups = groups

    async def on_my_chat_member(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        member_update = update.my_chat_member or update.chat_member
        if member_update is None:
            return
        if member_update.new_chat_member.user.id != context.bot.id:
            return

        chat = member_update.chat
        new_member = member_update.new_chat_member
        old_status = member_update.old_chat_member.status
        new_status = new_member.status
        is_member = getattr(new_member, "is_member", None)
        if not _is_target_chat(chat):
            logger.info(
                "Chat %s (%s) ignorado: %s -> %s",
                chat.id,
                chat.type,
                old_status,
                new_status,
            )
            return

        active = membership_is_active(new_status, is_member=is_member)
        if active is None:
            logger.warning(
                "Status de membro ignorado no chat %s: %s -> %s",
                chat.id,
                old_status,
                new_status,
            )
            return
        self._remember(chat, active)

    async def on_membership_service(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Fallback: alguns grupos só entregam a entrada como mensagem de serviço."""
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not _is_target_chat(chat):
            return

        bot_id = context.bot.id
        joined = message.new_chat_members and any(
            user.id == bot_id for user in message.new_chat_members
        )
        left = message.left_chat_member is not None and message.left_chat_member.id == bot_id
        if joined:
            self._remember(chat, True)
        elif left:
            self._remember(chat, False)

    def _remember(self, chat: Chat, active: bool) -> None:
        self._groups.upsert_group(chat.id, chat.title, active=active)
        logger.info(
            "Chat %s (%s) %s: %s",
            chat.id,
            chat.type,
            chat.title,
            "ativo" if active else "inativo",
        )
