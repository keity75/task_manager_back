import time
import uuid
from contextvars import ContextVar

import structlog
from fastapi import Request
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

# リクエストIDを格納するコンテキスト変数 (型ヒント用)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """APIリクエスト/レスポンス情報をログ出力し、request_idを付与するMiddleware。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """リクエスト/レスポンスのログ出力とrequest_idの付与を行う。"""
        # --- 1. リクエストIDの生成とコンテキストへのバインド ---
        request_id = str(uuid.uuid4())
        # コンテキスト変数にセット
        token = request_id_var.set(request_id)
        # structlogのコンテキストにもバインド (これにより以降のログに自動で含まれる)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.time()

        # --- 2. リクエスト開始ログ ---
        logger.info(
            "Request started",  # ログ設計に合わせたeventメッセージ
            method=request.method,
            path=request.url.path,
            client_host=request.client.host if request.client else "unknown",
        )

        try:
            # --- 3. 次の処理へ ---
            response = await call_next(request)
            # レスポンスヘッダーにもリクエストIDを追加 (デバッグ用に便利)
            response.headers["X-Request-ID"] = request_id

        except Exception:
            # 例外発生時もログを出力してから再送出 (例外ハンドラが別途処理)
            logger.exception(
                "Request failed during processing",
                method=request.method,
                path=request.url.path,
            )
            # コンテキスト変数をクリア
            structlog.contextvars.clear_contextvars()
            request_id_var.reset(token)
            raise  # 例外を再送出

        process_time_ms = (time.time() - start_time) * 1000
        # レスポンスヘッダーに処理時間を追加
        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"

        # --- 4. リクエスト終了ログ ---
        logger.info(
            "Request finished",  # ログ設計に合わせたeventメッセージ
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(process_time_ms, 2),  # ミリ秒に統一
        )

        # --- 5. コンテキスト変数のクリア ---
        structlog.contextvars.clear_contextvars()
        request_id_var.reset(token)  # Pythonのコンテキスト変数もリセット

        return response
