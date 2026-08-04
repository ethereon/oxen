import unittest

from oxen.task import Task, TaskStatus
from oxen.tui import TaskListItem, TaskLog, TUI
from textual.widgets import ContentSwitcher


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
            self.assertIn('hello', '\n'.join(str(line) for line in selected_log.lines))
            first_item = app.query_one(TaskListItem)
            self.assertEqual(first_item.oxen_task.status, TaskStatus.FAILED)

            await pilot.press('r')
            await pilot.pause()
            self.assertEqual(first.stop_count, 1)
            self.assertEqual(first.run_count, 1)

            await pilot.press('down')
            await pilot.pause()
            self.assertIs(app.selected_task, second)

    async def test_custom_action_and_split_view_shortcuts(self) -> None:
        task = FakeTask('task')
        app = TUI(task, auto_start=False)
        app.add_split_view('stacked', orientation='vertical', key='2')
        invoked: list[Task | None] = []
        app.add_action('capture', lambda _, selected: invoked.append(selected), key='c')

        async with app.run_test() as pilot:
            await pilot.press('c', '2')
            await pilot.pause()

            self.assertEqual(invoked, [task])
            self.assertEqual(app.query_one('#views', ContentSwitcher).current, 'task-view-1')

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


if __name__ == '__main__':
    unittest.main()
