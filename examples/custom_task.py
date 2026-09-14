"""
Demonstrates how to implement custom async tasks.
"""

import asyncio

from oxen import Oxen, Task, TaskStatus


class ReachabilityCheck(Task):
    """
    A task that checks whether a given host is reachable.
    """

    def __init__(self, host: str, timeout: float = 3) -> None:
        super().__init__(host)
        self.host = host
        self.timeout = timeout
        self._runner: asyncio.Task[None] | None = None

    async def run(self) -> None:
        if self.status is TaskStatus.RUNNING:
            return

        # Status and output changes are reflected immediately in the UI.
        self.status = TaskStatus.RUNNING
        self._runner = asyncio.current_task()
        self.output.append(f'Checking {self.host}:\n')
        try:
            # Opening a TLS connection verifies both DNS and connectivity.
            started = asyncio.get_running_loop().time()
            async with asyncio.timeout(self.timeout):
                _, writer = await asyncio.open_connection(self.host, 443, ssl=True)
                writer.close()
                await writer.wait_closed()

            elapsed = asyncio.get_running_loop().time() - started
            self.output.append(f'Reachable in {elapsed:.2f}s\n')
            self.status = TaskStatus.COMPLETED
        except asyncio.CancelledError:
            self.status = TaskStatus.STOPPED
            raise
        except (OSError, TimeoutError) as error:
            self.output.append(f'{type(error).__name__}: {error}\n')
            self.status = TaskStatus.FAILED
        finally:
            self._runner = None

    async def stop(self) -> None:
        if self._runner is not None:
            # Cancelling run() also cancels its pending network operation.
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        elif self.status is TaskStatus.PENDING:
            self.status = TaskStatus.STOPPED


if __name__ == '__main__':
    # Oxen starts and displays each custom task independently.
    Oxen(
        ReachabilityCheck('python.org'),
        ReachabilityCheck('pypi.org'),
        ReachabilityCheck('192.0.2.1'),  # Likely timeout
    ).run()
