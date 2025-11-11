# Dashboard Service Dockerfile
# Runs Streamlit dashboard

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Optimize build performance
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Copy dependency files and source code needed for package build
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src

# Install dependencies (without dev)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Final stage
FROM python:3.13-slim-bookworm AS final

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/web ./src/web

# Ensure the venv is used by default
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Expose Streamlit default port
EXPOSE 8501

# Run Streamlit
CMD ["streamlit", "run", "src/web/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
