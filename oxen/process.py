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
    A task that runs a subprocess and publishes its output and status.

    Args:
        *args: The subprocess argument vector.

        name: An optional name displayed in the UI.
            By default, a name is derived from the process arguments.

        shell: Whether to treat the invocation as a shell command.
            Defaults to False.

        encoding: The encoding used to decode process output.
            Defaults to 'utf-8'.

        decoding_errors: The error-handling scheme used when decoding process output.
            For options, see: https://docs.python.org/3/library/codecs.html
            Defaults to 'replace'.

        **spawn_kwargs: Additional keyword arguments forwarded to the selected
            asyncio subprocess function, based on `shell`:
                asyncio.create_subprocess_shell      (if shell)
                asyncio.create_subprocess_exec       (otherwise)
    """

    _READ_SIZE = 64 * 1024

    def __init__(
        self,
        *args: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        name: str | None = None,
        shell: bool = False,
        encoding: str = 'utf-8',
        decoding_errors: str = 'replace',
        **spawn_kwargs: Any,
    ) -> None:
        if not args:
            raise ValueError('Process requires at least one process argument.')

        super().__init__(name=name or self._shell_command(args))

        self.args = args
        self.shell = shell
        self.encoding = encoding
        self.decoding_errors = decoding_errors
        self.spawn_kwargs: dict[str, Any] = spawn_kwargs
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

        spawn_kwargs = self.spawn_kwargs.copy()

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
            if self.shell:
                command = self._shell_command(self.args)
                process = await asyncio.create_subprocess_shell(command, **spawn_kwargs)
            else:
                process = await asyncio.create_subprocess_exec(*self.args, **spawn_kwargs)
            self.process = process
            if self._stop_requested and process.returncode is None:
                process.terminate()

            async with asyncio.TaskGroup() as readers:
                if process.stdout is not None:
                    readers.create_task(self._publish_stream(process.stdout, self.encoding, self.decoding_errors))
                if process.stderr is not None and process.stderr is not process.stdout:
                    readers.create_task(self._publish_stream(process.stderr, self.encoding, self.decoding_errors))
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
        decoding_errors: str,
    ) -> None:
        decoder = codecs.getincrementaldecoder(encoding)(errors=decoding_errors)

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
