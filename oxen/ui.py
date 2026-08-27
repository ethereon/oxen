from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .task import Task

if TYPE_CHECKING:
    from .core import Oxen


class UserInterface(Protocol):
    def run(self, *args: Any, **kwargs: Any) -> Any: ...

    def add_layout(
        self,
        layout: TaskLayout,
        *,
        name: str,
        default: bool = False,
        shortcut: str | None = None,
    ) -> None: ...


class UIFactory(Protocol):
    def __call__(self, oxen: Oxen, /) -> UserInterface: ...


type TaskLayout = (
    list[Task | TaskLayout]  # Vertically stacked
    | tuple[Task | TaskLayout, ...]  # Horizontally stacked
    # list[] is not covariant, so explicitly add list[Task] to allow
    # registered task lists to be used directly.
    | list[Task]
)


def normalize_task_layout(layout: TaskLayout) -> tuple[TaskLayout, list[Task]]:
    """
    Validate a task layout and return its unique tasks in display order.
    """
    tasks: list[Task] = []
    seen_tasks: set[int] = set()
    active_containers: set[int] = set()

    def normalize(value: object, path: str) -> Task | TaskLayout:
        if isinstance(value, Task):
            if id(value) not in seen_tasks:
                seen_tasks.add(id(value))
                tasks.append(value)
            return value
        if not isinstance(value, (list, tuple)):
            raise TypeError(f'{path} must be a Task, list, or tuple')
        if not value:
            raise ValueError(f'{path} must not be empty')
        if id(value) in active_containers:
            raise ValueError(f'{path} contains a recursive container')

        active_containers.add(id(value))
        try:
            children = (normalize(item, f'{path}[{index}]') for index, item in enumerate(value))
            return list(children) if isinstance(value, list) else tuple(children)
        finally:
            active_containers.remove(id(value))

    normalized = normalize(layout, 'layout')
    if isinstance(normalized, Task):
        raise TypeError('layout must be a list or tuple')
    return normalized, tasks
