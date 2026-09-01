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


class TestTaskUpdateRequestPartialUpdateSemantics:
    """TaskUpdateRequestの部分更新セマンティクス(model_fields_setによる判定)"""

    def test_all_fields_omitted_results_in_empty_fields_set(self) -> None:
        """正常系: 何も指定しない場合、model_fields_setは空(=何も更新しない)"""
        req = schemas.TaskUpdateRequest()

        assert req.model_fields_set == set()

    def test_only_provided_field_appears_in_fields_set(self) -> None:
        """正常系: 指定したフィールドのみmodel_fields_setに含まれる"""
        req = schemas.TaskUpdateRequest(title="New Title")

        assert req.model_fields_set == {"title"}
        assert req.title == "New Title"

    def test_explicit_null_is_distinguishable_from_omission(self) -> None:
        """正常系: 明示的なnullは省略と区別され、model_fields_setに含まれる"""
        req = schemas.TaskUpdateRequest(due_at=None)

        assert req.model_fields_set == {"due_at"}
        assert req.due_at is None

    def test_extra_readonly_fields_are_rejected(self) -> None:
        """異常系: calendarLink/userId/createdAt/deletedAt等は受け付けない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(userId="someone-else")

    def test_extra_calendar_link_field_is_rejected(self) -> None:
        """異常系: calendarLinkフィールドは受け付けない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(calendarLink="https://example.com")


class TestTaskUpdateRequestTitle:
    """titleフィールドのバリデーション(部分更新)"""

    def test_title_omitted_is_valid(self) -> None:
        """正常系: 未指定は許容される(更新対象外)"""
        req = schemas.TaskUpdateRequest()
        assert req.title is None
        assert "title" not in req.model_fields_set

    def test_title_explicit_null_is_rejected(self) -> None:
        """異常系: titleはDB上NOT NULLのため、明示的なnullは許容されない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(title=None)

    def test_title_explicit_empty_string_is_rejected(self) -> None:
        """異常系: 空文字("")も空不可のため許容されない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(title="")

    def test_title_exceeding_max_length_is_rejected(self) -> None:
        """境界値: 256文字は最大長超過でエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(title="a" * (TITLE_MAX_LENGTH + 1))

    def test_title_at_max_length_boundary_is_accepted(self) -> None:
        """境界値: 255文字ちょうどは許容される"""
        req = schemas.TaskUpdateRequest(title="a" * TITLE_MAX_LENGTH)
        assert req.title is not None
        assert len(req.title) == TITLE_MAX_LENGTH


class TestTaskUpdateRequestPriorityAndStatus:
    """priority/statusフィールドのバリデーション(部分更新)"""

    def test_priority_omitted_is_valid(self) -> None:
        """正常系: 未指定は許容される(更新対象外)"""
        req = schemas.TaskUpdateRequest()
        assert "priority" not in req.model_fields_set

    def test_priority_explicit_null_is_rejected(self) -> None:
        """異常系: priorityはDB上NOT NULLのため、明示的なnullは許容されない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(priority=None)

    @pytest.mark.parametrize("priority", [0, 5, -1])
    def test_priority_outside_allowed_choices_is_rejected(self, priority: int) -> None:
        """異常系: 許容値(1-4)以外はエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(priority=priority)

    def test_status_omitted_is_valid(self) -> None:
        """正常系: 未指定は許容される(更新対象外)"""
        req = schemas.TaskUpdateRequest()
        assert "status" not in req.model_fields_set

    def test_status_explicit_null_is_rejected(self) -> None:
        """異常系: statusはDB上NOT NULLのため、明示的なnullは許容されない"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(status=None)


class TestTaskUpdateRequestDescriptionAndDueAt:
    """description/due_atフィールドのバリデーション(部分更新、null許容)"""

    def test_description_explicit_null_clears_value(self) -> None:
        """正常系: descriptionはnull許容フィールドのため、明示的なnullが許容される(クリア指示)"""
        req = schemas.TaskUpdateRequest(description=None)
        assert req.description is None
        assert "description" in req.model_fields_set

    def test_description_exceeding_max_length_is_rejected(self) -> None:
        """境界値: 100001文字は最大長超過でエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(description="a" * (DESCRIPTION_MAX_LENGTH + 1))

    def test_due_at_explicit_null_clears_value(self) -> None:
        """正常系: due_atはnull許容フィールドのため、明示的なnullが許容される(クリア指示)"""
        req = schemas.TaskUpdateRequest(due_at=None)
        assert req.due_at is None
        assert "due_at" in req.model_fields_set

    def test_due_at_naive_datetime_is_interpreted_as_jst_and_converted_to_utc(
        self,
    ) -> None:
        """正常系: タイムゾーン情報がないdatetimeはJSTとして解釈されUTCに正規化される"""
        naive_jst_9am = datetime(2026, 1, 1, 9, 0)  # noqa: DTZ001
        req = schemas.TaskUpdateRequest(due_at=naive_jst_9am)

        assert req.due_at == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_due_at_invalid_value_is_rejected(self) -> None:
        """異常系: 日時として解釈できない文字列はエラー"""
        with pytest.raises(ValidationError):
            schemas.TaskUpdateRequest(due_at="not-a-date")
