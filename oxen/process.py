import asyncio
import logging
import signal

from ptyprocess import PtyProcess

from .color import ColorText
from .task import BufferedTask, TaskStatus, TaskAction, TaskEvent


class Process(BufferedTask):
    """
    A task that executes a process within a pseudo-terminal.

    * [argv]
      All positional arguments to the constructor are interpreted as the arguments to the process.
    * shell
      Not implemented yet.
    * cwd
      Optional current working directory for the process.
    * env
      Optional environment dictionary.
    * name
      Optional name for this task. If not provided, the command string is used as the name.
    """

    BLOCK_SIZE = 1024

    def __init__(self, *argv, shell=False, cwd=None, env=None, name=None):
        self.argv = list(map(str, argv))
        super().__init__(name=(name or ' '.join(self.argv)))
        # TODO(saumitro): Implement shell support
        self.shell = shell
        self.process = None
        self.cwd = cwd
        self.env = env
        self.future_process_exit = None
        self.future_restart = None

    def start(self):
        assert (self.process is None) or (not self.process.isalive())

        # Make sure any previously registered readers are first removed so that
        # they aren't accidentally invoked for the new process
        if self.process is not None:
            self.loop.remove_reader(self.process.fd)

        # Start the process
        self.process = PtyProcess.spawn(
            self.argv,
            cwd=self.cwd,
            env=self.env,
        )

        # Monitor process output
        self.loop.add_reader(self.process.fd, self.on_data_available)

        # Monitor process exit
        async def monitor_process_status(process):
            while process.isalive():
                await asyncio.sleep(0.5)
            self.on_process_terminate(process)
            self.future_process_exit = None
        self.future_process_exit = asyncio.ensure_future(monitor_process_status(self.process))

        # Transition status
        self.events.publish(TaskEvent.STATUS_CHANGED)

    def stop(self):
        # The force flag is treated as a last resort. PtyProcess first attempts
        # to amicably terminate the process with SIGHUP/SIGINT.
        self.process.terminate(force=True)

    def restart(self):
        if self.future_restart is not None:
            return

        async def stop_then_start():
            if self.future_process_exit is not None:
                self.stop()
                await self.future_process_exit
            self.start()
            self.future_restart = None

        self.future_restart = asyncio.ensure_future(stop_then_start())

    def on_data_available(self):
        if not self.process.isalive():
            return
        try:
            self.write_output(self.process.read(self.BLOCK_SIZE).decode('utf8'))
        except EOFError:
            pass

    def on_process_terminate(self, process):
        if process != self.process:
            logging.warn(f'Internal inconsistency: process changed before termination callback.')
            return
        self.loop.remove_reader(self.process.fd)
        self.output_termination_message(self.get_status())
        self.events.publish(TaskEvent.STATUS_CHANGED)

    def output_termination_message(self, status):
        # TODO(saumitro): Also output human readable uptime
        colorant = ColorText.red
        reason = 'due to unknown reasons'
        if self.process.exitstatus is not None:
            colorant = ColorText.red if status == TaskStatus.FAILED else ColorText.green
            reason = f'with code {self.process.exitstatus}'
        elif self.process.signalstatus is not None:
            signal_name = signal.Signals(self.process.signalstatus).name
            reason = f'due to signal {self.process.signalstatus} ({signal_name})'
        self.write_output(colorant(f'\n[Process exited {reason}]\n\n'))

    def get_actions(self):
        return [
            TaskAction(name='Stop', handler=self.stop),
            TaskAction(name='Restart', handler=self.restart)
        ]

    def get_status(self):
        if self.process.isalive():
            return TaskStatus.ACTIVE
        if self.process.exitstatus == 0:
            return TaskStatus.FINISHED
        return TaskStatus.FAILED
