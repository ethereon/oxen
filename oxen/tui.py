from __future__ import annotations

import inspect

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Footer, Label, ListItem, ListView, Log, RichLog

from .core import Oxen, TaskOperationError, TaskOutputChange, TaskStatusChange
from .publisher import SubscriptionStore
from .task import Task, TaskStatus
from .terminal import TerminalBuffer, contains_terminal_controls
from .ui import TaskLayout

# The return value of the action handler is opaque from the perspective
# of OxenTUI. However, if an awaitable is returned, OxenTUI will await it.
type ActionHandler = Callable[[OxenTUI, Task | None], object]

type ViewFactory = Callable[[OxenTUI], Widget]

ACTION_DESCRIPTIONS: dict[str, str] = {
    'restart': 'Restart Task',
    'stop': 'Stop Task',
    'run': 'Run Task',
    'next_view': 'Next View',
    'quit': 'Quit',
}

DEFAULT_BINDINGS: dict[str, str | None] = {
    'restart': 'r',
    'stop': 's',
    'run': 'g',
    'next_view': 'v',
    'quit': 'q',
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


class TaskLog(Widget):
    """
    A live task output widget.

    Pass a task to pin the widget to it. With no task, its owner can change the
    displayed task with `select`.
    """

    can_focus = True

    def __init__(self, task: Task | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.oxen_task = task
        self.follows_selection = task is None
        self._terminal: TerminalBuffer | None = None
        self._log: Log | RichLog = Log()
        self._sync_pending = False

    def compose(self) -> ComposeResult:
        yield self._log

    def on_mount(self) -> None:
        self._sync_pending = False
        self.reload()

    def on_focus(self) -> None:
        self._log.focus()

    def select(self, task: Task | None) -> None:
        if not self.follows_selection or task is self.oxen_task:
            return
        self.oxen_task = task
        self.reload()

    def reload(self) -> None:
        output = '' if self.oxen_task is None else self.oxen_task.output.get_output()
        rich = contains_terminal_controls(output)
        self._set_rich_mode(rich)
        self._log.clear()

        if rich:
            assert isinstance(self._log, RichLog)
            self._terminal = TerminalBuffer()
            self._terminal.feed(output)
            self._log.write(self._terminal.render_text())
        else:
            assert isinstance(self._log, Log)
            self._terminal = None
            self._log.write(output)

    def append_output(self, task: Task, output: str) -> None:
        if task is not self.oxen_task:
            return

        if self._terminal is None and not contains_terminal_controls(output):
            self._log.write(output)
            return

        if self._terminal is None:
            self._terminal = TerminalBuffer()
            self._terminal.feed(task.output.get_output())
            self._set_rich_mode(True)
        else:
            self._terminal.feed(output)
        self._schedule_sync()

    def _schedule_sync(self) -> None:
        if self._sync_pending:
            return

        self._sync_pending = True
        if not self._log.call_after_refresh(self._flush_output):
            self._sync_pending = False
            self._sync_output()

    def _flush_output(self) -> None:
        self._sync_pending = False
        if isinstance(self._log, RichLog):
            self._sync_output()

    def _sync_output(self) -> None:
        assert isinstance(self._log, RichLog)
        assert self._terminal is not None
        self._log.clear()
        self._log.write(self._terminal.render_text())

    def _set_rich_mode(self, rich: bool) -> None:
        if rich == isinstance(self._log, RichLog):
            return
        had_focus = self.has_focus_within
        old_log = self._log
        self._log = RichLog() if rich else Log()
        old_log.remove()
        self.mount(self._log)
        if had_focus:
            self._log.focus()


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


class TaskSplitView(Container):
    """
    A recursively nested split view of task panels.

    Lists stack their children vertically and tuples stack them horizontally.
    """

    def __init__(
        self,
        layout: TaskLayout,
        oxen: Oxen,
        colors: Mapping[TaskStatus, str],
        **kwargs: Any,
    ) -> None:
        self._oxen = oxen
        self._subscriptions = SubscriptionStore()
        super().__init__(
            *self._children(layout, colors),
            classes=f'task-layout-split {self._orientation(layout)}',
            **kwargs,
        )

    @staticmethod
    def _orientation(layout: TaskLayout) -> Literal['horizontal', 'vertical']:
        return 'vertical' if isinstance(layout, list) else 'horizontal'

    @classmethod
    def _children(
        cls,
        layout: TaskLayout,
        colors: Mapping[TaskStatus, str],
    ) -> list[Widget]:
        return [
            TaskPanel(item, colors)
            if isinstance(item, Task)
            else Container(
                *cls._children(item, colors),
                classes=f'task-layout-split {cls._orientation(item)}',
            )
            for item in layout
        ]

    def on_mount(self) -> None:
        self._subscriptions.add(
            self._oxen.on_task_status_change.subscribe(self._update_task_status),
            self._oxen.on_task_output_change.subscribe(self._append_task_output),
        )

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def on_show(self) -> None:
        # Focus the currently selected task.
        # It's possible that the currently selected task is not present
        # in this view. If that's the case, select and focus the first visible view.
        logs = list(self.query(TaskLog))
        log = next(
            (log for log in logs if log.oxen_task is self._oxen.selected_task),
            logs[0],
        )
        self._oxen.select(log.oxen_task)
        log.focus()

    def _update_task_status(self, change: TaskStatusChange) -> None:
        for panel in self.query(TaskPanel):
            if panel.oxen_task is change.task:
                panel.update_status()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if panel := event.widget.query_ancestor(TaskPanel):
            self._oxen.select(panel.oxen_task)

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
        oxen: Oxen,
        colors: Mapping[TaskStatus, str],
        **kwargs: Any,
    ) -> None:
        self._oxen = oxen
        self._subscriptions = SubscriptionStore()
        task_list = TaskList(oxen.tasks, colors, id='task-list')
        self._header = TaskHeader(oxen.selected_task, colors)
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
            self._oxen.on_task_added.subscribe(self._add_task),
            self._oxen.on_selected_task_change.subscribe(self._select),
            self._oxen.on_task_status_change.subscribe(self._update_task_status),
            self._oxen.on_task_output_change.subscribe(self._append_task_output),
        )
        self._select(self._oxen.selected_task)

    def on_unmount(self) -> None:
        self._subscriptions.clear()

    def on_show(self) -> None:
        self.query_one(TaskList).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, TaskListItem):
            self._oxen.select(event.item.oxen_task)

    def _add_task(self, task: Task) -> None:
        self.query_one(TaskList).add_task(task)

    def _update_task_status(self, change: TaskStatusChange) -> None:
        if item := self.query_one(TaskList).item_for(change.task):
            item.update_status()
        if self._oxen.selected_task is change.task:
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


class OxenTUI(App[None]):
    """
    Interactive text-based UI for Oxen tasks.
    """

    CSS_PATH = 'tui.tcss'

    def __init__(
        self,
        oxen: Oxen,
        bindings: Mapping[str, str | None] | None = None,
        status_colors: Mapping[TaskStatus, str] | None = None,
        stop_tasks_on_exit: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.oxen = oxen
        self.stop_tasks_on_exit = stop_tasks_on_exit
        self.status_colors = {**DEFAULT_STATUS_COLORS, **(status_colors or {})}
        self._subscriptions = SubscriptionStore()
        self._actions: dict[str, ActionHandler] = {}
        self._views: dict[str, ViewSpec] = {}
        self._view_order: list[str] = []
        self._default_view = 'default'
        self._mounted = False

        self.add_view(
            'default',
            lambda app: TaskBrowser(app.oxen, app.status_colors),
        )

        configured_bindings = {**DEFAULT_BINDINGS, **(bindings or {})}
        for action, key in configured_bindings.items():
            if key:
                self.bind(
                    key,
                    action,
                    description=ACTION_DESCRIPTIONS[action],
                )

    def compose(self) -> ComposeResult:
        views = []
        for view in self._views.values():
            view.widget = view.factory(self)
            views.append(Container(view.widget, id=view.widget_id, classes='view-slot'))
        yield ContentSwitcher(*views, initial=self._views[self._default_view].widget_id, id='views')
        yield Footer()

    @property
    def tasks(self) -> list[Task]:
        return self.oxen.tasks

    @property
    def selected_task(self) -> Task | None:
        return self.oxen.selected_task

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
        if (not name) or (name in ACTION_DESCRIPTIONS):
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
        shortcut: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        Register a named view factory before the app starts.
        """
        if self._mounted:
            raise RuntimeError('Views must be registered before Oxen starts')
        if not name or name in self._views:
            raise ValueError(f'Invalid or duplicate view name: {name!r}')
        view = ViewSpec(name, factory, f'task-view-{len(self._views)}')
        self._views[name] = view
        self._view_order.append(name)
        if shortcut:
            self.bind(
                shortcut,
                f'show_view({name!r})',
                description=description or name,
            )

    def add_layout(
        self,
        layout: TaskLayout,
        *,
        name: str,
        default: bool = False,
        shortcut: str | None = None,
    ) -> None:
        self.add_view(
            name,
            lambda app: TaskSplitView(layout, app.oxen, app.status_colors),
            shortcut=shortcut,
        )
        if default:
            self._default_view = name

    def on_mount(self) -> None:
        self._mounted = True
        self._subscriptions.add(self.oxen.on_task_operation_error.subscribe(self._notify_operation_error))
        self.oxen.start()

    def on_unmount(self) -> None:
        self._mounted = False
        self._subscriptions.clear()

    def _notify_operation_error(self, failure: TaskOperationError) -> None:
        self.notify(
            f'{failure.operation} {failure.task.name}: {failure.error}',
            title='Task operation failed',
            severity='error',
        )

    async def action_quit(self) -> None:
        if self.stop_tasks_on_exit:
            await self.oxen.shutdown()
        self.exit()

    def action_restart(self) -> None:
        if task := self._require_selected_task():
            self.oxen.restart_task(task)

    def action_stop(self) -> None:
        if task := self._require_selected_task():
            self.oxen.stop_task(task)

    def action_run(self) -> None:
        if task := self._require_selected_task():
            if task.status is TaskStatus.RUNNING:
                self.notify(f'{task.name} is already running', severity='warning')
            else:
                self.oxen.run_task(task)

    def action_next_view(self) -> None:
        switcher = self.query_one('#views', ContentSwitcher)
        current_name = next(
            (name for name, view in self._views.items() if view.widget_id == switcher.current),
            'default',
        )
        index = (self._view_order.index(current_name) + 1) % len(self._view_order)
        self.action_show_view(self._view_order[index])

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'next_view' and len(self._views) <= 1:
            return False
        return super().check_action(action, parameters)

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
