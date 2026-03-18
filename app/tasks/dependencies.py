from typing import Annotated

from fastapi import Depends

from app.tasks.calendar_links import CalendarLinkGenerator, get_calendar_link_generator
from app.tasks.firestore_repository import get_task_repository
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskService


def get_task_service(
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    calendar_gen: Annotated[
        CalendarLinkGenerator, Depends(get_calendar_link_generator)
    ],
) -> TaskService:
    """TaskRepositoryを注入してTaskServiceのインスタンスを生成する

    Args:
        repo: タスクリポジトリ
        calendar_gen: カレンダーリンクジェネレータ

    Returns:
        TaskService

    """
    return TaskService(
        task_repo=repo,
        calendar_link_generator=calendar_gen,
    )
