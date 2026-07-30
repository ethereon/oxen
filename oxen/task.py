from enum import Enum

from .publisher import Publisher


class TaskStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


class Task:
    """
    Abstract base class for tasks.
    """

    def __init__(self):
        # Published when the task produces new output (e.g., log lines).
        # The value is a string containing the new output.
        self.on_new_output = Publisher[str]()

        # Published when the task's status changes.
        self.on_status_change = Publisher[TaskStatus]()

        # Published when the task's past output is reset (e.g., cleared).
        self.on_output_reset = Publisher[None]()

        self._status = TaskStatus.PENDING

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
