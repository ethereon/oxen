from __future__ import annotations

import asyncio
import codecs
import os
import shlex

from collections.abc import Sequence
from typing import Any

from .task import Task, TaskStatus


class Process(Task):
    """
    A task that runs a subprocess.

    Positional arguments form the subprocess argument vector.
    Keyword arguments are passed to `asyncio.create_subprocess_exec` (or
    `asyncio.create_subprocess_shell` when ``shell=True``).

    Unless explicitly supplied, stdout and stderr are captured and published
    through `Task.on_new_output`.
    """

    _READ_SIZE = 64 * 1024

    def __init__(
        self,
        *args: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> None:
        if not args:
            raise ValueError('Process requires at least one process argument.')

        process_kwargs = dict(kwargs)
        super().__init__(
            name=process_kwargs.pop('name', None) or self._shell_command(args),
        )

        self.args = args
        self.kwargs = process_kwargs
        self.process: asyncio.subprocess.Process | None = None
        self.returncode: int | None = None
        self._runner: asyncio.Task[None] | None = None
        self._run_complete = asyncio.Event()
        self._run_complete.set()
        self._stop_requested = False

    async def run(self) -> None:
        """
        Start the process and wait for it to exit.
        """
        if self.status is TaskStatus.RUNNING:
            raise RuntimeError('Process is already running.')

        spawn_kwargs = self.kwargs.copy()
        shell = bool(spawn_kwargs.pop('shell', False))
        encoding = spawn_kwargs.pop('encoding', None) or 'utf-8'
        errors = spawn_kwargs.pop('errors', None) or 'replace'
        text = spawn_kwargs.pop('text', None)
        universal_newlines = spawn_kwargs.pop('universal_newlines', None)

        if text is not None and universal_newlines is not None and text != universal_newlines:
            raise ValueError('text and universal_newlines have different values')

        spawn_kwargs.setdefault('stdout', asyncio.subprocess.PIPE)
        spawn_kwargs.setdefault('stderr', asyncio.subprocess.PIPE)

        # Configure subprocess environment vars
        supplied_env = spawn_kwargs.get('env')
        env = dict(os.environ if supplied_env is None else supplied_env)
        # Disable Python output buffering unless the caller explicitly configures it.
        # Otherwise, output may be delayed until Python flushes its buffers.
        env.setdefault('PYTHONUNBUFFERED', '1')
        spawn_kwargs['env'] = env

        self.returncode = None
        self.process = None
        self._stop_requested = False
        self._runner = asyncio.current_task()
        self._run_complete.clear()
        self.status = TaskStatus.RUNNING

        try:
            if shell:
                command = self._shell_command(self.args)
                process = await asyncio.create_subprocess_shell(command, **spawn_kwargs)
            else:
                process = await asyncio.create_subprocess_exec(*self.args, **spawn_kwargs)
            self.process = process
            if self._stop_requested and process.returncode is None:
                process.terminate()

            async with asyncio.TaskGroup() as readers:
                if process.stdout is not None:
                    readers.create_task(self._publish_stream(process.stdout, encoding, errors))
                if process.stderr is not None and process.stderr is not process.stdout:
                    readers.create_task(self._publish_stream(process.stderr, encoding, errors))
                await process.wait()

            self.returncode = process.returncode
            if self._stop_requested:
                self.status = TaskStatus.STOPPED
            else:
                self.status = TaskStatus.COMPLETED if self.returncode == 0 else TaskStatus.FAILED
        except asyncio.CancelledError:
            await self._terminate()
            self.returncode = self.process.returncode if self.process is not None else None
            self.status = TaskStatus.FAILED
            raise
        except Exception:
            await self._terminate()
            self.returncode = self.process.returncode if self.process is not None else None
            self.status = TaskStatus.FAILED
            raise
        finally:
            self._runner = None
            self._run_complete.set()

    async def stop(self) -> None:
        """
        Terminate the subprocess, if it is running.
        """
        self._stop_requested = True
        await self._terminate()
        if self._runner is not None and self._runner is not asyncio.current_task():
            await self._run_complete.wait()
        elif self.status is TaskStatus.PENDING:
            self.status = TaskStatus.STOPPED

    async def _terminate(self) -> None:
        process = self.process
        if process is None or process.returncode is not None:
            return

        try:
            process.terminate()
        except ProcessLookupError:
            pass
        await process.wait()

    async def _publish_stream(
        self,
        stream: asyncio.StreamReader,
        encoding: str,
        errors: str,
    ) -> None:
        decoder = codecs.getincrementaldecoder(encoding)(errors=errors)

        while chunk := await stream.read(self._READ_SIZE):
            if output := decoder.decode(chunk):
                self.output.append(output)

        if output := decoder.decode(b'', final=True):
            self.output.append(output)

    @staticmethod
    def _shell_command(
        args: Sequence[str | bytes | os.PathLike[str] | os.PathLike[bytes]],
    ) -> str:
        if len(args) == 1:
            return os.fsdecode(args[0])

        return shlex.join([os.fsdecode(arg) for arg in args])


class Shell(Process):
    """
    A task that runs a shell command.
    Equivalent to Process(..., shell=True).
    """

    def __init__(
        self,
        command: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        **kwargs: Any,
    ) -> None:
        kwargs['shell'] = True
        super().__init__(command, **kwargs)
