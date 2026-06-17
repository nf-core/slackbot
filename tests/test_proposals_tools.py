"""Tests for the read-only research command tool (security-critical)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nf_core_bot.proposals import tools
from nf_core_bot.proposals.tools import DisallowedCommandError, validate_command

# ── Allowlist: accepted commands ─────────────────────────────────────


class TestAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            "gh issue view 148 --repo nf-core/proposals",
            "gh issue list --repo nf-core/proposals --label new-pipeline --state open",
            "gh search code --repo nf-core/modules fastqc --limit 5",
            "gh search issues spatial --repo nf-core/proposals",
            "gh repo view nf-core/sarek",
            "nf-core modules info fastqc",
            "nf-core modules list remote",
            "nf-core subworkflows list remote",
            "nf-core subworkflows info bam_sort_stats_samtools",
            "nf-core pipelines list",
            "nf-core list",
            "jq -n '1 + 1'",
            "gh repo list nf-core --limit 300 --json name,description | jq -r '.[].name'",
        ],
    )
    def test_accepts(self, command: str) -> None:
        segments = validate_command(command)
        assert segments and all(seg for seg in segments)


# ── Allowlist: rejected commands ─────────────────────────────────────


class TestRejected:
    @pytest.mark.parametrize(
        "command",
        [
            # wrong binary
            "rm -rf /",
            "curl https://evil.example.com",
            "echo hello",
            "bash -c 'rm -rf /'",
            "python -c 'print(1)'",
            # gh write operations
            "gh issue comment 148 --body 'hi'",
            "gh issue edit 148 --add-label accepted",
            "gh issue create --title x",
            "gh pr create --title x",
            "gh pr merge 1",
            "gh repo clone nf-core/sarek",
            "gh repo delete nf-core/x",
            "gh secret set FOO",
            "gh auth token",
            # gh api is disallowed entirely (SSRF: it accepts absolute URLs)
            "gh api repos/nf-core/proposals/issues/148/comments",
            "gh api repos/nf-core/proposals --method GET",
            "gh api http://169.254.170.2/v2/credentials",
            "gh api repos/x -f body=hi",
            # --hostname would redirect gh to an arbitrary host (SSRF)
            "gh repo list nf-core --hostname 169.254.169.254",
            "gh issue view 1 --hostname evil.internal --repo nf-core/proposals",
            # nf-core write/other operations
            "nf-core modules create",
            "nf-core modules install fastqc",
            "nf-core pipelines create",
            "nf-core download rnaseq",
            "nf-core lint",
            # shell operators / injection attempts
            "gh issue view 1 && rm -rf /",
            "gh issue view 1 ; rm -rf /",
            "gh repo list nf-core > /etc/passwd",
            "gh repo list nf-core | rm -rf /",
            "jq -n `whoami`",
            "gh issue view $(whoami)",
        ],
    )
    def test_rejects(self, command: str) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command(command)

    def test_empty(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command("   ")

    def test_unbalanced_quotes(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command("gh issue view 'unterminated")


# ── Bundled scripts via bash ─────────────────────────────────────────


class TestBundledScripts:
    def test_accepts_bundled_scripts(self) -> None:
        for name in tools._ALLOWED_SCRIPTS:
            cmd = f"bash {tools._SCRIPTS_DIR}/{name} fastp star"
            assert validate_command(cmd)

    def test_rejects_bash_c(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command("bash -c 'rm -rf /'")

    def test_rejects_arbitrary_script(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command("bash /tmp/evil.sh")

    def test_rejects_unknown_script_in_scripts_dir(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command(f"bash {tools._SCRIPTS_DIR}/evil.sh")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(DisallowedCommandError):
            validate_command(f"bash {tools._SCRIPTS_DIR}/../../../etc/passwd")


# ── Environment scrubbing ────────────────────────────────────────────


class TestEnvScrubbing:
    def test_jq_gets_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
        env = tools._env_for("jq")
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env
        assert "SLACK_BOT_TOKEN" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_gh_gets_token_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-secret")
        env = tools._env_for("gh")
        assert env["GH_TOKEN"] == "ghp_secret"
        assert "SLACK_BOT_TOKEN" not in env

    def test_proposals_token_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_broad")
        monkeypatch.setenv("PROPOSALS_GITHUB_TOKEN", "ghp_readonly")
        env = tools._env_for("gh")
        assert env["GH_TOKEN"] == "ghp_readonly"


# ── run_command behaviour ────────────────────────────────────────────


class TestRunCommand:
    async def test_rejected_returns_error_string(self) -> None:
        out = await tools.run_command("rm -rf /")
        assert out.startswith("ERROR: command rejected")

    async def test_successful_exec(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"fastqc module exists\n", b"")
        proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            spawn.return_value = proc
            out = await tools.run_command("nf-core modules info fastqc")
        assert "fastqc module exists" in out
        spawn.assert_awaited_once()

    async def test_nonzero_exit_returns_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"could not find module\n")
        proc.returncode = 1
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            spawn.return_value = proc
            out = await tools.run_command("nf-core modules info nope")
        assert "exit 1" in out
        assert "could not find module" in out
