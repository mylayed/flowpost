from __future__ import annotations

from aiogram.types import (
    ChatAdministratorRights,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)

from flowpost.i18n import t

REQUEST_CHANNEL = 1
REQUEST_GROUP = 2


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn.create_post")), KeyboardButton(text=t("btn.content_plan"))],
            [KeyboardButton(text=t("btn.ad_post")), KeyboardButton(text=t("btn.edit_post"))],
            [KeyboardButton(text=t("btn.projects")), KeyboardButton(text=t("btn.settings"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t("menu.placeholder"),
    )


def _rights(*, channel: bool) -> ChatAdministratorRights:
    return ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=False,
        can_delete_messages=True,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_send_welcome_messages=False,
        can_post_messages=True if channel else None,
        can_edit_messages=True if channel else None,
        can_pin_messages=None if channel else True,
    )


def add_channel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text=t("btn.connect_channel"),
                request_chat=KeyboardButtonRequestChat(
                    request_id=REQUEST_CHANNEL,
                    chat_is_channel=True,
                    bot_administrator_rights=_rights(channel=True),
                    request_title=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(
                text=t("btn.connect_group"),
                request_chat=KeyboardButtonRequestChat(
                    request_id=REQUEST_GROUP,
                    chat_is_channel=False,
                    bot_administrator_rights=_rights(channel=False),
                    request_title=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(text=t("btn.main_menu"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
