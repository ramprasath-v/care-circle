FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["carecircle"]
