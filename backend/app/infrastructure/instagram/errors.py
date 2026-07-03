"""Exceptions raised by Instagram adapters.

These signal conditions the use case turns into a Result.Err. They are the
boundary between the fragile IG/ToS layer and the rest of the app.
"""

from __future__ import annotations


class InstagramError(Exception):
    """Base for adapter-level failures."""


class PostNotFoundError(InstagramError):
    pass


class ChallengeRequiredError(InstagramError):
    """IG asked for verification (challenge / checkpoint)."""


class LoginRequiredError(InstagramError):
    pass


class RateLimitedError(InstagramError):
    pass


class SendBlockedError(InstagramError):
    """Instagram refused a DM send (feedback_required / spam / action block).

    Signals the campaign sender to stop immediately instead of hammering.
    """


class SendNotSupportedError(InstagramError):
    """This data source can't send DMs (use the Playwright source)."""
