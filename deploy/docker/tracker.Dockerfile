FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin shardnet

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir .

RUN mkdir -p /app/data && chown -R shardnet:shardnet /app
USER shardnet

EXPOSE 8000

CMD ["uvicorn", "shardnet.tracker.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
