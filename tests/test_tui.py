import unittest

from textual.containers import Container
from textual.widgets import ContentSwitcher

from oxen.task import Task, TaskStatus
from oxen.tui import TaskHeader, TaskSplitView, TaskListItem, TaskLog, TaskPanel, TUI


class FakeTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.run_count = 0
        self.stop_count = 0

    async def run(self) -> None:
        self.run_count += 1
        self.status = TaskStatus.RUNNING

    async def stop(self) -> None:
        self.stop_count += 1
        self.status = TaskStatus.STOPPED


class TUITest(unittest.IsolatedAsyncioTestCase):
    async def test_auto_start_requires_task_flag(self) -> None:
        enabled = FakeTask('enabled')
        disabled = FakeTask('disabled')
        disabled.auto_start = False
        app = TUI(enabled, disabled)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(enabled.run_count, 1)
            self.assertEqual(disabled.run_count, 0)

            added_enabled = FakeTask('added-enabled')
            added_disabled = FakeTask('added-disabled')
            added_disabled.auto_start = False
            app.add(added_enabled, added_disabled)
            await pilot.pause()

            self.assertEqual(added_enabled.run_count, 1)
            self.assertEqual(added_disabled.run_count, 0)

    async def test_live_output_status_and_task_actions(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        app = TUI(first, second, auto_start=False)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(app.query(TaskListItem)), 2)

            output = first.output
            output.append('hello\n')
            first.status = TaskStatus.FAILED
            await pilot.pause()

            selected_log = app.query_one('#selected-task-output', TaskLog)
            selected_header = app.query_one('#output-pane TaskHeader', TaskHeader)
            self.assertIn('hello', '\n'.join(str(line) for line in selected_log.lines))
            self.assertEqual(selected_header.content.plain, '● first')
            first_item = app.query_one(TaskListItem)
            self.assertEqual(first_item.oxen_task.status, TaskStatus.FAILED)

            await pilot.press('r')
            await pilot.pause()
            self.assertEqual(first.stop_count, 1)
            self.assertEqual(first.run_count, 1)

            await pilot.press('down')
            await pilot.pause()
            self.assertIs(app.selected_task, second)
            self.assertEqual(selected_header.content.plain, '● second')

    async def test_task_output_interprets_terminal_control_sequences(self) -> None:
        task = FakeTask('terminal')
        app = TUI(task, auto_start=False)

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
            self.assertEqual([str(line) for line in log.lines], ['progress: 25%', ''])

    async def test_task_log_replays_controls_when_switching_tasks(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        first.output.append('obsolete\n\x1b[2J\x1b[Hcurrent')
        app = TUI(first, second, auto_start=False)

        async with app.run_test() as pilot:
            await pilot.pause()
            log = app.query_one('#selected-task-output', TaskLog)
            self.assertEqual([str(line) for line in log.lines], ['current'])

            await pilot.press('down')
            await pilot.press('up')
            await pilot.pause()
            self.assertEqual([str(line) for line in log.lines], ['current'])

    async def test_default_binding_can_be_replaced(self) -> None:
        task = FakeTask('task')
        app = TUI(task, auto_start=False, bindings={'restart': 'x'})

        async with app.run_test() as pilot:
            await pilot.press('r')
            await pilot.pause()
            self.assertEqual(task.run_count, 0)

            await pilot.press('x')
            await pilot.pause()
            self.assertEqual(task.run_count, 1)

    async def test_add_layout_registers_tasks_and_builds_nested_splits(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        third = FakeTask('third')
        app = TUI(auto_start=False)
        app.add_layout(
            [
                (first, second),
                [(third,)],
            ],
            name='Main',
            default=True,
            shortcut='m',
        )

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
            first.status = TaskStatus.FAILED
            await pilot.pause()
            second_panel = next(panel for panel in layout.query(TaskPanel) if panel.oxen_task is second)
            first_header = first_panel.query_one(TaskHeader)
            second_header = second_panel.query_one(TaskHeader)
            self.assertEqual(first_header.content.plain, '● first')
            self.assertEqual(second_header.content.plain, '● second')
            self.assertIn('layout output', '\n'.join(str(line) for line in first_panel.query_one(TaskLog).lines))

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

    def test_add_layout_reuses_registered_tasks_and_validates_shape(self) -> None:
        task = FakeTask('task')
        app = TUI(task, auto_start=False)
        app.add_layout([(task, task)], name='Repeated')
        self.assertEqual(app.tasks, [task])

        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            app.add_layout([], name='Empty')
        with self.assertRaisesRegex(TypeError, 'must be a Task, list, or tuple'):
            app.add_layout([[object()]], name='Invalid')


if __name__ == '__main__':
    unittest.main()
