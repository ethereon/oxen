from __future__ import annotations

import asyncio
import math
import os

from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from .task import Task, TaskStatus


type PathArgument = str | bytes | os.PathLike[str] | os.PathLike[bytes]


class Watch(Task):
    """
    Watch paths and restart another task when one of them changes.

    Args:
        *paths: One or more files or directories to watch.

        task: The task to restart after a change is detected.

        name: An optional name displayed in the UI.
            Defaults to the given task's name.

        recursive: Whether changes below watched directories are included.
            Defaults to True. This does not affect explicitly watched files.

        run_on_start: Whether to run the task unconditionally when watching starts.
            Defaults to False.

        debounce: Seconds to wait after the most recent change before
            restarting the task. Set to 0 to restart immediately.
            Defaults to 0.1.

        verbose: Whether to log watcher activity in the task's output.
            Defaults to False.

        auto_start: Whether to automatically start watching when the UI runs.
            Defaults to True.
    """

    _CHANGE_EVENT_TYPES = frozenset({'created', 'deleted', 'modified', 'moved'})

    def __init__(
        self,
        *paths: PathArgument,
        task: Task,
        name: str | None = None,
        recursive: bool = True,
        run_on_start: bool = False,
        debounce: float = 0.1,
        verbose: bool = False,
        auto_start: bool = True,
    ) -> None:
        if not paths:
            raise ValueError('Watch requires at least one path.')

        if not math.isfinite(debounce) or debounce < 0:
            raise ValueError('debounce must be a finite, non-negative number of seconds.')

        super().__init__(name=name or task.name, auto_start=auto_start, output=task.output)
        self.paths = tuple(Path(os.fsdecode(path)).absolute() for path in paths)
        self.task = task
        self.recursive = recursive
        self.run_on_start = run_on_start
        self.debounce = debounce
        self.verbose = verbose

        self._change_detected: asyncio.Event | None = None
        self._last_change_at: float | None = None
        self._observer: BaseObserver | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watched_files: set[Path] = set()
        self._watched_directories: set[Path] = set()

    async def _execute(self) -> TaskStatus:
        """
        Start watching and continue until the watcher is stopped.
        """
        self._change_detected = asyncio.Event()
        self._last_change_at = None

        observer: BaseObserver | None = None
        observer_started = False
        try:
            observer = Observer()
            self._observer = observer
            roots, self._watched_files, self._watched_directories = self._watch_targets()
            self._loop = asyncio.get_running_loop()
            handler = FileSystemEventHandler()
            handler.on_any_event = self.dispatch
            for root, recursive in roots.items():
                observer.schedule(handler, os.fspath(root), recursive=recursive)
            observer.start()
            observer_started = True

            if self.verbose:
                for path in sorted(self._watched_directories):
                    self._log(f'Watching directory: {path} (recursive={self.recursive})')
                for path in sorted(self._watched_files):
                    self._log(f'Watching file: {path}')

            if self.run_on_start:
                self._log('Running task on start')
                await self.task.restart()
                self._log(f'Task finished with status {self.task.status.value}')

            while not self._stop_requested:
                await self._wait_for_changes_to_settle()
                if not self._stop_requested:
                    await self.task.restart()
                    self._log(f'Task finished with status {self.task.status.value}')

            return TaskStatus.COMPLETED
        finally:
            try:
                if observer is not None and observer_started:
                    observer.stop()
                    await asyncio.to_thread(observer.join)
            finally:
                self._observer = None
                self._loop = None
                self._watched_files.clear()
                self._watched_directories.clear()
                self._change_detected = None
                self._last_change_at = None
                if observer_started:
                    self._log('Stopped watching')

    async def _interrupt(self) -> None:
        """
        Wake the watcher so its execution loop can stop.
        """
        if self._change_detected is not None:
            self._change_detected.set()

    async def _wait_for_changes_to_settle(self) -> None:
        """
        Wait for a change, then for a full quiet interval after the latest one.
        """
        change_detected = self._change_detected
        assert change_detected is not None
        await change_detected.wait()
        change_detected.clear()

        loop = asyncio.get_running_loop()
        while not self._stop_requested and self.debounce:
            changed_at = self._last_change_at
            if changed_at is None:
                break
            remaining = changed_at + self.debounce - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(change_detected.wait(), remaining)
            except TimeoutError:
                pass
            change_detected.clear()

    def _watch_targets(self) -> tuple[dict[Path, bool], set[Path], set[Path]]:
        watched_files: set[Path] = set()
        watched_directories: set[Path] = set()
        roots: dict[Path, bool] = {}

        for path in self.paths:
            if not path.exists():
                raise FileNotFoundError(path)

            if path.is_dir():
                watched_directories.add(path)
                roots[path] = roots.get(path, False) or self.recursive
            else:
                watched_files.add(path)
                roots.setdefault(path.parent, False)

        return roots, watched_files, watched_directories

    def dispatch(self, event: FileSystemEvent) -> None:
        """
        Receive a watchdog event from the observer thread.
        """
        loop = self._loop
        change_detected = self._change_detected
        if self._stop_requested or loop is None or change_detected is None:
            return
        if not self._event_matches(event, self._watched_files, self._watched_directories):
            return

        try:
            loop.call_soon_threadsafe(self._record_change, change_detected, event)
        except RuntimeError:
            # The event loop may be closing at the same moment as the observer
            # thread dispatches its final event.
            pass

    def _record_change(self, change_detected: asyncio.Event, event: FileSystemEvent) -> None:
        if self._stop_requested:
            return
        if self.verbose:
            self._log(f'Change detected: {self._event_description(event)}')
        self._last_change_at = asyncio.get_running_loop().time()
        change_detected.set()

    def _log(self, message: str) -> None:
        if self.verbose:
            prefix = '' if not self.output.text or self.output.text.endswith('\n') else '\n'
            self.output.append(f'{prefix}[Watch] {message}\n')

    @staticmethod
    def _event_description(event: FileSystemEvent) -> str:
        event_type = getattr(event, 'event_type', None) or 'changed'
        source_path = getattr(event, 'src_path', None)
        source = os.fsdecode(source_path) if source_path else ''
        destination = getattr(event, 'dest_path', None)
        if source and destination:
            return f'{event_type}: {source} -> {os.fsdecode(destination)}'
        if destination:
            return f'{event_type}: {os.fsdecode(destination)}'
        return f'{event_type}: {source}'

    @staticmethod
    def _event_matches(event: FileSystemEvent, watched_files: set[Path], watched_directories: set[Path]) -> bool:
        event_type = getattr(event, 'event_type', None)
        if event_type is not None and event_type not in Watch._CHANGE_EVENT_TYPES:
            return False

        event_paths = (
            getattr(event, 'src_path', None),
            getattr(event, 'dest_path', None),
        )
        for event_path in event_paths:
            if not event_path:
                continue
            path = Path(os.fsdecode(event_path)).absolute()
            if path in watched_files or any(path.is_relative_to(directory) for directory in watched_directories):
                return True
        return False
