"""PRO AI moderation of discussion comments: comments that passed the word/link filters wait here and are checked
by AI in batches, so one «ai_mod» check of the channel covers up to `ai_mod_batch` comments."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Pending:
    chat_id: int
    message_id: int
    user_tg_id: int
    text: str
    publication_id: int | None  # the post it was counted as a comment on, if any


@dataclass
class _Batch:
    since: float
    items: list[Pending] = field(default_factory=list)


class Queue:
    """Comments waiting for an AI check, per channel. Kept in memory: a restart only loses a minute of checks."""

    MAX_PER_CHANNEL = 500  # a runaway flood can't grow memory without bound; the extra comments go unchecked

    def __init__(self, batch: int, wait_seconds: float):
        self.batch = batch
        self.wait_seconds = wait_seconds
        self._pending: dict[int, _Batch] = {}

    def add(self, channel_id: int, item: Pending, *, now: float | None = None) -> bool:
        """Queue a comment; True once the channel has a full batch waiting, so it can be checked right away."""
        now = time.monotonic() if now is None else now
        pending = self._pending.setdefault(channel_id, _Batch(since=now))
        if len(pending.items) < self.MAX_PER_CHANNEL:
            pending.items.append(item)
        return len(pending.items) >= self.batch

    def due(self, *, now: float | None = None, flush: bool = False) -> list[tuple[int, list[Pending]]]:
        """Take the batches ready to be checked: full ones, ones whose oldest comment waited long enough, or all."""
        now = time.monotonic() if now is None else now
        ready: list[tuple[int, list[Pending]]] = []
        for channel_id in list(self._pending):
            pending = self._pending[channel_id]
            if flush or now - pending.since >= self.wait_seconds:
                del self._pending[channel_id]
                items = pending.items
            elif len(pending.items) >= self.batch:
                items, pending.items = pending.items[:self.batch], pending.items[self.batch:]
                pending.since = now
            else:
                continue
            ready += [(channel_id, items[i:i + self.batch]) for i in range(0, len(items), self.batch)]
        return ready
