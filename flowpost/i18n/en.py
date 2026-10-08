"""English texts. Every string goes through str.format — write literal braces as {{ }}."""

TEXTS: dict[str, str] = {
    # ---- Bot profile & commands --------------------------------------------------------------
    "bot.description": (
        "👋 I'm FlowPost — an SMM assistant that never takes a day off.\n\n"
        "✍️ I build posts with photos, videos, buttons and an auto-signature\n"
        "🎠 Carousels, spoilers and paid posts for Stars\n"
        "🕒 I publish on schedule — even while you sleep\n"
        "🤖 I turn raw text or a screenshot into a ready post with AI\n"
        "🎁 I run comment giveaways and pick winners at random\n"
        "🚪 I approve join requests and greet new subscribers\n"
        "⭐ PRO: ad links, RSS, an idea bank, an AI content plan, "
        "auto-translation and a weekly report\n\n"
        "Tap /start — let's go!"
    ),
    "bot.short_description": "Autoposting for Telegram channels: scheduling, AI, watermarks, buttons.",
    "cmd.start": "Main menu",
    "cmd.menu": "Show the menu buttons",
    "cmd.restart": "🔄 Restart the bot",
    "cmd.newpost": "Create a post",
    "cmd.addchannel": "Connect a channel or group",
    "cmd.plan": "Content plan",
    "cmd.ad": "Ad post",
    "cmd.edit": "Edit a post",
    "cmd.projects": "My projects",
    "cmd.settings": "Settings",
    "cmd.subscribe": "Subscription",
    "cmd.paysupport": "Payment support",
    "cmd.terms": "Terms of use",
    "cmd.help": "What the bot can do",

    # ---- Start & menu ------------------------------------------------------------------------
    "start.welcome": (
        "Hi, {name}! 👋\n\n"
        "I'm <b>FlowPost</b> — I'll help you run channels without the routine:\n\n"
        "✍️ posts with photos, videos, buttons and an auto-signature\n"
        "🕒 scheduled publishing, auto-repeat and multiposting\n"
        "🤖 an AI assistant that turns a draft into a ready post\n"
        "💧 watermarks on photos and videos\n\n"
        "🎁 Every channel gets <b>{days} days</b> free, counted from the moment you connect it.\n"
        "Action buttons are below the input field 👇"
    ),
    "start.no_channels": "To get started, connect your channel or group — it takes a minute.",
    "start.restarted": "🔄 Bot restarted. Main menu 👇",
    "menu.main": "Main menu 👇",
    "menu.placeholder": "Send a photo, video or text…",
    "help.text": (
        "ℹ️ <b>How to use FlowPost</b>\n\n"
        "1. /addchannel — connect a channel or group.\n"
        "2. Send the bot a photo, video, text, or a poll — the editor opens.\n"
        "3. Add buttons, a watermark, an auto-signature or polish the text with AI.\n"
        "4. Tap «Publish» or «Schedule».\n\n"
        "/plan — content plan\n"
        "/edit — edit a post\n"
        "/projects — channel settings\n"
        "/subscribe — subscription\n"
        "/paysupport — payment support\n\n"
        "<b>Also included:</b>\n"
        "🔁 duplicate protection — warns if similar text or media was already published\n"
        "🎯 smart posting time — suggests the best slots based on subscriber activity\n"
        "📊 polls & quizzes — a post type of their own (just send a poll like any other content)\n"
        "🎠 carousel — 2–10 photos or videos flipped with arrows or a swipe, with buttons under the post "
        "(editor → “Carousel”)\n"
        "🎞 media display — a spoiler, or a paid post: photos and videos unlock for Stars that go to the "
        "channel's balance (editor → “🎞 Media display”)\n"
        "🛡 comment moderation — removes profanity and spam in the discussion group (My Projects → Comments)\n"
        "🎁 comment giveaway — the bot counts everyone who comments on a post and randomly picks winners "
        "(My Projects → channel → “🎁 Giveaway”)\n"
        "🚪 join requests & welcome — the bot approves join requests and greets new people in private "
        "(My Projects → channel → “🚪 Join requests & welcome”)\n\n"
        "<b>⭐ PRO tools</b> (My projects → channel → «⭐ PRO tools»; paid plan or trial):\n"
        "🔗 ad links — a link per ad: how many came, how many left, and the cost per subscriber\n"
        "🧠 AI comment moderation — AI removes insults, ads and scams the regular filter misses\n"
        "📰 RSS autoposting — new items from sites become posts, rewritten by AI in the channel's style\n"
        "🧠 AI content plan — 7 ready posts for the week, each opens in the editor\n"
        "🌐 auto-translation — in multiposting a post comes out in each channel's language\n"
        "📊 weekly report — every Monday: growth, best posts, best time and days without posts\n"
        "💡 idea bank — send the bot anything (text, a photo, a forwarded post, a link) and tap “💡 To ideas”\n"
        "🔒 hidden text — only subscribers can see it (editor → More settings)"
    ),
    "btn.create_post": "✍️ Create post",
    "btn.content_plan": "🗓 Content plan",
    "btn.ad_post": "📣 Ad post",
    "btn.edit_post": "✏️ Edit post",
    "btn.projects": "📂 My projects",
    "btn.settings": "⚙️ Settings",
    "btn.main_menu": "🏠 Main menu",
    "btn.connect_channel": "📢 Connect channel",
    "btn.connect_group": "👥 Connect group",
    "btn.add_channel": "➕ Connect a channel or group",
    "btn.back": "↩️ Back",
    "btn.pay": "💳 Subscribe",
    "btn.manage_sub": "💳 Manage subscription",
    "btn.topic_general": "💬 General topic",
    "btn.topic_set": "🧵 Choose topic",

    # ---- Connecting a channel ----------------------------------------------------------------
    "addch.text": (
        "📡 <b>Connect a channel or group</b>\n\n"
        "1. Tap «Connect channel» or «Connect group» below.\n"
        "2. Pick the chat from the list.\n"
        "3. Telegram will offer to add FlowPost as an admin — accept.\n\n"
        "The bot needs rights to post, edit and delete messages. "
        "You can also do it manually: add the bot as an admin and the channel connects automatically."
    ),
    "addch.done": "✅ <b>{title}</b> is connected! Tap «Create post» or just send me a photo, video or text.",
    "addch.forum": "This group has topics enabled. Which topic should posts go to?",
    "addch.lost": "⚠️ FlowPost no longer has admin rights in «{title}». It's been removed from «My projects» and scheduled posts won't go out there. Give the bot its rights back and the channel returns with all its settings.",
    "addch.err_bot_not_admin": "The bot isn't an admin of this chat yet. Add FlowPost as an admin and try again.",
    "addch.err_no_access": "Couldn't check the chat. Make sure the bot is an admin and try again.",
    "addch.err_no_post_right": "The bot can't post messages in this channel. Enable that right in the admin settings.",
    "addch.err_user_not_admin": "You can only connect channels and groups where you are an admin.",

    # ---- Creating a post ---------------------------------------------------------------------
    "post.no_channels": "First connect a channel or group to publish to.",
    "post.choose_channel": "Which channel is this post for?",

    # ---- Editor ------------------------------------------------------------------------------
    "ed.title": "✏️ <b>Post editor</b>",
    "ed.title_published": "✏️ <b>Editing a published post</b>",
    "ed.channels": "📡 Channels: {names}",
    "ed.part": "🧩 Message {n} of {total}",
    "ed.part_short": "{n}/{total}",
    "ed.scheduled_at": "🕒 Scheduled: {date} at {time}",
    "ed.hint": "<i>To replace media, send a new photo, video or animation. To fix the text, send a new one.</i>",
    "ed.hint_empty": "<i>Send a photo, video, GIF, text, or a poll (📎 → Poll) — the post is built from it. Text sent separately becomes the media caption.</i>",
    "ed.hint_poll": "<i>This is a poll. To replace it, send another one via 📎 → Poll.</i>",
    "ed.hint_published": "<i>Send new text or media, change buttons — then tap «Save in channel».</i>",
    "ed.updated_media": "✅ Media updated",
    "ed.updated_text": "✅ Text updated",
    "ed.updated_poll": "✅ Poll added",
    "ed.deleted_text": "✅ Text deleted",
    "ed.delete_text": "🗑 Delete text",
    "ed.delete_source_signature": "🗑 Delete source signature",
    "ed.deleted_source_signature": "✅ Source signature deleted",
    "ed.delete_poll": "🗑 Delete poll",
    "ed.deleted_poll": "✅ Poll deleted",
    "ed.primary_channel_note": "ℹ️ Settings are shown for the first channel. Change them for other channels in «My projects».",
    "ed.watermark": "💧 Watermark",
    "ed.buttons": "🔘 Buttons",
    "ed.media": "🖼 Media",
    "ed.signature": "✍️ Auto-signature",
    "ed.ai": "🤖 AI assistant",
    "ed.more": "⚙️ More settings",
    "ed.carousel": "Carousel",
    "ed.media_view": "🎞 Media display",
    "mv.title": "🎞 <b>Media display</b>",
    "mv.help": (
        "Choose how subscribers see the post's photos and videos.\n\n"
        "⭐ <b>Paid post</b> — the media stays blurred until the reader unlocks it for Stars. In a channel the "
        "Stars go to the channel's balance.\n"
        "🫥 <b>Spoiler</b> — the media stays blurred until the reader taps it."
    ),
    "mv.paid": "Paid post",
    "mv.price": "Post price: {n} ⭐",
    "mv.spoiler": "Spoiler",
    "mv.price_prompt": "⭐ <b>Post price</b>\n\nSend the bot the price of the post in Stars (1 to {max}).",
    "ed.messages": "➕ Messages",
    "ed.repeat": "🔁 Auto-repeat",
    "ed.schedule": "🕒 Schedule",
    "ed.multipost": "📡 Multiposting",
    "ed.publish": "🚀 Publish",
    "ed.cancel": "✖️ Cancel and back",
    "ed.idea": "💡 To ideas",
    "ed.idea_keep": "💡 Keep in ideas",
    "ed.save_published": "💾 Save in channel",
    "ed.exit": "↩️ Close editor",
    "ed.sum_signature": "signature",
    "ed.sum_watermark": "watermark",
    "ed.sum_silent": "silent",
    "ed.sum_protect": "copy protection",
    "ed.sum_nopreview": "no link previews",
    "ed.sum_pin": "pin",
    "ed.sum_pin_hours": "pin for {hours} h",
    "ed.sum_delete": "delete after {hours} h",
    "ed.sum_repeat": "repeat every {interval}",

    # ---- Channel post defaults ---------------------------------------------------------------
    "ed.def_btn": "Save formatting and settings",
    "ed.def_title": "🗄 <b>Save formatting and settings</b>",
    "ed.def_confirm": "Confirm that new posts should use these settings and formatting by default.",
    "ed.def_saving": "Will be saved: {items}",
    "ed.def_no_signature": "no signature",
    "ed.def_no_comments": "no comments",
    "ed.def_buttons": "buttons ({n})",
    "ed.def_help_title": "ℹ️ How default settings work",
    "ed.def_help": (
        "Every new post in this channel will open with these settings and buttons already applied — "
        "you can always change them in the editor, and posts you already created stay untouched. "
        "To update the defaults, save them from another post."
    ),
    "ed.def_save": "Save as default",
    "ed.def_back": "← Back",
    "ed.def_saved_short": "Saved!",
    "ed.def_saved": "✅ New posts in {channels} will use these settings.",
    "fmt.days": "{n} d",
    "fmt.hours": "{n} h",
    "fmt.minutes": "{n} min",

    # ---- Buttons -----------------------------------------------------------------------------
    "btn_menu.giveaway_kept": "🎁 The giveaway join button stays under the post apart from these buttons.",
    "btn_menu.title": "🔘 <b>Buttons</b>",
    "btn_menu.pick": "› Pick a section",
    "btn_menu.or_send": "› Or send new buttons — the format is detected automatically:",
    "btn_menu.formats": (
        "<blockquote>🔗 <b>Button — https://link.com</b>\n\n"
        "<i>Separate several buttons in one row with</i> <code>|</code>\n\n"
        "<i>Or reactions:</i>\n<b>👍 / 👎</b>\n\n"
        "<i>Or a hint button:</i>\n<b>👉 Read more — the hint's text</b>\n\n"
        "💡 <i>See each section for format details.</i></blockquote>"
    ),
    "btn_menu.current": "Under the post now:",
    "btn_menu.url": "URL buttons",
    "btn_menu.url_add": "➕ URL buttons",
    "btn_menu.hidden": "Hidden continuation",
    "btn_menu.quiz": "Quiz",
    "btn_menu.reactions": "Reactions",
    "btn_menu.comment": "Leave a comment",
    "btn_menu.edit": "✏️ Edit",
    "btn_menu.delete": "🗑 Delete",
    "btn_menu.favorites": "🤍 Favorites",
    "btn_menu.nothing": "There are no buttons under the post yet.",
    "btn_menu.edit_prompt": "Copy the current buttons, fix them and send them back — they replace the existing ones:",
    "btn_menu.pick_delete": "Pick a button to remove it from under the post.",
    "btn_menu.removed": "Button removed",
    "btn_menu.delete_all": "🗑 Delete all",
    "btn_menu.cleared": "Buttons removed",
    "btn_menu.prompt": (
        "Send buttons as <code>Button text — link</code>\n\n"
        "Each line is a row. To put several buttons in one row, separate them with <code>|</code>.\n\n"
        "Example:\n<code>Read more — https://t.me/nashe_misto</code>\n"
        "<code>Website — https://example.com | Chat — https://t.me/chat</code>\n\n"
        "💡 A hint button has text instead of a link, shown in a pop-up after the tap:\n"
        "<code>👉 Read more — Continued tomorrow at 10:00</code>"
    ),
    "btn_menu.example": (
        "Correct format example:\n<code>Read more — https://t.me/your_channel</code>\n"
        "or a hint button:\n<code>👉 Read more — the hint's text</code>"
    ),
    "btn_menu.hint_prompt": (
        "💡 Hint button «{name}»\n\n"
        "Send the hint's text — up to {max} characters. Everyone who taps the button will see it."
    ),
    "err.hint_long": "Line {line}: the hint's text is longer than {max} characters.",
    "btn_menu.saved": "✅ Buttons saved",
    "err.buttons_empty": "I don't see any buttons.",
    "err.buttons_format": "Line {line}: couldn't recognize the «Text — link» format.",
    "err.buttons_text": "Line {line}: button text is empty or longer than {max} characters.",
    "err.buttons_url": "Line {line}: the link must start with https:// or t.me/.",
    "err.buttons_row": "Line {line}: no more than {max} buttons per row.",
    "err.buttons_rows": "Too many button rows — {max} at most.",

    # ---- Media -------------------------------------------------------------------------------
    "media_menu.title": "🖼 <b>Post media</b> ({n}/{max})",
    "media_menu.empty": "No media yet — this will be a text post.",
    "media_menu.help": "Photos and videos can be combined into an album of up to 10. GIFs only on their own. Documents and audio only with the same type.",
    "media_menu.add": "➕ Add media",
    "media_menu.clear": "🗑 Remove all media",
    "media_menu.changed": "Done",
    "media_menu.back_to_preview": "Tap «Back» to see the updated preview.",
    "media_menu.add_prompt": "Send photos, videos or GIFs (albums work too). When you're finished, tap «Done».",
    "media_menu.added": "✅ Added. The post now has {n}/{max} media. Send more or tap «Done».",
    "media_menu.done": "✅ Done",

    # ---- Album -------------------------------------------------------------------------------
    "alb.title": "🗂 <b>Media {n} of {total}</b> {icon}",
    "alb.help": "<i>Pick a number to preview that media. To replace the selected one, send a new file.</i>",
    "alb.wm_status": "💧 Watermark: {status}",
    "alb.wm_on": "applied",
    "alb.wm_off": "not applied",
    "alb.wm_as_album": "(same as the whole album)",
    "alb.wm_own_text": "own text «{text}»",
    "alb.wm_own_image": "own logo",
    "alb.wm_unsupported": "not available for this file type",
    "alb.wm_item": "💧 Watermark on this media",
    "alb.wm_all": "💧 Watermark on all media",
    "alb.move": "🔀 Move",
    "alb.delete": "🗑 Delete",
    "alb.add": "➕ Add media to album",
    "alb.move_prompt": "🔀 <b>Move media {n}</b>\n\nWhich media should it swap places with?",
    "alb.moved": "✅ Media {src} and {dst} swapped",
    "alb.deleted": "✅ Media deleted",
    "alb.replaced": "✅ Media replaced",
    "alb.cleared": "✅ All media removed",
    "alb.saved": "✅ Saved",
    "alb.one_file": "Send a single file — it will replace the selected media. To add several, tap «Add media to album».",
    "alb.wm_item_title": "💧 <b>Watermark · media {n} of {total}</b>",
    "alb.wm_item_help": "You can watermark only this media, leave only this one clean, or set its own text or logo.",
    "alb.wm_mode_on": "Apply to this media",
    "alb.wm_mode_off": "No watermark",
    "alb.wm_mode_album": "Same as the whole album",
    "alb.wm_custom": "🔤 Own watermark: text or logo",
    "alb.wm_custom_reset": "↩️ Remove own watermark",
    "alb.wm_custom_prompt": "Send the watermark: text (up to {max} characters) or a PNG with a transparent background <b>as a file</b>. Position, opacity and size follow the channel settings.",
    "alb.wm_need_setup": "Set a watermark first: in the channel settings or an own one for the media.",
    "alb.wm_all_title": "💧 <b>Watermark on all media</b>",
    "alb.wm_all_help": "An album-wide choice resets per-media on/off choices. An own watermark for all replaces the channel's one on every photo and video.",
    "alb.wm_overrides": "Media with their own settings: {n}",
    "alb.wm_all_on": "Apply to all",
    "alb.wm_all_off": "Remove from all",
    "alb.wm_custom_all": "🔤 Own watermark for all",
    "alb.wm_channel": "⚙️ Channel watermark: position, size",
    "alb.wm_all_enabled": "✅ The watermark will be applied to all media",
    "alb.wm_all_disabled": "✅ The watermark was removed from all media",
    "media.photo": "Photo",
    "media.video": "Video",
    "media.animation": "GIF",
    "media.document": "Document",
    "media.audio": "Audio",
    "err.media_too_many": "A post can have at most 10 media items.",
    "err.media_gif_group": "GIFs can't be combined with other media in an album — Telegram doesn't support it.",
    "err.media_mix_document": "Documents can only be grouped with documents.",
    "err.media_mix_audio": "Audio can only be grouped with audio.",

    # ---- Watermark ---------------------------------------------------------------------------
    "wm.title": "💧 <b>Watermark</b> · {title}",
    "wm.kind_text": "Text: <b>{text}</b>",
    "wm.kind_image": "Image (logo)",
    "wm.not_set": "Not set up yet — add a text or a logo.",
    "wm.params": "Position {position} · opacity {opacity}% · size {scale}%",
    "wm.help": "The watermark is applied to photos, videos and GIFs when publishing. Videos over 20 MB are posted without it.",
    "wm.apply_post": "Apply to this post",
    "wm.set_text": "🔤 Text",
    "wm.set_image": "🖼 Logo",
    "wm.position": "📍 Position",
    "wm.position_title": "📍 Choose where to place the watermark:",
    "wm.opacity_short": "Opacity {v}%",
    "wm.scale_short": "Size {v}%",
    "wm.default_toggle": "Enable for new posts",
    "wm.need_setup": "Set a watermark text or logo first.",
    "wm.text_prompt": "Send the watermark text (up to {max} characters), e.g. <code>@nashe_misto</code>.",
    "wm.image_prompt": "Send your logo. To keep transparency, send a PNG <b>as a file</b> (uncompressed).",
    "wm.saved": "✅ Watermark saved",

    # ---- Auto-signature ----------------------------------------------------------------------
    "sig.title": "✍️ <b>Auto-signature</b> · {title}",
    "sig.preview": "It will look like this:",
    "sig.template": "Template: <code>{template}</code>",
    "sig.help": (
        "The signature is added under every post. The template can use "
        "<code>{{title}}</code> — channel name, <code>{{link}}</code> — link, <code>{{username}}</code> — @username."
    ),
    "sig.apply_post": "Add to this post",
    "sig.edit": "✏️ Change template",
    "sig.reset": "↩️ Default template",
    "sig.default_toggle": "Enable for new posts",
    "sig.prompt": (
        "Send the signature template (up to 512 characters). Telegram formatting or HTML is fine, for example:\n"
        "<code>👉 &lt;a href=\"{{link}}\"&gt;{{title}}&lt;/a&gt;</code>"
    ),
    "sig.invalid": "The signature came out empty. Try another template.",
    "sig.saved": "✅ Auto-signature saved",
    "sig.item_main": "<b>Template {n}</b> · main",
    "sig.item": "<b>Template {n}</b>",
    "sig.pick": "Template {n}",
    "sig.add": "➕ Add template",
    "sig.deleted": "Template deleted",
    "sig.add_prompt": (
        "Send a new signature template (up to 512 characters). You'll be able to pick it in the post editor "
        "with the «✍️ Auto-signature» button. Telegram formatting or HTML is fine, for example:\n"
        "<code>👉 &lt;a href=\"{{link}}\"&gt;{{title}}&lt;/a&gt;</code>"
    ),
    "sig.added": "✅ Template added",
    "sig.edit_pick": "✏️ Which template do you want to change?",
    "sig.edit_current": "<b>Template {n}</b> now: <code>{template}</code>",
    "sig.too_many": "You can have up to {max} templates. Delete one to add a new one.",

    # ---- Comments (discussion group) ----------------------------------------------------------
    "cm.title": "💬 <b>Comments</b> · {title}",
    "cm.linked": "Linked in the bot: <b>{title}</b>",
    "cm.not_linked": "No discussion group linked in the bot yet.",
    "cm.help": (
        "⚠️ The «Comment» button under posts only appears once a discussion group is linked to "
        "the channel in Telegram itself: <b>Channel settings → Discussion → pick a group</b>. "
        "That's a one-time step in the Telegram app — the bot can't do it.\n\n"
        "Linking a group here, in the bot, is for something else: turning comments off for "
        "individual posts and enabling moderation (removing profanity and spam). Link the <b>same</b> "
        "group, enable «Topics» in it, and add the bot as an administrator with the manage-topics and "
        "delete-messages rights."
    ),
    "cm.link": "🔗 Link a group in the bot",
    "cm.relink": "🔗 Change group",
    "cm.unlink": "❌ Unlink",
    "cm.link_prompt": "Pick the same discussion group that's linked to the channel in Telegram. The bot must already be an admin there.",
    "cm.linked_done": "✅ Group «{title}» linked in the bot. Remember: the «Comment» button only shows up if this same group is linked to the channel via Telegram (Channel settings → Discussion).",
    "cm.err_bot_not_admin": "The bot isn't an admin of that group. Add it as an administrator and try again.",

    # ---- Comment moderation --------------------------------------------------------------------
    "cm.moderation_on": "🛡 Comment moderation: on",
    "cm.moderation_off": "🛡 Comment moderation: off",
    "cm.moderation_toggle": "Moderation",
    "cm.banned_words_count": "Custom banned words: {n}",
    "cm.banned_words_btn": "✏️ Banned words",
    "cm.aimod_on": "🧠 AI moderation (PRO): on",
    "cm.aimod_off": "🧠 AI moderation (PRO): off",
    "cm.aimod_paused": "⏸ AI checks have run out — only the regular filter works. Buy more in Billing → «Top up limits».",
    "cm.aimod_btn": "🧠 AI moderation ⭐",
    "aimod.on_done": (
        "🧠 AI moderation is on. Besides profanity and links, AI will remove insults, ads and scams.\n\n"
        "Comments are checked in batches of up to {batch}: one batch uses 1 AI check of the channel's limits."
    ),
    "aimod.out": (
        "⏸ AI comment moderation in «{title}» is paused: the AI checks have run out. "
        "The regular profanity and link filter keeps working.\n\n"
        "Buy more checks and AI moderation resumes on its own."
    ),
    "aimod.buy_btn": "🧠 Buy AI checks",
    "cm.auto_on": "📝 Auto comment under posts: on",
    "cm.auto_off": "📝 Auto comment under posts: off",
    "cm.auto_preview": "<b>Auto comment text:</b>",
    "cm.auto_btn": "Auto comment",
    "cm.auto_text_btn": "✏️ Auto comment text",
    "cm.auto_default": "💬 Share your thoughts in the comments!",
    "cm.auto_need_group": "Link a discussion group first.",
    "cm.auto_prompt": (
        "Send the text the bot will leave as the first comment under every published post "
        "(up to {max} characters). Formatting and links are kept.\n\n"
        "Tip: to have the comment shown on behalf of the group rather than the bot, turn on "
        "«Remain anonymous» in the bot's admin rights in the group."
    ),
    "cm.auto_saved": "✅ Auto comment saved and turned on.",
    "mod.words_prompt": (
        "Send words or phrases to remove from comments — one per line or comma-separated "
        "(up to {max}). They're added on top of the built-in profanity list.\n\n"
        "Current: {current}"
    ),
    "mod.words_none": "none set",
    "mod.words_saved": "✅ Saved ({n})",
    "mod.words_too_many": "Too many words — {max} max.",
    "btn.connect_discussion": "👥 Choose discussion group",

    # ---- Channel analytics ---------------------------------------------------------------------
    "stats.title": "📊 <b>Analytics</b> · {title}",
    "stats.summary": "Posts: {count} · Reactions: {reactions} · Comments: {comments}",
    "stats.top_title": "<b>Top posts:</b>",
    "stats.row": "{n}. {title} — ❤️ {reactions} · 💬 {comments}",
    "stats.no_text": "(no text)",
    "stats.empty": "No posts published in this period yet.",
    "stats.period_7": "7 days",
    "stats.period_30": "30 days",

    # ---- AI assistant ------------------------------------------------------------------------
    "ai.title": "🤖 <b>AI assistant</b>",
    "ai.help": "Choose what to do with the text of the current message. I'll show the result before applying it.",
    "ai.disabled": "The AI assistant hasn't been set up by the bot owner yet.",
    "ai.quota": "Requests left today: {left}",
    "ai.quota_over": "The daily AI request limit is used up. Try again later.",
    "ai.quota_channel": "AI texts left for this channel: {left}",
    "ai.quota_channel_over": "This channel's AI text limit is used up. Top up limits in billing.",
    "ai.format": "✨ Polish the post",
    "ai.shorten": "✂️ Shorten",
    "ai.fix": "📝 Fix mistakes",
    "ai.emoji": "😊 Add emoji",
    "ai.custom": "💬 Custom request",
    "ai.screenshot": "📸 Post from a screenshot",
    "ai.style": "🎨 Channel style",
    "ai.working": "⏳ AI is working on the text…",
    "ai.need_text": "Send the post text first.",
    "ai.result_title": "🤖 <b>AI suggestion:</b>",
    "ai.apply": "✅ Apply",
    "ai.again": "🔄 Another version",
    "ai.applied": "✅ AI text applied",
    "ai.custom_prompt": "Describe what to change in the post. For example: «make the tone more formal and add a call to subscribe».",
    "ai.screenshot_prompt": "Send a screenshot (photo or JPG/PNG file) — I'll turn it into a ready post.",
    "ai.image_too_big": "The image is too big — send a file up to 5 MB.",
    "ai.style_prompt": (
        "🎨 <b>Channel style</b>\n\n"
        "Describe how posts should sound: tone, length, emoji, hashtags, words to avoid. The AI will follow it every time.\n\n"
        "Current: {current}\n\nSend the description (up to {max} characters)."
    ),
    "ai.style_none": "not set",
    "ai.style_reset": "🗑 Reset style",
    "ai.style_reset_done": "Style reset",
    "ai.style_saved": "✅ Channel style saved",
    "ai.busy": "The AI is overloaded right now. Try again in a minute.",
    "ai.failed": "Couldn't get a response from the AI. Please try again.",
    "ai.refused": "The AI declined to process this text.",
    "ai.empty": "The AI returned an empty response. Please try again.",
    "ai.check": "🔎 Check before publishing",
    "ai.series": "🧵 Series from a long text",
    "ai.free_help": "🆓 «Check» and «Series» are free.",
    "ai.free_quota_over": "The daily limit of free AI checks is used up. Please try again later.",
    # ---- Check before publishing -------------------------------------------------------------
    "check.title": "🔎 <b>Check before publishing</b>",
    "check.working": "⏳ Checking the text…",
    "check.clean": "✅ No mistakes, unnatural wording or factual risks found.",
    "check.kind_error": "Mistakes",
    "check.kind_surzhyk": "Unnatural wording (surzhyk)",
    "check.kind_fact": "Factual risks — worth checking",
    "check.over_limit": "⛔ The text is too long for Telegram: {n} characters, the limit is {limit}.",
    "check.too_long": "📏 The text is too long ({n} characters).",
    "check.length_ok": "📏 The length is fine ({n} characters).",
    "check.cta_ok": "📣 There is a call to action.",
    "check.cta_missing": "📣 No call to action.",
    "check.apply_fix": "✅ Fix the mistakes",
    "check.again": "🔄 Check again",
    "check.fixed": "✅ Fixes applied",
    # ---- Series from a long text -------------------------------------------------------------
    "series.prompt": (
        "🧵 <b>Series from a long text</b>\n\n"
        "Send a long text or a link to an article — the AI will split it into 3–5 posts that become the messages "
        "of this post's series. Then you pick the publishing time right away."
    ),
    "series.use_current": "📄 Use the current message's text",
    "series.fetching": "⏳ Loading the article…",
    "series.working": "⏳ The AI is splitting the text into posts…",
    "series.too_short": "The text is too short for a series — it needs at least {n} characters. Send a longer text or a link to an article.",
    "series.err_fetch": "Couldn't open the link. Check the address or send the article's text itself.",
    "series.err_too_big": "The page is too big. Send the article's text itself.",
    "series.err_no_text": "No article text found on the page. Send the text itself.",
    "series.result": "🧵 <b>A series of {n} posts:</b>",
    "series.result_help": "<i>The posts become the messages of the series and go out one after another. The current message texts will be replaced; media stays.</i>",
    "series.apply_schedule": "✅ Make a series and schedule",
    "series.apply": "✅ Just make a series",
    "series.applied": "✅ A series of {n} posts is ready",
    "series.published": "A series can only be made from a new or scheduled post.",
    "series.has_poll": "The post has a poll — remove it to make a series.",

    # ---- More settings -----------------------------------------------------------------------
    "more.title": "⚙️ <b>More settings</b>",
    "more.help": "Options for this post: notifications, protection, pinning and auto-delete.",
    "more.silent": "🔕 Silent publishing",
    "more.protect": "🛡 Protect from copying",
    "more.link_preview": "🔗 Link previews",
    "more.comments": "💬 Comments on this post",
    "more.pin_off": "📌 Pin: no",
    "more.pin_forever": "📌 Pin: yes",
    "more.pin_hours": "📌 Pin for {hours} h",
    "more.delete_off": "🗑 Auto-delete: no",
    "more.delete_hours": "🗑 Delete after {hours} h",
    "more.custom": "⌨️ Custom time",
    "more.pin_prompt": "For how many hours should the post stay pinned? Send a number from 1 to {max}.",
    "more.delete_prompt": "After how many hours should the post be deleted? Send a number from 1 to {max}.",
    "err.number": "Send a whole number from 1 to {max}.",

    # ---- Message series ----------------------------------------------------------------------
    "parts.title": "🧩 <b>Messages in the series: {n}</b>",
    "parts.help": "A series is published in order: message 1 first, then message 2 and so on. The auto-signature goes under the last one.",
    "parts.add": "➕ Add a message",
    "parts.delete": "🗑 Delete message {n}",
    "parts.added": "✅ Message {n} added. Send its text or media.",
    "parts.deleted": "🗑 Message deleted",
    "parts.limit": "A series can have up to {max} messages.",
    "parts.no_text": "no text",

    # ---- Auto-repeat -------------------------------------------------------------------------
    "rep.title": "🔁 <b>Auto-repeat</b>",
    "rep.off": "Off.",
    "rep.current": "Repeat every {interval}, {count}.",
    "rep.infinite": "no limit",
    "rep.times": "{n} more time(s)",
    "rep.deletes_previous": "The previous publication is deleted before the new one.",
    "rep.help": "After each publication the post will go out again after the chosen interval.",
    "rep.custom": "⌨️ Custom interval (h)",
    "rep.inf_short": "∞",
    "rep.delete_prev": "Delete previous",
    "rep.disable": "⛔ Turn off auto-repeat",
    "rep.custom_prompt": "Send the interval in hours (1 to {max}).",

    # ---- Schedule ----------------------------------------------------------------------------
    "sch.title": "🕒 <b>Schedule publication</b>",
    "sch.date": "📅 {date}",
    "sch.planned": "Scheduled for this day:",
    "sch.none": "Nothing is scheduled for this day.",
    "sch.smart_hint": "🎯 Best time based on subscriber activity: {slots}",
    "sch.pick": "Choose the publication time or send your own as <b>Hours:Minutes</b>, e.g. <code>14:35</code>.",
    "sch.no_slots": "No free slots left for this day — choose another day, or send your own time as <b>Hours:Minutes</b>.",
    "sch.this_post": "this post",
    "sch.more_slots": "↓ More slots",
    "sch.past": "That time has already passed — choose a later one.",
    "sch.confirm": "Schedule the post for <b>{date}</b> at <b>{time}</b>?\n{channels}\nChannels: {n}",
    "sch.confirm_repeat": "🔁 Auto-repeat will kick in after publishing.",
    "sch.confirm_yes": "✅ Confirm",
    "sch.change": "✏️ Change",
    "sch.done": "<b>Done</b> ✈️\n\nThe post «{title}» is scheduled for <b>{when}</b> in {channels}.",
    "sch.done_no_time": "<b>Done</b> ✈️\n\nThe post «{title}» is scheduled in {channels}.",
    "sch.done_short": "Scheduled!",
    "err.time_format": "❌ Wrong time format. Send it as Hours:Minutes, for example: <code>09:05</code> or <code>14:35</code>.",

    # ---- Multiposting ------------------------------------------------------------------------
    "multi.title": "📡 <b>Multiposting</b> — channels selected: {n}",
    "multi.help": "Tick the channels this post will go to.",
    "multi.only_one": "Only one channel is connected. Add more in «My projects» to publish to several at once.",
    "multi.need_one": "At least one channel must be selected.",
    "multi.done": "✅ Done",

    # ---- Publish, cancel, save ---------------------------------------------------------------
    "pub.confirm": "🚀 Publish the post now? Channels: {n}\n{names}",
    "pub.confirm_yes": "🚀 Yes, publish",
    "pub.working": "⏳ Publishing…",
    "pub.done": "<b>Done</b> ✈️\n\nThe post «{title}» is published in {channels}.",
    "pub.result_title": "📬 <b>Publishing result</b>",
    "pub.ok_line": "✅ {title}: <a href=\"{link}\">open post</a>",
    "pub.fail_line": "❌ {title}: {error}",

    # ---- Duplicate protection --------------------------------------------------------------------
    "conflict.title": "⚠️ <b>The channel already has a publication within an hour of this time:</b>",
    "conflict.line": "• {time} — {kind} in \"{channel}\": {what}",
    "conflict.post": "post",
    "conflict.ad": "📣 ad",
    "conflict.schedule_anyway": "✅ Schedule anyway",
    "conflict.publish_anyway": "🚀 Publish anyway",
    "dup.warn_text": "⚠️ Similar text was already published in \"{channel}\" {date}.",
    "dup.warn_media": "⚠️ This media was already published in \"{channel}\" {date}.",
    "dup.warn_link": "(<a href=\"{link}\">that post</a>)",

    "cancel.confirm": "Cancel creating this post? The draft will be deleted.",
    "cancel.yes": "🗑 Yes, delete",
    "cancel.done": "Draft deleted. Main menu 👇",
    "cancel.closed": "Editor closed, changes saved. Main menu 👇",
    "save.title": "💾 <b>Saving changes in channels</b>",
    "save.working": "Saving…",
    "save.ok_line": "✅ {title}: updated",
    "save.media_count": "The number of media changed — Telegram doesn't allow adding or removing media in a published album. Only the text was updated.",
    "save.poll_not_editable": "Polls can't be edited after publishing — Telegram doesn't allow it.",
    "save.buttons_album": "Buttons can't be added under a published album without a separate message.",
    "save.parts_added": "New series messages aren't published while editing — publish them as a separate post.",

    # ---- Content plan ------------------------------------------------------------------------
    "plan.pick_channel": "🗓 <b>Content plan</b>\n\nChoose a channel:",
    "plan.all_channels": "🔀 All channels",
    "plan.channels_btn": "🔀 Another channel",
    "plan.title": "🗓 <b>Content plan</b>",
    "plan.tab_scheduled": "🕒 Scheduled",
    "plan.tab_published": "✅ Published",
    "plan.count": "Scheduled posts: {n}. Tap a post to manage it.",
    "plan.empty": "Nothing is scheduled for this day.",
    "plan.count_published": "Published posts: {n}. Tap a post to edit it.",
    "plan.empty_published": "Nothing was published on this day.",
    "plan.new_post": "✍️ Create post",
    "plan.calendar": "📅 Weekly calendar",
    "proj.gap_on": "📅 Empty-day reminders: on",
    "proj.gap_off": "📅 Empty-day reminders: off",
    "proj.gap_toggle_on": "🔕 Stop empty-day reminders",
    "proj.gap_toggle_off": "📅 Remind me about empty days",
    "gap.text": "📅 <b>{title}</b>: nothing is scheduled for {days} yet.\nSchedule posts ahead so the channel doesn't go quiet.",
    "gap.ideas": "💡 The channel has {n} ideas waiting. Open the calendar and drag them onto the free days.",
    "gap.tomorrow": "tomorrow",
    "gap.calendar_btn": "📅 Open calendar",
    "gap.plan_btn": "🗓 Content plan",
    "gap.off_btn": "🔕 Don't remind me",
    "gap.off_done": "Empty-day reminders are off. You can turn them back on in the channel's card.",
    "proj.calendar_btn": "📅 Publishing calendar",
    "plan.post_title": "🗓 <b>Scheduled post</b>",
    "plan.post_title_published": "✅ <b>Published post</b>",
    "plan.edit": "✏️ Edit",
    "plan.move": "🕒 Reschedule",
    "plan.now": "🚀 Publish now",
    "plan.drop": "🗑 Cancel publication",
    "plan.drop_confirm": "Cancel the scheduled publication of this post? Auto-repeat will be turned off too.",
    "plan.drop_yes": "🗑 Yes, cancel",
    "plan.dropped": "Publication cancelled",

    # ---- Edit post ---------------------------------------------------------------------------
    "editp.pick_channel": "✏️ <b>Edit a post</b>\n\nChoose a channel:",
    "editp.title": "✏️ <b>Edit a post</b>",
    "editp.help": "Pick a post from the list or forward a post from your channel here.",
    "editp.empty": "No published or scheduled posts yet. Forward a post from your channel if it was published via FlowPost.",
    "editp.published_note": "ℹ️ This post is already published. Text, button and media changes are applied in the channel after «Save in channel».",
    "editp.forward_channel_only": "Please forward the post from a channel.",
    "editp.not_connected": "This channel isn't connected to FlowPost.",
    "editp.not_found": "Couldn't find this post among those published via FlowPost.",

    # ---- My projects -------------------------------------------------------------------------
    "proj.title": "📂 <b>My projects</b>",
    "proj.help": "Choose a channel to set up its auto-signature, watermark and AI style.",
    "proj.empty": "No channels connected yet.",
    "proj.kind": "Type: {kind}",
    "proj.kind_channel": "channel",
    "proj.kind_group": "group",
    "proj.status_active": "🟢 Connected",
    "proj.status_inactive": "⛔ Disconnected",
    "proj.signature": "✍️ Signature: {signature}",
    "proj.signature_off": "✍️ Signature is off for new posts",
    "proj.watermark_on": "💧 Watermark: on",
    "proj.watermark_off": "💧 Watermark: off",
    "proj.ai_style_set": "🎨 AI style: set",
    "proj.ai_style_none": "🎨 AI style: not set",
    "proj.ai_style_btn": "🎨 AI style",
    "proj.topic": "🧵 Topic: {topic}",
    "proj.topic_general": "general",
    "proj.notify_on": "🔔 Publish notification: on ({recipients})",
    "proj.notify_off": "🔕 Publish notification: off",
    "proj.notify_toggle_on": "🔕 Turn off publish notification",
    "proj.notify_toggle_off": "🔔 Turn on publish notification",
    "proj.notify_recipients_owner": "owner",
    "proj.notify_recipients_admin": "admin",
    "proj.notify_recipients_both": "owner and admin",
    "proj.notify_rcpt_owner": "👤 Owner",
    "proj.notify_rcpt_admin": "👥 Admin",
    "proj.notify_rcpt_both": "👤👥 Both",
    "proj.comments_btn": "💬 Comments",
    "proj.comments_on": "💬 Comments: group «{title}»",
    "proj.comments_off": "💬 Comments: no group linked",
    "proj.stats_btn": "📊 Analytics",
    "proj.disconnect": "🔌 Disconnect",
    "proj.disconnect_confirm": "Disconnect <b>{title}</b>? The channel will be removed from the bot along with its settings, stats and scheduled publications. Its paid plan will be lost too — move it to another channel in «FlowPost Billing» first.",
    "proj.disconnect_yes": "🔌 Yes, disconnect",
    "proj.disconnected": "Channel removed from the bot",

    # ---- Channel administrators -----------------------------------------------------------------
    "admins.manage_btn": "👥 Administrators",
    "admins.list_title": "👥 <b>Administrators of «{title}»</b>",
    "admins.list_empty": "No administrators added yet.",
    "admins.invite_btn": "➕ Invite an administrator",
    "admins.remove_confirm": "Remove {name} from the administrators of «{title}»?",
    "admins.remove_yes": "❌ Yes, remove",
    "admins.removed": "Administrator removed",
    "admins.perm_posts": "📝 Posts",
    "admins.perm_settings": "⚙️ Settings",
    "admins.perm_disconnect": "🔌 Disconnect",
    "admins.new_title": "Choose what to allow the administrator to do in «{title}»:",
    "admins.edit_title": "👤 <b>{name}</b> — administrator of «{title}».\n\nTick what they may do:",
    "admins.remove_btn": "❌ Remove from administrators",
    "admins.edit_need_one": "At least one permission is needed. To take access away completely, tap «Remove from administrators».",
    "admins.perms_changed": "The owner of «{title}» changed your permissions.\nYou can now: {perms}",
    "admins.perms_help": (
        "📝 <b>Posts</b> — create, edit, publish, schedule\n"
        "⚙️ <b>Settings</b> — signature, watermark, AI style\n"
        "🔌 <b>Disconnect</b> — disconnect the channel from the bot"
    ),
    "admins.new_create": "🔗 Create invite link",
    "admins.new_need_one": "Pick at least one permission.",
    "admins.invite_created": (
        "✅ Invite link created (one-time use):\n\n{link}\n\n"
        "Permissions: {perms}\n\nSend this link to the person you want to make an administrator."
    ),
    "admins.invite_invalid": "This invite link is invalid or already used.",
    "admins.invite_self": "That's your own channel — no invite needed.",
    "admins.invite_accepted": "✅ You're now an administrator of «{title}».\nYour permissions: {perms}",
    "topic.prompt": "Send a link to the topic (e.g. <code>https://t.me/c/1234567890/15</code>) or its number.",
    "topic.saved": "✅ Posts will be published to topic #{topic}.",
    "topic.saved_general": "✅ Posts will be published to the general topic.",
    "err.topic": "Couldn't recognize the topic. Send a link like https://t.me/c/1234567890/15 or the topic number.",

    # ---- Settings ----------------------------------------------------------------------------
    "set.title": "⚙️ <b>Settings</b>",
    "set.lang": "🌐 Language: {lang}",
    "set.tz": "🕒 Time zone: {tz} (now {time})",
    "set.sub_trial": "🎁 Free trial until {date} {time} — {days} days left",
    "set.sub_paid": "💎 Subscription active until {date} ({provider}) — {days} days left",
    "set.sub_cancelled": "💎 Subscription valid until {date} ({provider}), auto-renewal off — {days} days left",
    "set.sub_trial_pending": "🎁 Your {days}-day free trial starts when you connect a channel",
    "set.sub_none": "⛔ No active subscription",
    "set.change_lang": "🌐 Змінити мову / Change language",
    "set.change_tz": "🕒 Change time zone",
    "set.manage_sub": "💎 Manage subscription",
    "set.interface": "🎛 Interface",
    "set.interface_title": "🎛 <b>Interface</b>",
    "set.interface_text": "Tune the bot's interface for more convenient posting.",
    "set.interface_folders": "🗂 Folders",
    "set.interface_channels": "📢 Channels",
    "set.interface_editor": "🧩 Post editor",
    "set.ed_title": "🧩 <b>Post editor settings</b>",
    "set.ed_text": (
        "Tick the buttons to show in the post editor. Hidden buttons are still in «⚙️ More settings», and auto-repeat, multiposting and the idea stay in place while they're on for the post. Buttons that only appear for a particular post (delete the caption, media view, carousel) aren't configurable."
    ),
    "set.ch_title": "📢 <b>Channel list settings</b>",
    "set.ch_text": "Here you can set the order and the display of your channels.",
    "set.ch_order": "⇅ Channel order",
    "set.ch_per_page": "Channels per page: {n}",
    "set.ch_per_page_title": "🔢 <b>Channels per page</b>",
    "set.ch_per_page_text": "Choose how many channels to show per page when creating posts and in the content plan.",
    "set.ch_order_title": "⇅ <b>Channel order</b>",
    "set.ch_order_text": (
        "Choose which channels come first in the channel lists "
        "when creating posts, in the content plan and in the settings."
    ),
    "set.ch_order_empty": "Connect channels first.",
    "set.support": "🆘 Support",

    # ---- Channel folders ---------------------------------------------------------------------
    "fld.title": "🗂 <b>Folders</b>",
    "fld.help": (
        "Folders keep things tidy when you have many channels. "
        "Group them by topic, region or however you like."
    ),
    "fld.row": "{icon} {title} ({n})",
    "fld.new": "➕ New folder",
    "fld.create_title": "🗂 <b>Create a folder</b>",
    "fld.create_prompt": "Send a name for the new folder.",
    "fld.name_empty": "A folder name can't be empty.",
    "fld.created": "✅ Folder «{title}» created. Now add channels to it.",
    "fld.pick_title": "{icon} <b>{title}</b>",
    "fld.pick": "Choose what goes into this folder.",
    "fld.select_all": "Select all",
    "fld.clear": "Clear selection",
    "fld.save": "Save →",
    "fld.cancel_back": "← Cancel and back",
    "fld.saved": "✅ Folder saved",
    "fld.settings": "⚙️ Settings",
    "fld.cz_title": "⚙️ <b>Folder settings</b>",
    "fld.cz_folder": "Folder:",
    "fld.cz_hint": "› Send a new name or an icon\n› Or change the style from the menu",
    "fld.delete": "🗑 Delete",
    "fld.delete_confirm": "Delete the folder «{title}»? The channels themselves stay connected.",
    "fld.delete_yes": "🗑 Yes, delete",
    "fld.deleted": "Folder deleted",
    "fld.no_channels": "Connect channels first — then you can sort them into folders.",
    "fld.leave": "↥ Leave folder",
    "fld.empty_folder": "This folder has no channels yet.",
    "set.support_text": "🆘 Questions, ideas or problems — write to: {contact}",
    "set.support_prompt": "🆘 Describe your question, idea or problem in one message — I'll pass it to the support team.",
    "set.support_sent": "✅ Message sent to support. We'll get back to you shortly.",
    "set.support_failed": "⚠️ Couldn't send the message to support. Please try again later.",
    "set.support_reply_prompt": "✍️ Write your reply — I'll pass it to the support team.",
    "set.support_reply_btn": "✍️ Reply",
    "set.support_answer": "💬 <b>Support reply</b>\n\n{text}",
    "set.lang_changed": "✅ Language changed. Main menu 👇",
    "set.tz_title": "🕒 Choose your time zone (current: {tz})",
    "set.tz_manual": "⌨️ Enter manually",
    "set.tz_prompt": "Send an IANA time zone name, e.g. <code>Europe/Kyiv</code> or <code>America/Toronto</code>.",
    "set.tz_invalid": "Unknown time zone. Example: Europe/Kyiv",
    "set.saved": "✅ Saved",
    "provider.stars": "Telegram Stars",
    "provider.liqpay": "card, LiqPay",
    "provider.manual": "manual",

    # ---- Billing -----------------------------------------------------------------------------
    "pay.open": (
        "💎 <b>FlowPost subscription</b>\n\n"
        "Plans, Telegram Stars top-ups and channel subscriptions live in the «FlowPost Billing» app. "
        "Tap the button below."
    ),
    "pay.unavailable": "Payments are unavailable right now. Please contact support: {contact}",
    "pay.cancel_btn": "❌ Turn off auto-renewal",
    "pay.cancel_confirm": "Turn off auto-renewal? You keep access until the end of the paid period.",
    "pay.cancel_yes": "❌ Yes, turn off",
    "pay.cancelled": "Auto-renewal is off. Access remains until {date}.",
    "pay.change_failed": "Couldn't change the subscription. Try again later or contact support.",
    "pay.invalid": "This invoice is no longer valid. Open the payment again from the subscription menu.",
    "pay.success": "🎉 Thank you! Your subscription is active until {date}.",
    "pay.failed": "⚠️ The payment didn't go through. Try again or choose another payment method.",
    "pay.topup_title": "FlowPost balance top-up",
    "pay.topup_desc": "Adds {stars} ⭐ to your FlowPost balance for paying channel subscriptions.",
    "pay.topup_done": "✅ Balance topped up with {stars} ⭐\nTotal balance: {balance} ⭐",
    "pay.topup_done_cashback": "✅ Balance topped up with {stars} ⭐ (+{cashback} ⭐ cashback)\nTotal balance: {balance} ⭐",
    "pay.support": "🆘 <b>Payment support</b>\n\nIf something went wrong with a payment, write to {contact}: describe the problem and include the payment date.",
    "pay.terms": (
        "📄 <b>FlowPost terms of use</b>\n\n"
        "• Every connected channel gets a free trial: {days} days and up to {posts} posts, "
        "plus watermarks on {photo} photos and {video} videos, {ai} AI texts and {mod} AI comment checks.\n"
        "• After that the channel runs on the free plan ({free} posts a day) or on a paid subscription "
        "paid with Telegram Stars via the «Subscribe» button.\n"
        "• The bot only publishes to channels where you are an admin, and only content you created.\n"
        "• The channel owner is responsible for the content of posts.\n\n"
        "Payment questions — /paysupport"
    ),
    "paywall.text": (
        "⛔ <b>Your free trial has ended</b>\n\n"
        "Publishing, scheduling and AI are available with a FlowPost subscription. Your drafts and settings are saved."
    ),
    "paywall.short": "Subscription required — the free trial has ended.",
    "paywall.extras": (
        "⛔ <b>Available with a subscription or during the trial</b>\n\n"
        "The channel is on the free plan: the AI assistant, watermarks, multiposting and auto-repeat aren't included. "
        "Subscribe for the channel, or publish the post to a single channel without auto-repeat."
    ),
    "paywall.extras_short": "Not included in the free plan — the channel needs a subscription.",

    # ---- Notifications -----------------------------------------------------------------------
    "notify.published": "✅ Post published in «{title}»: {link}",
    "notify.failed": "❌ Couldn't publish the post in «{title}»: {error}",
    "notify.missed": "⚠️ The publication in «{title}» was skipped: the bot was unavailable at the scheduled time. Open «Content plan» to reschedule.",
    "notify.paused": "⏸ Scheduled posts are paused: the trial or subscription has ended. Subscribe and they'll continue going out.",
    "notify.paused_extras": "⏸ The post in «{title}» is paused: {error}. Subscribe for the channel and it will go out.",
    "notify.limit": "⏸ The post in «{title}» didn't go out: {error}.\nTo publish more, subscribe or upgrade your plan.",
    "notify.trial_ending":"⏳ The trial of «{title}» ends in less than a day. Get a plan to keep posts going out on schedule.",
    "notify.sub_ending": "⏳ Your FlowPost subscription ends tomorrow — the last day. Renew it to keep posts going out on schedule.",
    "notify.grant": "🎁 <b>«{title}» has been credited with:</b>\n{items}",
    "notify.grant_note": "💬 {note}",
    "grant.kind_wm_photo": "• watermarks (photo): +{n}",
    "grant.kind_wm_video": "• watermarks (video): +{n}",
    "grant.kind_ai_text": "• AI texts: +{n}",
    "grant.kind_ai_mod": "• AI moderation checks: +{n}",
    "grant.days": "• plan of {posts} posts/day: +{n} days",

    # ---- Errors & warnings -------------------------------------------------------------------
    "err.post_limit": "the plan's post limit is used up; new publication time",
    "err.bot_not_admin":"the bot is not an admin of the channel",
    "err.channel_inactive": "the channel is disconnected",
    "err.post_empty": "📭 Nothing's been sent yet — the post is empty. Add some text, a photo, or a video, then try again.",
    "err.pub_missing": "the post or channel was deleted",
    "err.no_access": "no active subscription",
    "err.extras_plan": "multiposting and auto-repeat aren't included in the free plan",
    "err.missed": "skipped",
    "err.retry_later": "we'll retry shortly",
    "err.telegram": "Telegram rejected the message (check formatting and media)",
    "err.network": "connection problems with Telegram",
    "err.unknown": "unknown error",
    "err.not_found": "Not found.",
    "err.post_not_found": "Post not found — it may have been deleted.",
    "err.expected_input": "I'm expecting a different reply. Use the hint above or tap «Back».",
    "err.text_too_long": "The text is too long: Telegram allows up to {max} characters.",
    "err.unknown_command": "Unknown command. Menu — /start, help — /help.",
    "err.unsupported_content": "This message type isn't supported. Send a photo, video, GIF, document, audio or text.",
    "warn.paid_types": "only a post with photos and videos (up to 10) can be paid — this one goes out free",
    "warn.paid_group": "in a group the Stars for a paid post would go to the bot, not to you, so this post goes out free there",
    "warn.album_buttons": "Telegram doesn't show buttons under albums — the text and buttons will go in a separate message right after the album.",
    "warn.long_caption": "The text is longer than 1024 characters — media and text will go out as two messages.",
    "warn.text_too_long": "The text with the signature is longer than 4096 characters — please shorten it.",
    "warn.premium_emoji": "premium emoji will go out as plain ones — Telegram allows them only for bots with a username from Fragment.",
    "warn.pin_failed": "couldn't pin the post (check the bot's rights)",
    "warn.preview_failed": "Couldn't show the preview: {error}",
    "ed.wm_rendering": "⏳ Adding the watermark to the video — the preview refreshes shortly; this is the original for now.",
    "warn.wm_failed": "couldn't watermark the video — the original was published",
    "warn.wm_no_ffmpeg": "video watermarks are unavailable on the server (ffmpeg missing)",
    "warn.wm_too_big": "the file is larger than 20 MB — published without a watermark",
    "warn.wm_no_quota": "watermark quota used up — published without it. Top up limits in billing",
    "warn.wm_plan": "watermarks aren't included in the free plan — the post goes out without them",

    # ---- PRO tools ----------------------------------------------------------------------------
    "pro.btn": "⭐ PRO tools",
    "pro.title": "⭐ <b>PRO tools · {title}</b>",
    "pro.help": (
        "Tools to grow the channel: ad links that count subscribers, autoposting from RSS, "
        " an AI content plan, an idea bank, auto-translation, a weekly report, AI comment moderation, the channel's "
        "voice, ad posts from a brief, niche research and an AI answerer in comments."
    ),
    "pro.locked": "🔒 Available on the channel's paid plan or during its trial.",
    "pro.paywall": "⭐ PRO tools come with the channel's paid plan and trial. Get a plan in billing to use them.",
    "pro.links": "🔗 Ad links",
    "pro.join": "🚪 Join requests & welcome",
    "pro.rss": "📰 Autoposting from RSS",
    "pro.plan": "🧠 AI content plan for the week",
    "pro.ideas": "💡 Idea bank",
    "pro.translate": "🌐 Auto-translation: {lang}",
    "pro.translate_off": "off",
    "pro.report": "📊 Weekly report",
    "pro.aimod": "🧠 AI comment moderation · {n}",
    "pro.voice": "🎯 Channel voice",
    "pro.adgen": "🤝 Ad post",
    "pro.niche": "🔍 Niche research",
    "pro.answer": "🤖 AI answerer in comments",

    "voice.title": "🎯 <b>Channel voice · {title}</b>",
    "voice.help": (
        "The AI studies up to 40 of the channel's best posts of the last six months and describes its style: tone, "
        "how readers are addressed, length, structure, favourite words and emoji. The profile becomes the channel's "
        "style, so every AI feature writes the way this channel does.\n\nOne analysis costs 1 AI text of the channel."
    ),
    "voice.current": "<b>Current style:</b>\n{style}",
    "voice.go": "🧠 Analyse the posts",
    "voice.few_posts": "Not enough published posts with text to analyse: at least {n} are needed.",
    "voice.working": "⏳ Studying {n} of the channel's posts…",
    "voice.result": "🎯 <b>Channel voice</b> (from {n} posts):",
    "voice.result_help": "<i>Save the profile to replace the channel's current style.</i>",
    "voice.save": "✅ Save as the channel style",
    "voice.saved": "✅ The channel voice is saved. Every AI feature now writes in this style.",
    "voice.expired": "The profile has expired — run the analysis again.",

    "adgen.prompt": (
        "🤝 <b>Ad post · {title}</b>\n\n"
        "Send the advertiser's brief in one message: what is advertised, the link, benefits, prices or a promo code, "
        "wishes for the text. The AI writes a native post in your channel's style.\n\n"
        "One post costs 1 AI text of the channel."
    ),
    "adgen.working": "⏳ Writing the ad post…",
    "adgen.result": "🤝 <b>Ad post:</b>",
    "adgen.use": "✍️ Open in the editor",
    "adgen.opened": "🤝 The ad post is ready. Add media and buttons, then schedule it.",
    "adgen.expired": "The brief has expired — send it again.",
    "ad.start": (
        "💲 <b>New ad</b>\n\n"
        "<blockquote expandable>Ad posts work differently from regular ones. They carry no signature of your channel, "
        "no watermark and no default formatting.</blockquote>\n\n"
        "Choose the channel to publish your ad in."
    ),
    "ad.restore": "📥 Restore draft",
    "ad.channel": (
        "<b>Ad post in {channel}</b>\n\n"
        "Send the ad post.\n\n"
        "No post or payment yet? Book a slot — the ad will be published if you confirm the booking later."
    ),
    "ad.new_booking": "➕ New booking",
    "ad.pick_booking": "Need to confirm a booking? Pick it from the list.",
    "ad.no_time": "no time",
    "ad.drop": "❌ Cancel booking",
    "ad.drop_confirm": "Cancel this booking? The ad won't go out and the post will be deleted.",
    "ad.drop_yes": "❌ Yes, cancel",
    "ad.dropped": "Booking cancelled",
    "ed.buttons_skipped": "{n} button(s) weren't carried over: they only work in the bot that made them. Add your own under «Buttons».",
    "ad.back": "← Back",
    "ad.booking": (
        "<b>New booking in {channel}</b>\n\n"
        "Send the post. If you don't have it yet, send the bot the advertiser's name, and you can upload the content later."
    ),
    "ad.booked": "📌 Slot booked for «{name}». Set the time, send the ad post here later — and confirm the booking.",
    "ad.settings": "⚙️ <b>Ad settings</b>",
    "ad.settings_booking": "⚙️ <b>Ad booking settings</b>",
    "ad.settings_help": "Set up the options and the publishing time of your ad post.",
    "ad.formats_help": "<i>1 / 24 — an hour at the top (the channel's other posts wait) and 24 hours in the feed, then the ad is deleted.</i>",
    "ad.advertiser": "👤 Advertiser: {name}",
    "ad.reply_line": "↩️ Reply to post: {url}",
    "ad.booking_unconfirmed": "⏳ The booking isn't confirmed — without confirmation the ad won't go out.",
    "ad.hint_empty": "<i>Send the ad post here — text, a photo, a video or an album.</i>",
    "ad.url_buttons": "URL buttons",
    "ad.preview": "Preview",
    "ad.reply_no": "Reply to post: no",
    "ad.reply_yes": "Reply to post: yes",
    "ad.no_pin": "Don't pin",
    "ad.pin": "Pin",
    "ad.delete_timer": "Delete timer",
    "ad.delete_hours": "🗑 Delete in {hours} h",
    "ad.sound": "With sound",
    "ad.silent": "Silent",
    "ad.no_comments": "Turn off comments",
    "ad.repeat": "Auto-repeat",
    "ad.multipost": "🔀 Multiposting",
    "ad.schedule": "⏰ Set time",
    "ad.publish": "🚀 Publish",
    "ad.confirm": "✅ Confirm booking",
    "ad.cancel": "← Cancel and back",
    "ad.hours": "{hours} h",
    "ad.delete_never": "Don't delete",
    "ad.delete_title": "🗑 <b>Delete timer</b>\n\nHow many hours after publishing should the ad be deleted from the channel?",
    "ad.reply_prompt": (
        "↩️ <b>Reply to post</b>\n\n"
        "Send a link to a channel post (e.g. <code>https://t.me/channel/123</code>) or forward it here — "
        "the ad goes out as a reply to it."
    ),
    "ad.reply_wrong": "I don't recognise that post. Send a link to a post of the channel the ad goes to, or forward it from there.",
    "ad.reply_saved": "✅ The ad goes out as a reply to the post",
    "ad.reply_removed": "Reply to post is off",
    "ad.confirmed": "Booking confirmed",
    "ad.confirm_empty": "Send the ad post first — a booking can't be confirmed without it.",
    "ad.publish_booking": "This is a booking: set the time and confirm it for the ad to go out.",
    "err.booking_unconfirmed": "the booking wasn't confirmed",
    "err.ad_top": "an ad is at the top of the channel, new publishing time",
    "notify.booking_unconfirmed": "⚠️ The ad in «{title}» wasn't published: the booking wasn't confirmed by the scheduled time, so the slot was released.",
    "adchk.btn": "🛡 Check the ad",
    "adchk.btn_ok": "🟢 Checked",
    "adchk.btn_warn": "🟡 Has remarks",
    "adchk.btn_risk": "🔴 Risky",
    "adchk.line_ok": "🛡 AI check: 🟢 safe to publish",
    "adchk.line_warn": "🛡 AI check: 🟡 questions for the advertiser",
    "adchk.line_risk": "🛡 AI check: 🔴 risky ad",
    "adchk.title": "🛡 <b>Ad check</b>",
    "adchk.verdict_ok": "🟢 <b>Safe to publish</b>",
    "adchk.verdict_warn": "🟡 <b>Some questions for the advertiser</b>",
    "adchk.verdict_risk": "🔴 <b>Better refuse or ask for changes</b>",
    "adchk.category": "🏷 Advertised: {text}",
    "adchk.links": "<b>Links:</b>",
    "adchk.again": "🔄 Check again · 1 AI text",
    "adchk.working": "⏳ Checking the ad and its links…",
    "adchk.empty": "Send the ad post first — there's nothing to check yet.",
    "adrep.btn": "📊 Report for advertiser",
    "adrep.line": "📊 A report for the advertiser comes after the ad",
    "adrep.on": "📊 Once the ad has run, the bot sends you a report: views, reactions, comments, the subscriber change and an AI conclusion (1 AI text). Just forward it to the advertiser.",
    "adrep.off": "Report turned off",
    "adrep.title": "📊 <b>Ad report in «{channel}»</b>",
    "adrep.ad": "📝 {title}",
    "adrep.period": "🗓 {period}",
    "adrep.format": "format {top}/{feed}",
    "adrep.views": "👁 Views: {n}",
    "adrep.views_private": "👁 Views: not available for a private channel",
    "adrep.views_unknown": "👁 Views: couldn't be read",
    "adrep.reactions": "❤️ Reactions: {n}",
    "adrep.comments": "💬 Comments: {n}",
    "adrep.members": "👥 Subscribers while the ad ran: {delta} ({before} → {after})",
    "adrep.link": "🔗 Post: {link}",
    "adrep.summary": "🤖 <b>Conclusion:</b> {text}",
    "adrep.no_ai": "ℹ️ No AI conclusion: the channel is out of AI texts.",

    "niche.title": "🔍 <b>Niche research · {title}</b>",
    "niche.help": (
        "List up to 5 public competitor channels. The AI reads their latest posts and shows what they write about, "
        "which formats get views and what your channel is missing — and suggests 5 ready posts.\n\n"
        "One analysis costs 1 AI text of the channel."
    ),
    "niche.list": "<b>Competitors:</b> {channels}",
    "niche.empty": "No competitors listed yet.",
    "niche.go": "🔍 Run the analysis",
    "niche.set": "✏️ Change the competitors",
    "niche.prompt": "Send up to {max} public channels: @username or t.me/… links, separated by spaces or new lines.",
    "niche.saved": "✅ The competitors are saved.",
    "niche.fetching": "⏳ Reading the posts of {n} channels…",
    "niche.working": "⏳ The AI is analysing the niche…",
    "niche.err_none": "Couldn't read any of the channels. Make sure they're public and have a web preview (t.me/s/name).",
    "niche.result": "🔍 <b>Niche research · {title}</b>",
    "niche.skipped": "<i>Couldn't read: {channels}</i>",
    "niche.save_ideas": "💡 Save {n} posts to the idea bank",
    "niche.ideas_saved": "💡 {n} posts were added to the idea bank — edit and schedule them from there.",
    "niche.expired": "The result has expired — run the analysis again.",

    "aians.title": "🤖 <b>AI answerer in comments · {title}</b>",
    "aians.help": (
        "The bot answers typical questions under posts («how much is it», «where are you», «when is the next "
        "giveaway») from a knowledge base you fill in. Harder questions the base doesn't cover are forwarded to you "
        "and the admins.\n\n"
        "The AI only sees comments that look like questions. Each of them costs 1 AI text of the channel."
    ),
    "aians.on": "✅ On",
    "aians.off": "⏸ Off",
    "aians.paused": "⏸ Out of AI texts — the answerer is paused. Top up the limits in billing.",
    "aians.no_group": "⚠️ Link a discussion group in the channel's comment settings first.",
    "aians.kb_line": "<b>Knowledge base:</b>\n{kb}",
    "aians.kb_empty": "<b>Knowledge base:</b> empty.",
    "aians.toggle": "AI answerer",
    "aians.kb_btn": "📚 Fill in the knowledge base",
    "aians.need_kb": "Fill in the knowledge base first — without it the AI has nothing to answer with.",
    "aians.on_done": "🤖 The AI answerer is on. It will answer questions in comments from your knowledge base.",
    "aians.kb_prompt": (
        "📚 Send the knowledge base in one message (up to {max} characters): prices, addresses, opening hours, "
        "delivery, giveaway rules, answers to frequent questions. The AI answers only from this data."
    ),
    "aians.kb_saved": "✅ The knowledge base is saved.",
    "aians.escalated": "❓ <b>A question in the comments of «{title}»</b>\n\nThe AI found no answer in the knowledge base — it needs your reply:\n\n<i>{text}</i>",
    "aians.open_btn": "💬 Open the comment",
    "aians.out": (
        "⏸ The AI answerer in the comments of «{title}» is paused: the channel is out of AI texts.\n\n"
        "Top up AI texts and the answerer resumes by itself."
    ),
    "aians.buy_btn": "🤖 Buy AI texts",

    "lnk.title": "🔗 <b>Ad links · {title}</b>",
    "lnk.help": (
        "Create a separate invite link for each ad. The bot counts how many people came through it, how many "
        "left, and what one subscriber cost."
    ),
    "lnk.new": "➕ New link",
    "lnk.row": "{n}. <b>{name}</b> — came {joined}, stayed {stayed}",
    "lnk.row_price": " · {price} per subscriber",
    "lnk.name_prompt": "What should the link be called? For example: <i>Ad in @kyiv_news 18.09</i> (up to 32 characters).",
    "lnk.too_many": "You can have up to {max} active links. Revoke old ones.",
    "lnk.err_create": "⚠️ Couldn't create the link. Make sure the bot is an admin allowed to invite users.",
    "lnk.created": "✅ Link created. Give it to the advertiser.",
    "lnk.detail_title": "🔗 <b>{name}</b>",
    "lnk.detail_stats": "Came: {joined} · Left: {left} · Stayed: {stayed}",
    "lnk.detail_cost": "💰 Ad cost: {cost}",
    "lnk.detail_price": "👤 Cost per subscriber: {price}",
    "lnk.detail_help": "The numbers update by themselves as people join or leave.",
    "lnk.set_cost": "💰 Set the ad cost",
    "lnk.cost_prompt": "How much did this ad cost? Send a number, e.g. <code>1500</code>. Any currency — the bot just divides it by the number of subscribers.",
    "lnk.revoke": "🗑 Revoke link",
    "lnk.revoke_confirm": "Revoke «{name}»? Nobody will be able to join through it, and its numbers leave the list.",
    "lnk.revoke_yes": "🗑 Yes, revoke",
    "lnk.revoked": "Link revoked",

    "jr.title": "🚪 <b>Join requests · {title}</b>",
    "jr.help": (
        "The bot can approve join requests for you and send new people a welcome message in private right away. "
        "Requests come when someone joins through a «join request» link (you can create one below) or when a "
        "group approves new members."
    ),
    "jr.approve_line": "✅ Auto-approve: {value}",
    "jr.approve_btn": "Auto-approve: {value} ▸",
    "jr.approve_off": "off",
    "jr.approve_now": "right away",
    "jr.approve_after": "after {minutes}",
    "jr.welcome_on": "👋 Welcome: on",
    "jr.welcome_off": "👋 Welcome: off",
    "jr.welcome_btn": "Welcome",
    "jr.welcome_text_btn": "✏️ Welcome text",
    "jr.welcome_preview": "<b>Welcome text:</b>",
    "jr.welcome_default": "👋 Welcome, {name}! Thanks for your interest in «{title}». We've got your request.",
    "jr.welcome_prompt": (
        "Send the welcome text (up to {max} characters). Formatting is kept. "
        "You can use <code>{{name}}</code> for the person's name and <code>{{title}}</code> for the channel name."
    ),
    "jr.welcome_saved": "✅ Welcome saved and turned on.",
    "jr.link_btn": "🔗 Create a join request link",
    "jr.link_line": "🔗 Join request link: <code>{url}</code>",

    "rss.title": "📰 <b>Autoposting from RSS · {title}</b>",
    "rss.help": (
        "Add a site's or blog's RSS feed. The bot turns new items into posts, rewritten by AI in the channel's "
        "style. Get them for approval or publish them right away. Each rewrite uses 1 AI text of the channel's limits."
    ),
    "rss.add": "➕ Add a source",
    "rss.url_prompt": "Send the address of an RSS or Atom feed, e.g. <code>https://example.com/feed</code>.",
    "rss.checking": "⏳ Checking the feed…",
    "rss.added": "✅ Source added ({n} items in the feed now). The bot will only post new ones that appear from now on.",
    "rss.feed_title": "📰 <b>{title}</b>",
    "rss.mode_line": "Mode: {mode}",
    "rss.mode_draft": "for approval",
    "rss.mode_auto": "publish right away",
    "rss.mode_btn": "🔁 Switch mode",
    "rss.ai_on": "🧠 AI rewrite: on",
    "rss.ai_off": "🧠 AI rewrite: off (title, summary and link)",
    "rss.ai_btn": "AI rewrite",
    "rss.active": "▶️ Running",
    "rss.paused": "⏸ Paused",
    "rss.pause_btn": "⏸ Pause",
    "rss.resume_btn": "▶️ Resume",
    "rss.delete_btn": "🗑 Delete",
    "rss.deleted": "Source deleted",
    "rss.err_url": "Invalid address. A public http(s) link is needed.",
    "rss.err_fetch": "Couldn't download the feed. Check the address.",
    "rss.err_too_big": "The feed is too big (over 2 MB).",
    "rss.err_parse": "There's no RSS or Atom feed at this address.",
    "rss.err_plan": "The source isn't checked: the channel has no paid plan or trial.",
    "rss.read_more": "Read more",
    "rss.draft_title": "📰 New item from «{feed}» — publish it?",
    "rss.draft_publish": "✅ Publish",
    "rss.draft_edit": "✏️ Edit",
    "rss.draft_skip": "✖️ Skip",
    "rss.draft_gone": "This item has already been published or skipped.",
    "rss.skipped": "Skipped",

    "plan.title": "🧠 <b>Content plan for the week · {title}</b>",
    "plan.working": "🧠 Putting the content plan together… This may take up to a minute.",
    "plan.help": "Tap a number to open the post in the editor, where you can polish, schedule or publish it.",
    "plan.again": "🔄 Another plan",
    "plan.expired": "This plan is out of date. Generate a new one.",
    "plan.opened": "🧠 Post #{n} from the content plan",

    "idea.title": "💡 <b>Idea bank · {title}</b>",
    "idea.help": (
        "Send the bot anything that could become a post: a thought as text, a photo, a link, someone else's "
        "forwarded post. Tap “💡 To ideas” in the editor and it waits here until you get to it. "
        "Ideas also show up in the channel's calendar, where you can drag them onto a day."
    ),
    "idea.pick": "Tap an idea to open it in the editor: polish it with AI, schedule or publish it.",
    "idea.empty": "No ideas yet.",
    "idea.empty_post": "You haven't sent anything yet. Send a text, photo or video, then you can save it to ideas.",
    "idea.saved": "💡 Saved to the ideas of “{title}”. Come back to it when you have time.",
    "idea.all": "💡 All ideas",
    "idea.opened": "💡 An idea from the idea bank",
    "idea.gone": "This idea is gone: it was published, scheduled or deleted.",
    "idea.paywall": (
        "💡 The idea bank comes with the channel's paid plan and trial. Get a plan in billing to collect "
        "everything that could become a post here."
    ),

    "gw.btn": "🎁 Giveaway",
    "gw.title": "🎁 <b>Giveaways · {title}</b>",
    "gw.help": (
        "Two ways to run a giveaway:\n"
        "• <b>With a button</b> — write the giveaway post and the bot puts a join button under it. Whoever taps it "
        "enters (once), and the button shows how many have entered.\n"
        "• <b>In the comments</b> — everyone who commented on a post published through the bot enters.\n\n"
        "The bot picks the winners at random; the result can be published right away, scheduled or edited."
    ),
    "gw.no_group": (
        "💬 For comment giveaways, link the channel's discussion group in the comment settings — "
        "the bot must be an admin there."
    ),
    "gw.pick_post": "Pick the post the giveaway ran under (👥 — number of entrants):",
    "gw.no_posts": "No posts published through the bot yet. Publish the giveaway post through the bot, and it will count everyone who comments on it.",
    "gw.post_title": "🎁 <b>Giveaway</b>",
    "gw.entrants": "👥 Entrants (commented): <b>{n}</b>",
    "gw.subs_on": "✅ Channel subscribers only — whoever unsubscribed is out",
    "gw.subs_off": "☑️ Among everyone who commented",
    "gw.subs_btn": "Subscribers only",
    "gw.choose_count": "How many winners? Tap 1 or 3, or enter your own number.",
    "gw.no_entrants": "Nobody has commented on this post yet.",
    "gw.run_1": "🥇 1 winner",
    "gw.run_3": "🏆 3 winners",
    "gw.run_custom": "✍️ Custom number",
    "gw.count_prompt": "How many winners? Send a number from 1 to {max}.",
    "gw.drawing": "🎲 Picking the winners…",
    "gw.none_eligible": "😕 Nobody to pick: none of the entrants qualify (maybe they all left the channel).",
    "gw.drawn_note": "🎲 <b>Winners picked!</b> Here's the message for the channel — publish it now, schedule it or edit it.",
    "gw.fewer": "⚠️ Only {n} entrants qualify.",
    "gw.publish_now": "🚀 Publish now",
    "gw.schedule": "🕒 Schedule",
    "gw.edit": "✏️ Edit",
    "gw.reroll": "🔄 Pick again",
    "gw.expired": "This result was already used or is out of date. Run the giveaway again.",
    "gw.opened": "🎁 Giveaway results",
    "gw.res_title": "🎉 <b>Giveaway results</b>",
    "gw.res_post": "this post",
    "gw.res_intro_one": "Giveaway under {post}. Entrants: <b>{total}</b>. The winner:",
    "gw.res_intro_many": "Giveaway under {post}. Entrants: <b>{total}</b>. The winners:",
    "gw.res_congrats": "Congratulations to the winners! 🎉",
    "gw.res_footer": "<i>🎲 Picked at random · {date} at {time}</i>",

    "gwb.new": "➕ New giveaway with a button",
    "gwb.pick": "🔘 Giveaways with a button (📝 draft · ✅ published · 🔒 closed to entries):",
    "gwb.gone": "This giveaway is no longer available — its post was deleted.",
    "gwb.button_prompt": (
        "🎁 <b>New giveaway with a button</b>\n\n"
        "What should the join button under the post say? Pick one or send your own text (up to {max} characters)."
    ),
    "gwb.preset_0": "I'm in!",
    "gwb.preset_1": "🎁 Join the giveaway",
    "gwb.preset_2": "🎲 Take part",
    "gwb.template": (
        "🎁 <b>Giveaway!</b>\n\n"
        "How to enter:\n"
        "1️⃣ Subscribe to {title}\n"
        "2️⃣ Tap «{button}» under this post\n\n"
        "📅 Results: <i>add the date and time</i>\n\n"
        "Winners are picked at random 🎲 Good luck!"
    ),
    "gwb.opened": (
        "🎁 Giveaway draft. Send your own text (a photo or video too) — the join button stays under the post. "
        "Then publish or schedule it. Pick the winners in «🎁 Giveaway» on the channel card."
    ),
    "gwb.title": "🎁 <b>Giveaway with a button</b>",
    "gwb.st_draft": "📝 The post isn't published yet (draft)",
    "gwb.st_scheduled": "🕒 The post is scheduled",
    "gwb.st_published": "✅ The post is published",
    "gwb.button": "🔘 Button: «{text}»",
    "gwb.entrants": "👥 Entrants: <b>{n}</b>",
    "gwb.open": "🔓 Open to entries",
    "gwb.closed": "🔒 Closed to entries",
    "gwb.subs_on": "✅ Channel subscribers only — others can't enter, and whoever leaves is out",
    "gwb.subs_off": "☑️ Anyone can enter",
    "gwb.not_published": "Publish or schedule the post — entrants appear as people tap the button.",
    "gwb.no_entrants": "Nobody has tapped the button yet.",
    "gwb.open_post": "📝 Open the post in the editor",
    "gwb.already_published": "The post is already published — change it with «✏️ Edit post».",
    "gwb.close_btn": "🔒 Close entries",
    "gwb.reopen_btn": "🔓 Reopen entries",
    "gwb.app_joined": "🎉 You're in the giveaway now!",
    "gwb.app_already": "✅ You're already in the giveaway. Good luck!",
    "gwb.app_subscribe": "📢 To enter, subscribe to the channel, then tap the button again.",
    "gwb.app_closed": "⏳ The giveaway is closed to new entries.",
    "gwb.app_gone": "😕 This giveaway is no longer running.",

    "tr.title": "🌐 <b>Auto-translation · {title}</b>",
    "tr.help": (
        "When a post goes to several channels (multiposting), it comes out in this channel translated into the "
        "chosen language. Each new translation uses 1 AI text of the channel's limits."
    ),

    "wr.title": "📊 <b>Weekly report · {title}</b>",
    "wr.period": "{start} — {end}",
    "wr.members": "👥 Subscribers: {n}{change}",
    "wr.summary": "📝 Posts: {posts} · ❤️ reactions: {reactions} · 💬 comments: {comments}",
    "wr.top": "🏆 <b>Best posts of the week:</b>",
    "wr.top_row": "{n}. {title} — ❤️ {reactions} · 💬 {comments}",
    "wr.links": "🔗 <b>Came through links:</b>",
    "wr.link_row": "• {name}: +{n}",
    "wr.best_time": "⏰ Best time to post: {slots}",
    "wr.plan_full": "🗓 The content plan for the week is full — great!",
    "wr.plan_gaps": "🗓 No posts scheduled for: {days}",
    "wr.off_btn": "🔕 Turn off the report for this channel",
    "wr.off_done": "The weekly report for this channel is off. Turn it back on in «⭐ PRO tools».",

    "hidden.btn": "🔒 Show hidden text",
    "hidden.subscribe": "🔒 Only subscribers can see this text. Subscribe to the channel and tap again.",
    "hidden.gone": "The hidden text is no longer available.",
    "hidden.need_boost": "🚀 Only people who boost the channel can see this. Boost the channel and tap again.",
    # ---- Buttons → Hidden continuation ---------------------------------------------------------
    "hc.title": "🙈 <b>Add a hidden continuation</b>",
    "hc.intro": "A hidden continuation is a button that hides part of the post from people who aren't subscribed to the channel.",
    "hc.step1": "<b>Step 1.</b> Send the button's name. {who} will see the hidden text after tapping it.",
    "hc.who_subs": "Subscribers",
    "hc.who_boost": "People who boost the channel",
    "hc.name_line": "🔘 Button: «{name}»",
    "hc.step2": "<b>Step 2.</b> Send the hidden text — up to {max} characters. A pop-up shows it after the tap.",
    "hc.step3_subs": (
        "<b>Step 3.</b> Send the text for people who aren't subscribed (up to {max} characters), "
        "or tap «Skip» — then the bot just asks them to subscribe."
    ),
    "hc.step3_boost": (
        "<b>Step 3.</b> Send the text for people who don't boost the channel (up to {max} characters), "
        "or tap «Skip» — then the bot just asks them to boost the channel."
    ),
    "hc.ai_title": "🪄 <b>Hidden continuation</b>",
    "hc.ai_help": (
        "AI writes hidden continuation buttons for you — one or several at once. Just send a request: "
        "ask it to continue the story or list what the buttons should say in any form.\n\n"
        "For a more precise result you can give:\n\n"
        "› Button names\n"
        "› The hidden text for each\n"
        "› The text for non-subscribers"
    ),
    "hc.ai_result": "🪄 <b>Here's what came out</b>\n\n🔓 — the hidden text, 🔒 — what everyone else sees.",
    "hc.ai_apply": "✅ Add under the post",
    "hc.ai_paid": "The AI generator comes with a paid plan or trial. Turn it off to add the button by hand.",
    "hc.color": "Button colour: {color}",
    "hc.color_title": "🎨 <b>Button colour</b>\n\nPick a colour for the button.",
    "hc.color_none": "no colour",
    "hc.color_primary": "blue",
    "hc.color_success": "green",
    "hc.color_danger": "red",
    "hc.ai": "AI generator",
    "hc.audience": "Show text to: {who}",
    "hc.aud_subs": "subscribers",
    "hc.aud_boost": "boosters",
    "hc.skip": "⏭ Skip",
    "hc.cancel": "← Cancel and back",
    "hc.saved": "✅ Hidden continuation added",
    "hc.bad_name": "The button's name must be 1 to {max} characters long.",
    "hc.too_long": "Too long: {n} characters, and the pop-up fits up to {max}. Please shorten it.",
    # ---- Buttons → Quiz ------------------------------------------------------------------------
    "qz.title": "🧩 <b>Add a quiz answer</b>",
    "qz.intro": (
        "A <b>quiz</b> is a post with a question and answer options. Each option shows as its own button. "
        "Only subscribers can see the results and statistics."
    ),
    "qz.step1": "<b>Step 1.</b> Send an answer option. It will be shown on the button.",
    "qz.step2": (
        "🧩 <b>Step 2</b>\n\n"
        "Send a <b>comment on the answer (right or wrong)</b>. Under it people will see how many answered the same.\n\n"
        "<b>Important.</b> The message can be at most {max} characters, the answer statistics included. "
        "If it's longer, the statistics get shortened."
    ),
    "qz.step3_subs": (
        "🧩 <b>Step 3</b>\n\n"
        "Send the message for people who are <b>NOT subscribed</b> to the channel.\n\n"
        "To keep the current text, tap «Continue».\n\n"
        "<blockquote><b>Current text:</b>\n\n{current}</blockquote>"
    ),
    "qz.step3_boost": (
        "🧩 <b>Step 3</b>\n\n"
        "Send the message for people who do <b>NOT boost</b> the channel.\n\n"
        "To keep the current text, tap «Continue».\n\n"
        "<blockquote><b>Current text:</b>\n\n{current}</blockquote>"
    ),
    "qz.continue": "Continue →",
    "qz.locked_subs": "Subscribe to the channel first.",
    "qz.locked_boost": "Boost the channel first.",
    "qz.added": (
        "✅ <b>Answer option #{n} added</b>\n\n"
        "Now you can:\n\n"
        "› Send another option\n"
        "› Or finish the quiz"
    ),
    "qz.place": "Insert position: {place}",
    "qz.place_new": "new row",
    "qz.place_same": "same row",
    "qz.done": "Finish the quiz",
    "qz.saved": "✅ The quiz is under the post",
    "qz.ai_title": "🪄 <b>Quiz</b>",
    "qz.ai_help": (
        "AI writes the quiz: answer options with a comment for each. Just send a request: "
        "a topic or a question, with answer options if you have them.\n\n"
        "For a more precise result you can give:\n\n"
        "› The answer options and which one is right\n"
        "› A comment for each\n"
        "› The text for non-subscribers"
    ),
    "qz.ai_result": "🪄 <b>Here's what came out</b>",
    "qz.yours": "Your answer: «{text}»",
    "qz.stats": "📊 {pct}% answered the same ({n} of {total})",
    "qz.stats_short": "📊 {pct}%",
    # ---- Buttons → Reactions -------------------------------------------------------------------
    "rc.title": (
        "☺️ <b>Reaction buttons</b>\n\n"
        "› Pick a colour and reactions from the grid below\n"
        "› Or send them in this format:\n\n"
        "<blockquote>👍 / 👎\nYes / No</blockquote>"
    ),
    "rc.current": "Under the post now:",
    "rc.color": "Colour: {color}",
    "rc.clear": "🗑 Remove reactions",
    "rc.cleared": "Reactions removed",
    "rc.done": "✅ Done",
    "rc.saved": "✅ Reactions added",
    "rc.example": "Send reactions separated by «/», each line is a row:\n<code>👍 / 👎</code>\n<code>Yes / No</code>",
    "rc.preview": "In the channel, taps here are counted on the button",
    "rc.put": "You picked {text}",
    "rc.taken_back": "Reaction taken back",
    # ---- Buttons → Leave a comment -------------------------------------------------------------
    "cm.btn": "💬 Leave a comment",
    "cm.on": "A «Leave a comment» button will be under the post",
    "cm.off": "The «Leave a comment» button is removed",
    "cm.no_discussion": (
        "The button is added. But for the post to have comments, the channel needs a discussion group "
        "in Telegram itself: channel settings → Discussion."
    ),
    "cm.preview": "💬 In the channel this button opens the comments under the post",
    # ---- Buttons → Favorites -------------------------------------------------------------------
    "fv.title": "🤍 <b>Favorite buttons</b>",
    "fv.help": "Save the buttons of this post to use them in one tap.",
    "fv.use_help": "Tap a saved button and it appears under this post.",
    "fv.save": "Save the buttons of this post",
    "fv.delete": "🗑 Delete from favorites",
    "fv.saved": "✅ Buttons saved.",
    "fv.nothing": "There are no buttons under the post that can be saved. Quiz answers and the giveaway button aren't saved.",
    "fv.full": "Favorites hold up to {max} buttons. Delete some and try again.",
    "fv.added": "✅ Added: {text}",
    "fv.already": "That button is already under the post",
    "fv.pick_delete": "Pick a button to delete it from Favorites.",
    "fv.removed": "Deleted from favorites",
    "more.hidden": "🔒 Hidden text for subscribers",
    "more.hidden_prompt": (
        "🔒 Send the text (up to {max} characters) only the channel's subscribers will see: a «Show hidden text» "
        "button appears under the post. Works on a paid plan or during the trial."
    ),
    "more.hidden_current": "Now: <i>{text}</i>",
    "more.hidden_remove": "🗑 Remove hidden text",
    "more.hidden_removed": "Hidden text removed",
    "more.hidden_saved": "✅ Hidden text added",
    "ed.sum_hidden": "🔒 hidden text",
    "ed.sum_carousel": "🎠 carousel",
    "ed.sum_paid": "⭐ paid post: {n} ⭐",
    "ed.sum_spoiler": "🫥 spoiler",
    "warn.translate_failed": "couldn't translate the post — published in the original language",
    "warn.translate_no_quota": "AI text limit used up — the post went out untranslated",
}
