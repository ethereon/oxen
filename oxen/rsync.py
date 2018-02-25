from pathlib import Path

from .process import Process
from .watch import Watch


def auto_rsync(
    source,
    dest,
    *,
    name,
    verbose=True,
    archive=True,
    recursive=True,
    # If true, skip files that are newer on the receiver
    update=False,
    # If true, delete extraneous files from dest dirs
    delete=False,
    compress=True
):
    command = ['rsync', source, dest]
    flag_map = {
        'archive': archive,
        'compress': compress,
        'delete': delete,
        'recursive': recursive,
        'update': update,
        'verbose': verbose,
    }
    for flag, is_set in flag_map.items():
        if is_set:
            command.append('--' + flag)

    # Establish the directory to watch for changes
    watch_dir = Path(source)
    if not watch_dir.is_dir():
        # Source is a file. Watch its parent directory.
        watch_dir = watch_dir.parent

    return Watch(
        # Watch the source path for changes
        path=watch_dir,
        # Sync the destination using rsync when changes are detected
        handler=Process(*command, name='rsync'),
        # Ensure the destination is synced at start
        force_once=True,
        recursive=recursive,
        name=name
    )
