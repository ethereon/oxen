from __future__ import annotations

import asyncio
import inspect

from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Footer, Label, ListItem, ListView, Log

from .publisher import SubscriptionStore
from .store import TaskOutputChange, TaskStatusChange, TaskStore
from .task import Task, TaskStatus

type ActionHandler = Callable[[TUI, Task | None], Any | Awaitable[Any]]
type ViewFactory = Callable[[TUI], Widget]


DEFAULT_BINDINGS: dict[str, str | None] = {
    'quit': 'q',
    'restart': 'r',
    'stop': 's',
    'run': 'g',
    'next_view': 'v',
}

DEFAULT_STATUS_COLORS: dict[TaskStatus, str] = {
    TaskStatus.PENDING: '#FFFFFF',
    TaskStatus.RUNNING: '#35C759',
    TaskStatus.COMPLETED: '#70B0EB',
    TaskStatus.FAILED: '#FF5C60',
    TaskStatus.STOPPED: '#FAC800',
}


def _status_text(task: Task, colors: Mapping[TaskStatus, str]) -> Text:
    color = colors.get(task.status, 'white')
    return Text.assemble(('● ', color), task.name)


class TaskListItem(ListItem):
    """
    One task in the navigation pane.
    """

    def __init__(self, task: Task, colors: Mapping[TaskStatus, str]) -> None:
        self.oxen_task = task
        self._colors = colors
        self._label = Label(_status_text(task, colors))
        super().__init__(self._label)

    def update_status(self) -> None:
        self._label.update(_status_text(self.oxen_task, self._colors))


class TaskList(ListView):
    """
    Navigation list containing every registered task.
    """

    def __init__(self, tasks: Iterable[Task], colors: Mapping[TaskStatus, str], **kwargs: Any) -> None:
        self._colors = colors
        super().__init__(*(TaskListItem(task, colors) for task in tasks), **kwargs)

    def item_for(self, task: Task) -> TaskListItem | None:
        return next((item for item in self.query(TaskListItem) if item.oxen_task is task), None)

    def select(self, task: Task | None) -> None:
        self.index = next(
            (index for index, item in enumerate(self.query(TaskListItem)) if item.oxen_task is task),
            None,
        )

    def add_task(self, task: Task) -> None:
        self.append(TaskListItem(task, self._colors))


class TaskLog(Log):
    """
    A live task output widget.

    Pass a task to pin the widget to it. With no task, its owner can change the
    displayed task with `select`.
    """

    def __init__(self, task: Task | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.oxen_task = task
        self.follows_selection = task is None

    def on_mount(self) -> None:
        self.reload()

    def select(self, task: Task | None) -> None:
        if not self.follows_selection or task is self.oxen_task:
            return
        self.oxen_task = task
        self.reload()

    def reload(self) -> None:
        self.clear()
        if self.oxen_task is not None:
            self.write(self.oxen_task.output.get_output())

    def append_output(self, task: Task, output: str) -> None:
        if task is self.oxen_task:
            self.write(output)


class TaskHeader(Label):
    def __init__(
        self,
        task: Task | None,
        colors: Mapping[TaskStatus, str],
    ) -> None:
        self._colors = colors
        super().__init__(
            _status_text(task, colors) if task is not None else '',
            classes='task-header',
        )

    def update_task(self, task: Task | None) -> None:
        self.update(_status_text(task, self._colors) if task is not None else '')


class TaskPanel(Vertical):
    """
    A reusable status-and-output panel for a single task.
    """

    def __init__(self, task: Task, colors: Mapping[TaskStatus, str], **kwargs: Any) -> None:
        self.oxen_task = task
        self._header = TaskHeader(task, colors)
        super().__init__(self._header, TaskLog(task), **kwargs)

    def update_status(self) -> None:
        self._header.update_task(self.oxen_task)


type SplitViewOrientation = Literal['horizontal', 'vertical']


class TaskSplitView(Container):
    """
    A built-in custom view that shows all tasks at once.
    """

    def __init__(
        self,
        store: TaskStore,
        colors: Mapping[TaskStatus, str],
        *,
        orientation: SplitViewOrientation = 'horizontal',
        **kwargs: Any,
    ) -> None:
        if orientation not in {'horizontal', 'vertical'}:
            raise ValueError("orientation must be 'horizontal' or 'vertical'")
        self._store = store
        self._colors = colors
        self._subscriptions = SubscriptionStore()
        super().__init__(
            *(TaskPanel(task, colors) for task in store.tasks),
            classes=f'task-split {orientation}',
            **kwargs,
        )

    def on_mount(self) -> None:
        self._subscriptions.add(
            self._store.on_task_added.subscribe(self._add_task),
            self._store.on_task_status_change.subscribe(self._update_task_status),
            self._store.on_task_output_change.subscribe(self._append_task_output),
        )

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def _add_task(self, task: Task) -> None:
        self.mount(TaskPanel(task, self._colors))

    def _update_task_status(self, change: TaskStatusChange) -> None:
        if panel := next((panel for panel in self.query(TaskPanel) if panel.oxen_task is change.task), None):
            panel.update_status()

    def _append_task_output(self, change: TaskOutputChange) -> None:
        for log in self.query(TaskLog):
            log.append_output(change.task, change.output)


class TaskBrowser(Horizontal):
    """
    Displays a list of tasks in a sidebar alongside a live output
    pane for the selected task.
    """

    def __init__(
        self,
        store: TaskStore,
        colors: Mapping[TaskStatus, str],
        **kwargs: Any,
    ) -> None:
        self._store = store
        self._subscriptions = SubscriptionStore()
        task_list = TaskList(store.tasks, colors, id='task-list')
        self._header = TaskHeader(store.selected_task, colors)
        self._log = TaskLog(id='selected-task-output')
        output = Vertical(
            self._header,
            self._log,
            id='output-pane',
        )
        super().__init__(
            Vertical(Label('Tasks', classes='pane-title'), task_list, id='task-pane'),
            output,
            **kwargs,
        )

    def on_mount(self) -> None:
        self._subscriptions.add(
            self._store.on_task_added.subscribe(self._add_task),
            self._store.on_selected_task_change.subscribe(self._select),
            self._store.on_task_status_change.subscribe(self._update_task_status),
            self._store.on_task_output_change.subscribe(self._append_task_output),
        )
        self.query_one(TaskList).focus()
        self._select(self._store.selected_task)

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, TaskListItem):
            self._store.select(event.item.oxen_task)

    def _add_task(self, task: Task) -> None:
        self.query_one(TaskList).add_task(task)

    def _update_task_status(self, change: TaskStatusChange) -> None:
        if item := self.query_one(TaskList).item_for(change.task):
            item.update_status()
        if self._store.selected_task is change.task:
            self._header.update_task(change.task)

    def _append_task_output(self, change: TaskOutputChange) -> None:
        self._log.append_output(change.task, change.output)

    def _select(self, task: Task | None) -> None:
        self.query_one(TaskList).select(task)
        self._header.update_task(task)
        self._log.select(task)


@dataclass(slots=True)
class ViewSpec:
    name: str
    factory: ViewFactory
    widget_id: str
    widget: Widget | None = None


class TUI(App[None]):
    """
    Task runner with a text-based user interface.
    """

    CSS_PATH = 'tui.tcss'

    def __init__(
        self,
        *tasks: Task,
        bindings: Mapping[str, str | None] | None = None,
        status_colors: Mapping[TaskStatus, str] | None = None,
        auto_start: bool = True,
        stop_tasks_on_exit: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.store = TaskStore()
        self.auto_start = auto_start
        self.stop_tasks_on_exit = stop_tasks_on_exit
        self.status_colors = {**DEFAULT_STATUS_COLORS, **(status_colors or {})}
        self._operations: set[asyncio.Task[Any]] = set()
        self._actions: dict[str, ActionHandler] = {}
        self._views: dict[str, ViewSpec] = {}
        self._view_order: list[str] = []
        self._mounted = False

        self.add(*tasks)
        self.add_view(
            'default',
            lambda app: TaskBrowser(app.store, app.status_colors),
        )

        configured_bindings = {**DEFAULT_BINDINGS, **(bindings or {})}
        descriptions = {
            'quit': 'Quit',
            'restart': 'Restart task',
            'stop': 'Stop task',
            'run': 'Run task',
            'next_view': 'Next view',
        }
        for action, key in configured_bindings.items():
            if key:
                self.bind(key, action, description=descriptions.get(action, action.replace('_', ' ').title()))

    def compose(self) -> ComposeResult:
        views = []
        for view in self._views.values():
            view.widget = view.factory(self)
            views.append(Container(view.widget, id=view.widget_id, classes='view-slot'))
        yield ContentSwitcher(*views, initial=self._views['default'].widget_id, id='views')
        yield Footer()

    @property
    def tasks(self) -> list[Task]:
        return self.store.tasks

    @property
    def selected_task(self) -> Task | None:
        """
        The task currently selected in the shared store.
        """
        return self.store.selected_task

    def add(self, *tasks: Task) -> None:
        """
        Register tasks with the TUI.
        """
        for task in tasks:
            self.store.add(task)
            if self._mounted and self.auto_start and task.auto_start and task.status is TaskStatus.PENDING:
                self._schedule(task.run(), f'run {task.name}')

    def __iadd__(self, task: Task) -> Self:
        self.add(task)
        return self

    def add_action(
        self,
        name: str,
        handler: ActionHandler,
        *,
        key: str | None = None,
        description: str | None = None,
        show: bool = True,
    ) -> None:
        """
        Register an action receiving `(tui, selected_task)`.
        """
        if not name or name in {'quit', 'restart', 'stop', 'run', 'next_view'}:
            raise ValueError(f'Invalid or reserved custom action name: {name!r}')
        self._actions[name] = handler
        if key:
            self.bind(
                key,
                f'invoke({name!r})',
                description=description or name.replace('_', ' ').title(),
                show=show,
            )

    def add_view(
        self,
        name: str,
        factory: ViewFactory,
        *,
        key: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Register a named view factory before the app starts.
        """
        if self._mounted:
            raise RuntimeError('Views must be registered before the TUI starts')
        if not name or name in self._views:
            raise ValueError(f'Invalid or duplicate view name: {name!r}')
        view = ViewSpec(name, factory, f'task-view-{len(self._views)}')
        self._views[name] = view
        self._view_order.append(name)
        if key:
            self.bind(
                key,
                f'show_view({name!r})',
                description=description or f'Show {name}',
            )

    def add_split_view(
        self,
        name: str,
        *,
        orientation: SplitViewOrientation = 'horizontal',
        key: str | None = None,
    ) -> None:
        """
        Convenience helper for an all-task horizontal or vertical view.
        """
        self.add_view(
            name,
            lambda app: TaskSplitView(app.store, app.status_colors, orientation=orientation),
            key=key,
        )

    def on_mount(self) -> None:
        self._mounted = True
        if self.auto_start:
            for task in self.tasks:
                if task.auto_start and task.status is TaskStatus.PENDING:
                    self._schedule(task.run(), f'run {task.name}')

    def on_unmount(self) -> None:
        self._mounted = False

    def _schedule(self, coroutine: Coroutine, description: str) -> None:
        operation = asyncio.create_task(coroutine, name=f'oxen: {description}')
        self._operations.add(operation)

        def completed(done: asyncio.Task[Any]) -> None:
            self._operations.discard(done)
            if done.cancelled():
                return
            if error := done.exception():
                self.notify(f'{description}: {error}', title='Task operation failed', severity='error')

        operation.add_done_callback(completed)

    async def action_quit(self) -> None:
        if self.stop_tasks_on_exit:
            await asyncio.gather(
                *(task.stop() for task in self.tasks if task.status is TaskStatus.RUNNING),
                return_exceptions=True,
            )
        self.exit()

    def action_restart(self) -> None:
        if task := self._require_selected_task():
            self._schedule(task.restart(), f'restart {task.name}')

    def action_stop(self) -> None:
        if task := self._require_selected_task():
            self._schedule(task.stop(), f'stop {task.name}')

    def action_run(self) -> None:
        if task := self._require_selected_task():
            if task.status is TaskStatus.RUNNING:
                self.notify(f'{task.name} is already running', severity='warning')
            else:
                self._schedule(task.run(), f'run {task.name}')

    def action_next_view(self) -> None:
        switcher = self.query_one('#views', ContentSwitcher)
        current_name = next(
            (name for name, view in self._views.items() if view.widget_id == switcher.current),
            'default',
        )
        index = (self._view_order.index(current_name) + 1) % len(self._view_order)
        self.action_show_view(self._view_order[index])

    def action_show_view(self, name: str) -> None:
        try:
            view = self._views[name]
        except KeyError:
            self.notify(f'Unknown view: {name}', severity='error')
            return
        self.query_one('#views', ContentSwitcher).current = view.widget_id

    async def action_invoke(self, name: str) -> None:
        try:
            handler = self._actions[name]
        except KeyError:
            self.notify(f'Unknown action: {name}', severity='error')
            return
        result = handler(self, self.selected_task)
        if inspect.isawaitable(result):
            await result

    def _require_selected_task(self) -> Task | None:
        if self.selected_task is None:
            self.notify('No task is selected', severity='warning')
        return self.selected_task
