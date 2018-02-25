import functools
import watchdog.observers

from .color import ColorText
from .stream import StringStream
from .task import Task, BufferedTask, TaskEvent, TaskStatus, TaskAction


class Watch(BufferedTask):
    """
    Watches a path and invokes a task whenever a change is detected.

    * path
      The path to watch for changes.
    * handler
      Either a task instance that can be started multiple times, or a function that
      that accepts a list of watchdog fs events and returns a task to execute.
    * recursive
      If true, the given path is recursively watched.
    * delay
      A debounce interval for accumulating changes (in seconds).
    * force_once
      If true, the handler is invoked unconditionally when the watch starts.
    """

    def __init__(self, path, *, handler, name, recursive=False, delay=1.0, force_once=False):
        super().__init__(name)
        self.path = str(path)
        self.handler = (lambda _: handler) if isinstance(handler, Task) else handler
        self.delay = delay
        self.force_once = force_once
        self.queue = []
        self.pending_consume = False
        self.active_task = None
        self.active_task_stream = None
        self.observer = watchdog.observers.Observer()
        self.observer.schedule(self, self.path, recursive=recursive)

    def start(self):
        self.write_line(f'{ColorText.green("Watching:")} {self.path}')
        self.observer.start()
        if self.force_once:
            self.write_line('Invoking task once unconditionally')
            self.initiate_consume()

    def stop(self):
        if self.active_task is not None:
            self.active_task.stop()
        self.observer.stop()
        self.observer.join()

    def get_status(self):
        return TaskStatus.ACTIVE

    def dispatch(self, event):
        self.queue.append(event)
        self.initiate_consume()

    def initiate_consume(self, delay=None):
        if self.pending_consume:
            return
        self.pending_consume = True
        if delay is None:
            delay = self.delay
        self.loop.call_soon_threadsafe(self.loop.call_later, delay, self.consume)

    def consume(self):
        if self.active_task is not None:
            # Wait for the task to complete. Events will keep queueing until then.
            self.loop.call_later(self.delay, self.consume)
            return
        events, self.queue = self.queue, []
        self.active_task = self.handler(events)
        self.active_task_stream = StringStream.from_task(self.active_task)
        self.active_task.events.subscribe(self.on_task_event)
        self.start_subtask(self.active_task)
        self.pending_consume = False

    def on_task_event(self, event):
        if event == TaskEvent.OUTPUT_UPDATED:
            self.write_output(self.active_task_stream.read())
        elif event == TaskEvent.STATUS_CHANGED:
            if not self.active_task.is_active:
                self.active_task.events.unsubscribe(self.on_task_event)
                self.active_task = None
                self.active_task_stream = None

    def get_actions(self):
        return [
            TaskAction(
                name='Trigger',
                handler=functools.partial(self.initiate_consume, delay=0)
            )
        ]
