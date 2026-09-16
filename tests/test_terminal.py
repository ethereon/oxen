import unittest

from rich.color import ColorTriplet
from rich.console import Console

from oxen.terminal import TerminalBuffer, contains_terminal_controls


class TerminalBufferTest(unittest.TestCase):
    console = Console()

    def render(self, *chunks: str) -> str:
        terminal = TerminalBuffer()
        for chunk in chunks:
            terminal.feed(chunk)
        return terminal.render_text().plain

    def test_overwrites_using_carriage_return_backspace_and_cursor_movement(self) -> None:
        self.assertEqual(self.render('progress: 10%\rprogress: 20%'), 'progress: 20%')
        self.assertEqual(self.render('abc\b\bXY'), 'aXY')
        self.assertEqual(self.render('abcdef\x1b[3D\x1b[K'), 'abc')

    def test_clears_and_repositions_the_screen(self) -> None:
        self.assertEqual(self.render('obsolete\ntext\x1b[2J\x1b[Hcurrent'), 'current')
        self.assertEqual(self.render('top\nbottom\x1b[1A\x1b[2K\rreplacement'), 'replacement\nbottom')

    def test_preserves_ansi_colors_in_rich_text(self) -> None:
        self.assertEqual(self.render('\x1b[31mred\x1b[0m'), 'red')

        terminal = TerminalBuffer()
        terminal.feed('\x1b[31mred \x1b[91mbright \x1b[38;5;202mindexed \x1b[38;2;1;2;3mrgb \x1b[0mplain')
        rendered = terminal.render_text()
        self.assertEqual(rendered.plain, 'red bright indexed rgb plain')
        self.assertEqual(rendered.get_style_at_offset(self.console, 0).color.number, 1)
        self.assertEqual(rendered.get_style_at_offset(self.console, 4).color.number, 9)
        self.assertEqual(rendered.get_style_at_offset(self.console, 11).color.number, 202)
        self.assertEqual(rendered.get_style_at_offset(self.console, 19).color.triplet, ColorTriplet(1, 2, 3))
        self.assertIsNone(rendered.get_style_at_offset(self.console, 23).color)

    def test_applies_style_across_chunks_and_overwrites(self) -> None:
        terminal = TerminalBuffer()
        terminal.feed('\x1b[3')
        terminal.feed('1mred\r\x1b[32mgreen')
        rendered = terminal.render_text()
        self.assertEqual(rendered.plain, 'green')
        self.assertEqual(rendered.get_style_at_offset(self.console, 0).color.number, 2)

    def test_ignores_terminal_metadata_sequences(self) -> None:
        self.assertEqual(self.render('a\x1b]0;window title\x07b'), 'ab')
        self.assertEqual(self.render('a\x1bPdevice control\x1b\\b'), 'ab')

    def test_parses_sequences_split_across_chunks(self) -> None:
        self.assertEqual(self.render('old\x1b[', '2', 'J\x1b[H', 'new'), 'new')

    def test_detects_terminal_controls(self) -> None:
        self.assertFalse(contains_terminal_controls('plain\ntext\t'))
        self.assertTrue(contains_terminal_controls('\x1b['))
        self.assertTrue(contains_terminal_controls('\x9b31m'))


if __name__ == '__main__':
    unittest.main()
