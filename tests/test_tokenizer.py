from __future__ import annotations

from gerberdelta.parse.tokenizer import TokenType, tokenize_gerber


def tokens(s: str) -> list:
    return list(tokenize_gerber(s))


def test_g_code() -> None:
    toks = tokens("G01*")
    assert toks[0].type == TokenType.G
    assert toks[0].value == 1
    assert toks[1].type == TokenType.END_OF_BLOCK


def test_extended_command() -> None:
    toks = tokens("%FSLAX25Y25*%")
    assert toks[0].type == TokenType.EXTENDED
    assert toks[0].value == "FSLAX25Y25"


def test_multiple_extended_in_block() -> None:
    # Multiple commands inside one % block (e.g. AM definitions)
    toks = tokens("%AMTEST*1,1,0.5,0,0*%")
    extended = [t for t in toks if t.type == TokenType.EXTENDED]
    assert extended[0].value == "AMTEST"
    assert extended[1].value == "1,1,0.5,0,0"


def test_coordinate_word() -> None:
    toks = tokens("X123456Y789012*")
    assert toks[0].type == TokenType.X
    assert toks[0].value == 123456
    assert toks[1].type == TokenType.Y
    assert toks[1].value == 789012


def test_negative_coordinate() -> None:
    toks = tokens("X-5000*")
    assert toks[0].value == -5000


def test_eof() -> None:
    toks = tokens("")
    assert toks[-1].type == TokenType.EOF


def test_line_counting() -> None:
    toks = tokens("G01*\nG02*")
    assert toks[0].line == 1
    assert toks[2].line == 2


def test_d_code() -> None:
    toks = tokens("D10*")
    assert toks[0].type == TokenType.D
    assert toks[0].value == 10


def test_m_code() -> None:
    toks = tokens("M02*")
    assert toks[0].type == TokenType.M
    assert toks[0].value == 2


def test_g04_comment() -> None:
    toks = tokens("G04 a gerber comment *")
    assert toks[0].type == TokenType.COMMENT
    assert toks[0].value == "a gerber comment"


def test_raw_field_on_coordinate_tokens() -> None:
    # raw field carries the digit string (with sign if present) for X/Y/I/J
    toks = tokens("X-1234Y5678*")
    assert toks[0].raw == "-1234"
    assert toks[1].raw == "5678"


def test_arc_offsets() -> None:
    toks = tokens("I100J200*")
    assert toks[0].type == TokenType.I
    assert toks[0].value == 100
    assert toks[1].type == TokenType.J
    assert toks[1].value == 200


def test_whitespace_skipped() -> None:
    toks = tokens("  G01  *  ")
    types = [t.type for t in toks]
    assert TokenType.G in types
    assert TokenType.END_OF_BLOCK in types
    assert TokenType.EOF in types
