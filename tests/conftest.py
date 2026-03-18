"""Pytest共通フィクスチャ

Firestore Emulator接続とテストデータクリーンアップを提供する。
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from google.cloud import firestore

from app.core.settings import settings


@pytest.fixture(autouse=True)
def _no_domain_restriction() -> Generator[None]:
    """デフォルトでドメイン制限なし(個別テストでオーバーライド可能)"""
    with patch.object(settings, "ALLOWED_EMAIL_DOMAINS", []):
        yield


@pytest.fixture(scope="session")
def firestore_emulator_host() -> str:
    """Firestore Emulatorのホスト情報を返す

    compose.ymlで起動されているFirestore Emulatorに接続する。
    """
    return "localhost:8080"


@pytest.fixture(scope="session")
def firestore_project_id() -> str:
    """Firestore EmulatorのプロジェクトIDを返す"""
    return "demo-task-manager"


@pytest.fixture
def db(
    firestore_emulator_host: str, firestore_project_id: str
) -> Generator[firestore.Client]:
    """Firestore Emulatorに接続するクライアントを提供

    各テスト関数ごとに新しいクライアントを作成し、
    テスト後にデータをクリーンアップする。
    """
    client = firestore.Client(
        project=firestore_project_id,
        client_options={"api_endpoint": firestore_emulator_host},
    )

    yield client

    # テスト後のクリーンアップ: 全コレクションを削除
    _cleanup_firestore(client)


def _cleanup_firestore(client: firestore.Client) -> None:
    """Firestoreの全データを削除する

    テスト後のクリーンアップ用。全コレクションとサブコレクションを削除する。
    """
    collections = [
        "users",
        "auth_providers",
        "backend_sessions",
    ]

    for collection_name in collections:
        _delete_collection(client.collection(collection_name), batch_size=100)


def _delete_collection(collection_ref: Any, batch_size: int = 100) -> None:
    """コレクション内の全ドキュメントを削除する

    Args:
        collection_ref: Firestoreコレクション参照
        batch_size: 一度に削除するドキュメント数

    """
    docs = collection_ref.limit(batch_size).stream()
    deleted = 0

    for doc in docs:
        # サブコレクションも削除
        for subcollection in doc.reference.collections():
            _delete_collection(subcollection, batch_size)

        doc.reference.delete()
        deleted += 1

    if deleted >= batch_size:
        # まだドキュメントが残っている可能性があるので再帰的に削除
        _delete_collection(collection_ref, batch_size)
