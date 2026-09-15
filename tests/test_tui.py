import unittest

from textual.containers import Container
from textual.widgets import ContentSwitcher, Log, RichLog

from oxen.core import Oxen
from oxen.task import Task, TaskStatus
from oxen.tui import OxenTUI, TaskHeader, TaskSplitView, TaskListItem, TaskLog, TaskPanel


def task_log_lines(task_log: TaskLog) -> list[str]:
    log = task_log._log
    return [line.text for line in log.lines] if isinstance(log, RichLog) else log._lines


class FakeTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.stop_count = 0

    async def execute(self) -> bool:
        return True

    async def interrupt(self) -> None:
        self.stop_count += 1


class OxenTest(unittest.IsolatedAsyncioTestCase):
    async def test_auto_start_requires_task_flag(self) -> None:
        enabled = FakeTask('enabled')
        disabled = FakeTask('disabled')
        disabled.auto_start = False
        oxen = Oxen(enabled, disabled)
        app = oxen.ui

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(enabled.run_count, 1)
            self.assertEqual(disabled.run_count, 0)

            added_enabled = FakeTask('added-enabled')
            added_disabled = FakeTask('added-disabled')
            added_disabled.auto_start = False
            oxen.add(added_enabled, added_disabled)
            await pilot.pause()

            self.assertEqual(added_enabled.run_count, 1)
            self.assertEqual(added_disabled.run_count, 0)

    async def test_live_output_status_and_task_actions(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        app = Oxen(first, second, auto_start=False).ui

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(app.query(TaskListItem)), 2)

            output = first.output
            output.append('hello\n')
            first._set_status(TaskStatus.FAILED)
            await pilot.pause()

            selected_log = app.query_one('#selected-task-output', TaskLog)
            selected_header = app.query_one('#output-pane TaskHeader', TaskHeader)
            self.assertIn('hello', '\n'.join(task_log_lines(selected_log)))
            self.assertIsInstance(selected_log._log, Log)
            self.assertIsNone(selected_log._terminal)
            self.assertEqual(len(selected_log.children), 1)
            self.assertEqual(selected_header.content.plain, '● first')
            first_item = app.query_one(TaskListItem)
            self.assertEqual(first_item.oxen_task.status, TaskStatus.FAILED)

            await pilot.press('r')
            await pilot.pause()
            self.assertEqual(first.stop_count, 0)
            self.assertEqual(first.run_count, 1)

            await pilot.press('down')
            await pilot.pause()
            self.assertIs(app.selected_task, second)
            self.assertEqual(selected_header.content.plain, '● second')

    async def test_task_header_shows_count_after_second_run(self) -> None:
        task = FakeTask('repeated')
        app = Oxen(task, auto_start=False).ui

        async with app.run_test() as pilot:
            await pilot.pause()
            header = app.query_one('#output-pane TaskHeader', TaskHeader)
            self.assertEqual(header.content.plain, '● repeated')

            await task.run()
            await pilot.pause()
            self.assertEqual(header.content.plain, '● repeated')

            await task.run()
            await pilot.pause()
            self.assertEqual(header.content.plain, '● repeated (2)')

            await task.run()
            await pilot.pause()
            self.assertEqual(header.content.plain, '● repeated (3)')

    async def test_task_output_interprets_terminal_control_sequences(self) -> None:
        task = FakeTask('terminal')
        app = Oxen(task, auto_start=False).ui

        async with app.run_test() as pilot:
            await pilot.pause()
            output = task.output
            output.append('\x1b[31mold screen\x1b[0m\n')
            output.append('\x1b[2')
            output.append('J\x1b[Hprogress: 10%')
            output.append('\rprogress: 20%')
            output.append('\b\b\b25%\n')
            await pilot.pause()

            log = app.query_one('#selected-task-output', TaskLog)
            self.assertEqual(task_log_lines(log), ['progress: 25%', ''])

            output.append('\x1b[31mred\x1b[0m')
            await pilot.pause()
            rich_log = log._log
            assert isinstance(rich_log, RichLog)
            red_segment = next(segment for segment in rich_log.lines[-1] if segment.text == 'red')
            self.assertEqual(red_segment.style.color.number, 1)
            self.assertIsNotNone(log._terminal)
            self.assertEqual(len(log.children), 1)

    async def test_task_log_replays_controls_when_switching_tasks(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        first.output.append('obsolete\n\x1b[2J\x1b[Hcurrent')
        app = Oxen(first, second, auto_start=False).ui

        async with app.run_test() as pilot:
            await pilot.pause()
            log = app.query_one('#selected-task-output', TaskLog)
            self.assertEqual(task_log_lines(log), ['current'])

            await pilot.press('down')
            await pilot.press('up')
            await pilot.pause()
            self.assertEqual(task_log_lines(log), ['current'])

    async def test_default_binding_can_be_replaced(self) -> None:
        task = FakeTask('task')
        app = Oxen(
            task,
            auto_start=False,
            ui=lambda oxen: OxenTUI(oxen, bindings={'restart': 'x'}),
        ).ui

        async with app.run_test() as pilot:
            await pilot.press('r')
            await pilot.pause()
            self.assertEqual(task.run_count, 0)

            await pilot.press('x')
            await pilot.pause()
            self.assertEqual(task.run_count, 1)

    async def test_next_view_action_requires_multiple_views(self) -> None:
        single_view = Oxen(auto_start=False)
        async with single_view.ui.run_test() as pilot:
            await pilot.pause()
            self.assertFalse(any(binding.action == 'next_view' for _, binding, _, _ in single_view.ui.screen.active_bindings.values()))

        multiple_views = Oxen(auto_start=False)
        task = FakeTask('task')
        multiple_views.add_layout([task], name='Layout')
        async with multiple_views.ui.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(any(binding.action == 'next_view' for _, binding, _, _ in multiple_views.ui.screen.active_bindings.values()))

    async def test_add_layout_registers_tasks_and_builds_nested_splits(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        third = FakeTask('third')
        oxen = Oxen(auto_start=False)
        oxen.add_layout(
            [
                (first, second),
                [(third,)],
            ],
            name='Main',
            default=True,
            shortcut='m',
        )
        app = oxen.ui

        self.assertEqual(app.tasks, [first, second, third])
        async with app.run_test() as pilot:
            await pilot.pause()
            switcher = app.query_one('#views', ContentSwitcher)
            self.assertEqual(switcher.current, app._views['Main'].widget_id)

            layout = app.query_one(TaskSplitView)
            self.assertTrue(layout.has_class('vertical'))
            top_row = layout.children[0]
            nested_column = layout.children[1]
            bottom_row = nested_column.children[0]
            self.assertTrue(top_row.has_class('horizontal'))
            self.assertTrue(nested_column.has_class('vertical'))
            self.assertTrue(bottom_row.has_class('horizontal'))
            nested = [container for container in layout.query(Container) if not isinstance(container, TaskPanel)]
            self.assertTrue(any(container.has_class('horizontal') for container in nested))
            self.assertTrue(any(container.has_class('vertical') for container in nested))
            self.assertEqual([panel.oxen_task for panel in layout.query(TaskPanel)], [first, second, third])
            first_panel = next(panel for panel in layout.query(TaskPanel) if panel.oxen_task is first)
            self.assertTrue(first_panel.has_focus_within)

            first.output.append('layout output\n')
            first._set_status(TaskStatus.FAILED)
            await pilot.pause()
            second_panel = next(panel for panel in layout.query(TaskPanel) if panel.oxen_task is second)
            first_header = first_panel.query_one(TaskHeader)
            second_header = second_panel.query_one(TaskHeader)
            self.assertEqual(first_header.content.plain, '● first')
            self.assertEqual(second_header.content.plain, '● second')
            self.assertIn('layout output', '\n'.join(task_log_lines(first_panel.query_one(TaskLog))))

            self.assertTrue(await pilot.click(second_panel.query_one(TaskLog)))
            await pilot.pause()
            self.assertIs(app.selected_task, second)
            self.assertFalse(first_panel.has_focus_within)
            self.assertTrue(second_panel.has_focus_within)

            app.action_show_view('default')
            await pilot.press('m')
            await pilot.pause()
            self.assertEqual(switcher.current, app._views['Main'].widget_id)
            self.assertTrue(second_panel.has_focus_within)

    async def test_layout_selects_first_task_when_current_selection_is_absent(self) -> None:
        selected = FakeTask('selected')
        first_visible = FakeTask('first visible')
        second_visible = FakeTask('second visible')
        oxen = Oxen(selected, auto_start=False)
        oxen.add_layout([first_visible, second_visible], name='Subset')
        app = oxen.ui

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIs(app.selected_task, selected)

            app.action_show_view('Subset')
            await pilot.pause()

            layout = app.query_one(TaskSplitView)
            first_panel = next(panel for panel in layout.query(TaskPanel) if panel.oxen_task is first_visible)
            self.assertIs(app.selected_task, first_visible)
            self.assertTrue(first_panel.has_focus_within)

    def test_add_layout_reuses_registered_tasks_and_validates_shape(self) -> None:
        task = FakeTask('task')
        oxen = Oxen(task, auto_start=False)
        oxen.add_layout([(task, task)], name='Repeated')
        self.assertEqual(oxen.tasks, [task])

        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            oxen.add_layout([], name='Empty')
        with self.assertRaisesRegex(TypeError, 'must be a Task, list, or tuple'):
            oxen.add_layout([[object()]], name='Invalid')


if __name__ == '__main__':
    unittest.main()
