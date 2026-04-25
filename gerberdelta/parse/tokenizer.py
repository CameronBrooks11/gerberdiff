from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from enum import StrEnum


class TokenType(StrEnum):
    G = "G"
    D = "D"
    M = "M"
    X = "X"
    Y = "Y"
    I = "I"  # noqa: E741
    J = "J"
    END_OF_BLOCK = "EOB"
    EXTENDED = "EXTENDED"
    COMMENT = "COMMENT"
    EOF = "EOF"


@dataclass
class Token:
    type: TokenType
    value: int | str | None  # int for G/D/M/X/Y/I/J; str for EXTENDED/COMMENT; None for EOB/EOF
    line: int
    # raw digit string for X/Y/I/J — needed by convert_coordinate for trailing-zero omission
    raw: str | None = field(default=None)


def tokenize_gerber(content: str) -> Generator[Token, None, None]:
    """Yield tokens from a Gerber RS-274X file content string.

    Handles:
    - %...% extended command blocks (yields one EXTENDED token per *-terminated
      command inside the block; the % delimiters are stripped)
    - G04 comments (rest of block until * is the comment body)
    - Coordinate words: X, Y, I, J with sign-aware integer values
    - G, D, M codes with integer values
    - Bare * end-of-block separators
    - Whitespace and newlines outside extended blocks are silently skipped
    """
    pos = 0
    line = 1
    length = len(content)

    def peek() -> str:
        return content[pos] if pos < length else ""

    def advance() -> str:
        nonlocal pos, line
        ch = content[pos]
        pos += 1
        if ch == "\n":
            line += 1
        return ch

    def read_digits() -> tuple[str, int]:
        """Consume an optional leading sign then digit characters.

        Returns (raw_str, parsed_int).  raw_str carries the sign (if any) and
        all digit characters exactly as written — needed for trailing-zero-omission
        coordinate scaling.  parsed_int is the signed integer value (0 on empty).
        """
        raw = ""
        if peek() in ("+", "-"):
            raw += advance()
        while pos < length and content[pos].isdigit():
            raw += advance()
        value = int(raw, 10) if raw and raw not in ("+", "-") else 0
        return raw, value

    while pos < length:
        ch = peek()

        # Skip whitespace and newlines (newlines also increment `line` via advance)
        if ch in (" ", "\t", "\r", "\n"):
            advance()
            continue

        tok_line = line

        if ch == "%":
            advance()  # consume opening %
            buf = ""
            while pos < length and peek() != "%":
                c = peek()
                if c == "*":
                    advance()
                    if buf:
                        yield Token(TokenType.EXTENDED, buf, tok_line)
                        buf = ""
                elif c in ("\n", "\r"):
                    advance()
                else:
                    buf += advance()
            # Emit any trailing content before closing %
            if buf:
                yield Token(TokenType.EXTENDED, buf, tok_line)
            if pos < length and peek() == "%":
                advance()  # consume closing %

        elif ch == "G":
            advance()
            raw, num = read_digits()
            if num == 4:
                # G04: rest of block (until *) is a comment
                comment = ""
                while pos < length and peek() != "*":
                    comment += advance()
                yield Token(TokenType.COMMENT, comment.strip(), tok_line)
            else:
                yield Token(TokenType.G, num, tok_line)

        elif ch == "D":
            advance()
            _, num = read_digits()
            yield Token(TokenType.D, num, tok_line)

        elif ch == "M":
            advance()
            _, num = read_digits()
            yield Token(TokenType.M, num, tok_line)

        elif ch == "X":
            advance()
            raw, num = read_digits()
            yield Token(TokenType.X, num, tok_line, raw)

        elif ch == "Y":
            advance()
            raw, num = read_digits()
            yield Token(TokenType.Y, num, tok_line, raw)

        elif ch == "I":
            advance()
            raw, num = read_digits()
            yield Token(TokenType.I, num, tok_line, raw)

        elif ch == "J":
            advance()
            raw, num = read_digits()
            yield Token(TokenType.J, num, tok_line, raw)

        elif ch == "*":
            advance()
            yield Token(TokenType.END_OF_BLOCK, None, tok_line)

        else:
            # Unknown character — skip silently (robustness for non-standard files)
            advance()

    yield Token(TokenType.EOF, None, line)
