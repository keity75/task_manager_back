# Task Manager Backend

## 概要

Task Manager の研修用バックエンドです。  
FastAPI + Firestore Emulator で構成されています。

## 前提条件

- Docker Desktop
- Docker Compose v2

## セットアップ

```bash
cp .env.example .env
```

`.env` に以下を設定してください。

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `ENCRYPTION_KEY`（フロントと同じ値）
- `BACKEND_JWT_SECRET`（`NEXTAUTH_SECRET` とは別値）

起動:

```bash
docker compose -f compose.yml up -d
```

## 動作確認

- `http://localhost:8000/`（ヘルスチェック）
- `http://localhost:8000/docs`（OpenAPI）
- `http://localhost:4000/`（Firestore Emulator UI）
- フロントからログイン後、`/api/v1/auth/sync` と `/api/v1/tasks/summary` が成功する

## 品質チェック

```bash
poetry run ruff check app/ tests/
poetry run ruff format --check app/ tests/
poetry run mypy app/
poetry run pytest
```

## 補足

- スケルトン期間中は `GET /api/v1/tasks` が未実装です。
