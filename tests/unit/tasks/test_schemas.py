"""TaskCreateRequestのバリデーション単体テスト

create_taskエンドポイントの入力仕様(app/tasks/schemas.py)を検証する。
サービス層(TaskService.create_task)に到達する前に、Pydanticのfield_validatorで
弾かれる/正規化される値を対象とする。
"""
# ruff: noqa: PLR2004

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.tasks import schemas

TITLE_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 100000


class TestTaskCreateRequestTitle:
    """titleフィールドのバリデーション"""

    def test_title_is_required(self) -> None:
        """異常系: title未指定はエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest()

    def test_title_empty_string_is_rejected(self) -> None:
        """異常系: title=""は必須チェックに引っかかる"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest(title="")

    def test_title_at_max_length_boundary_is_accepted(self) -> None:
        """境界値: 255文字ちょうどは許容される"""
        req = schemas.TaskCreateRequest(title="a" * TITLE_MAX_LENGTH)
        assert len(req.title) == TITLE_MAX_LENGTH

    def test_title_exceeding_max_length_is_rejected(self) -> None:
        """境界値: 256文字は最大長超過でエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest(title="a" * (TITLE_MAX_LENGTH + 1))


class TestTaskCreateRequestPriority:
    """priorityフィールドのバリデーション(許容値: 1/2/3/4)"""

    def test_priority_omitted_defaults_to_none(self) -> None:
        """正常系: 未指定はNone(サービス層でデフォルト値2が補完される)"""
        req = schemas.TaskCreateRequest(title="t")
        assert req.priority is None

    @pytest.mark.parametrize("priority", [1, 2, 3, 4])
    def test_priority_within_allowed_choices_is_accepted(self, priority: int) -> None:
        """正常系: 1〜4は許容される"""
        req = schemas.TaskCreateRequest(title="t", priority=priority)
        assert req.priority == priority

    @pytest.mark.parametrize("priority", [0, 5, -1])
    def test_priority_outside_allowed_choices_is_rejected(self, priority: int) -> None:
        """異常系: 許容値(1-4)以外はエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest(title="t", priority=priority)


class TestTaskCreateRequestStatus:
    """statusフィールドのバリデーション

    注意: priorityと異なり、statusには選択肢(10/20/30)の制約が実装されていない。
    現状の仕様では任意のintが受理される。
    """

    def test_status_omitted_defaults_to_none(self) -> None:
        """正常系: 未指定はNone(サービス層でデフォルト値10が補完される)"""
        req = schemas.TaskCreateRequest(title="t")
        assert req.status is None

    def test_status_outside_defined_constants_is_currently_accepted(self) -> None:
        """仕様確認: 定義済み定数(10/20/30)以外の値も現状はバリデーションエラーにならない"""
        req = schemas.TaskCreateRequest(title="t", status=999)
        assert req.status == 999


class TestTaskCreateRequestDescription:
    """descriptionフィールドのバリデーション"""

    def test_description_omitted_defaults_to_none(self) -> None:
        """正常系: 未指定はNone"""
        req = schemas.TaskCreateRequest(title="t")
        assert req.description is None

    def test_description_at_max_length_boundary_is_accepted(self) -> None:
        """境界値: 100000文字ちょうどは許容される"""
        req = schemas.TaskCreateRequest(title="t", description="a" * DESCRIPTION_MAX_LENGTH)
        assert req.description is not None
        assert len(req.description) == DESCRIPTION_MAX_LENGTH

    def test_description_exceeding_max_length_is_rejected(self) -> None:
        """境界値: 100001文字は最大長超過でエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest(
                title="t", description="a" * (DESCRIPTION_MAX_LENGTH + 1)
            )


class TestTaskCreateRequestDueAt:
    """due_atフィールドのバリデーション(タイムゾーン正規化)"""

    def test_due_at_omitted_defaults_to_none(self) -> None:
        """正常系: 未指定はNone"""
        req = schemas.TaskCreateRequest(title="t")
        assert req.due_at is None

    def test_due_at_naive_datetime_is_interpreted_as_jst_and_converted_to_utc(
        self,
    ) -> None:
        """正常系: タイムゾーン情報がないdatetimeはJSTとして解釈されUTCに正規化される"""
        naive_jst_9am = datetime(2026, 1, 1, 9, 0)  # noqa: DTZ001
        req = schemas.TaskCreateRequest(title="t", due_at=naive_jst_9am)

        assert req.due_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_due_at_aware_datetime_is_converted_to_utc_without_reinterpretation(
        self,
    ) -> None:
        """正常系: タイムゾーン付きdatetimeはJST変換されず、そのままUTCへ変換される"""
        aware_utc_9am = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        req = schemas.TaskCreateRequest(title="t", due_at=aware_utc_9am)

        assert req.due_at == aware_utc_9am

    def test_due_at_invalid_value_is_rejected(self) -> None:
        """異常系: 日時として解釈できない文字列はエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskCreateRequest(title="t", due_at="not-a-date")
