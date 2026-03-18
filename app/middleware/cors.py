from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# core/settings.py から設定オブジェクトをインポート
from app.core.settings import settings


def setup_cors(app: FastAPI) -> None:
    """CORS (Cross-Origin Resource Sharing) Middlewareをアプリケーションに適用します。

    Args:
        app: FastAPIアプリケーションインスタンス

    """
    app.add_middleware(
        CORSMiddleware,
        # settings.pyから許可するオリジンを読み込む
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
