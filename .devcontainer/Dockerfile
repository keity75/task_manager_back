FROM python:3.13-slim

# 開発ユーザー作成
RUN useradd -m vscode

# 必要なパッケージをインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# pip を最新化
RUN pip install --upgrade pip

# Poetryのインストール（全ユーザーから参照可能なディレクトリに配置）
ENV POETRY_HOME=/opt/poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s ${POETRY_HOME}/bin/poetry /usr/local/bin/poetry && \
    chmod -R a+rx ${POETRY_HOME}

# Poetryの設定: 仮想環境を作成しない(コンテナ内なので不要)
RUN poetry config virtualenvs.create false

# pyproject.tomlとpoetry.lockをコピー
COPY pyproject.toml poetry.lock* /tmp/

# 依存関係をインストール
RUN cd /tmp && poetry lock --no-interaction --no-ansi && poetry install --no-interaction --no-ansi --no-root

USER vscode
WORKDIR /workspace
