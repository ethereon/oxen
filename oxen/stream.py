class StringStream:
    """
    Progressively reads from a string whose length is monotonically increasing.

    The `reader` argument should be a nullary function that returns a string.
    """

    def __init__(self, reader):
        self.reader = reader
        self.offset = 0

    def read(self):
        output = self.reader()
        next_offset = len(output)

        if next_offset == self.offset:
            # No new data
            return None

        assert next_offset > self.offset
        fragment = output[self.offset:]
        self.offset = next_offset
        return fragment

    @classmethod
    def from_task(cls, task):
        return cls(lambda: task.get_output())
