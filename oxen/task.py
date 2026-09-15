import asyncio
import io

from enum import Enum

from .publisher import Publisher


class TaskStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    STOPPED = 'stopped'


class TaskOutput:
    """
    Base class for task output.
    """

    def __init__(self):
        self.on_update = Publisher[str]()

    def append(self, text: str) -> None:
        """
        Append text to the output and notify subscribers.
        """
        raise NotImplementedError('Subclasses must implement the append method.')

    def clear(self) -> None:
        """
        Clear the output and notify subscribers.
        """
        raise NotImplementedError('Subclasses must implement the clear method.')

    @property
    def text(self) -> str:
        """
        The current output of the task.
        """
        raise NotImplementedError('Subclasses must implement the text property.')


class BufferedTaskOutput(TaskOutput):
    """
    StringIO backed task output.
    """

    def __init__(self):
        super().__init__()
        self._output = io.StringIO()

    def append(self, text: str) -> None:
        self._output.write(text)
        self.on_update.publish(text)

    def clear(self) -> None:
        self._output.seek(0)
        self._output.truncate()
        self.on_update.publish('\x1bc')

    @property
    def text(self) -> str:
        return self._output.getvalue()


class Task:
    """
    Base class for a task: asynchronous work that reports its
    status transitions and output changes.

    Subclasses should implement _execute and, optionally, _interrupt.
    """

    def __init__(
        self,
        name: str,
        *,
        auto_start: bool = True,
        output: TaskOutput | None = None,
    ):
        self.name = name
        self.output = output if output is not None else BufferedTaskOutput()
        self.auto_start = auto_start
        self._status = TaskStatus.PENDING
        self._runner: asyncio.Task[None] | None = None
        self._run_complete = asyncio.Event()
        self._run_complete.set()
        self._stop_requested = False
        self._transition_lock = asyncio.Lock()

        # Published when the task's status changes.
        self.on_status_change = Publisher[TaskStatus]()

    async def run(self) -> None:
        """
        Execute the task and publish its lifecycle state.
        """
        async with self._transition_lock:
            if self.status is TaskStatus.RUNNING:
                raise RuntimeError(f'{self.name} is already running.')

            self._stop_requested = False
            self._runner = asyncio.current_task()
            self._run_complete.clear()
            self._set_status(TaskStatus.RUNNING)

        final_status = TaskStatus.FAILED
        try:
            result = await self._execute()
            if result not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                raise ValueError(f'_execute() returned invalid terminal status: {result!r}')
            final_status = TaskStatus.STOPPED if self._stop_requested else result
        except asyncio.CancelledError:
            final_status = TaskStatus.STOPPED
            if not self._stop_requested:
                raise
        finally:
            self._runner = None
            self._run_complete.set()
            self._set_status(final_status)

    async def stop(self) -> None:
        """
        Interrupt the task if it is running and wait for it to finish.
        """
        async with self._transition_lock:
            if self.status is TaskStatus.PENDING:
                self._set_status(TaskStatus.STOPPED)
                return
            if self.status is not TaskStatus.RUNNING:
                return

            should_interrupt = not self._stop_requested
            self._stop_requested = True
            runner = self._runner

        if should_interrupt:
            await self._interrupt()
        if runner is not None and runner is not asyncio.current_task():
            await self._run_complete.wait()

    async def restart(self) -> None:
        """
        Stop the task if it is running, then run it again.
        """
        if self.status is TaskStatus.RUNNING:
            await self.stop()
        await self.run()

    async def _execute(self) -> TaskStatus:
        """
        Perform the actual work.

        Subclasses must implement this method to perform the
        task-specific work. On completion, return the new status
        of the task (either COMPLETED or FAILED).

        Invoked via `run`.
        """
        raise NotImplementedError

    async def _interrupt(self) -> None:
        """
        Interrupt an active execution.

        The default implementation cancels the execution coroutine.
        Subclasses may override this to provide custom graceful interruption.

        Invoked via `stop`.
        """
        runner = self._runner
        if runner is not None and runner is not asyncio.current_task():
            runner.cancel()

    @property
    def status(self) -> TaskStatus:
        return self._status

    def _set_status(self, new_status: TaskStatus) -> None:
        """
        Perform a status transition.

        This typically does not need to be invoked by subclasses
        and should be considered private. The status transitions are
        handled by the base class implementation of `run` and `stop`.
        """
        if new_status != self._status:
            self._status = new_status
            self.on_status_change.publish(new_status)
