from __future__ import annotations

from aiogram.types import KeyboardButton, KeyboardButtonRequestChat, ReplyKeyboardMarkup

from flowpost.i18n import t

REQUEST_CHANNEL = 1
REQUEST_GROUP = 2
REQUEST_DISCUSSION = 3


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


def add_channel_kb() -> ReplyKeyboardMarkup:
    # No `bot_administrator_rights` here: Telegram rejects the whole request with
    # USER_RIGHTS_MISSING because ChatAdministratorRights' required can_post_stories /
    # can_edit_stories / can_delete_stories fields can't be granted to a bot at all, even as
    # False. Telegram's own chat picker still offers to add the bot as admin without it — we
    # verify the actual grant afterwards in channels.rights_error().
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text=t("btn.connect_channel"),
                request_chat=KeyboardButtonRequestChat(
                    request_id=REQUEST_CHANNEL, chat_is_channel=True, request_title=True, request_username=True
                ),
            )],
            [KeyboardButton(
                text=t("btn.connect_group"),
                request_chat=KeyboardButtonRequestChat(
                    request_id=REQUEST_GROUP, chat_is_channel=False, request_title=True, request_username=True
                ),
            )],
            [KeyboardButton(text=t("btn.main_menu"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def link_discussion_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text=t("btn.connect_discussion"),
                request_chat=KeyboardButtonRequestChat(
                    request_id=REQUEST_DISCUSSION, chat_is_channel=False, bot_is_member=True,
                    request_title=True, request_username=True,
                ),
            )],
            [KeyboardButton(text=t("btn.main_menu"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
