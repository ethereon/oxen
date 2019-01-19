import enum
import io
import itertools

from .event import EventEmitter


class TaskStatus(enum.Enum):
    ACTIVE = 'active'
    FINISHED = 'finished'
    FAILED = 'failed'


class TaskEvent(enum.Enum):
    OUTPUT_UPDATED = 'output-updated'
    STATUS_CHANGED = 'status-changed'


class TaskAction:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler


class Task:
    """
    Abstract base class for tasks: an asynchronous worker.
    """

    id_generator = itertools.count()

    def __init__(self, name):
        # A unique ID associated with this task.
        # By default, a monotonically increasing integer.
        self.id = next(Task.id_generator)
        # A name associated with this task (not necessarily unique)
        self.name = name
        # Event publisher / subscriber
        self.events = EventEmitter()
        # An asyncio event loop. Subclasses must register tasks with this event loop.
        self.loop = None

    def start(self):
        """
        Register tasks with the event loop.
        """
        raise NotImplementedError

    def stop(self):
        """
        Stop the task and remove from the event loop.
        """
        raise NotImplementedError

    def get_output(self):
        """
        Provide the output for this task.
        """
        raise NotImplementedError

    def get_actions(self):
        """
        Returns a list of strings describing the available actions for this task.
        """
        return []

    def get_status(self):
        """
        Returns a value from TaskStatus.
        """
        raise NotImplementedError

    def set_event_loop(self, event_loop):
        """
        Invoked by the session before starting the task.
        """
        self.loop = event_loop

    def perform_action(self, action_name):
        """
        Execute the given action, where action is one of the strings returned
        the get_actions method.
        """
        for action in self.get_actions():
            if action.name == action_name:
                return action.handler()
        raise ValueError('Unsupported action: {}'.format(action_name))

    def start_subtask(self, task):
        """
        Initiate a task owned by `self` rather than the session.
        """
        assert self.loop is not None
        task.loop = self.loop
        task.start()

    @property
    def is_active(self):
        return self.get_status() == TaskStatus.ACTIVE


class BufferedTask(Task):
    """
    A task that stores its output in an in-memory buffer.
    """

    def __init__(self, name):
        super().__init__(name)
        self.output = io.StringIO()

    def write_output(self, text):
        self.output.write(text)
        self.events.publish(TaskEvent.OUTPUT_UPDATED)

    def write_line(self, line):
        self.write_output(line + '\n')

    def get_output(self):
        return self.output.getvalue()


class Lazy(Task):
    """
    A task wrapper that accepts a task instance and makes it "lazily"
    initialized. That is, it must be manually initiated by the user.
    Until then, it remains in an inactive state.

    Useful for creating "on demand" tasks.
    """

    def __init__(self, task):
        super().__init__(name=task.name)
        self._wrapped_task = task
        self._num_invocations = 0
        self.id = task.id
        self.events = task.events

    @property
    def has_been_manually_invoked(self):
        return self._num_invocations > 1

    def set_event_loop(self, event_loop):
        super().set_event_loop(event_loop)
        self._wrapped_task.set_event_loop(event_loop)

    def start(self):
        self._num_invocations += 1
        # Suppress the first invocation
        if self._num_invocations == 2:
            self._wrapped_task.start()
            # Trigger an update (most notably, for the actions displayed in the client)
            self.events.publish(TaskEvent.STATUS_CHANGED)

    def stop(self):
        if self.has_been_manually_invoked:
            self._wrapped_task.stop()

    def get_output(self):
        if self.has_been_manually_invoked:
            return self._wrapped_task.get_output()
        return f'Task "{self.name}" has not been started.'

    def _get_wrapper_actions(self):
        return [TaskAction(name='Start', handler=self.start)]

    def get_actions(self):
        if self.has_been_manually_invoked:
            return self._wrapped_task.get_actions()
        return self._get_wrapper_actions()

    def get_status(self):
        if self.has_been_manually_invoked:
            return self._wrapped_task.get_status()
        return TaskStatus.FINISHED

    def perform_action(self, action_name):
        if self.has_been_manually_invoked:
            try:
                self._wrapped_task.perform_action(action_name)
            except ValueError:
                # Suppress duplicate actions sent to the lazy wrapper
                if action_name not in (action.name for action in self._get_wrapper_actions()):
                    raise
        else:
            super().perform_action(action_name)
