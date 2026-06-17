FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── System tools used by the proposal-review skill (read-only research) ──
# gh  — GitHub CLI (issue/repo/search reads)   jq — JSON filtering   git — gh dep
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg jq git \
    && mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# nf-core CLI (module/subworkflow/pipeline lookups). Installed via pipx in its own
# virtualenv so its large dependency tree never conflicts with the bot's deps.
ENV PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin
RUN pip install --no-cache-dir pipx \
    && pipx install "nf-core>=3,<4"

# Install dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ src/
COPY hackathons/ hackathons/

# Re-install in editable mode so the package resolves properly
RUN pip install --no-cache-dir -e .

# Run as non-root
RUN useradd --create-home botuser
USER botuser

CMD ["python", "-m", "nf_core_bot"]
