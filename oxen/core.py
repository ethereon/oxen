from __future__ import annotations

import asyncio

from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Self

from .publisher import Publisher, SubscriptionStore
from .task import Task, TaskStatus
from .ui import TaskLayout, UIFactory, UserInterface, normalize_task_layout


@dataclass(frozen=True, slots=True)
class TaskStatusChange:
    task: Task
    status: TaskStatus


@dataclass(frozen=True, slots=True)
class TaskOutputChange:
    task: Task
    output: str


@dataclass(frozen=True, slots=True)
class TaskOperationError:
    task: Task
    operation: str
    error: BaseException


def _make_tui(oxen: Oxen) -> UserInterface:
    # Lazily import TUI dependencies
    from .tui import OxenTUI

    return OxenTUI(oxen)


class Oxen:
    """
    Manage a collection of tasks and present them through a user interface.

    Oxen coordinates task registration, selection, lifecycle operations, status
    changes, and output updates. Calling `run()` starts the configured user
    interface; by default, Oxen uses its terminal interface.

    Args:
        *tasks: Tasks to register initially. Additional tasks can be registered
            later with `add()` or as part of an `add_layout()` call.

        auto_start: Whether `start()` should run pending tasks whose
            `auto_start` flag is enabled. Tasks added after startup follow the
            same rule.
            Defaults to True.

        ui: A user interface class or factory. It is called with this `Oxen`
            instance and must return an object implementing the user interface
            protocol.
            Defaults to the terminal interface.
    """

    def __init__(
        self,
        *tasks: Task,
        auto_start: bool = True,
        ui: UIFactory = _make_tui,
    ) -> None:
        self.tasks: list[Task] = []
        self.auto_start = auto_start
        self._selected_task: Task | None = None
        self._subscriptions = SubscriptionStore()

        self.on_task_added = Publisher[Task]()
        self.on_selected_task_change = Publisher[Task | None]()
        self.on_task_status_change = Publisher[TaskStatusChange]()
        self.on_task_output_change = Publisher[TaskOutputChange]()
        self.on_task_operation_error = Publisher[TaskOperationError]()
        self._operations: set[asyncio.Task[Any]] = set()
        self._started = False
        self._ui_factory = ui
        self._ui: UserInterface | None = None
        self.add(*tasks)

    @property
    def selected_task(self) -> Task | None:
        return self._selected_task

    @selected_task.setter
    def selected_task(self, task: Task | None) -> None:
        self.select(task)

    @property
    def ui(self) -> UserInterface:
        """
        Return this manager's UI, creating it on first access.
        """
        if self._ui is None:
            self._ui = self._ui_factory(self)
        return self._ui

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """
        Run the configured UI.
        """
        return self.ui.run(*args, **kwargs)

    def add(self, *tasks: Task) -> None:
        for task in tasks:
            if any(registered is task for registered in self.tasks):
                raise ValueError(f'Task {task.name!r} is already registered')

            self.tasks.append(task)
            self._subscriptions.add(
                task.on_status_change.subscribe(lambda status, task=task: self.on_task_status_change.publish(TaskStatusChange(task, status))),
                task.output.on_update.subscribe(lambda output, task=task: self.on_task_output_change.publish(TaskOutputChange(task, output))),
            )
            self.on_task_added.publish(task)

            if self._selected_task is None:
                self.select(task)

            if self._started and self.auto_start and task.auto_start and task.status is TaskStatus.PENDING:
                self.run_task(task)

    def add_layout(
        self,
        layout: TaskLayout,
        *,
        name: str,
        default: bool = False,
        shortcut: str | None = None,
    ) -> None:
        """
        Register a recursively nested split view.

        Lists stack their children vertically:
            [
                task_a,
                task_b,
                ...
            ]

        Tuples stack their children horizontally:
            (task_a, task_b, ...)

        Lists and tuples can be nested in any combination:
            [
                (task_a, task_b),
                task_c
            ]
        """
        normalized, tasks = normalize_task_layout(layout)
        registered = {id(task) for task in self.tasks}
        self.add(*(task for task in tasks if id(task) not in registered))
        self.ui.add_layout(
            normalized,
            name=name,
            default=default,
            shortcut=shortcut,
        )

    def select(self, task: Task | None) -> None:
        """
        Select a registered task, or clear the selection with `None`.
        """
        if task is not None:
            self._validate_task(task)
        if task is self._selected_task:
            return

        self._selected_task = task
        self.on_selected_task_change.publish(task)

    def __iadd__(self, task: Task) -> Self:
        self.add(task)
        return self

    def start(self) -> None:
        """
        Start every eligible task and enable auto-start for newly added tasks.
        """
        if self._started:
            return
        self._started = True
        if self.auto_start:
            for task in self.tasks:
                if task.auto_start and task.status is TaskStatus.PENDING:
                    self.run_task(task)

    def run_task(self, task: Task) -> None:
        self._validate_task(task)
        self._schedule(task.run(), task, 'run')

    def restart_task(self, task: Task) -> None:
        self._validate_task(task)
        self._schedule(task.restart(), task, 'restart')

    def stop_task(self, task: Task) -> None:
        self._validate_task(task)
        self._schedule(task.stop(), task, 'stop')

    async def shutdown(self) -> None:
        """
        Stop all running tasks and disable auto-start until started again.
        """
        self._started = False
        await asyncio.gather(
            *(task.stop() for task in self.tasks if task.status is TaskStatus.RUNNING),
            return_exceptions=True,
        )

    def _validate_task(self, task: Task) -> None:
        if not any(registered is task for registered in self.tasks):
            raise ValueError(f'Task {task.name!r} is not registered')

    def _schedule(
        self,
        coroutine: Coroutine[Any, Any, None],
        task: Task,
        operation_name: str,
    ) -> None:
        operation = asyncio.create_task(coroutine, name=f'oxen: {operation_name} {task.name}')
        self._operations.add(operation)

        def completed(done: asyncio.Task[Any]) -> None:
            self._operations.discard(done)
            if done.cancelled():
                return
            if error := done.exception():
                self.on_task_operation_error.publish(TaskOperationError(task, operation_name, error))

        operation.add_done_callback(completed)
