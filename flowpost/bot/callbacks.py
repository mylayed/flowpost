from aiogram.filters.callback_data import CallbackData


class Ed(CallbackData, prefix="ed"):
    """Post editor. `p` — post id, `a` — action, `v` — value."""

    a: str
    p: int
    v: str = ""


class Cs(CallbackData, prefix="cs"):
    """Channel settings (watermark, signature, AI style, topic). `p` — post id to return to (0 = projects)."""

    a: str
    c: int
    p: int = 0
    v: str = ""


class Nc(CallbackData, prefix="nc"):
    """Choose a channel for a new post."""

    c: int
    p: int = 0


class Cp(CallbackData, prefix="cp"):
    """Content plan. `d` — date ordinal, `id` — post id, `m` — tab: s(cheduled)|p(ublished), `c` — channel filter (0 = all)."""

    a: str
    d: int = 0
    id: int = 0
    m: str = "s"
    c: int = 0


class Pj(CallbackData, prefix="pj"):
    """Projects (connected channels)."""

    a: str
    c: int = 0


class St(CallbackData, prefix="st"):
    """User settings."""

    a: str
    v: str = ""


class Bl(CallbackData, prefix="bl"):
    """Billing."""

    a: str


class Ep(CallbackData, prefix="ep"):
    """Editing already-published or scheduled posts. `c` — channel filter (0 = all/not chosen yet)."""

    a: str
    id: int = 0
    c: int = 0


class Ca(CallbackData, prefix="ca"):
    """Channel administrators. `c` — channel id, `id` — admin grant id, `v` — permission bits "posts,settings,disconnect"."""

    a: str
    c: int = 0
    id: int = 0
    v: str = ""
