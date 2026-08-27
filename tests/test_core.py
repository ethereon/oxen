import unittest

from oxen.core import Oxen, TaskOperationError, TaskOutputChange, TaskStatusChange
from oxen.task import Task, TaskStatus


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


class FailingTask(FakeTask):
    async def run(self) -> None:
        raise RuntimeError('broken')


class FakeUI:
    def __init__(self, oxen: Oxen) -> None:
        self.oxen = oxen
        self.run_count = 0
        self.layouts: list[tuple[object, str, bool, str | None]] = []

    def run(self) -> str:
        self.run_count += 1
        return 'ran'

    def add_layout(
        self,
        layout: object,
        *,
        name: str,
        default: bool = False,
        shortcut: str | None = None,
    ) -> None:
        self.layouts.append((layout, name, default, shortcut))


class OxenStateTest(unittest.TestCase):
    def test_adds_tasks_and_selects_the_first(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        oxen = Oxen(first, second)

        self.assertEqual(oxen.tasks, [first, second])
        self.assertIs(oxen.selected_task, first)

    def test_publishes_add_and_selection_changes(self) -> None:
        oxen = Oxen()
        first = FakeTask('first')
        second = FakeTask('second')
        added: list[Task] = []
        selected: list[Task | None] = []
        oxen.on_task_added.subscribe(added.append)
        oxen.on_selected_task_change.subscribe(selected.append)

        oxen.add(first, second)
        oxen.select(second)
        oxen.selected_task = None

        self.assertEqual(added, [first, second])
        self.assertEqual(selected, [first, second, None])

    def test_forwards_task_status_and_output_changes(self) -> None:
        task = FakeTask('task')
        oxen = Oxen(task)
        statuses: list[TaskStatusChange] = []
        outputs: list[TaskOutputChange] = []
        oxen.on_task_status_change.subscribe(statuses.append)
        oxen.on_task_output_change.subscribe(outputs.append)

        task.status = TaskStatus.RUNNING
        task.output.append('hello')

        self.assertEqual(statuses, [TaskStatusChange(task, TaskStatus.RUNNING)])
        self.assertEqual(outputs, [TaskOutputChange(task, 'hello')])

    def test_rejects_duplicate_and_unregistered_tasks(self) -> None:
        task = FakeTask('task')
        other = FakeTask('other')
        oxen = Oxen(task)

        with self.assertRaises(ValueError):
            oxen.add(task)
        with self.assertRaises(ValueError):
            oxen.select(other)

    def test_add_layout_registers_tasks_and_delegates_to_ui(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        oxen = Oxen(first, auto_start=False, ui=FakeUI)

        oxen.add_layout([(first, second), [second]], name='Main', default=True, shortcut='m')

        self.assertEqual(oxen.tasks, [first, second])
        self.assertEqual(oxen.ui.layouts, [([(first, second), [second]], 'Main', True, 'm')])


class OxenTest(unittest.IsolatedAsyncioTestCase):
    async def test_constructs_and_runs_configured_ui(self) -> None:
        oxen = Oxen(ui=FakeUI)

        self.assertEqual(oxen.run(), 'ran')
        self.assertIs(oxen.ui, oxen.ui)
        self.assertIs(oxen.ui.oxen, oxen)
        self.assertEqual(oxen.ui.run_count, 1)

    async def test_reports_operation_errors_without_a_ui(self) -> None:
        task = FailingTask('failure')
        oxen = Oxen(task, auto_start=False)
        failures: list[TaskOperationError] = []
        oxen.on_task_operation_error.subscribe(failures.append)

        oxen.run_task(task)
        await asyncio_pause()

        self.assertEqual(len(failures), 1)
        self.assertIs(failures[0].task, task)
        self.assertEqual(failures[0].operation, 'run')
        self.assertIsInstance(failures[0].error, RuntimeError)


async def asyncio_pause() -> None:
    # Two turns allow the operation and its done callback to run.
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)


if __name__ == '__main__':
    unittest.main()
