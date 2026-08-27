from __future__ import annotations
import re
from itertools import groupby
from typing import Literal

from rich.ansi import AnsiDecoder
from rich.style import Style
from rich.text import Text


type Cursor = tuple[int, int]
type TerminalCell = tuple[str, Style]
type TerminalLine = list[TerminalCell]
type ParserState = Literal[
    'ground',
    'escape',
    'csi',
    'string',
    'string-escape',
    'escape-character',
]

_TERMINAL_CONTROL_PATTERN = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def contains_terminal_controls(text: str) -> bool:
    return _TERMINAL_CONTROL_PATTERN.search(text) is not None


class TerminalBuffer:
    """
    Terminal output renderer.
    This class implements the output-side controls commonly emitted by CLIs while
    deliberately ignoring input related controls.
    Select Graphic Rendition (SGR) styling is supported.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._lines: list[TerminalLine] = [[]]
        self._row: int = 0
        self._column: int = 0
        self._saved_cursor: Cursor = (0, 0)
        self._state: ParserState = 'ground'
        self._sequence: str = ''
        self._ansi_decoder = AnsiDecoder()

    def feed(self, text: str) -> None:
        for character in text:
            match self._state:
                case 'ground':
                    self._ground(character)
                case 'escape':
                    self._escape(character)
                case 'csi':
                    self._csi(character)
                case 'string':
                    match character:
                        case '\x07' | '\x9c':
                            self._state = 'ground'
                        case '\x1b':
                            self._state = 'string-escape'
                case 'string-escape':
                    self._state = 'ground' if character == '\\' else 'string'
                case _:  # A one-character escape sequence such as ESC ( B.
                    self._state = 'ground'

    def render_text(self) -> Text:
        last_content_row = max(
            (index for index, line in enumerate(self._lines) if any(character != ' ' for character, _style in line)),
            default=0,
        )
        last_row = max(self._row, last_content_row)
        self._ensure_row(last_row)
        rendered = Text()
        for row, line in enumerate(self._lines[: last_row + 1]):
            last_column = next(
                (column for column in range(len(line) - 1, -1, -1) if line[column][0] != ' '),
                -1,
            )
            for style, cells in groupby(line[: last_column + 1], key=lambda cell: cell[1]):
                rendered.append(''.join(character for character, _style in cells), style or None)
            if row < last_row:
                rendered.append('\n')
        return rendered

    def _ground(self, character: str) -> None:
        match character:
            case '\x1b':
                self._state = 'escape'
            case '\x9b':
                self._state = 'csi'
                self._sequence = ''
            case '\x9d' | '\x90' | '\x98' | '\x9e' | '\x9f':
                self._state = 'string'
            case '\n' | '\x0b' | '\x0c':
                self._row += 1
                self._column = 0
                self._ensure_row(self._row)
            case '\r':
                self._column = 0
            case '\b':
                self._column = max(0, self._column - 1)
            case '\t':
                self._column = (self._column // 8 + 1) * 8
            case _ if ' ' <= character <= '~' or character >= '\xa0':
                self._write(character)

    def _escape(self, character: str) -> None:
        match character:
            case '[':
                self._state = 'csi'
                self._sequence = ''
            case ']' | 'P' | 'X' | '^' | '_':
                self._state = 'string'
            case '(' | ')' | '*' | '+' | '-' | '.' | '/' | '#' | '%':
                self._state = 'escape-character'
            case _:
                self._state = 'ground'
                match character:
                    case '7':
                        self._saved_cursor = (self._row, self._column)
                    case '8':
                        self._row, self._column = self._saved_cursor
                        self._ensure_row(self._row)
                    case 'D':
                        self._row += 1
                        self._ensure_row(self._row)
                    case 'E':
                        self._row += 1
                        self._column = 0
                        self._ensure_row(self._row)
                    case 'M':
                        self._row = max(0, self._row - 1)
                    case 'c':
                        self.reset()

    def _csi(self, character: str) -> None:
        match character:
            case '\x1b':
                self._state = 'escape'
                self._sequence = ''
            case _ if '@' <= character <= '~':
                sequence = self._sequence
                self._state = 'ground'
                self._sequence = ''
                self._dispatch_csi(character, sequence)
            case _ if len(self._sequence) < 128:
                self._sequence += character

    def _dispatch_csi(self, command: str, sequence: str) -> None:
        # Private-mode prefixes and intermediate bytes don't change numeric
        # cursor/erase arguments. Unsupported commands are harmlessly ignored.
        parameter_text = sequence.lstrip('?><=!')
        parameter_text = ''.join(character for character in parameter_text if character.isdigit() or character in ';:')
        raw_parameters = parameter_text.replace(':', ';').split(';') if parameter_text else []
        parameters = [int(value) if value else 0 for value in raw_parameters]

        def parameter(index: int = 0, default: int = 1) -> int:
            if index >= len(parameters) or parameters[index] == 0:
                return default
            return parameters[index]

        match command:
            case 'A':
                self._row = max(0, self._row - parameter())
            case 'B':
                self._row += parameter()
            case 'C' | 'a':
                self._column += parameter()
            case 'D':
                self._column = max(0, self._column - parameter())
            case 'E':
                self._row += parameter()
                self._column = 0
            case 'F':
                self._row = max(0, self._row - parameter())
                self._column = 0
            case 'G' | '`':
                self._column = parameter() - 1
            case 'H' | 'f':
                self._row = parameter(0) - 1
                self._column = parameter(1) - 1
            case 'd':
                self._row = parameter() - 1
            case 'J':
                self._erase_display(parameters[0] if parameters else 0)
            case 'K':
                self._erase_line(parameters[0] if parameters else 0)
            case 'P':
                line = self._line()
                del line[self._column : self._column + parameter()]
            case '@':
                line = self._line()
                line[self._column : self._column] = [self._blank()] * parameter()
            case 'X':
                line = self._line()
                self._pad(line, self._column + parameter())
                line[self._column : self._column + parameter()] = [self._blank()] * parameter()
            case 'L':
                self._lines[self._row : self._row] = [[] for _ in range(parameter())]
            case 'M':
                del self._lines[self._row : self._row + parameter()]
            case 'S':
                count = min(parameter(), len(self._lines))
                del self._lines[:count]
                self._lines.extend([] for _ in range(count))
            case 'T':
                self._lines[:0] = [[] for _ in range(parameter())]
            case 'm':
                # Rich's ANSI decoder handles standard, bright, 256-color, and
                # true-color SGR parameters, as well as text attributes.
                self._ansi_decoder.decode_line(f'\x1b[{sequence}m')
            case 's':
                self._saved_cursor = (self._row, self._column)
            case 'u':
                self._row, self._column = self._saved_cursor

        self._ensure_row(self._row)

    def _write(self, character: str) -> None:
        line = self._line()
        self._pad(line, self._column)
        cell = (character, self._ansi_decoder.style)
        if self._column == len(line):
            line.append(cell)
        else:
            line[self._column] = cell
        self._column += 1

    def _erase_display(self, mode: int) -> None:
        match mode:
            case 2 | 3:
                self._lines = [[] for _ in range(max(1, self._row + 1))]
            case 0:
                self._erase_line(0)
                del self._lines[self._row + 1 :]
            case 1:
                for row in range(self._row):
                    self._lines[row] = []
                self._erase_line(1)

    def _erase_line(self, mode: int) -> None:
        line = self._line()
        match mode:
            case 0:
                del line[self._column :]
            case 1:
                self._pad(line, self._column + 1)
                line[: self._column + 1] = [self._blank()] * (self._column + 1)
            case 2:
                line.clear()

    def _line(self) -> TerminalLine:
        self._ensure_row(self._row)
        return self._lines[self._row]

    def _ensure_row(self, row: int) -> None:
        if row >= len(self._lines):
            self._lines.extend([] for _ in range(row + 1 - len(self._lines)))

    def _pad(self, line: TerminalLine, length: int) -> None:
        if len(line) < length:
            line.extend(self._blank() for _ in range(length - len(line)))

    def _blank(self) -> TerminalCell:
        return (' ', self._ansi_decoder.style)
