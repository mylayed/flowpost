"""Posting plans catalog shown on the Tariffs screen: per-channel prices, trial/free allowances, discounts."""
from __future__ import annotations

from flowpost.config import Settings


def catalog(settings: Settings) -> dict:
    return {
        "posting": [
            {
                "posts_per_day": posts,
                "stars": plan["stars"],
                "wm_photo": plan.get("wm_photo", 0),
                "wm_video": plan.get("wm_video", 0),
            }
            for posts, plan in sorted(settings.posting_plans.items())
        ],
        "trial": {"days": settings.trial_days, "posts": settings.trial_posts, "quotas": settings.trial_quotas},
        "free_posts_per_day": settings.free_posts_per_day,
        "channel_discounts": sorted(settings.channel_discounts.items()),
        "term_discounts": sorted(settings.term_discounts.items()),
        "max_channels": settings.calc_max_channels,
    }
