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
    Abstract base class for tasks.
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

        # Published when the task's status changes.
        self.on_status_change = Publisher[TaskStatus]()

    async def run(self) -> None:
        raise NotImplementedError('Subclasses must implement the run method.')

    async def stop(self) -> None:
        raise NotImplementedError('Subclasses must implement the stop method.')

    async def restart(self) -> None:
        await self.stop()
        await self.run()

    @property
    def status(self) -> TaskStatus:
        return self._status

    @status.setter
    def status(self, new_status: TaskStatus) -> None:
        if new_status != self._status:
            self._status = new_status
            self.on_status_change.publish(new_status)
