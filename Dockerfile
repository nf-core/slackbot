FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ src/
COPY forms/ forms/

# Re-install in editable mode so the package resolves properly
RUN pip install --no-cache-dir -e .

# Run as non-root
RUN useradd --create-home botuser
USER botuser

CMD ["python", "-m", "nf_core_bot"]
