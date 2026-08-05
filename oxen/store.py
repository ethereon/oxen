from __future__ import annotations

from dataclasses import dataclass

from .publisher import Publisher, SubscriptionStore
from .task import Task, TaskStatus


@dataclass(frozen=True, slots=True)
class TaskStatusChange:
    task: Task
    status: TaskStatus


@dataclass(frozen=True, slots=True)
class TaskOutputChange:
    task: Task
    output: str


class TaskStore:
    """
    The shared state and event source for a collection of tasks.

    The store also forwards status and output changes from its registered tasks,
    adding the task associated with each change to the published event.
    """

    def __init__(self, *tasks: Task) -> None:
        self.tasks: list[Task] = []
        self._selected_task: Task | None = None
        self._subscriptions = SubscriptionStore()

        self.on_task_added = Publisher[Task]()
        self.on_selected_task_change = Publisher[Task | None]()
        self.on_task_status_change = Publisher[TaskStatusChange]()
        self.on_task_output_change = Publisher[TaskOutputChange]()

        self.add(*tasks)

    @property
    def selected_task(self) -> Task | None:
        return self._selected_task

    @selected_task.setter
    def selected_task(self, task: Task | None) -> None:
        self.select(task)

    def select(self, task: Task | None) -> None:
        """
        Select a registered task, or clear the selection with `None`.
        """
        if task is not None and not any(registered is task for registered in self.tasks):
            raise ValueError(f'Task {task.name!r} is not registered')
        if task is self._selected_task:
            return

        self._selected_task = task
        self.on_selected_task_change.publish(task)

    def add(self, *tasks: Task) -> None:
        """
        Register tasks and select the first task added to an empty store.
        """
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
