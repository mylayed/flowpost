"""Posting plans catalog shown on the Tariffs screen: per-channel prices, trial/free allowances, discounts."""
from __future__ import annotations

import math

from flowpost.config import Settings


def channel_discount(settings: Settings, channels: int) -> int:
    return max((pct for count, pct in settings.channel_discounts.items() if channels >= count), default=0)


def quote(
    settings: Settings, posts_per_day: int, days: int, channels: int, round_to_pack: bool = False
) -> tuple[int, int] | None:
    """(Stars to pay, days granted per channel) for a subscription, or None if the plan or term isn't on sale."""
    plan = settings.posting_plans.get(posts_per_day)
    if plan is None or days not in settings.term_discounts or channels < 1:
        return None
    pct = channel_discount(settings, channels) + settings.term_discounts[days]
    stars = math.ceil(plan["stars"] * channels * days * (100 - pct) / 3000)
    if not round_to_pack:
        return stars, days
    pack = next((size for size in sorted(settings.stars_packs) if size > stars), None)
    # Paying a whole Stars pack buys proportionally more days at the same rate.
    extended = days * pack // stars if pack else days
    if extended <= days:
        return None
    return pack, extended


def catalog(settings: Settings) -> dict:
    return {
        "posting": [
            {
                "posts_per_day": posts,
                "stars": plan["stars"],
                "wm_photo": plan.get("wm_photo", 0),
                "wm_video": plan.get("wm_video", 0),
                "ai_text": plan.get("ai_text", 0),
            }
            for posts, plan in sorted(settings.posting_plans.items())
        ],
        "trial": {"days": settings.trial_days, "posts": settings.trial_posts, "quotas": settings.trial_quotas},
        "free_posts_per_day": settings.free_posts_per_day,
        "channel_discounts": sorted(settings.channel_discounts.items()),
        "term_discounts": sorted(settings.term_discounts.items()),
        "max_channels": settings.calc_max_channels,
        "stars_packs": sorted(settings.stars_packs),
    }
