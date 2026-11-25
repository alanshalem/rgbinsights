"""Instagram failures, as the domain knows them.

Every InstagramSource adapter raises only these (it converts the library's own
exceptions at its boundary); use cases turn them into a Result.Err and the
campaign sender decides from their type whether to stop, pause, wait or skip.
Messages are Spanish: the UI shows them as is.
"""

from __future__ import annotations

from datetime import datetime


class InstagramError(Exception):
    """Base for every Instagram failure."""


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
    """A safety rail stopped the call: request budget spent, Instagram asked us
    to slow down (cooldown), or another rail is open. Nothing was sent."""


class BudgetExhaustedError(RateLimitedError):
    """Our own hourly/daily request budget is spent — not an Instagram push-back.

    Nothing is wrong with the account: work may simply resume at `retry_at`
    (the campaign sender waits for it instead of pausing).
    """

    def __init__(self, message: str, *, retry_at: datetime) -> None:
        super().__init__(message)
        self.retry_at = retry_at


class IgBusyError(RateLimitedError):
    """Another Instagram operation held the process-wide lock for too long.

    Not a problem with the account: the caller may simply retry later (the
    campaign sender waits and retries the same target).
    """


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
