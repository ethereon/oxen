import asyncio
import unittest

from oxen.core import Oxen, TaskOperationError, TaskOutputChange, TaskStatusChange
from oxen.task import BufferedTaskOutput, Task, TaskStatus


class FakeTask(Task):
    def __init__(
        self,
        name: str,
        result: TaskStatus = TaskStatus.COMPLETED,
        output: BufferedTaskOutput | None = None,
    ) -> None:
        super().__init__(name, output=output)
        self.result = result
        self.run_count = 0
        self.stop_count = 0

    async def _execute(self) -> TaskStatus:
        self.run_count += 1
        return self.result

    async def _interrupt(self) -> None:
        self.stop_count += 1


class FailingTask(FakeTask):
    async def _execute(self) -> TaskStatus:
        raise RuntimeError('broken')


class BlockingTask(FakeTask):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.release = asyncio.Event()

    async def _execute(self) -> TaskStatus:
        self.run_count += 1
        await self.release.wait()
        return self.result

    async def _interrupt(self) -> None:
        self.stop_count += 1
        self.release.set()


class CancellableTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.started = asyncio.Event()

    async def _execute(self) -> TaskStatus:
        self.started.set()
        await asyncio.Event().wait()
        return TaskStatus.COMPLETED


class InvalidResultTask(Task):
    async def _execute(self) -> TaskStatus:
        return TaskStatus.RUNNING


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
    def test_task_can_share_an_existing_output(self) -> None:
        output = BufferedTaskOutput()
        task = FakeTask('shared output', output=output)

        self.assertIs(task.output, output)

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

        task._set_status(TaskStatus.RUNNING)
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
    async def test_task_owns_status_transitions(self) -> None:
        task = FakeTask('task')
        statuses: list[TaskStatus] = []
        task.on_status_change.subscribe(statuses.append)

        with self.assertRaises(AttributeError):
            task.status = TaskStatus.RUNNING  # type: ignore[misc]

        await task.run()

        self.assertEqual(statuses, [TaskStatus.RUNNING, TaskStatus.COMPLETED])
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    async def test_task_maps_results_exceptions_and_invalid_results(self) -> None:
        failed = FakeTask('failed', result=TaskStatus.FAILED)
        await failed.run()
        self.assertEqual(failed.status, TaskStatus.FAILED)

        raised = FailingTask('raised')
        with self.assertRaisesRegex(RuntimeError, 'broken'):
            await raised.run()
        self.assertEqual(raised.status, TaskStatus.FAILED)

        invalid = InvalidResultTask('invalid')
        with self.assertRaisesRegex(ValueError, 'invalid terminal status'):
            await invalid.run()
        self.assertEqual(invalid.status, TaskStatus.FAILED)

    async def test_default_interrupt_cancels_execution(self) -> None:
        task = CancellableTask('task')
        runner = asyncio.create_task(task.run())
        await task.started.wait()

        await task.stop()

        await runner
        self.assertFalse(runner.cancelled())
        self.assertEqual(task.status, TaskStatus.STOPPED)

    async def test_external_cancellation_propagates(self) -> None:
        task = CancellableTask('task')
        runner = asyncio.create_task(task.run())
        await task.started.wait()

        runner.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await runner
        self.assertEqual(task.status, TaskStatus.STOPPED)

    async def test_rejects_overlapping_runs(self) -> None:
        task = BlockingTask('task')
        runner = asyncio.create_task(task.run())
        await asyncio_pause()

        with self.assertRaisesRegex(RuntimeError, 'already running'):
            await task.run()

        await task.stop()
        await runner

    async def test_restart_only_stops_a_running_task(self) -> None:
        for status in (TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED):
            with self.subTest(status=status):
                task = FakeTask('task')
                task._set_status(status)

                await task.restart()

                self.assertEqual(task.stop_count, 0)
                self.assertEqual(task.run_count, 1)

        task = BlockingTask('task')
        first_run = asyncio.create_task(task.run())
        await asyncio_pause()

        await task.restart()
        await first_run

        self.assertEqual(task.stop_count, 1)
        self.assertEqual(task.run_count, 2)

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
