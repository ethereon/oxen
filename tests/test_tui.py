import unittest

from oxen.task import Task, TaskStatus
from oxen.tui import TaskHeader, TaskListItem, TaskLog, TUI


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
