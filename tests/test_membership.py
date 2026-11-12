from __future__ import annotations

import unittest
from types import SimpleNamespace

from telegram.constants import ChatMemberStatus

from bot.tg.handlers import GroupMembershipHandler, membership_is_active


class MembershipStatusTests(unittest.TestCase):
    def test_member_and_admin_are_active(self) -> None:
        self.assertTrue(membership_is_active(ChatMemberStatus.MEMBER))
        self.assertTrue(membership_is_active(ChatMemberStatus.ADMINISTRATOR))
        self.assertTrue(membership_is_active(ChatMemberStatus.OWNER))

    def test_restricted_member_is_active(self) -> None:
        self.assertTrue(
            membership_is_active(ChatMemberStatus.RESTRICTED, is_member=True)
        )

    def test_restricted_non_member_is_inactive(self) -> None:
        self.assertFalse(
            membership_is_active(ChatMemberStatus.RESTRICTED, is_member=False)
        )

    def test_left_and_banned_are_inactive(self) -> None:
        self.assertFalse(membership_is_active(ChatMemberStatus.LEFT))
        self.assertFalse(membership_is_active("kicked"))

    def test_unknown_status_is_ignored(self) -> None:
        self.assertIsNone(membership_is_active("mystery"))


class _Groups:
    def __init__(self) -> None:
        self.rows: list[tuple[int, str | None, bool]] = []

    def upsert_group(self, chat_id: int, title: str | None, *, active: bool = True) -> None:
        self.rows.append((chat_id, title, active))


def _context(bot_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(bot=SimpleNamespace(id=bot_id))


def _member_update(status: str, *, is_member: bool | None = None, user_id: int = 7) -> SimpleNamespace:
    member = SimpleNamespace(status=status, user=SimpleNamespace(id=user_id))
    if is_member is not None:
        member.is_member = is_member
    chat = SimpleNamespace(id=-100123, type="supergroup", title="Alertas")
    return SimpleNamespace(
        chat=chat,
        old_chat_member=SimpleNamespace(status="left", user=SimpleNamespace(id=user_id)),
        new_chat_member=member,
    )


class GroupMembershipHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_restricted_join_registers_group_as_active(self) -> None:
        groups = _Groups()
        handler = GroupMembershipHandler(groups)  # type: ignore[arg-type]
        update = SimpleNamespace(
            my_chat_member=_member_update(ChatMemberStatus.RESTRICTED, is_member=True),
            chat_member=None,
        )

        await handler.on_my_chat_member(update, _context())  # type: ignore[arg-type]

        self.assertEqual(groups.rows, [(-100123, "Alertas", True)])

    async def test_channel_admin_is_registered_as_active(self) -> None:
        groups = _Groups()
        handler = GroupMembershipHandler(groups)  # type: ignore[arg-type]
        member_update = _member_update(ChatMemberStatus.ADMINISTRATOR)
        member_update.chat.type = "channel"
        update = SimpleNamespace(my_chat_member=member_update, chat_member=None)

        await handler.on_my_chat_member(update, _context())  # type: ignore[arg-type]

        self.assertEqual(groups.rows, [(-100123, "Alertas", True)])

    async def test_leave_deactivates_group(self) -> None:
        groups = _Groups()
        handler = GroupMembershipHandler(groups)  # type: ignore[arg-type]
        update = SimpleNamespace(
            my_chat_member=_member_update(ChatMemberStatus.LEFT),
            chat_member=None,
        )

        await handler.on_my_chat_member(update, _context())  # type: ignore[arg-type]

        self.assertEqual(groups.rows, [(-100123, "Alertas", False)])

    async def test_service_message_join_registers_group(self) -> None:
        groups = _Groups()
        handler = GroupMembershipHandler(groups)  # type: ignore[arg-type]
        chat = SimpleNamespace(id=-55, type="group", title="Sala")
        message = SimpleNamespace(
            new_chat_members=[SimpleNamespace(id=7)],
            left_chat_member=None,
        )
        update = SimpleNamespace(effective_message=message, effective_chat=chat)

        await handler.on_membership_service(update, _context())  # type: ignore[arg-type]

        self.assertEqual(groups.rows, [(-55, "Sala", True)])

    async def test_other_member_changes_are_ignored(self) -> None:
        groups = _Groups()
        handler = GroupMembershipHandler(groups)  # type: ignore[arg-type]
        update = SimpleNamespace(
            my_chat_member=None,
            chat_member=_member_update(ChatMemberStatus.MEMBER, user_id=99),
        )

        await handler.on_my_chat_member(update, _context())  # type: ignore[arg-type]

        self.assertEqual(groups.rows, [])
