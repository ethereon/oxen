"""
Demonstrates how to implement custom async tasks.
"""

import asyncio

from oxen import Oxen, Task


class ReachabilityCheck(Task):
    """
    A task that checks whether a given host is reachable.
    """

    def __init__(self, host: str, timeout: float = 3) -> None:
        super().__init__(host)
        self.host = host
        self.timeout = timeout

    async def execute(self) -> bool:
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
            return True
        except (OSError, TimeoutError) as error:
            self.output.append(f'{type(error).__name__}: {error}\n')
            return False


if __name__ == '__main__':
    # Oxen starts and displays each custom task independently.
    Oxen(
        ReachabilityCheck('python.org'),
        ReachabilityCheck('pypi.org'),
        ReachabilityCheck('192.0.2.1'),  # Likely timeout
    ).run()
