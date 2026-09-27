FROM carecircle-mcp:phase3-claude-arm64
WORKDIR /app
COPY src /app/src
ENV PYTHONPATH=/app/src
CMD ["carecircle"]
