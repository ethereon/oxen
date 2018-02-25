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
        self.id = next(Task.id_generator)
        self.name = name
        self.events = EventEmitter()
        self.loop = None

    def start(self):
        """
        Register tasks with the event loop
        """
        raise NotImplementedError

    def stop(self):
        """
        Stop the task and remove from the event loop
        """
        raise NotImplemented

    def get_output(self):
        """
        Provide the output for this task
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
