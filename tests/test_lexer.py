"""Test suite for Phase 4: PDF Lexical Scanner."""

from __future__ import annotations

import unittest

from anyconvert.exceptions import PDFSyntaxError
from anyconvert.pdf.lexer import Lexer, Token, TokenType


class TestLexer(unittest.TestCase):
    """Test PDF lexical tokenization."""

    def test_booleans_and_null(self) -> None:
        lexer = Lexer(b"true false null")
        t1 = lexer.next_token()
        self.assertEqual(t1.type, TokenType.BOOLEAN)
        self.assertIs(t1.value, True)

        t2 = lexer.next_token()
        self.assertEqual(t2.type, TokenType.BOOLEAN)
        self.assertIs(t2.value, False)

        t3 = lexer.next_token()
        self.assertEqual(t3.type, TokenType.KEYWORD)
        self.assertIsNone(t3.value)

        self.assertEqual(lexer.next_token().type, TokenType.EOF)

    def test_numeric_tokens(self) -> None:
        lexer = Lexer(b"0 42 -17 +300 3.14 -0.005 +.5 12.")
        expected = [0, 42, -17, 300, 3.14, -0.005, 0.5, 12.0]
        for val in expected:
            tok = lexer.next_token()
            if isinstance(val, int):
                self.assertEqual(tok.type, TokenType.INTEGER)
                self.assertEqual(tok.value, val)
            else:
                self.assertEqual(tok.type, TokenType.REAL)
                self.assertAlmostEqual(tok.value, val)

    def test_literal_strings_and_nesting(self) -> None:
        # Balanced nested parentheses: (Hello (World (PDF) !) )
        raw = b"(Hello (World (PDF) !) )"
        lexer = Lexer(raw)
        tok = lexer.next_token()
        self.assertEqual(tok.type, TokenType.STRING_LITERAL)
        self.assertEqual(tok.value, b"Hello (World (PDF) !) ")

    def test_literal_string_escapes(self) -> None:
        # Escapes: \n, \r, \t, \b, \f, \(, \), \\, \101 (octal 'A')
        raw = b"(\\n\\r\\t\\b\\f\\(\\)\\\\ \\101\\102)"
        lexer = Lexer(raw)
        tok = lexer.next_token()
        self.assertEqual(tok.value, b"\n\r\t\b\x0c()\\ AB")

    def test_literal_string_line_continuation(self) -> None:
        raw = b"(This is a multi-\\\nline string)"
        lexer = Lexer(raw)
        tok = lexer.next_token()
        self.assertEqual(tok.value, b"This is a multi-line string")

    def test_hex_strings(self) -> None:
        # Standard hex string
        lexer = Lexer(b"<48656C6C6F>")
        tok = lexer.next_token()
        self.assertEqual(tok.type, TokenType.STRING_HEX)
        self.assertEqual(tok.value, b"Hello")

        # Hex string with whitespace
        lexer_ws = Lexer(b"< 48 65 6c 6c 6f >")
        tok_ws = lexer_ws.next_token()
        self.assertEqual(tok_ws.value, b"Hello")

        # Odd number of digits: pads trailing 0 -> <901> becomes <9010> -> b"\x90\x10"
        lexer_odd = Lexer(b"<901>")
        tok_odd = lexer_odd.next_token()
        self.assertEqual(tok_odd.value, bytes([0x90, 0x10]))

    def test_names_and_escapes(self) -> None:
        raw = b"/Normal /Name#20With#20Spaces /Slash#2FInside /Hash#23Char"
        lexer = Lexer(raw)

        t1 = lexer.next_token()
        self.assertEqual(t1.type, TokenType.NAME)
        self.assertEqual(t1.value, "Normal")

        t2 = lexer.next_token()
        self.assertEqual(t2.value, "Name With Spaces")

        t3 = lexer.next_token()
        self.assertEqual(t3.value, "Slash/Inside")

        t4 = lexer.next_token()
        self.assertEqual(t4.value, "Hash#Char")

    def test_delimiters_and_keywords(self) -> None:
        raw = b"[ ] << >> { } obj endobj stream endstream xref trailer startxref R"
        lexer = Lexer(raw)
        expected_delims = ["[", "]", "<<", ">>", "{", "}"]
        for d in expected_delims:
            tok = lexer.next_token()
            self.assertEqual(tok.type, TokenType.DELIMITER)
            self.assertEqual(tok.value, d)

        expected_kws = [
            "obj",
            "endobj",
            "stream",
            "endstream",
            "xref",
            "trailer",
            "startxref",
            "R",
        ]
        for kw in expected_kws:
            tok = lexer.next_token()
            self.assertEqual(tok.type, TokenType.KEYWORD)
            self.assertEqual(tok.value, kw)

    def test_peek_and_push_token(self) -> None:
        lexer = Lexer(b"123 456")
        p = lexer.peek_token()
        self.assertEqual(p.value, 123)

        t1 = lexer.next_token()
        self.assertEqual(t1.value, 123)

        lexer.push_token(t1)
        t1_again = lexer.next_token()
        self.assertEqual(t1_again.value, 123)

        t2 = lexer.next_token()
        self.assertEqual(t2.value, 456)


if __name__ == "__main__":
    unittest.main()
