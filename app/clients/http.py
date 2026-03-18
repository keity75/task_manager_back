from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.logging import get_logger
from app.core.settings import settings

log = get_logger(__name__)


# --- カスタム例外クラス ---
# アプリケーションがhttpxに直接依存しないように、例外をラップします。
class HttpClientError(Exception):
    """HTTPクライアントで発生したエラーの基底クラス。"""

    @classmethod
    def from_unexpected_error(cls, error: str) -> HttpClientError:
        """予期しないエラーから例外を生成する。"""
        message = f"An unexpected error occurred: {error}"
        return cls(message)


class HttpRequestError(HttpClientError):
    """リクエスト失敗(4xx/5xx系)を示す例外。"""

    def __init__(self, message: str, status_code: int, response_body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

    @classmethod
    def from_response(
        cls,
        url: str,
        status_code: int,
        response_body: str,
    ) -> HttpRequestError:
        """HTTPレスポンスから例外を生成する。"""
        message = f"Request to {url} failed with status {status_code}"
        return cls(message, status_code, response_body)


class HttpNetworkError(HttpClientError):
    """ネットワーク関連のエラー(タイムアウト等)やリトライ上限到達を示す例外。"""

    @classmethod
    def from_request(cls, url: str) -> HttpNetworkError:
        """リクエスト失敗から例外を生成する。"""
        message = f"Network error while requesting {url}"
        return cls(message)


# --- リトライ戦略をデコレータとして定義 ---
# 設定ファイルからリトライ回数を読み込みます。
_retry_decorator = retry(
    stop=stop_after_attempt(settings.HTTP_CLIENT_MAX_RETRIES),
    wait=wait_exponential_jitter(initial=0.2, max=2.0),
    retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
    reraise=True,
    before_sleep=lambda retry_state: log.warning(
        "Retrying HTTP request",
        attempt=retry_state.attempt_number,
        wait_time=retry_state.next_action.sleep if retry_state.next_action else None,
        original_error=str(retry_state.outcome.exception())
        if retry_state.outcome
        else "Unknown error",
    ),
)


class HttpClient:
    """リトライ機能と構造化ロギングを備えた、汎用的な非同期HTTPクライアント。"""

    def __init__(self, timeout_seconds: float = settings.HTTP_CLIENT_TIMEOUT) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def aclose(self) -> None:
        """アプリケーション終了時にコネクションプールを解放します。"""
        log.info("Closing HTTP client connection pool...")
        await self._client.aclose()
        log.info("HTTP client connection pool closed.")

    @_retry_decorator
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """リトライロジックが適用された、内部的なリクエスト処理メソッド。"""
        log.debug("Requesting HTTP request", method=method, url=url, extra_args=kwargs)
        response: httpx.Response | None = None
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as err:
            log.exception(
                "HTTP request failed with status code",
                method=method,
                url=url,
                status_code=err.response.status_code,
                response_body=err.response.text,
            )
            raise HttpRequestError.from_response(
                url,
                err.response.status_code,
                err.response.text,
            ) from err
        except (httpx.TransportError, RetryError) as err:
            log.exception(
                "HTTP request failed due to a network error after all retries",
                method=method,
                url=url,
                original_error=str(err),
            )
            raise HttpNetworkError.from_request(url) from err
        except Exception as err:
            log.critical(
                "An unexpected error occurred in the HTTP client",
                method=method,
                url=url,
                original_error=str(err),
                exc_info=err,
            )
            raise HttpClientError.from_unexpected_error(str(err)) from err
        else:
            return response

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        """GETリクエストを送信し、レスポンスボディをJSONとして返します。"""
        response = await self._request("GET", url, **kwargs)
        return response.json()

    async def post_json(self, url: str, **kwargs: Any) -> Any:
        """POSTリクエストを送信し、レスポンスボディをJSONとして返します。"""
        response = await self._request("POST", url, **kwargs)
        return response.json()


class HttpClientManager:
    """HttpClientのシングルトンインスタンスとライフサイクルを管理する責務を持つクラス。"""

    _client: HttpClient | None = None

    def get_client(self) -> HttpClient:
        """スレッドセーフなシングルトンインスタンスを取得します。"""
        if self._client is None:
            # 複数スレッドからの同時アクセスでも安全なように一度だけインスタンス化
            self._client = HttpClient()
        return self._client

    async def close_client(self) -> None:
        """アプリケーション終了時にクライアントをクローズします。"""
        if self._client:
            await self._client.aclose()
            self._client = None


# マネージャークラスをインスタンス化
http_client_manager = HttpClientManager()


# FastAPIのDependsで使うためのショートカット関数
def get_http_client() -> HttpClient:
    """HttpClientのシングルトンインスタンスを取得する。"""
    return http_client_manager.get_client()


# FastAPIのlifespanで使うためのショートカット関数
async def close_http_client() -> None:
    """HttpClientの接続をクローズする。"""
    await http_client_manager.close_client()
