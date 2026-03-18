FROM python:3.13-slim

# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージの更新と必要なパッケージのインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# pip を最新化
RUN pip install --upgrade pip

# Poetryのインストール
ENV POETRY_HOME=/opt/poetry
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VENV_IN_PROJECT=1
ENV POETRY_CACHE_DIR=/tmp/poetry_cache

RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s ${POETRY_HOME}/bin/poetry /usr/local/bin/poetry && \
    chmod -R a+rx ${POETRY_HOME}

# Poetryの設定: 仮想環境を作成しない（コンテナ内なので不要）
RUN poetry config virtualenvs.create false

# 依存関係ファイルをコピー
COPY pyproject.toml poetry.lock* ./

# 依存関係をインストール（開発依存関係は除外）
RUN poetry install --no-interaction --no-ansi --no-root --only main && \
    rm -rf $POETRY_CACHE_DIR

# アプリケーションコードをコピー
COPY app/ ./app/

# 非rootユーザーを作成して使用
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
