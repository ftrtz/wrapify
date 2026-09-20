# ETL Service Dockerfile
# Runs Prefect flows in serve mode - listens for scheduled/triggered flow runs

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Optimize build performance
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Only the dependency metadata - the source is copied into the final stage, so
# this layer is reused as long as the lockfile is unchanged.
COPY pyproject.toml uv.lock ./

# Install ONLY the etl extra (no dev, no project) so the image does not carry
# the dashboard or API dependency trees.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --no-default-groups --extra etl

# Final stage
FROM python:3.13-slim-bookworm AS final

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy ETL source code
COPY src/etl ./src/etl

# Ensure the venv is used by default
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1

# Enable Prefect runner health server for container health checks
ENV PREFECT_RUNNER_SERVER_ENABLE=true \
    PREFECT_RUNNER_SERVER_HOST=0.0.0.0 \
    PREFECT_RUNNER_SERVER_PORT=8080

# Health check for production monitoring
# Checks if the Prefect runner is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8080/health', timeout=1)"

# Expose health check port
EXPOSE 8080

# Run the serve script to start listening for flow runs
CMD ["python", "-m", "etl.serve"]
