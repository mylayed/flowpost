from aiogram.fsm.state import State, StatesGroup


class Editor(StatesGroup):
    content = State()        # main editor: new media/text replaces the current part
    add_media = State()      # "Медіа → Додати"
    album = State()          # "Альбом": a sent file replaces the selected album item
    album_wm = State()       # "Альбом → Водяний знак → Свій знак": text or logo for one item or all of them
    buttons = State()        # waiting for "Текст — посилання" lines
    ai_custom = State()      # free-form AI instruction
    ai_image = State()       # screenshot for AI vision
    schedule = State()       # schedule screen: date/slot picker; also accepts typed "ГГ:ХХ" directly
    repeat_hours = State()   # custom auto-repeat interval
    delete_hours = State()   # custom auto-delete delay
    pin_hours = State()      # custom pin duration
    confirm = State()        # yes/no confirmation screen: text input is ignored, only buttons act
    hidden_text = State()    # «Прихований текст» for subscribers only


class ChannelInput(StatesGroup):
    signature = State()
    wm_text = State()
    wm_image = State()
    ai_style = State()
    topic = State()
    discussion_group = State()
    banned_words = State()


class SettingsInput(StatesGroup):
    tz = State()
    support = State()


class FolderInput(StatesGroup):
    title = State()      # name for a folder being created
    customize = State()  # folder settings screen: a sent message is a new name or a new icon


class EditPublished(StatesGroup):
    waiting_forward = State()


class ProInput(StatesGroup):
    link_name = State()   # name of a new tracked invite link
    link_cost = State()   # what the ad behind a tracked link cost
    welcome = State()     # welcome message for people who ask to join
    feed_url = State()    # address of a new RSS source


class BroadcastInput(StatesGroup):
    message = State()  # the owner's message to send to every admin
