# Oxen

Oxen is a lightweight Python library for managing multiple tasks.

- Run subprocesses and custom async work as observable tasks
- Stream their output into a terminal-based UI
- Use keyboard shortcuts to quickly manage task lifecycles (run/stop/restart)
- Easily define split views to create custom task dashboards

```python
from oxen import Oxen, Shell

Oxen(
    Shell('python -m http.server', name='server'),
    Shell('tsc --watch', name='compile'),
).run()
```

## Install

Oxen requires Python 3.12 or newer.

```console
pip install oxen
```

## Quickstart

The `Oxen` class manages a collection of arbitrary `Task` instances. You can either pass tasks during construction:

```python
ox = Oxen(
    Shell('python -m http.server', name='server'),
    Shell('ping google.com', name='ping'),
)
```

Or add them after construction:

```python
ping = Shell('ping google.com')
ox.add(ping)
```

By default, eligible tasks are automatically started and displayed in a text-based UI when the `run` method is called:

```python
# Displays TUI and runs all eligible tasks.
ox.run()
```

## Tasks

A `Task` represents asynchronous work and reports its status and output.

You can either subclass `Task` to provide your own custom logic, or use one of the built-in utility subclasses described below.

### Subprocesses

Use `Process` or `Shell` for subprocess tasks.

```python
from oxen import Oxen, Process

tests = Process('python', '-m', 'unittest', 'discover', name='tests')
Oxen(tests).run()
```

`Shell` is essentially a shorthand for `Process(..., shell=True)`. Use it when you want pipes, redirects, variables, or other shell syntax:

```python
from oxen import Oxen, Shell

monitor = Shell(
    'tail -f console.log | grep -i error',
    pty=True,
    name='logs',
)
Oxen(monitor).run()
```

- By default, both `stdout` and `stderr` are captured.
- Oxen correctly renders common interactive output, such as progress bars, by interpreting cursor, erase, color, and carriage-return sequences.
- [Pseudoterminal](https://en.wikipedia.org/wiki/Pseudoterminal) (PTY) mode can be enabled on POSIX platforms by passing `pty=True`.

### Watching the Filesystem

Use `Watch` to auto-run a task whenever one or more files or directories change:

```python
from oxen import Oxen, Shell
from oxen.watch import Watch

watch_tests = Watch(
    # Watch the src and test directories for changes
    'src',
    'tests',
    # Run unit tests whenever changes are detected
    task=Shell('python -m unittest discover', name='tests'),
)
Oxen(watch_tests).run()
```

`Watch` requires the [Watchdog library](https://pypi.org/project/watchdog/) for filesystem events monitoring. Install it with:

```console
pip install 'oxen[watch]'
```

### Custom Tasks

Subclass `Task` to put any asynchronous work behind the same status, output, and lifecycle interface:

```python
from oxen import Task

class MyTask(Task):

    async def execute(self) -> bool:
        self.output.append('Working...\n')

        # ... do asynchronous work here ...

        return True
```

See [custom_task.py](examples/custom_task.py) for a simple example.

## Dashboards

The default task browser shows the selected task’s output. Split views can display several tasks simultaneously:

```python
ox.add_layout(
    [
        (frontend, backend),  # tuple: stacked horizontally
        tests,
    ],  # list: stacked vertically
    name='Development',
    default=True,  # Show this by default instead of the task browser
    shortcut='d',  # Keyboard shortcut for this layout
)
```

Lists stack items vertically while tuples arrange them horizontally. These can be arbitrarily nested. Tasks found in a layout are registered automatically, and focusing a panel selects its task for lifecycle actions.

See [dashboard.py](examples/dashboard.py) for a simple example.

## License

Oxen is available under the [3-Clause BSD License](LICENSE).
