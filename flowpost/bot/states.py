from aiogram.fsm.state import State, StatesGroup


class Editor(StatesGroup):
    content = State()        # main editor: new media/text replaces the current part
    add_media = State()      # "Медіа → Додати"
    buttons = State()        # waiting for "Текст — посилання" lines
    ai_custom = State()      # free-form AI instruction
    ai_image = State()       # screenshot for AI vision
    schedule = State()       # schedule screen: date/slot picker; also accepts typed "ГГ:ХХ" directly
    repeat_hours = State()   # custom auto-repeat interval
    delete_hours = State()   # custom auto-delete delay
    pin_hours = State()      # custom pin duration


class ChannelInput(StatesGroup):
    signature = State()
    wm_text = State()
    wm_image = State()
    ai_style = State()
    topic = State()


class SettingsInput(StatesGroup):
    tz = State()


class EditPublished(StatesGroup):
    waiting_forward = State()
