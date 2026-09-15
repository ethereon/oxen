import asyncio
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oxen import Task, TaskStatus

try:
    from oxen.watch import Watch
except ImportError:
    WATCHDOG_AVAILABLE = False
else:
    WATCHDOG_AVAILABLE = True


class FakeTask(Task):
    def __init__(self) -> None:
        super().__init__('target')
        self.stop_count = 0

    async def execute(self) -> TaskStatus:
        return TaskStatus.COMPLETED

    async def interrupt(self) -> None:
        self.stop_count += 1


class ClearingTask(FakeTask):
    async def execute(self) -> TaskStatus:
        if self.run_count > 1:
            self.output.clear()
        return await super().execute()


class FakeObserver:
    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler: object, path: str, *, recursive: bool) -> None:
        self.scheduled.append((handler, path, recursive))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self) -> None:
        self.joined = True

    def dispatch(self, src_path: Path, dest_path: Path | None = None, event_type: str = 'modified') -> None:
        event = SimpleNamespace(src_path=str(src_path), dest_path=str(dest_path) if dest_path else '', event_type=event_type)
        for handler, _, _ in self.scheduled:
            handler.dispatch(event)


@unittest.skipUnless(WATCHDOG_AVAILABLE, 'watchdog is not installed')
class WatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_task_on_start_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = FakeTask()
            observer = FakeObserver()
            watch = Watch(temporary_directory, task=target, run_on_start=True)

            with patch('oxen.watch.Observer', return_value=observer):
                runner = asyncio.create_task(watch.run())
                await self._wait_until(lambda: target.run_count == 1)
                await watch.stop()
                await runner

            self.assertTrue(observer.started)
            self.assertEqual(target.run_count, 1)

    async def test_batches_changes_until_the_interval_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = FakeTask()
            observer = FakeObserver()
            watch = Watch(root, task=target, debounce=0.1)

            with patch('oxen.watch.Observer', return_value=observer):
                runner = asyncio.create_task(watch.run())
                await self._wait_until(lambda: observer.started)

                observer.dispatch(root / 'first.py')
                await asyncio.sleep(0.05)
                observer.dispatch(root / 'second.py')
                await asyncio.sleep(0.06)
                self.assertEqual(target.run_count, 0)

                await self._wait_until(lambda: target.run_count == 1)
                await asyncio.sleep(0.12)
                self.assertEqual(target.run_count, 1)
                await watch.stop()
                await runner

    async def test_stop_discards_pending_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = FakeTask()
            observer = FakeObserver()
            watch = Watch(root, task=target, debounce=1)

            with patch('oxen.watch.Observer', return_value=observer):
                runner = asyncio.create_task(watch.run())
                await self._wait_until(lambda: observer.started)
                observer.dispatch(root / 'changed.py')
                await asyncio.sleep(0)
                await watch.stop()
                await runner

            self.assertEqual(target.run_count, 0)

    async def test_zero_interval_restarts_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = FakeTask()
            observer = FakeObserver()
            watch = Watch(root, task=target, debounce=0)

            with patch('oxen.watch.Observer', return_value=observer):
                runner = asyncio.create_task(watch.run())
                await self._wait_until(lambda: observer.started)
                observer.dispatch(root / 'changed.py')
                await self._wait_until(lambda: target.run_count == 1)
                await watch.stop()
                await runner

    async def test_rejects_invalid_debounce(self) -> None:
        for interval in (-1, float('nan'), float('inf')):
            with self.subTest(interval=interval), self.assertRaisesRegex(ValueError, 'debounce'):
                Watch('.', task=FakeTask(), debounce=interval)

    async def test_watches_directories_and_individual_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            directory = root / 'source'
            directory.mkdir()
            watched_file = root / 'config.toml'
            watched_file.touch()
            unrelated_file = root / 'other.toml'
            unrelated_file.touch()

            target = FakeTask()
            observer = FakeObserver()
            watch = Watch(directory, watched_file, task=target)

            self.assertIs(watch.output, target.output)
            target.output.append('initial output\n')
            self.assertEqual(watch.output.text, 'initial output\n')

            with patch('oxen.watch.Observer', return_value=observer):
                runner = asyncio.create_task(watch.run())
                await self._wait_until(lambda: observer.started)

                scheduled = {(Path(path), recursive) for _, path, recursive in observer.scheduled}
                self.assertEqual(scheduled, {(directory, True), (root, False)})

                observer.dispatch(unrelated_file)
                await asyncio.sleep(0)
                self.assertEqual(target.run_count, 0)

                observer.dispatch(watched_file, event_type='opened')
                await asyncio.sleep(0)
                self.assertEqual(target.run_count, 0)

                observer.dispatch(directory / 'module.py')
                await self._wait_until(lambda: target.run_count == 1)

                observer.dispatch(watched_file)
                await self._wait_until(lambda: target.run_count == 2)

                terminal_cleanup: list[bool] = []

                def record_cleanup_state(status: TaskStatus) -> None:
                    if status is TaskStatus.STOPPED:
                        terminal_cleanup.append(observer.joined and watch._observer is None and watch._runner is None and watch._run_complete.is_set())

                watch.on_status_change.subscribe(record_cleanup_state)
                await watch.stop()
                await runner

            self.assertEqual(watch.status, TaskStatus.STOPPED)
            self.assertEqual(target.stop_count, 0)
            self.assertTrue(observer.stopped)
            self.assertTrue(observer.joined)
            self.assertEqual(terminal_cleanup, [True])

    async def test_rejects_missing_paths_when_started(self) -> None:
        watch = Watch('/a/path/that/does/not/exist', task=FakeTask())
        terminal_cleanup: list[bool] = []

        def record_cleanup_state(status: TaskStatus) -> None:
            if status is TaskStatus.FAILED:
                terminal_cleanup.append(watch._observer is None and watch._runner is None and watch._run_complete.is_set())

        watch.on_status_change.subscribe(record_cleanup_state)

        with patch('oxen.watch.Observer', return_value=FakeObserver()), self.assertRaises(FileNotFoundError):
            await watch.run()

        self.assertEqual(watch.status, TaskStatus.FAILED)
        self.assertFalse(watch._observer)
        self.assertEqual(terminal_cleanup, [True])

    async def test_stop_before_run_sets_stopped_status(self) -> None:
        watch = Watch('.', task=FakeTask())

        await watch.stop()

        self.assertEqual(watch.status, TaskStatus.STOPPED)

    async def test_requires_at_least_one_path(self) -> None:
        with self.assertRaisesRegex(ValueError, 'at least one path'):
            Watch(task=FakeTask())

    async def _wait_until(self, predicate: object) -> None:
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)


if __name__ == '__main__':
    unittest.main()
