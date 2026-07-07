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


class IpBlockedError(InstagramError):
    """Instagram flagged the IP/proxy (not the session/credentials).

    A new sessionid won't help — the fix is a different network. Kept distinct
    from LoginRequiredError so the UI can say so plainly.
    """


class RateLimitedError(InstagramError):
    pass


class SendBlockedError(InstagramError):
    """Instagram refused a DM send (feedback_required / spam / action block).

    Signals the campaign sender to stop immediately instead of hammering.
    """


class RecipientUnavailableError(InstagramError):
    """This recipient can't receive the DM (they disabled message requests).

    A per-target condition — the account is fine, so the campaign skips this one
    and keeps going instead of stopping.
    """


class SendRetryableError(InstagramError):
    """A transient send failure (network/timeout/bad input), NOT an IG block.

    The campaign marks the target failed and continues — it must never be
    mistaken for an action-block that stops everything.
    """


class SendNotSupportedError(InstagramError):
    """This data source can't send DMs (only the instagrapi source can)."""
