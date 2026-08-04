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

    def get_output(self) -> str:
        """
        Get the current output of the task.
        """
        raise NotImplementedError('Subclasses must implement the get_output method.')


class BufferedTaskOutput(TaskOutput):
    def __init__(self):
        super().__init__()
        self._output = io.StringIO()

    def append(self, text: str) -> None:
        self._output.write(text)
        self.on_update.publish(text)

    def get_output(self) -> str:
        return self._output.getvalue()


class Task:
    """
    Abstract base class for tasks.
    """

    def __init__(self, name: str):
        self.name = name
        self.output = self.create_output()
        self.auto_start = True
        self._status = TaskStatus.PENDING

        # Published when the task's status changes.
        self.on_status_change = Publisher[TaskStatus]()

    async def run(self) -> None:
        """
        Run the task.
        """
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

    def create_output(self) -> TaskOutput:
        return BufferedTaskOutput()
