"""Test suite for Phase 4: PDF Object Parser."""

from __future__ import annotations

import unittest

from anyconvert.exceptions import PDFSyntaxError
from anyconvert.pdf.parser import (
    PDFIndirectObject,
    PDFName,
    PDFRef,
    PDFStream,
    PDFString,
    Parser,
)


class TestParser(unittest.TestCase):
    """Test parsing of composite PDF structures and indirect objects."""

    def test_parse_primitives(self) -> None:
        parser = Parser(b"true 123 45.67 (A string) <486578> /MyName null")
        self.assertIs(parser.parse_object(), True)
        self.assertEqual(parser.parse_object(), 123)
        self.assertAlmostEqual(parser.parse_object(), 45.67)

        s1 = parser.parse_object()
        self.assertIsInstance(s1, PDFString)
        self.assertEqual(s1.as_text(), "A string")
        self.assertFalse(s1.is_hex)

        s2 = parser.parse_object()
        self.assertIsInstance(s2, PDFString)
        self.assertEqual(s2.data, b"Hex")
        self.assertTrue(s2.is_hex)

        name = parser.parse_object()
        self.assertIsInstance(name, PDFName)
        self.assertEqual(name, "MyName")

        self.assertIsNone(parser.parse_object())

    def test_parse_array(self) -> None:
        raw = b"[1 2.5 (text) /Name [true false] 10 0 R]"
        parser = Parser(raw)
        arr = parser.parse_object()
        self.assertIsInstance(arr, list)
        self.assertEqual(len(arr), 6)
        self.assertEqual(arr[0], 1)
        self.assertAlmostEqual(arr[1], 2.5)
        self.assertEqual(arr[2].data, b"text")
        self.assertEqual(arr[3], "Name")
        self.assertEqual(arr[4], [True, False])
        self.assertEqual(arr[5], PDFRef(10, 0))

    def test_parse_dictionary(self) -> None:
        raw = b"<< /Type /Catalog /Pages 2 0 R /Version 1.7 /OpenAction [0 /Fit] >>"
        parser = Parser(raw)
        d = parser.parse_object()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["Type"], "Catalog")
        self.assertEqual(d["Pages"], PDFRef(2, 0))
        self.assertAlmostEqual(d["Version"], 1.7)
        self.assertEqual(d["OpenAction"], [0, "Fit"])

    def test_parse_indirect_object(self) -> None:
        raw = b"12 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj"
        parser = Parser(raw)
        obj = parser.parse_object()
        self.assertIsInstance(obj, PDFIndirectObject)
        self.assertEqual(obj.obj_num, 12)
        self.assertEqual(obj.gen_num, 0)
        self.assertIsInstance(obj.value, dict)
        self.assertEqual(obj.value["Type"], "Pages")
        self.assertEqual(obj.value["Count"], 1)
        self.assertEqual(obj.value["Kids"], [PDFRef(3, 0)])

    def test_parse_stream_with_length(self) -> None:
        stream_payload = b"BT /F1 12 Tf 72 712 Td (Hello World) Tj ET"
        raw = (
            b"5 0 obj\n"
            b"<< /Length " + str(len(stream_payload)).encode("ascii") + b" >>\n"
            b"stream\r\n" + stream_payload + b"\r\nendstream\nendobj"
        )
        parser = Parser(raw)
        obj = parser.parse_object()
        self.assertIsInstance(obj, PDFIndirectObject)
        self.assertEqual(obj.obj_num, 5)

        stream = obj.value
        self.assertIsInstance(stream, PDFStream)
        self.assertEqual(stream.to_bytes(), stream_payload)
        self.assertEqual(stream.dictionary["Length"], len(stream_payload))

    def test_parse_stream_without_length_fallback(self) -> None:
        stream_payload = b"q 1 0 0 1 50 50 cm /Im1 Do Q"
        raw = (
            b"<< /Type /XObject /Subtype /Form >>\n"
            b"stream\n" + stream_payload + b"\nendstream"
        )
        parser = Parser(raw)
        stream = parser.parse_object()
        self.assertIsInstance(stream, PDFStream)
        self.assertEqual(stream.to_bytes(), stream_payload)
        self.assertEqual(stream.dictionary["Subtype"], "Form")

    def test_syntax_errors(self) -> None:
        # Unclosed array
        with self.assertRaises(PDFSyntaxError):
            Parser(b"[1 2 3").parse_object()

        # Unclosed dict
        with self.assertRaises(PDFSyntaxError):
            Parser(b"<< /Key 123").parse_object()

        # Non-name key in dictionary
        with self.assertRaises(PDFSyntaxError):
            Parser(b"<< 123 /Value >>").parse_object()


if __name__ == "__main__":
    unittest.main()
