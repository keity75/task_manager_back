import logging
import sys
from typing import Any

import structlog


def configure_logging(log_level: int = logging.INFO) -> None:
    """structlogを使用して構造化JSONロギングを設定します。

    この設定により、自作のログだけでなく、Uvicornや
    他のライブラリが出力するログも全てJSON形式に統一されます。
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.dict_tracebacks,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    # 全てのログをJSONに変換するフォーマッターを定義します。
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,  # type: ignore[arg-type]
        processor=structlog.processors.JSONRenderer(ensure_ascii=False),
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # 意図しない重複ログを防ぐため、既存のハンドラーをクリアします。
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """設定済みのロガーインスタンスを取得するためのヘルパー関数です。"""
    return structlog.get_logger(name)
