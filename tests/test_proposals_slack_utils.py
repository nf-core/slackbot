"""Tests for proposal-review Slack helpers — the progress reporter's throttling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from nf_core_bot.proposals import slack_utils


class TestProgressReporter:
    async def test_first_round_always_posts(self) -> None:
        post = AsyncMock()
        report = slack_utils.make_progress_reporter(post)
        await report(1, "gh repo view")
        post.assert_awaited_once()
        assert "1 check" in post.await_args.args[0]

    async def test_throttles_within_interval(self) -> None:
        post = AsyncMock()
        with patch.object(slack_utils.time, "monotonic", side_effect=[0.0, 1.0]):
            report = slack_utils.make_progress_reporter(post, min_interval=25.0)
            await report(1)  # forced — first round
            await report(2)  # only 1s later → suppressed
        post.assert_awaited_once()

    async def test_posts_again_after_interval(self) -> None:
        post = AsyncMock()
        with patch.object(slack_utils.time, "monotonic", side_effect=[0.0, 30.0]):
            report = slack_utils.make_progress_reporter(post, min_interval=25.0)
            await report(1)
            await report(5)  # >25s later → posts again
        assert post.await_count == 2

    async def test_max_posts_cap(self) -> None:
        post = AsyncMock()
        with patch.object(slack_utils.time, "monotonic", side_effect=[0.0, 100.0, 200.0]):
            report = slack_utils.make_progress_reporter(post, min_interval=0.0, max_posts=2)
            await report(1)
            await report(2)
            await report(3)  # cap reached → suppressed
        assert post.await_count == 2

    async def test_final_signal_forced_past_cap(self) -> None:
        # round -1 ("composing") always posts, even once the cap is hit.
        post = AsyncMock()
        with patch.object(slack_utils.time, "monotonic", side_effect=[0.0, 0.1]):
            report = slack_utils.make_progress_reporter(post, min_interval=999.0, max_posts=1)
            await report(1)
            await report(-1)
        assert post.await_count == 2
        assert "writing the review" in post.await_args_list[-1].args[0]

    async def test_swallows_post_errors(self) -> None:
        # A failed status update must never take down the review itself.
        post = AsyncMock(side_effect=RuntimeError("slack down"))
        report = slack_utils.make_progress_reporter(post)
        await report(1)  # must not raise
