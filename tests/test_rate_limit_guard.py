"""
Tests for the 429 handling shared by the reasoning and TTS services.

Worth testing because none of it fails loudly. When this logic breaks the robot does not crash, it
just stops announcing that it has gone quiet, or starts repeating itself, and the fault only surfaces
the next time a quota actually runs out, which may be weeks later and is hard to reproduce on purpose.
The behaviour is also pure: no hardware, no network, and (via the `clock` fixture) no real waiting.
"""

import pytest

from google_ai_studio.rate_limit_guard import (
    RateLimitGuard,
    is_per_day_quota,
    is_rate_limit,
    parse_retry_delay,
)


class FakeApiError(Exception):
    """Shaped like google.genai.errors.APIError: a status code and a nested details payload."""

    def __init__(self, message: str, code: int = 429, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


def minute_limit_error(retry_delay: str = '27s') -> FakeApiError:
    """A per-minute 429, as the free tier sends it: a quota id plus the wait the server wants."""
    return FakeApiError('429 RESOURCE_EXHAUSTED: quota exceeded', details=[
        {'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
         'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]},
        {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': retry_delay},
    ])


def day_limit_error() -> FakeApiError:
    """A per-day 429. These carry no retryDelay, since the wait would be hours."""
    return FakeApiError('429 RESOURCE_EXHAUSTED: quota exceeded', details=[
        {'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
         'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]},
    ])


def build_guard(name: str = 'tts', min_notice_interval: float = 20) -> RateLimitGuard:
    return RateLimitGuard(
        name=name,
        default_cooldown=60,
        max_cooldown=900,
        backoff_factor=2,
        min_notice_interval=min_notice_interval,
    )


class TestErrorParsing:
    """Reading the two things that matter out of a 429: how long to wait, and which quota it was."""

    def test_retry_delay_read_from_details(self):
        assert parse_retry_delay(minute_limit_error()) == 27.0

    def test_retry_delay_accepts_a_plain_number(self):
        assert parse_retry_delay(FakeApiError('429', details=[{'retryDelay': 12}])) == 12.0

    def test_retry_delay_found_at_any_depth(self):
        # Where RetryInfo sits inside details has moved between google-genai versions, so the payload
        # is searched by key rather than by a fixed path.
        buried = FakeApiError('429', details={'error': {'info': [{'retryDelay': '5s'}]}})
        assert parse_retry_delay(buried) == 5.0

    def test_retry_delay_falls_back_to_the_error_text(self):
        # Last resort for a client version that does not expose details as a structure at all.
        assert parse_retry_delay(FakeApiError("429, 'retryDelay': '42s'")) == 42.0

    def test_retry_delay_absent_reads_as_zero(self):
        # 0.0 means "the server did not say", which the caller replaces with default_cooldown.
        assert parse_retry_delay(day_limit_error()) == 0.0

    def test_per_day_quota_recognised(self):
        assert is_per_day_quota(day_limit_error()) is True

    def test_per_minute_quota_is_not_per_day(self):
        assert is_per_day_quota(minute_limit_error()) is False

    @pytest.mark.parametrize('code, expected', [(429, True), (500, False), (None, False)])
    def test_rate_limit_is_identified_by_status_code(self, code, expected):
        assert is_rate_limit(FakeApiError('boom', code=code)) is expected


class TestPerMinuteLimit:
    """The common case: a short cooldown that clears by itself and is announced at both ends."""

    def test_failure_blocks_the_service_and_announces_it(self, clock):
        guard = build_guard()
        assert guard.available() is True

        assert guard.register_failure(minute_limit_error()) == 'tts_minute_limit'
        assert guard.available() is False
        assert guard.remaining_cooldown() == 27.0

    def test_the_server_retry_delay_wins_over_the_configured_default(self, clock):
        guard = build_guard()
        guard.register_failure(minute_limit_error(retry_delay='90s'))
        assert guard.remaining_cooldown() == 90.0

    def test_the_default_is_used_when_the_error_carries_no_delay(self, clock):
        guard = build_guard()
        guard.register_failure(FakeApiError('429 quota exceeded'))
        assert guard.remaining_cooldown() == 60.0

    def test_recovery_is_announced_once_the_cooldown_runs_out(self, clock):
        guard = build_guard()
        guard.register_failure(minute_limit_error())

        clock.advance(26)
        assert guard.poll_recovery() is None, 'announced while still blocked'

        clock.advance(2)
        assert guard.available() is True
        assert guard.poll_recovery() == 'tts_available'

    def test_recovery_is_announced_only_once(self, clock):
        guard = build_guard()
        guard.register_failure(minute_limit_error())
        clock.advance(30)

        assert guard.poll_recovery() == 'tts_available'
        assert guard.poll_recovery() is None
        # The success that follows must not say it again: the timer already did.
        assert guard.register_success() is None

    def test_a_request_during_the_cooldown_is_told_why(self, clock):
        guard = build_guard()
        guard.register_failure(minute_limit_error())

        clock.advance(21)
        assert guard.notice_while_blocked() == 'tts_minute_limit'


class TestBackoff:
    """A limit that keeps being hit has to back off, or it just keeps failing at a fixed rate."""

    def test_the_wait_doubles_per_consecutive_failure_and_is_capped(self, clock):
        guard = build_guard(min_notice_interval=0)

        waits = []
        for _ in range(7):
            guard.register_failure(minute_limit_error())
            waits.append(guard.remaining_cooldown())
            clock.advance(guard.remaining_cooldown())

        assert waits == [27, 54, 108, 216, 432, 864, 900]

    def test_a_success_resets_the_backoff(self, clock):
        guard = build_guard(min_notice_interval=0)
        for _ in range(3):
            guard.register_failure(minute_limit_error())
            clock.advance(guard.remaining_cooldown())
        assert guard.remaining_cooldown() == 0

        guard.register_success()
        guard.register_failure(minute_limit_error())
        assert guard.remaining_cooldown() == 27.0, 'backoff not reset by the successful call'


class TestPerDayQuota:
    """
    The daily quota is a different situation wearing the same status code.

    Its cooldown is only how long to wait before probing again, so it proves nothing when it expires:
    announcing recovery on that timer would usually be a lie, and announcing the limit itself once per
    cooldown would have the robot repeating the bad news every 15 minutes until midnight.
    """

    def test_it_waits_the_maximum_immediately(self, clock):
        guard = build_guard()
        assert guard.register_failure(day_limit_error()) == 'tts_day_limit'
        assert guard.remaining_cooldown() == 900

    def test_it_is_announced_once_not_once_per_cooldown(self, clock):
        guard = build_guard(min_notice_interval=0)
        guard.register_failure(day_limit_error())

        clock.advance(900)
        assert guard.register_failure(day_limit_error()) is None

    def test_the_timer_never_announces_recovery(self, clock):
        guard = build_guard(min_notice_interval=0)
        guard.register_failure(day_limit_error())

        clock.advance(900)
        assert guard.available() is True, 'a probe should be allowed once the wait is over'
        assert guard.poll_recovery() is None, 'a timer cannot know the daily quota came back'

    def test_recovery_is_announced_when_a_call_finally_succeeds(self, clock):
        guard = build_guard(min_notice_interval=0)
        guard.register_failure(day_limit_error())
        clock.advance(900)

        assert guard.register_success() == 'tts_available'
        assert guard.register_success() is None, 'announced twice'

    def test_the_daily_state_is_cleared_by_a_success(self, clock):
        guard = build_guard(min_notice_interval=0)
        guard.register_failure(day_limit_error())
        clock.advance(900)
        guard.register_success()

        # A new day, a new quota, so the news is worth saying again.
        assert guard.register_failure(day_limit_error()) == 'tts_day_limit'

    def test_a_reminder_reports_the_daily_limit_not_the_per_minute_one(self, clock):
        guard = build_guard()
        guard.register_failure(day_limit_error())

        clock.advance(21)
        assert guard.notice_while_blocked() == 'tts_day_limit'


class TestNoticeThrottling:
    """One clock per guard, so the robot cannot talk over itself when requests arrive in a burst."""

    def test_a_second_notice_is_suppressed_within_the_interval(self, clock):
        guard = build_guard(min_notice_interval=20)
        assert guard.register_failure(minute_limit_error()) == 'tts_minute_limit'

        clock.advance(19)
        assert guard.notice_while_blocked() is None

    def test_the_interval_is_measured_from_the_last_notice_of_any_kind(self, clock):
        guard = build_guard(min_notice_interval=20)
        guard.register_failure(minute_limit_error())

        clock.advance(21)
        assert guard.notice_while_blocked() == 'tts_minute_limit'
        clock.advance(19)
        assert guard.notice_while_blocked() is None
        clock.advance(2)
        assert guard.notice_while_blocked() == 'tts_minute_limit'


class TestNoticeKeys:
    """The keys must match the audio_notices block in configs/service_interface.yaml."""

    @pytest.mark.parametrize('name', ['tts', 'reasoning'])
    def test_notices_are_prefixed_with_the_service_name(self, clock, name):
        guard = build_guard(name=name, min_notice_interval=0)

        assert guard.register_failure(minute_limit_error()) == f'{name}_minute_limit'
        clock.advance(30)
        assert guard.poll_recovery() == f'{name}_available'
        assert guard.register_failure(day_limit_error()) == f'{name}_day_limit'

    def test_a_guard_that_never_failed_says_nothing(self, clock):
        guard = build_guard()
        assert guard.poll_recovery() is None
        assert guard.register_success() is None
