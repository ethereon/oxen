import unittest

from oxen.terminal import TerminalBuffer


class TerminalBufferTest(unittest.TestCase):
    def render(self, *chunks: str) -> str:
        terminal = TerminalBuffer()
        for chunk in chunks:
            terminal.feed(chunk)
        return terminal.render()

    def test_overwrites_using_carriage_return_backspace_and_cursor_movement(self) -> None:
        self.assertEqual(self.render('progress: 10%\rprogress: 20%'), 'progress: 20%')
        self.assertEqual(self.render('abc\b\bXY'), 'aXY')
        self.assertEqual(self.render('abcdef\x1b[3D\x1b[K'), 'abc')

    def test_clears_and_repositions_the_screen(self) -> None:
        self.assertEqual(self.render('obsolete\ntext\x1b[2J\x1b[Hcurrent'), 'current')
        self.assertEqual(self.render('top\nbottom\x1b[1A\x1b[2K\rreplacement'), 'replacement\nbottom')

    def test_ignores_style_and_terminal_metadata_sequences(self) -> None:
        self.assertEqual(self.render('\x1b[31mred\x1b[0m'), 'red')
        self.assertEqual(self.render('a\x1b]0;window title\x07b'), 'ab')
        self.assertEqual(self.render('a\x1bPdevice control\x1b\\b'), 'ab')

    def test_parses_sequences_split_across_chunks(self) -> None:
        self.assertEqual(self.render('old\x1b[', '2', 'J\x1b[H', 'new'), 'new')


if __name__ == '__main__':
    unittest.main()
