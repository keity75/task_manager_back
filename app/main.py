from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from google.cloud import firestore

from app.auth.exception_handlers import (
    handle_auth_repository_error,
    handle_auth_sync_error,
    handle_email_domain_not_allowed_error,
    handle_invalid_access_token_error,
    handle_invalid_refresh_token_error,
    handle_provider_not_found_error,
    handle_token_refresh_error,
    handle_token_update_error,
)
from app.auth.exceptions import (
    AuthRepositoryError,
    AuthSyncError,
    EmailDomainNotAllowedError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    ProviderNotFoundError,
    TokenRefreshError,
    TokenUpdateError,
)
from app.auth.router import router as auth_router
from app.clients.http import close_http_client
from app.core.exception_handlers import (
    handle_generic_exception,
    handle_validation_error,
)
from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.emails.exception_handlers import (
    handle_email_not_found_error,
    handle_gmail_permission_denied_error,
    handle_gmail_repository_error,
)
from app.emails.exceptions import (
    EmailNotFoundError,
    GmailPermissionDeniedError,
    GmailRepositoryError,
)
from app.emails.router import router as emails_router
from app.middleware.cors import setup_cors
from app.middleware.logging import RequestLoggingMiddleware
from app.tasks.exception_handlers import (
    handle_task_not_found_error,
    handle_task_repository_error,
)
from app.tasks.exceptions import TaskNotFoundError, TaskRepositoryError
from app.tasks.router import router as tasks_router

# --- 1. 初期設定 ---

configure_logging()
log = get_logger()


# --- 2. アプリケーションのライフサイクル管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """アプリケーションの起動・終了イベントを管理するコンテキストマネージャー。"""
    log.info("Application startup...")

    project_id = settings.GOOGLE_CLOUD_PROJECT
    emulator_host = settings.FIRESTORE_EMULATOR_HOST
    database_id = settings.FIRESTORE_DATABASE_ID

    db_kwargs: dict[str, Any] = {"project": project_id, "database": database_id}

    # ここにデータベース接続などの他の初期化処理を追加できます
    if emulator_host:
        log.info("firestore_emulator", host=emulator_host, database=database_id)
        db_kwargs["client_options"] = {"api_endpoint": emulator_host}
    else:
        log.info("firestore_production", database=database_id)

    db = firestore.Client(**db_kwargs)

    app.state.db = db
    log.info("Firestore client initialized.")

    yield
    log.info("Application shutdown...")
    await close_http_client()


# --- 3. FastAPIアプリケーションのインスタンス化 ---
app = FastAPI(
    title="Task Manager API",
    version="0.1.0",
    lifespan=lifespan,
)

# リクエスト処理時間ロギング
app.add_middleware(RequestLoggingMiddleware)
# CORS設定
setup_cors(app)

app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
app.add_exception_handler(TaskRepositoryError, handle_task_repository_error)  # type: ignore[arg-type]
app.add_exception_handler(TaskNotFoundError, handle_task_not_found_error)  # type: ignore[arg-type]
app.add_exception_handler(InvalidRefreshTokenError, handle_invalid_refresh_token_error)  # type: ignore[arg-type]
app.add_exception_handler(InvalidAccessTokenError, handle_invalid_access_token_error)  # type: ignore[arg-type]
app.add_exception_handler(
    EmailDomainNotAllowedError,
    cast(Any, handle_email_domain_not_allowed_error),  # type: ignore[arg-type]
)  # type: ignore[arg-type]
app.add_exception_handler(AuthSyncError, handle_auth_sync_error)  # type: ignore[arg-type]
app.add_exception_handler(TokenUpdateError, handle_token_update_error)  # type: ignore[arg-type]
app.add_exception_handler(AuthRepositoryError, handle_auth_repository_error)  # type: ignore[arg-type]
app.add_exception_handler(ProviderNotFoundError, handle_provider_not_found_error)  # type: ignore[arg-type]
app.add_exception_handler(TokenRefreshError, handle_token_refresh_error)  # type: ignore[arg-type]
app.add_exception_handler(EmailNotFoundError, handle_email_not_found_error)  # type: ignore[arg-type]
app.add_exception_handler(GmailPermissionDeniedError, handle_gmail_permission_denied_error)  # type: ignore[arg-type]
app.add_exception_handler(GmailRepositoryError, handle_gmail_repository_error)  # type: ignore[arg-type]
app.add_exception_handler(Exception, handle_generic_exception)  # type: ignore[arg-type]


# --- 4. APIエンドポイントの定義 ---
@app.get("/")
def read_root() -> dict[str, str]:
    """ヘルスチェック用のルートエンドポイント。"""
    return {"Hello": "World"}


api_v1_prefix = f"{settings.API_PREFIX}{settings.API_VERSION}"
app.include_router(tasks_router, prefix=api_v1_prefix)
app.include_router(auth_router, prefix=api_v1_prefix)
app.include_router(emails_router, prefix=api_v1_prefix)
