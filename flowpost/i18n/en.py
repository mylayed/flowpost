"""English texts. Every string goes through str.format — write literal braces as {{ }}."""

TEXTS: dict[str, str] = {
    # ---- Bot profile & commands --------------------------------------------------------------
    "bot.description": (
        "👋 I'm FlowPost — an SMM assistant that never takes a day off and never forgets a post.\n\n"
        "✍️ I build beautiful posts with photos, videos, buttons and an auto-signature\n"
        "🕒 I publish on schedule — even while you sleep\n"
        "🤖 I turn raw text or a screenshot into a ready post with AI\n\n"
        "Tap /start — let's go!"
    ),
    "bot.short_description": "Autoposting for Telegram channels: scheduling, AI, watermarks, buttons.",
    "cmd.start": "Main menu",
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
        "🎁 The first <b>{days} days</b> are free.\n"
        "Action buttons are below the input field 👇"
    ),
    "start.no_channels": "To get started, connect your channel or group — it takes a minute.",
    "menu.main": "Main menu 👇",
    "menu.placeholder": "Send a photo, video or text…",
    "help.text": (
        "ℹ️ <b>How to use FlowPost</b>\n\n"
        "1. /addchannel — connect a channel or group.\n"
        "2. Send the bot a photo, video or text — the editor opens.\n"
        "3. Add buttons, a watermark, an auto-signature or polish the text with AI.\n"
        "4. Tap «Publish» or «Schedule».\n\n"
        "/plan — content plan\n"
        "/edit — edit a post\n"
        "/projects — channel settings\n"
        "/subscribe — subscription\n"
        "/paysupport — payment support"
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
    "addch.lost": "⚠️ FlowPost no longer has admin rights in «{title}». Scheduled posts won't go out there — give the bot its rights back to continue.",
    "addch.err_bot_not_admin": "The bot isn't an admin of this chat yet. Add FlowPost as an admin and try again.",
    "addch.err_no_access": "Couldn't check the chat. Make sure the bot is an admin and try again.",
    "addch.err_no_post_right": "The bot can't post messages in this channel. Enable that right in the admin settings.",
    "addch.err_user_not_admin": "You can only connect channels and groups where you are an admin.",

    # ---- Creating a post ---------------------------------------------------------------------
    "post.no_channels": "First connect a channel or group to publish to.",
    "post.choose_channel": "Which channel is this post for?",
    "post.ad_intro": "📣 Ad post: the «Ad» label is added, auto-signature is off, auto-delete in 24 h. Change it in «More settings».",
    "post.ad_label": "Ad",

    # ---- Editor ------------------------------------------------------------------------------
    "ed.title": "✏️ <b>Post editor</b>",
    "ed.title_ad": "📣 <b>Ad post</b>",
    "ed.title_published": "✏️ <b>Editing a published post</b>",
    "ed.channels": "📡 Channels: {names}",
    "ed.part": "🧩 Message {n} of {total}",
    "ed.part_short": "{n}/{total}",
    "ed.scheduled_at": "🕒 Scheduled: {date} at {time}",
    "ed.hint": "<i>To replace media, send a new photo, video or animation. To fix the text, send a new one.</i>",
    "ed.hint_empty": "<i>Send a photo, video, GIF or text — the post is built from it. Text sent separately becomes the media caption.</i>",
    "ed.hint_published": "<i>Send new text or media, change buttons — then tap «Save in channel».</i>",
    "ed.updated_media": "✅ Media updated",
    "ed.updated_text": "✅ Text updated",
    "ed.primary_channel_note": "ℹ️ Settings are shown for the first channel. Change them for other channels in «My projects».",
    "ed.watermark": "💧 Watermark",
    "ed.buttons": "🔘 Buttons",
    "ed.media": "🖼 Media",
    "ed.signature": "✍️ Auto-signature",
    "ed.ai": "🤖 AI assistant",
    "ed.more": "⚙️ More settings",
    "ed.messages": "➕ Messages",
    "ed.repeat": "🔁 Auto-repeat",
    "ed.schedule": "🕒 Schedule",
    "ed.multipost": "📡 Multiposting",
    "ed.publish": "🚀 Publish",
    "ed.cancel": "✖️ Cancel and back",
    "ed.save_published": "💾 Save in channel",
    "ed.exit": "↩️ Close editor",
    "ed.sum_signature": "signature",
    "ed.sum_watermark": "watermark",
    "ed.sum_ad": "«Ad» label",
    "ed.sum_silent": "silent",
    "ed.sum_protect": "copy protection",
    "ed.sum_nopreview": "no link previews",
    "ed.sum_pin": "pin",
    "ed.sum_pin_hours": "pin for {hours} h",
    "ed.sum_delete": "delete after {hours} h",
    "ed.sum_repeat": "repeat every {interval}",
    "fmt.days": "{n} d",
    "fmt.hours": "{n} h",
    "fmt.minutes": "{n} min",

    # ---- Buttons -----------------------------------------------------------------------------
    "btn_menu.title": "🔘 <b>Buttons under the post</b>",
    "btn_menu.current": "Current:",
    "btn_menu.none": "no buttons",
    "btn_menu.help": "Link buttons will appear under the post.",
    "btn_menu.set": "✏️ Set buttons",
    "btn_menu.clear": "🗑 Remove buttons",
    "btn_menu.cleared": "Buttons removed",
    "btn_menu.prompt": (
        "Send buttons as <code>Button text — link</code>\n\n"
        "Each line is a row. To put several buttons in one row, separate them with <code>|</code>.\n\n"
        "Example:\n<code>Read more — https://t.me/nashe_misto</code>\n"
        "<code>Website — https://example.com | Chat — https://t.me/chat</code>"
    ),
    "btn_menu.example": "Correct format example:\n<code>Read more — https://t.me/your_channel</code>",
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

    # ---- Comments (discussion group) ----------------------------------------------------------
    "cm.title": "💬 <b>Comments</b> · {title}",
    "cm.linked": "Linked in the bot: <b>{title}</b>",
    "cm.not_linked": "No discussion group linked in the bot yet.",
    "cm.help": (
        "⚠️ The «Comment» button under posts only appears once a discussion group is linked to "
        "the channel in Telegram itself: <b>Channel settings → Discussion → pick a group</b>. "
        "That's a one-time step in the Telegram app — the bot can't do it.\n\n"
        "Linking a group here, in the bot, is for something else: turning comments off for "
        "individual posts. Link the <b>same</b> group, enable «Topics» in it, and add the bot as "
        "an administrator with the manage-topics right."
    ),
    "cm.link": "🔗 Link a group in the bot",
    "cm.relink": "🔗 Change group",
    "cm.unlink": "❌ Unlink",
    "cm.link_prompt": "Pick the same discussion group that's linked to the channel in Telegram. The bot must already be an admin there.",
    "cm.linked_done": "✅ Group «{title}» linked in the bot. Remember: the «Comment» button only shows up if this same group is linked to the channel via Telegram (Channel settings → Discussion).",
    "cm.err_bot_not_admin": "The bot isn't an admin of that group. Add it as an administrator and try again.",
    "btn.connect_discussion": "👥 Choose discussion group",

    # ---- AI assistant ------------------------------------------------------------------------
    "ai.title": "🤖 <b>AI assistant</b>",
    "ai.help": "Choose what to do with the text of the current message. I'll show the result before applying it.",
    "ai.disabled": "The AI assistant hasn't been set up by the bot owner yet.",
    "ai.quota": "Requests left today: {left}",
    "ai.quota_over": "The daily AI request limit is used up. Try again later.",
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
    "more.ad_label": "🏷 «Ad» label",
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
    "sch.pick": "Choose the publication time or send your own as <b>Hours:Minutes</b>, e.g. <code>14:35</code>.",
    "sch.no_slots": "No free slots left for this day — choose another day, or send your own time as <b>Hours:Minutes</b>.",
    "sch.this_post": "this post",
    "sch.more_slots": "↓ More slots",
    "sch.past": "That time has already passed — choose a later one.",
    "sch.confirm": "Schedule the post for <b>{date}</b> at <b>{time}</b>?\n{channels}\nChannels: {n}",
    "sch.confirm_repeat": "🔁 Auto-repeat will kick in after publishing.",
    "sch.confirm_yes": "✅ Confirm",
    "sch.change": "✏️ Change",
    "sch.done": "✅ Post scheduled for <b>{date}</b> at <b>{time}</b> (channels: {n})\n{channels}",
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
    "pub.result_title": "📬 <b>Publishing result</b>",
    "pub.ok_line": "✅ {title}: <a href=\"{link}\">open post</a>",
    "pub.fail_line": "❌ {title}: {error}",
    "cancel.confirm": "Cancel creating this post? The draft will be deleted.",
    "cancel.yes": "🗑 Yes, delete",
    "cancel.done": "Draft deleted. Main menu 👇",
    "cancel.closed": "Editor closed, changes saved. Main menu 👇",
    "save.title": "💾 <b>Saving changes in channels</b>",
    "save.working": "Saving…",
    "save.ok_line": "✅ {title}: updated",
    "save.media_count": "The number of media changed — Telegram doesn't allow adding or removing media in a published album. Only the text was updated.",
    "save.buttons_album": "Buttons can't be added under a published album without a separate message.",
    "save.parts_added": "New series messages aren't published while editing — publish them as a separate post.",

    # ---- Content plan ------------------------------------------------------------------------
    "plan.title": "🗓 <b>Content plan</b>",
    "plan.tab_scheduled": "🕒 Scheduled",
    "plan.tab_published": "✅ Published",
    "plan.count": "Scheduled posts: {n}. Tap a post to manage it.",
    "plan.empty": "Nothing is scheduled for this day.",
    "plan.count_published": "Published posts: {n}. Tap a post to edit it.",
    "plan.empty_published": "Nothing was published on this day.",
    "plan.new_post": "✍️ Create post",
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
    "proj.disconnect": "🔌 Disconnect",
    "proj.disconnect_confirm": "Disconnect <b>{title}</b>? Scheduled publications to this channel will be cancelled.",
    "proj.disconnect_yes": "🔌 Yes, disconnect",
    "proj.disconnected": "Channel disconnected",

    # ---- Channel administrators -----------------------------------------------------------------
    "admins.manage_btn": "👥 Administrators",
    "admins.list_title": "👥 <b>Administrators of «{title}»</b>",
    "admins.list_empty": "No administrators added yet.",
    "admins.invite_btn": "➕ Invite an administrator",
    "admins.remove_confirm": "Remove {name} from the administrators of «{title}»?",
    "admins.remove_yes": "❌ Yes, remove",
    "admins.removed": "Administrator removed",
    "admins.perm_posts": "📝 Posts (create, edit, publish, schedule)",
    "admins.perm_settings": "⚙️ Channel settings (signature, watermark, AI style)",
    "admins.perm_disconnect": "🔌 Disconnect the channel",
    "admins.new_title": "Choose what to allow the administrator to do in «{title}»:",
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
    "set.sub_trial": "🎁 Free trial until {date} {time}",
    "set.sub_paid": "💎 Subscription active until {date} ({provider}) — {days} days left",
    "set.sub_cancelled": "💎 Subscription valid until {date} ({provider}), auto-renewal off — {days} days left",
    "set.sub_none": "⛔ No active subscription",
    "set.change_lang": "🌐 Змінити мову / Change language",
    "set.change_tz": "🕒 Change time zone",
    "set.manage_sub": "💎 Manage subscription",
    "set.support": "🆘 Support",
    "set.support_text": "🆘 Questions, ideas or problems — write to: {contact}",
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
    "pay.title": "💎 <b>FlowPost subscription</b>",
    "pay.features": (
        "Everything, unlimited:\n"
        "• publishing and scheduled posting\n"
        "• auto-repeat, multiposting, series\n"
        "• AI assistant and posts from screenshots\n"
        "• watermarks on photos and videos"
    ),
    "pay.price": "Price: <b>${usd}/month</b>",
    "pay.card_btn": "💳 Card: {amount} {currency}",
    "pay.liqpay_desc": "FlowPost Pro subscription (monthly)",
    "pay.manual_btn": "🧾 Pay by bank transfer",
    "pay.manual_info": (
        "🧾 <b>Bank transfer</b>\n\n"
        "{requisites}\n\n"
        "After paying, send a <b>screenshot or receipt</b> here — I'll forward it to the owner, "
        "who will activate the subscription manually."
    ),
    "pay.manual_wrong": "Please send a screenshot or a receipt file (photo or document).",
    "pay.manual_sent": "✅ Thanks! The receipt was sent to the owner. Your subscription will be activated manually soon.",
    "pay.manual_admin_caption": (
        "🧾 Payment receipt from {name} (id {tg_id}{username}).\n"
        "Tap to copy the command, paste it into the message field and send:\n"
        "<code>/grant {tg_id} 30</code>"
    ),
    "pay.cancel_btn": "❌ Turn off auto-renewal",
    "pay.cancel_confirm": "Turn off auto-renewal? You keep access until the end of the paid period.",
    "pay.cancel_yes": "❌ Yes, turn off",
    "pay.cancelled": "Auto-renewal is off. Access remains until {date}.",
    "pay.change_failed": "Couldn't change the subscription. Try again later or contact support.",
    "pay.invalid": "This invoice is no longer valid. Open the payment again from the subscription menu.",
    "pay.success": "🎉 Thank you! Your subscription is active until {date}.",
    "pay.failed": "⚠️ The payment didn't go through. Try again or choose another payment method.",
    "pay.support": "🆘 <b>Payment support</b>\n\nIf something went wrong with a payment, write to {contact}: describe the problem and include the payment date.",
    "pay.terms": (
        "📄 <b>FlowPost terms of use</b>\n\n"
        "• Free trial — {days} days.\n"
        "• Then a ${usd}/month subscription with auto-renewal; turn it off any time in settings.\n"
        "• The bot only publishes to channels where you are an admin, and only content you created.\n"
        "• The channel owner is responsible for the content of posts.\n\n"
        "Payment questions — /paysupport"
    ),
    "paywall.text": (
        "⛔ <b>Your free trial has ended</b>\n\n"
        "Publishing, scheduling and AI are available with a FlowPost subscription. Your drafts and settings are saved."
    ),
    "paywall.short": "Subscription required — the free trial has ended.",

    # ---- Notifications -----------------------------------------------------------------------
    "notify.published": "✅ Post published in «{title}»: {link}",
    "notify.failed": "❌ Couldn't publish the post in «{title}»: {error}",
    "notify.missed": "⚠️ The publication in «{title}» was skipped: the bot was unavailable at the scheduled time. Open «Content plan» to reschedule.",
    "notify.paused": "⏸ Scheduled posts are paused: the trial or subscription has ended. Subscribe and they'll continue going out.",
    "notify.trial_ending": "⏳ Your FlowPost trial ends in less than a day. Subscribe to keep posts going out on schedule.",

    # ---- Errors & warnings -------------------------------------------------------------------
    "err.bot_not_admin": "the bot is not an admin of the channel",
    "err.channel_inactive": "the channel is disconnected",
    "err.post_empty": "📭 Nothing's been sent yet — the post is empty. Add some text, a photo, or a video, then try again.",
    "err.pub_missing": "the post or channel was deleted",
    "err.no_access": "no active subscription",
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
    "warn.album_buttons": "Telegram doesn't show buttons under albums — the text and buttons will go in a separate message right after the album.",
    "warn.long_caption": "The text is longer than 1024 characters — media and text will go out as two messages.",
    "warn.text_too_long": "The text with the signature is longer than 4096 characters — please shorten it.",
    "warn.pin_failed": "couldn't pin the post (check the bot's rights)",
    "warn.preview_failed": "Couldn't show the preview: {error}",
    "warn.wm_failed": "couldn't watermark the video — the original was published",
    "warn.wm_no_ffmpeg": "video watermarks are unavailable on the server (ffmpeg missing)",
    "warn.wm_too_big": "the file is larger than 20 MB — published without a watermark",
}
