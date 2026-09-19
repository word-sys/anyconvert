"""Unit tests for Phase 4: PDF Lexical Scanner and Object Parser."""

from __future__ import annotations

import unittest

from anyconvert.exceptions import PDFSyntaxError
from anyconvert.pdf.lexer import PDFLexer, TokenType
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFHexString,
    PDFIndirectObject,
    PDFIndirectRef,
    PDFName,
    PDFNull,
    PDFParser,
    PDFStream,
    PDFString,
)


class TestPDFLexer(unittest.TestCase):
    """Tests for PDF lexical analyzer."""

    def test_booleans_and_null(self) -> None:
        lexer = PDFLexer(b"true false null")
        tok1 = lexer.next_token()
        self.assertEqual(tok1.type, TokenType.BOOLEAN)
        self.assertIs(tok1.value, True)

        tok2 = lexer.next_token()
        self.assertEqual(tok2.type, TokenType.BOOLEAN)
        self.assertIs(tok2.value, False)

        tok3 = lexer.next_token()
        self.assertEqual(tok3.type, TokenType.KEYWORD)
        self.assertEqual(tok3.value, "null")

        self.assertEqual(lexer.next_token().type, TokenType.EOF)

    def test_numbers(self) -> None:
        lexer = PDFLexer(b"0 123 -456 +789 3.1415 -.002 12.")
        expected = [0, 123, -456, 789, 3.1415, -0.002, 12.0]
        for exp in expected:
            tok = lexer.next_token()
            self.assertEqual(tok.type, TokenType.NUMBER)
            self.assertEqual(tok.value, exp)

    def test_literal_strings(self) -> None:
        # Simple
        l1 = PDFLexer(b"(Hello World)")
        t1 = l1.next_token()
        self.assertEqual(t1.type, TokenType.STRING)
        self.assertEqual(t1.value, b"Hello World")

        # Nested balanced parentheses
        l2 = PDFLexer(b"(Text with (nested (parens)) inside)")
        t2 = l2.next_token()
        self.assertEqual(t2.value, b"Text with (nested (parens)) inside")

        # Escape sequences
        l3 = PDFLexer(rb"(Line 1\nLine 2\rTab\tBS\bFF\fEsc\(Esc\)Slash\\Octal\101)")
        t3 = l3.next_token()
        self.assertEqual(t3.value, b"Line 1\nLine 2\rTab\tBS\x08FF\x0cEsc(Esc)Slash\\OctalA")

        # Line continuation backslash
        l4 = PDFLexer(b"(This is a \\\ncontinued string)")
        t4 = l4.next_token()
        self.assertEqual(t4.value, b"This is a continued string")

        # Unterminated string raises PDFSyntaxError
        l5 = PDFLexer(b"(Unterminated string")
        with self.assertRaises(PDFSyntaxError):
            l5.next_token()

    def test_hex_strings(self) -> None:
        # Standard hex string
        l1 = PDFLexer(b"<48656C6C6F>")
        t1 = l1.next_token()
        self.assertEqual(t1.type, TokenType.HEX_STRING)
        self.assertEqual(t1.value, b"Hello")

        # Whitespace ignored in hex string
        l2 = PDFLexer(b"< 48 65 6C 6C 6F >")
        t2 = l2.next_token()
        self.assertEqual(t2.value, b"Hello")

        # Odd number of digits padded with 0
        l3 = PDFLexer(b"<48656C6C6>")
        t3 = l3.next_token()
        self.assertEqual(t3.value, b"Hell`")  # 0x60 is '`'

        # Unterminated hex string
        l4 = PDFLexer(b"<4865")
        with self.assertRaises(PDFSyntaxError):
            l4.next_token()

    def test_names(self) -> None:
        # Standard name
        l1 = PDFLexer(b"/Type /Page /Length")
        self.assertEqual(l1.next_token().value, "Type")
        self.assertEqual(l1.next_token().value, "Page")
        self.assertEqual(l1.next_token().value, "Length")

        # Hex escaped name per PDF 1.2+
        l2 = PDFLexer(b"/Name#20With#20Spaces /PANOSE#201")
        self.assertEqual(l2.next_token().value, "Name With Spaces")
        self.assertEqual(l2.next_token().value, "PANOSE 1")

    def test_delimiters_and_comments(self) -> None:
        raw = b"<< % Comment\n /Key [1 2 3] >>"
        lexer = PDFLexer(raw)
        self.assertEqual(lexer.next_token().value, "<<")
        self.assertEqual(lexer.next_token().value, "Key")
        self.assertEqual(lexer.next_token().value, "[")
        self.assertEqual(lexer.next_token().value, 1)
        self.assertEqual(lexer.next_token().value, 2)
        self.assertEqual(lexer.next_token().value, 3)
        self.assertEqual(lexer.next_token().value, "]")
        self.assertEqual(lexer.next_token().value, ">>")


class TestPDFParser(unittest.TestCase):
    """Tests for PDF recursive-descent object parser."""

    def test_primitives(self) -> None:
        parser = PDFParser(b"null true false (Hello) <414243> /TestName 42 3.14")
        self.assertIsInstance(parser.parse_object(), PDFNull)
        self.assertIs(parser.parse_object(), True)
        self.assertIs(parser.parse_object(), False)

        str_obj = parser.parse_object()
        self.assertIsInstance(str_obj, PDFString)
        assert isinstance(str_obj, PDFString)
        self.assertEqual(str_obj.value, b"Hello")
        self.assertEqual(str_obj.as_text(), "Hello")

        hex_obj = parser.parse_object()
        self.assertIsInstance(hex_obj, PDFHexString)
        assert isinstance(hex_obj, PDFHexString)
        self.assertEqual(hex_obj.value, b"ABC")

        name_obj = parser.parse_object()
        self.assertEqual(name_obj, PDFName("TestName"))
        self.assertEqual(name_obj, "TestName")
        self.assertEqual(name_obj, "/TestName")

        self.assertEqual(parser.parse_object(), 42)
        self.assertEqual(parser.parse_object(), 3.14)
        self.assertIsNone(parser.parse_object())

    def test_array(self) -> None:
        parser = PDFParser(b"[ 1 2.5 (three) /Four [ 5 6 ] ]")
        arr = parser.parse_object()
        self.assertIsInstance(arr, PDFArray)
        assert isinstance(arr, PDFArray)
        self.assertEqual(len(arr), 5)
        self.assertEqual(arr[0], 1)
        self.assertEqual(arr[1], 2.5)
        self.assertEqual(arr[2], PDFString(b"three"))
        self.assertEqual(arr[3], PDFName("Four"))
        self.assertEqual(arr[4], [5, 6])

    def test_dictionary(self) -> None:
        raw = b"<< /Type /Catalog /Pages 2 0 R /Metadata (Document Metadata) >>"
        parser = PDFParser(raw)
        d = parser.parse_object()
        self.assertIsInstance(d, PDFDict)
        assert isinstance(d, PDFDict)

        # Access with /Type, Type, or PDFName("Type")
        self.assertEqual(d["Type"], PDFName("Catalog"))
        self.assertEqual(d["/Type"], PDFName("Catalog"))
        self.assertEqual(d[PDFName("Type")], PDFName("Catalog"))

        self.assertEqual(d.get("Pages"), PDFIndirectRef(2, 0))
        self.assertEqual(d.get("/Pages"), PDFIndirectRef(2, 0))

        self.assertEqual(d["Metadata"], PDFString(b"Document Metadata"))

    def test_indirect_references(self) -> None:
        parser = PDFParser(b"10 0 R 45 2 R")
        ref1 = parser.parse_object()
        self.assertEqual(ref1, PDFIndirectRef(10, 0))
        ref2 = parser.parse_object()
        self.assertEqual(ref2, PDFIndirectRef(45, 2))

    def test_indirect_object_definition(self) -> None:
        raw = b"5 0 obj << /Type /Page /Rotate 0 >> endobj"
        parser = PDFParser(raw)
        obj = parser.parse_object()
        self.assertIsInstance(obj, PDFIndirectObject)
        assert isinstance(obj, PDFIndirectObject)
        self.assertEqual(obj.obj_id, 5)
        self.assertEqual(obj.generation, 0)
        self.assertIsInstance(obj.value, PDFDict)
        self.assertEqual(obj.value["Type"], PDFName("Page"))
        self.assertEqual(obj.value["Rotate"], 0)

    def test_stream_with_length(self) -> None:
        raw = (
            b"12 0 obj\n"
            b"<< /Length 13 /Filter /FlateDecode >>\n"
            b"stream\n"
            b"Hello World!\n"
            b"endstream\n"
            b"endobj"
        )
        parser = PDFParser(raw)
        obj = parser.parse_object()
        self.assertIsInstance(obj, PDFIndirectObject)
        assert isinstance(obj, PDFIndirectObject)
        self.assertEqual(obj.obj_id, 12)

        stream = obj.value
        self.assertIsInstance(stream, PDFStream)
        assert isinstance(stream, PDFStream)
        self.assertEqual(stream.dict["Length"], 13)
        self.assertEqual(stream.dict["Filter"], PDFName("FlateDecode"))
        self.assertEqual(stream.get_raw_bytes(), b"Hello World!\n")

    def test_stream_without_length_fallback(self) -> None:
        raw = (
            b"15 0 obj\n"
            b"<< >>\n"
            b"stream\r\n"
            b"Binary Payload Without Direct Length\r\n"
            b"endstream\n"
            b"endobj"
        )
        parser = PDFParser(raw)
        obj = parser.parse_object()
        assert isinstance(obj, PDFIndirectObject)
        stream = obj.value
        assert isinstance(stream, PDFStream)
        self.assertEqual(stream.get_raw_bytes(), b"Binary Payload Without Direct Length")

    def test_string_encodings(self) -> None:
        # UTF-16BE with BOM
        utf16_str = PDFString(b"\xfe\xff\x00H\x00e\x00l\x00l\x00o")
        self.assertEqual(utf16_str.as_text(), "Hello")

        # UTF-8 with BOM
        utf8_str = PDFString(b"\xef\xbb\xbfWorld")
        self.assertEqual(utf8_str.as_text(), "World")

        # Latin1 fallback
        latin1_str = PDFString(b"Caf\xe9")
        self.assertEqual(latin1_str.as_text(), "Café")


if __name__ == "__main__":
    unittest.main()
