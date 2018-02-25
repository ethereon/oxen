import os
import pathlib

# This acquires the concrete subclass for this platform (eg: PosixPath)
ConcretePath = type(pathlib.Path())


class Path(ConcretePath):
    """
    A pathlib.Path subclass that attempts to preserve the trailing
    path separator (which is stripped by the stdlib implementation).

    This is useful for various posix utilities like rsync where a trailing
    slash in the path can be significant.
    """

    def __new__(cls, *args, **kwargs):
        path = super().__new__(cls, *args, **kwargs)
        if args:
            path._capture_trailing_separator(args[-1])
        return path

    def _capture_trailing_separator(self, last_part):
        if last_part.endswith(os.sep):
            self._str_override = str(self) + os.sep
        return self

    def __truediv__(self, key):
        return super().__truediv__(key)._capture_trailing_separator(key)

    def __str__(self):
        return getattr(self, '_str_override', super().__str__())
