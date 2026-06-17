"""Read-only command tool exposed to Claude during a proposal review.

Claude (running the ``nfcore-proposal-review`` skill) needs to run the skill's
research commands — ``gh issue view``, ``gh search code``, ``nf-core modules
info``, ``jq`` filters, and so on. This module exposes a single tool that runs
exactly those commands, under a strict deny-by-default allowlist.

Safety model
------------
* **No shell.** Commands run via :func:`asyncio.create_subprocess_exec`, never
  through a shell, so ``;``, ``&&``, ``$(…)``, backticks, redirects, etc. are
  inert — they become literal argv that the target binary simply rejects. The
  only operator we interpret is ``|`` (handled by chaining processes ourselves).
* **Allowlist.** Only ``gh``, ``nf-core`` and ``jq`` binaries are permitted, and
  only their read-only subcommands (``gh issue view``, ``nf-core modules info``,
  …). ``gh api`` is restricted to GET. Everything else is rejected.
* **Scrubbed environment.** Each segment runs with a minimal environment. Only
  ``gh``/``nf-core`` segments receive a GitHub token; ``jq`` gets none, so its
  ``env`` builtin cannot exfiltrate Slack/AWS/GitHub secrets into the review.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex

from nf_core_bot import config

logger = logging.getLogger(__name__)

# Tool name surfaced to the model.
TOOL_NAME = "run_command"

# Per-invocation limits.
DEFAULT_TIMEOUT = 60.0  # seconds, per pipeline segment
MAX_OUTPUT_CHARS = 12_000

ALLOWED_BINARIES = frozenset({"gh", "nf-core", "jq", "bash"})

# Shell control operators rejected outright (we never run a shell regardless).
_FORBIDDEN_TOKENS = frozenset({";", "&&", "||", "&", ">", ">>", "<", "<<", "2>", "2>>"})

# ``bash`` is permitted ONLY to run the vetted bundled skill scripts (which
# themselves only call read-only gh/jq). Arbitrary bash (e.g. ``bash -c``) is
# rejected. The scripts quote their arguments, so hostile args can't inject.
_SCRIPTS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "skills", "nfcore-proposal-review", "scripts"))
_ALLOWED_SCRIPTS = frozenset({"fetch_proposal.sh", "check_tools.sh", "list_pipelines.sh"})

# Read-only ``gh`` subcommands, keyed by their first two positional tokens.
_GH_ALLOWED: frozenset[tuple[str, ...]] = frozenset(
    {
        ("issue", "view"),
        ("issue", "list"),
        ("search", "code"),
        ("search", "issues"),
        ("search", "prs"),
        ("search", "repos"),
        ("repo", "list"),
        ("repo", "view"),
        ("pr", "view"),
        ("pr", "list"),
    }
)

# Read-only ``nf-core`` subcommands.
_NFCORE_ALLOWED: frozenset[tuple[str, ...]] = frozenset(
    {
        ("modules", "list"),
        ("modules", "info"),
        ("subworkflows", "list"),
        ("subworkflows", "info"),
        ("pipelines", "list"),
        ("pipelines", "info"),
        ("list",),  # legacy `nf-core list`
    }
)

# Tool schema (Anthropic Messages API shape) handed to the model.
RESEARCH_TOOL: dict[str, object] = {
    "name": TOOL_NAME,
    "description": (
        "Run a single read-only research command and return its output. "
        "Allowed binaries: `gh` (GitHub CLI — issue/repo/search/pr read commands), "
        "`nf-core` (module/subworkflow/pipeline list & info), and "
        "`jq`. A single `|` pipe between allowed commands is supported (e.g. "
        "`gh repo list nf-core --json name,description | jq ...`). Write operations, "
        "other binaries, and shell features (`;`, `&&`, `$()`, redirects) are rejected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to run, e.g. `nf-core modules info fastqc`.",
            }
        },
        "required": ["command"],
    },
}


class DisallowedCommandError(ValueError):
    """Raised when a command is not permitted by the allowlist."""


def _positional(tokens: list[str]) -> list[str]:
    """Return the leading positional tokens (those before the first flag)."""
    out: list[str] = []
    for tok in tokens:
        if tok.startswith("-"):
            break
        out.append(tok)
    return out


def _validate_gh(argv: list[str]) -> None:
    # `--hostname` points gh at an arbitrary host (SSRF) — reject on every gh
    # command. (`gh api` is deliberately NOT in the allowlist: it accepts an
    # absolute URL, which would be an SSRF / cloud-metadata exfiltration vector.)
    if any(tok == "--hostname" or tok.startswith("--hostname=") for tok in argv[1:]):
        raise DisallowedCommandError("`gh --hostname` is not allowed")
    pos = _positional(argv[1:])  # tokens after "gh", before flags
    if not pos:
        raise DisallowedCommandError("`gh` requires a subcommand")
    key = tuple(pos[:2])
    if key not in _GH_ALLOWED:
        raise DisallowedCommandError(f"`gh {' '.join(pos[:2])}` is not an allowed read-only command")


def _validate_nfcore(argv: list[str]) -> None:
    pos = _positional(argv[1:])
    if not pos:
        raise DisallowedCommandError("`nf-core` requires a subcommand")
    if tuple(pos[:2]) in _NFCORE_ALLOWED or tuple(pos[:1]) in _NFCORE_ALLOWED:
        return
    raise DisallowedCommandError(f"`nf-core {' '.join(pos[:2])}` is not an allowed read-only command")


def _validate_bash(argv: list[str]) -> None:
    """Allow ``bash`` only to run one of the vetted bundled skill scripts."""
    if len(argv) < 2:
        raise DisallowedCommandError("`bash` requires a script path")
    script = argv[1]
    if script.startswith("-"):
        raise DisallowedCommandError("`bash` options (e.g. -c) are not allowed")
    realpath = os.path.realpath(script)
    if os.path.dirname(realpath) != _SCRIPTS_DIR or os.path.basename(realpath) not in _ALLOWED_SCRIPTS:
        raise DisallowedCommandError("`bash` may only run the bundled proposal-review scripts")


def _validate_segment(argv: list[str]) -> None:
    if not argv:
        raise DisallowedCommandError("empty command segment")
    binary = argv[0]
    if binary not in ALLOWED_BINARIES:
        raise DisallowedCommandError(f"`{binary}` is not an allowed command (allowed: gh, nf-core, jq, bash)")
    if binary == "gh":
        _validate_gh(argv)
    elif binary == "nf-core":
        _validate_nfcore(argv)
    elif binary == "bash":
        _validate_bash(argv)
    # jq: any invocation is allowed (it only transforms stdin; runs with no token).


def validate_command(command: str) -> list[list[str]]:
    """Parse and validate *command*, returning a list of argv segments.

    Raises :class:`DisallowedCommandError` if the command is not permitted.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise DisallowedCommandError(f"could not parse command: {exc}") from exc
    if not tokens:
        raise DisallowedCommandError("empty command")

    # Defense-in-depth: we never invoke a shell, so these are inert anyway, but
    # reject them explicitly so intent-violating commands fail loudly.
    for tok in tokens:
        if tok in _FORBIDDEN_TOKENS:
            raise DisallowedCommandError(f"shell operator not allowed: {tok}")
        if "`" in tok or "$(" in tok:
            raise DisallowedCommandError("command substitution not allowed")

    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok == "|":
            segments.append(current)
            current = []
        else:
            current.append(tok)
    segments.append(current)

    for seg in segments:
        _validate_segment(seg)
    return segments


def _base_env() -> dict[str, str]:
    """A minimal environment carrying no secrets."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    # Keep gh/nf-core non-interactive and quiet.
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    return env


def _env_for(binary: str) -> dict[str, str]:
    """Per-binary environment. Only gh/nf-core receive a GitHub token."""
    env = _base_env()
    token = config.PROPOSALS_GITHUB_TOKEN or config.GITHUB_TOKEN
    if not token:
        return env
    if binary in ("gh", "bash"):
        # bash only ever runs the bundled scripts, which call `gh`.
        env["GH_TOKEN"] = token
    elif binary == "nf-core":
        env["GITHUB_TOKEN"] = token
    # jq deliberately gets no token.
    return env


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… (output truncated at {MAX_OUTPUT_CHARS} chars)"


async def run_command(command: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Validate and run *command*, returning its combined output as text.

    Never raises for an allowlist violation or a non-zero exit — those are
    returned as an error string so the model can read and adapt.
    """
    try:
        segments = validate_command(command)
    except DisallowedCommandError as exc:
        return f"ERROR: command rejected — {exc}"

    data: bytes | None = None
    for argv in segments:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_env_for(argv[0]),
            )
        except FileNotFoundError:
            return f"ERROR: `{argv[0]}` is not installed in this environment"
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=data), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return f"ERROR: command timed out after {timeout:.0f}s: {' '.join(argv)}"

        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace").strip() or stdout.decode("utf-8", "replace").strip()
            return _truncate(f"ERROR (exit {proc.returncode}) running `{' '.join(argv)}`:\n{err}")
        data = stdout

    return _truncate((data or b"").decode("utf-8", "replace"))
