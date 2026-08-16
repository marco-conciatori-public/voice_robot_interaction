"""
Shared 429 handling for the Gemini services.

Both the reasoning model and the TTS model are called on the free tier, where a 429 is usually the
per-minute rate limit rather than a real outage: it clears by itself within tens of seconds. Neither
service should therefore be switched off for the rest of the run because one call was refused. What
they do instead is go quiet for a cooldown, tell the user once, and pick up again afterwards, which is
all this module implements.

One guard per service (they hit different models with different quotas, so their cooldowns are
independent). The guard decides *when* to speak and returns the key of the clip to play; it never
touches the speakers itself, since that needs the queue the caller owns.

The two kinds of 429 are treated differently on the way out:
  - per-minute: the cooldown is roughly how long the limit lasts, so the guard announces recovery when
    it runs out, without anyone having to try again to find out (see poll_recovery).
  - per-day: the cooldown is only a retry interval, and expiring says nothing about the quota, so
    nothing is announced until a call actually goes through again (see register_success).
"""

import re
import time
import threading

# Matches the wait the API asks for in the string form of a 429, e.g. "'retryDelay': '27s'".
_RETRY_DELAY_PATTERN = re.compile(r'retry[_-]?delay["\']?\s*[:=]\s*["\']?(\d+(?:\.\d+)?)s', re.IGNORECASE)

# Suffixes of the notice keys returned to the caller. A guard prefixes them with its own name, so the
# 'tts' guard asks for 'tts_minute_limit' and the 'reasoning' guard for 'reasoning_minute_limit', which
# are the keys of the audio_notices block in configs/service_interface.yaml.
MINUTE_LIMIT = 'minute_limit'
DAY_LIMIT = 'day_limit'
AVAILABLE = 'available'


def is_rate_limit(exception) -> bool:
    """Whether an exception is the API refusing the call because of a quota, rather than a real failure."""
    return getattr(exception, 'code', None) == 429


def find_error_values(payload, wanted_key: str) -> list:
    """Every value stored under `wanted_key` at any depth of a nested dict/list error payload."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == wanted_key:
                found.append(value)
            else:
                found.extend(find_error_values(value, wanted_key))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found.extend(find_error_values(item, wanted_key))
    return found


def parse_retry_delay(exception) -> float:
    """
    The wait the API asked for after a 429, in seconds, or 0.0 when the error does not carry one.

    A Gemini 429 body normally includes a google.rpc.RetryInfo entry ('retryDelay': '27s'), and the
    server knows better than any value hardcoded here. Where exactly that entry sits inside
    APIError.details has moved between google-genai versions, so the payload is searched by key at any
    depth, with the string form of the exception as a last resort, rather than depending on one layout.
    """
    for value in find_error_values(getattr(exception, 'details', None), 'retryDelay'):
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)s?', value.strip())
            if match:
                return float(match.group(1))
    match = _RETRY_DELAY_PATTERN.search(str(exception))
    if match:
        return float(match.group(1))
    return 0.0


def is_per_day_quota(exception) -> bool:
    """
    Whether a 429 is the daily quota rather than the per-minute rate limit.

    Free-tier quota violations name themselves, e.g. 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'
    against '...PerMinutePerProjectPerModel-FreeTier'. A daily one will not clear within any sensible
    cooldown, so the caller waits the maximum instead of retrying every minute for the rest of the day.
    """
    quota_ids = find_error_values(getattr(exception, 'details', None), 'quotaId')
    if any('perday' in str(quota_id).lower() for quota_id in quota_ids):
        return True
    return 'perday' in str(exception).lower()


class RateLimitGuard:
    """
    Tracks one service's 429s and says when it may be called again, and what to tell the user.

    Every method that changes state also returns the notice the caller should play, or None when this
    situation does not deserve one, so a caller that plays whatever it is handed cannot end up either
    silent or repeating itself.
    """

    def __init__(self,
                 name: str,
                 default_cooldown: float,
                 max_cooldown: float,
                 backoff_factor: float,
                 min_notice_interval: float,
                 ):
        """
        :param name: str: Prefix of the notice keys this guard returns ('tts' / 'reasoning').
        :param default_cooldown: float: Wait in seconds used when a 429 carries no retryDelay.
        :param max_cooldown: float: Ceiling for the wait, and the wait used for a per-day quota.
        :param backoff_factor: float: The wait is multiplied by this once per consecutive failure.
        :param min_notice_interval: float: Minimum gap in seconds between two notices from this guard.
        """
        self.name = name
        self.default_cooldown = default_cooldown
        self.max_cooldown = max_cooldown
        self.backoff_factor = backoff_factor
        self.min_notice_interval = min_notice_interval

        self._blocked_until = 0.0
        self._failure_count = 0
        self._day_limited = False
        # Set when the service goes quiet, cleared by whoever announces that it is back, so the two
        # routes into that announcement (the cooldown expiring, or a later call succeeding) cannot both
        # take it.
        self._recovery_owed = False
        self._last_notice = 0.0
        # The tts guard is written by the TTS thread and read by the reasoning thread, so the read-then-
        # write sequences below are not left to chance. There is no contention worth measuring: these
        # methods run once per request, not once per audio frame.
        self._lock = threading.Lock()

    def available(self) -> bool:
        """Whether a call may be attempted right now, i.e. no cooldown is running."""
        return time.time() >= self._blocked_until

    def remaining_cooldown(self) -> float:
        """Seconds left before calls are attempted again, 0.0 when the service is available."""
        return max(0.0, self._blocked_until - time.time())

    def register_failure(self, exception) -> str:
        """
        Record a 429 and start a cooldown, returning the notice key to play (or None to stay quiet).

        The base wait is the retryDelay the server asked for, or the configured default when the error
        carries none. It is then multiplied by backoff_factor once per consecutive failure and capped at
        max_cooldown, so a limit that keeps being hit backs off instead of retrying at a fixed rate
        forever. A 429 naming a per-day quota waits the maximum straight away, since it will not clear
        before then, and is announced only the first time: the cooldown expires long before the quota
        resets, so announcing it once per cooldown would have the robot repeating itself until midnight.
        The failure count is cleared by the first call that succeeds (see register_success).
        """
        with self._lock:
            self._failure_count += 1
            day_limited = is_per_day_quota(exception)
            if day_limited:
                cooldown = self.max_cooldown
            else:
                base_cooldown = parse_retry_delay(exception) or self.default_cooldown
                cooldown = base_cooldown * (self.backoff_factor ** (self._failure_count - 1))
            self._blocked_until = time.time() + min(cooldown, self.max_cooldown)
            self._recovery_owed = True

            was_day_limited = self._day_limited
            self._day_limited = day_limited
            if not day_limited:
                return self._notice(MINUTE_LIMIT)
            if was_day_limited:
                return None
            self._last_notice = time.time()
            return self._key(DAY_LIMIT)

    def register_success(self) -> str:
        """
        Record a call that went through, returning the 'available again' notice if one is still owed.

        Normally None: a per-minute cooldown has already been announced by poll_recovery when it ran
        out. It speaks up after a per-day quota, where nothing was announced because the cooldown
        expiring proved nothing, and this success is the first hard evidence that the quota is back.
        """
        with self._lock:
            self._failure_count = 0
            self._day_limited = False
            self._blocked_until = 0.0
            if not self._recovery_owed:
                return None
            self._recovery_owed = False
            self._last_notice = time.time()
            return self._key(AVAILABLE)

    def poll_recovery(self) -> str:
        """
        The 'available again' notice, once, when a per-minute cooldown has just run out.

        Called from the service's idle loop so the news does not have to wait for the next request. That
        matters because of what the user is left with meanwhile: they were told the service would signal
        when it came back, and the alternative (announcing on the next successful call) would arrive
        together with the answer that already proves it, having made them guess when to ask.

        Deliberately silent while the daily quota is the limit. There the cooldown is only how long to
        wait before probing again, and claiming the service is back on the strength of a timer that
        knows nothing about the quota would usually be a lie.
        """
        with self._lock:
            if not self._recovery_owed or self._day_limited:
                return None
            if time.time() < self._blocked_until:
                return None
            self._recovery_owed = False
            self._last_notice = time.time()
            return self._key(AVAILABLE)

    def notice_while_blocked(self) -> str:
        """
        The notice to repeat for a request that arrived during a cooldown, or None if one just played.

        The request itself is lost either way, but the user has just spoken and would otherwise get no
        reaction at all, which is indistinguishable from a robot that has stopped working.
        """
        with self._lock:
            return self._notice(DAY_LIMIT if self._day_limited else MINUTE_LIMIT)

    def _notice(self, suffix: str) -> str:
        """The notice key for `suffix`, or None when the previous notice is still too recent."""
        now = time.time()
        if now - self._last_notice < self.min_notice_interval:
            return None
        self._last_notice = now
        return self._key(suffix)

    def _key(self, suffix: str) -> str:
        return f'{self.name}_{suffix}'
