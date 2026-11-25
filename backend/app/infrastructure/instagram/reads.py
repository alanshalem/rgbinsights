"""Reads for the instagrapi adapter: posts, comments, likers, profiles and our
follow graph.

Every request here is exactly the one instagrapi itself sends for that read
(same endpoint, params, method and page size, pinned by test_request_shape);
only the decision to stop paging is ours. Each method gets the logged-in
client; the facade runs it as one guarded operation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.domain.entities import Comment, FollowGraph, IgUser, Post, ProfileInfo
from app.domain.errors import InstagramError, PostNotFoundError
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.error_mapping import session_error_types
from app.infrastructure.instagram.mapping import as_dt, raw_user_pk, to_post, to_user, utc

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

# Users per followers page: instagrapi's MAX_USER_COUNT.
_FOLLOW_PAGE_SIZE = 200


class IgReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # media pk -> full media id ("<pk>_<owner pk>"), learned from posts we
        # already fetched. instagrapi needs the full id for comments/likers and
        # spends one extra media lookup per call to find it when it only has the pk.
        self._media_ids: dict[str, str] = {}

    # -- follow graph ----------------------------------------------------------

    def follow_graph(self, client: Client, known: FollowGraph | None) -> FollowGraph:
        # friendships/show_many only reports who WE follow (no `followed_by`), so
        # to know "te sigue" we read our own followers/following lists. Followers
        # are paged newest-first; with `known` the read stops at the first page
        # made only of people we already know and returns just the new ones.
        # Following has no guaranteed order, so it is always read whole, with
        # exactly the call the app made before (instagrapi's user_following).
        our_id = str(client.user_id)
        cap = self._settings.relationship_fetch_max
        followers, saw_followers = self._read_followers(
            client, our_id, known.followers if known else None
        )
        following = {str(pk) for pk in client.user_following(our_id, amount=cap)}
        saw_following = bool(following)
        logger.info(
            "read graph (%s): %d followers, %d following",
            "incremental" if known else "full",
            len(followers),
            len(following),
        )
        # A logged-in account always has some followers/following. Nobody at all
        # means the read was blocked — refuse rather than overwrite good "te
        # sigue" data with all-False.
        if not saw_followers and not saw_following:
            raise InstagramError("no se pudo leer seguidores/seguidos (bloqueado?)")
        return FollowGraph(followers=followers, following=following)

    def _read_followers(
        self, client: Client, user_id: str, known: set[str] | None
    ) -> tuple[set[str], bool]:
        """Our followers, newest first, one request per page.

        Each request is exactly the one instagrapi's
        user_followers_v1_chunk(user_id, relationship_fetch_max,
        order="date_followed_latest") sends (same params, order, page size and
        shrinking last-page count); only the decision to stop is ours. Full read
        (`known` is None): every page up to the cap. Incremental: the pks not in
        `known`, stopping after the first page that brings nobody new. Also
        returns whether IG listed anyone.
        """
        cap = self._settings.relationship_fetch_max
        listed: set[str] = set()  # instagrapi's `unique_set`: drives count and cap
        found: set[str] = set()
        max_id = ""
        while True:
            count = min(cap - len(listed), _FOLLOW_PAGE_SIZE) if cap else _FOLLOW_PAGE_SIZE
            params: dict[str, Any] = {
                "count": count,
                "rank_token": client.rank_token,
                "search_surface": "follow_list_page",
                "query": "",
                "enable_groups": "true",
                "order": "date_followed_latest",
            }
            if max_id:
                params["max_id"] = max_id
            result = client.private_request(f"friendships/{user_id}/followers/", params=params)
            if result.get("should_limit_list_of_followers"):
                # IG truncates this list: read it whole the way instagrapi falls back.
                everyone = {str(u.pk) for u in client.user_followers_private_gql(user_id, cap)}
                return (everyone if known is None else everyone - known), bool(everyone)
            page = {pk for u in result.get("users") or [] if (pk := raw_user_pk(u))}
            new = (page if known is None else page - known) - listed
            listed |= page
            found |= new
            max_id = result.get("next_max_id") or ""
            if not max_id or (cap and len(listed) >= cap) or (known is not None and not new):
                return found, bool(listed)

    # -- profiles and posts ----------------------------------------------------

    def profile(self, client: Client, username: str) -> ProfileInfo:
        u = client.user_info_by_username(username)
        return ProfileInfo(
            pk=str(u.pk),
            username=u.username,
            full_name=u.full_name or "",
            follower_count=u.follower_count,
            is_verified=bool(u.is_verified),
            is_business=bool(getattr(u, "is_business", False)),
            biography=u.biography or "",
            is_private=bool(u.is_private),
            profile_pic_url=str(u.profile_pic_url) if u.profile_pic_url else None,
        )

    def post(self, client: Client, url: str) -> Post:
        from instagrapi.exceptions import ClientError, MediaNotFound

        try:
            media_pk = client.media_pk_from_url(url)
            media = client.media_info(media_pk)
        except MediaNotFound as exc:
            raise PostNotFoundError(url) from exc
        except session_error_types():
            raise  # a dead session is not a missing post; the facade classifies it
        except ClientError as exc:
            raise PostNotFoundError(url) from exc
        return self._post(media)

    def recent_posts(self, client: Client, limit: int) -> list[Post]:
        medias = client.user_medias(client.user_id, amount=limit)
        return [self._post(m) for m in medias]

    def _post(self, media: Any) -> Post:
        """Map a fetched media, remembering its full id for comments/likers."""
        full_id = str(getattr(media, "id", "") or "")
        if "_" in full_id:
            self._media_ids[str(media.pk)] = full_id
        return to_post(media)

    def _media_id(self, client: Client, media_pk: str) -> str:
        """Full media id for a pk: known from a fetched post, else resolved once
        (one media lookup) and remembered for the rest of the scan."""
        media_pk = str(media_pk)
        if "_" in media_pk:
            return media_pk
        if (full_id := self._media_ids.get(media_pk)) is None:
            full_id = self._media_ids[media_pk] = str(client.media_id(media_pk))
        return full_id

    # -- engagement ------------------------------------------------------------

    def likers(self, client: Client, media_pk: str) -> list[IgUser]:
        return [to_user(u) for u in client.media_likers(self._media_id(client, media_pk))]

    def comments(self, client: Client, media_pk: str, since: datetime | None) -> list[Comment]:
        """Comments, newest page first (media/<id>/comments/, as media_comments).

        Every request is exactly what instagrapi's media_comments sends: the
        first page with no arguments, then the cursor passed positionally (so
        instagrapi signs it as a POST body). Only the decision to stop is ours:
        at scan_comments_limit (without a cap a viral post means hundreds of
        requests) or, with `since` (the newest comment already stored), after the
        first older page in which EVERY comment is at or before `since` — the
        order is not strictly by date (pinned/ranked comments), so one old comment
        on a page proves nothing. Comments at or after `since` are returned.
        """
        endpoint = f"media/{self._media_id(client, media_pk)}/comments/"
        cap = self._settings.scan_comments_limit
        comments: list[Comment] = []
        result = client.private_request(endpoint, None)
        all_known = _take_comments(result, since, comments)
        while (result.get("has_more_comments") and result.get("next_max_id")) or (
            result.get("has_more_headload_comments") and result.get("next_min_id")
        ):
            if cap and len(comments) >= cap:
                break
            if result.get("has_more_comments"):
                if all_known:
                    break  # older pages only hold what we already stored
                params = {"max_id": result.get("next_max_id")}
            else:
                params = {"min_id": result.get("next_min_id")}
            if not (
                result.get("next_max_id") or result.get("next_min_id") or result.get("comments")
            ):
                break
            result = client.private_request(endpoint, params)
            all_known = _take_comments(result, since, comments)
        return comments[:cap] if cap else comments


def _take_comments(result: Any, since: datetime | None, into: list[Comment]) -> bool:
    """Add a comments page's entries at/after `since` to `into`; True if every
    comment on the page is at or before `since` (all already stored)."""
    from instagrapi.extractors import extract_comment

    all_known = True
    for raw in result.get("comments") or []:
        c = extract_comment(raw)
        created = as_dt(getattr(c, "created_at_utc", None))
        known = since is not None and created is not None and utc(created) <= since
        all_known = all_known and known
        if since is None or created is None or utc(created) >= since:
            into.append(Comment(user=to_user(c.user), text=c.text, created_at=created))
    return since is not None and all_known
