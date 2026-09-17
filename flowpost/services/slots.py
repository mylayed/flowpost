"""Date formatting and time-slot generation for the scheduling screen."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "uk": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MONTHS = {
    "uk": ["січ", "лют", "бер", "кві", "тра", "чер", "лип", "сер", "вер", "жов", "лис", "гру"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

MONTHS_FULL = {
    "uk": ["січня", "лютого", "березня", "квітня", "травня", "червня",
           "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}

SLOT_STEP_MINUTES = 5
SLOTS_PER_PAGE = 12
DAY_START = time(9, 0)


def fmt_date(d: date, lang: str) -> str:
    """'пт, 11 вер' / 'Fri, 11 Sep'."""
    lang = lang if lang in WEEKDAYS else "uk"
    return f"{WEEKDAYS[lang][d.weekday()]}, {d.day} {MONTHS[lang][d.month - 1]}"


def fmt_hm(t: time | datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def fmt_when_full(d: date, t: time, lang: str) -> str:
    """'пт 18 вересня 2026, 15:00' / 'Fri 18 September 2026, 15:00'."""
    lang = lang if lang in WEEKDAYS else "uk"
    return f"{WEEKDAYS[lang][d.weekday()]} {d.day} {MONTHS_FULL[lang][d.month - 1]} {d.year}, {fmt_hm(t)}"


def tz_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Kyiv")
    except Exception:  # noqa: BLE001 - unknown zone name
        return ZoneInfo("Europe/Kyiv")


def local_now(tz_name: str) -> datetime:
    return datetime.now(timezone.utc).astimezone(tz_of(tz_name))


def to_utc(day: date, t: time, tz_name: str) -> datetime:
    return datetime.combine(day, t, tzinfo=tz_of(tz_name)).astimezone(timezone.utc)


def day_bounds_utc(day: date, tz_name: str) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=tz_of(tz_name))
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _ceil_to_step(dt: datetime, step: int) -> datetime:
    dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    remainder = dt.minute % step
    if remainder:
        dt += timedelta(minutes=step - remainder)
    return dt


def generate_slots(
    day: date,
    now_local: datetime,
    page: int = 0,
    step: int = SLOT_STEP_MINUTES,
    per_page: int = SLOTS_PER_PAGE,
) -> tuple[list[time], bool]:
    """Return a page of future time slots for `day` and whether more pages exist."""
    if day < now_local.date():
        return [], False
    if day == now_local.date():
        first = _ceil_to_step(now_local, step)
        if first.date() != day:
            return [], False
        start_minutes = first.hour * 60 + first.minute
    else:
        start_minutes = DAY_START.hour * 60 + DAY_START.minute
    all_minutes = list(range(start_minutes, 24 * 60, step))
    chunk = all_minutes[page * per_page:(page + 1) * per_page]
    has_more = len(all_minutes) > (page + 1) * per_page
    return [time(m // 60, m % 60) for m in chunk], has_more


def is_future(day: date, t: time, tz_name: str, now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    return to_utc(day, t, tz_name) > now_utc
