from __future__ import annotations

import asyncio
import codecs
import errno
import os
import shlex
import signal

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

        pty: Whether to connect stdout and stderr to a pseudo-terminal instead
            of separate pipes. This can prevent programs from block-buffering
            output when they are not connected to a terminal. PTY output is
            merged and may contain terminal-specific formatting.
            Defaults to False.

        encoding: The encoding used to decode process output.
            Defaults to 'utf-8'.

        decoding_errors: The error-handling scheme used when decoding process output.
            For options, see: https://docs.python.org/3/library/codecs.html
            Defaults to 'replace'.

        terminate_timeout: Seconds to wait after terminating a process before killing it.
            Defaults to 3 seconds.

        **spawn_kwargs: Additional keyword arguments forwarded to the selected
            asyncio subprocess function, based on `shell`:
                asyncio.create_subprocess_shell      (if shell)
                asyncio.create_subprocess_exec       (otherwise)
    """

    _READ_SIZE = 64 * 1024
    _TERMINATE_POLL_INTERVAL = 0.01

    def __init__(
        self,
        *args: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        name: str | None = None,
        shell: bool = False,
        pty: bool = False,
        encoding: str = 'utf-8',
        decoding_errors: str = 'replace',
        terminate_timeout: float = 3.0,
        **spawn_kwargs: Any,
    ) -> None:
        if not args:
            raise ValueError('Process requires at least one process argument.')

        super().__init__(name=name or self._shell_command(args))

        self.args = args
        self.shell = shell
        self.pty = pty
        self.encoding = encoding
        self.decoding_errors = decoding_errors
        self.terminate_timeout = terminate_timeout
        self.spawn_kwargs: dict[str, Any] = spawn_kwargs
        self.process: asyncio.subprocess.Process | None = None
        self.returncode: int | None = None

        self._runner: asyncio.Task[None] | None = None
        self._run_complete = asyncio.Event()
        self._run_complete.set()
        self._stop_requested = False
        self._process_group_id: int | None = None

    async def run(self) -> None:
        """
        Start the process and wait for it to exit.
        """
        if self.status is TaskStatus.RUNNING:
            raise RuntimeError('Process is already running.')

        spawn_kwargs = self.spawn_kwargs.copy()

        # A pseudoterminal (PTY) encourages interactive flushing.
        # Otherwise, capture them with separate pipes.
        pty_main_fd: int | None = None
        pty_sub_fd: int | None = None
        if self.pty:
            if os.name != 'posix':
                raise NotImplementedError('PTY-backed processes are only supported on POSIX systems.')
            conflicting_streams = {'stdout', 'stderr'} & spawn_kwargs.keys()
            if conflicting_streams:
                streams = ', '.join(sorted(conflicting_streams))
                raise ValueError(f'pty=True cannot be combined with custom {streams}.')
        else:
            spawn_kwargs.setdefault('stdout', asyncio.subprocess.PIPE)
            spawn_kwargs.setdefault('stderr', asyncio.subprocess.PIPE)

        # Isolate subprocess trees so stopping a task terminates pipelines and their descendants.
        owns_process_group = False
        if os.name == 'posix':
            if 'start_new_session' not in spawn_kwargs and 'process_group' not in spawn_kwargs:
                spawn_kwargs['start_new_session'] = True
                owns_process_group = True
            elif spawn_kwargs.get('start_new_session') is True or spawn_kwargs.get('process_group') == 0:
                owns_process_group = True

        # Configure subprocess environment vars
        supplied_env = spawn_kwargs.get('env')
        env = dict(os.environ if supplied_env is None else supplied_env)
        # Disable Python output buffering unless the caller explicitly configures it.
        # Otherwise, output may be delayed until Python flushes its buffers.
        env.setdefault('PYTHONUNBUFFERED', '1')
        spawn_kwargs['env'] = env

        self.returncode = None
        self.process = None
        self._process_group_id = None
        self._stop_requested = False
        self._runner = asyncio.current_task()
        self._run_complete.clear()
        self.status = TaskStatus.RUNNING

        try:
            if self.pty:
                pty_main_fd, pty_sub_fd = os.openpty()
                spawn_kwargs['stdout'] = pty_sub_fd
                spawn_kwargs['stderr'] = pty_sub_fd
            try:
                if self.shell:
                    command = self._shell_command(self.args)
                    process = await asyncio.create_subprocess_shell(command, **spawn_kwargs)
                else:
                    process = await asyncio.create_subprocess_exec(*self.args, **spawn_kwargs)
            finally:
                if pty_sub_fd is not None:
                    os.close(pty_sub_fd)
            self.process = process
            if owns_process_group:
                self._process_group_id = process.pid
            if self._stop_requested and process.returncode is None:
                await self._terminate()

            async with asyncio.TaskGroup() as readers:
                if pty_main_fd is not None:
                    readers.create_task(self._publish_pty(pty_main_fd, self.encoding, self.decoding_errors))
                    pty_main_fd = None
                elif process.stdout is not None:
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
            if pty_main_fd is not None:
                os.close(pty_main_fd)
            self._runner = None
            self._process_group_id = None
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
        if process is None:
            return

        process_group_id = self._process_group_id
        self._send_terminate(process, process_group_id)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.terminate_timeout

        try:
            async with asyncio.timeout(max(0, deadline - loop.time())):
                await process.wait()
        except TimeoutError:
            pass

        while self._termination_target_exists(process, process_group_id) and loop.time() < deadline:
            await asyncio.sleep(self._TERMINATE_POLL_INTERVAL)

        if self._termination_target_exists(process, process_group_id):
            self._send_kill(process, process_group_id)

        await process.wait()

    @staticmethod
    def _send_terminate(process: asyncio.subprocess.Process, process_group_id: int | None) -> None:
        try:
            if process_group_id is not None:
                os.killpg(process_group_id, signal.SIGTERM)
            elif process.returncode is None:
                process.terminate()
        except ProcessLookupError:
            pass

    @staticmethod
    def _send_kill(process: asyncio.subprocess.Process, process_group_id: int | None) -> None:
        try:
            if process_group_id is not None:
                os.killpg(process_group_id, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass

    @staticmethod
    def _termination_target_exists(process: asyncio.subprocess.Process, process_group_id: int | None) -> bool:
        if process_group_id is None:
            return process.returncode is None

        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        else:
            return True

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

    async def _publish_pty(self, fd: int, encoding: str, decoding_errors: str) -> None:
        decoder = codecs.getincrementaldecoder(encoding)(errors=decoding_errors)
        loop = asyncio.get_running_loop()
        complete = loop.create_future()

        def finish(error: BaseException | None = None) -> None:
            loop.remove_reader(fd)
            if complete.done():
                return
            if error is None:
                complete.set_result(None)
            else:
                complete.set_exception(error)

        def read_ready() -> None:
            try:
                chunk = os.read(fd, self._READ_SIZE)
            except OSError as error:
                # Linux reports EIO when the final sub descriptor closes.
                finish(None if error.errno == errno.EIO else error)
                return

            if chunk:
                try:
                    if output := decoder.decode(chunk):
                        self.output.append(output)
                except BaseException as error:
                    finish(error)
            else:
                finish()

        loop.add_reader(fd, read_ready)
        try:
            await complete
            if output := decoder.decode(b'', final=True):
                self.output.append(output)
        finally:
            loop.remove_reader(fd)
            os.close(fd)

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
