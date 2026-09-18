"""Test suite for Phase 5: Cross-Reference Indexer & Object Stream Resolver."""

from __future__ import annotations

import unittest
import zlib

from anyconvert.common.reader import ByteReader
from anyconvert.exceptions import PDFTrailerNotFoundError, PDFXRefError
from anyconvert.pdf.parser import PDFRef, PDFStream
from anyconvert.pdf.xref import (
    ObjectStreamUnpacker,
    XRefEntry,
    XRefParser,
    XRefResolver,
    XRefTable,
    XRefType,
    _apply_png_predictor,
)


class TestXRef(unittest.TestCase):
    """Test cross-reference tables, xref streams, and compressed object streams."""

    def test_locate_startxref(self) -> None:
        raw = (
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog >> endobj\n"
            b"xref\n0 2\n0000000000 65535 f \n0000000010 00000 n \n"
            b"trailer << /Size 2 /Root 1 0 R >>\n"
            b"startxref\n"
            b"45\n"
            b"%%EOF\n"
        )
        parser = XRefParser(raw)
        self.assertEqual(parser.locate_startxref(), 45)

    def test_locate_startxref_missing_raises_error(self) -> None:
        raw = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF"
        parser = XRefParser(raw)
        with self.assertRaises(PDFTrailerNotFoundError):
            parser.locate_startxref()

    def test_parse_classic_xref_and_resolve(self) -> None:
        header = b"%PDF-1.4\n"
        obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        obj2 = b"2 0 obj\n<< /Type /Pages /Count 0 /Kids [] >>\nendobj\n"

        offset1 = len(header)
        offset2 = offset1 + len(obj1)
        xref_offset = offset2 + len(obj2)

        xref_block = (
            f"xref\n"
            f"0 3\n"
            f"0000000000 65535 f \r\n"
            f"{offset1:010d} 00000 n \r\n"
            f"{offset2:010d} 00000 n \r\n"
            f"trailer\n"
            f"<< /Size 3 /Root 1 0 R >>\n"
            f"startxref\n"
            f"{xref_offset}\n"
            f"%%EOF\n"
        ).encode("ascii")

        full_pdf = header + obj1 + obj2 + xref_block


        resolver = XRefResolver(full_pdf)
        self.assertEqual(resolver.trailer["Size"], 3)
        self.assertEqual(resolver.trailer["Root"], PDFRef(1, 0))

        # Resolve Root (obj 1)
        root = resolver.resolve(1)
        self.assertIsInstance(root, dict)
        self.assertEqual(root["Type"], "Catalog")
        self.assertEqual(root["Pages"], PDFRef(2, 0))

        # Resolve Pages (obj 2)
        pages = resolver.resolve_ref(root["Pages"])
        self.assertIsInstance(pages, dict)
        self.assertEqual(pages["Type"], "Pages")
        self.assertEqual(pages["Count"], 0)

    def test_incremental_update_with_prev(self) -> None:
        # Revision 1 at offset 100, Revision 2 at offset 200 with /Prev 100
        # Obj 1 modified in Revision 2
        rev1_xref = (
            b"xref\n0 2\n"
            b"0000000000 65535 f \r\n"
            b"0000000010 00000 n \r\n"
            b"trailer << /Size 2 /Title (Original) >>\n"
        )
        # Pad up to 100
        part1 = b" " * 100 + rev1_xref
        # Now at len(part1), pad up to 200
        part2 = b" " * (200 - len(part1))

        rev2_xref = (
            b"xref\n1 1\n"
            b"0000000050 00000 n \r\n"  # Obj 1 moved to offset 50
            b"trailer << /Size 2 /Title (Updated) /Prev 100 >>\n"
            b"startxref\n200\n%%EOF\n"
        )
        pdf = part1 + part2 + rev2_xref

        xref_table = XRefParser(pdf).parse()
        # Obj 1 should have offset 50 from rev2 (newest)
        entry1 = xref_table.get_entry(1)
        self.assertIsNotNone(entry1)
        assert entry1 is not None
        self.assertEqual(entry1.offset, 50)
        self.assertEqual(xref_table.trailer["Title"].as_text(), "Updated")

    def test_binary_xref_stream(self) -> None:
        # Cross-reference stream /Type /XRef
        # W = [1, 2, 1] (total 4 bytes per entry)
        # Entry 0: Type 0, NextFree 0, Gen 65535 -> 00 0000 FFFF
        # Entry 1: Type 1, Offset 100, Gen 0     -> 01 0064 0000
        # Entry 2: Type 2, ObjStm 5, Idx 1       -> 02 0005 0001
        entries = bytes([
            0, 0, 0, 0xFF,
            1, 0, 100, 0,
            2, 0, 5, 1,
        ])
        compressed_entries = zlib.compress(entries)

        stream_body = (
            b"10 0 obj\n"
            b"<< /Type /XRef /Size 3 /W [1 2 1] /Length "
            + str(len(compressed_entries)).encode("ascii")
            + b" /Filter /FlateDecode >>\n"
            b"stream\n"
            + compressed_entries
            + b"\nendstream\nendobj\n"
            b"startxref\n0\n%%EOF\n"
        )

        xref_table = XRefTable()
        parser = XRefParser(stream_body)
        parser._parse_xref_stream(0, xref_table)

        self.assertEqual(len(xref_table.entries), 3)
        e0 = xref_table.get_entry(0)
        assert e0 is not None
        self.assertEqual(e0.entry_type, XRefType.FREE)

        e1 = xref_table.get_entry(1)
        assert e1 is not None
        self.assertEqual(e1.entry_type, XRefType.UNCOMPRESSED)
        self.assertEqual(e1.offset, 100)

        e2 = xref_table.get_entry(2)
        assert e2 is not None
        self.assertEqual(e2.entry_type, XRefType.COMPRESSED)
        self.assertEqual(e2.offset, 5)  # ObjStm container
        self.assertEqual(e2.gen_or_idx, 1)  # index within stream

    def test_compressed_object_stream_unpacking(self) -> None:
        # Build an /ObjStm with two objects:
        # Obj 20: [1 2 3]
        # Obj 21: << /Greeting (Hello) >>
        header = b"20 0 21 8 "  # First=18
        body = b"[1 2 3] << /Greeting (Hello) >>"
        full_content = header + body  # len(header) = 10 -> First is 10
        # Wait: header is b"20 0 21 8 ", length is 10 bytes!
        # At rel offset 0: b"[1 2 3] " (len 8)
        # At rel offset 8: b"<< /Greeting (Hello) >>"
        first_offset = len(header)
        compressed = zlib.compress(full_content)

        obj_stm_raw = (
            b"5 0 obj\n"
            b"<< /Type /ObjStm /N 2 /First " + str(first_offset).encode("ascii")
            + b" /Length " + str(len(compressed)).encode("ascii")
            + b" /Filter /FlateDecode >>\n"
            b"stream\n"
            + compressed
            + b"\nendstream\nendobj\n"
        )

        reader = ByteReader(obj_stm_raw)
        xref = XRefTable()
        xref.add_entry(XRefEntry(5, XRefType.UNCOMPRESSED, offset=0, gen_or_idx=0))
        xref.add_entry(XRefEntry(20, XRefType.COMPRESSED, offset=5, gen_or_idx=0))
        xref.add_entry(XRefEntry(21, XRefType.COMPRESSED, offset=5, gen_or_idx=1))

        unpacker = ObjectStreamUnpacker(reader, xref)
        val20 = unpacker.unpack_object(5, 20)
        self.assertEqual(val20, [1, 2, 3])

        val21 = unpacker.unpack_object(5, 21)
        self.assertIsInstance(val21, dict)
        self.assertEqual(val21["Greeting"].as_text(), "Hello")

    def test_png_predictor_inversion(self) -> None:
        # Test 2 rows of 3 columns with PNG Up predictor (filter type 2)
        # Row 1 (filter 0 - None): 10, 20, 30
        # Row 2 (filter 2 - Up):   1,  2,  3 -> reconstructed: 11, 22, 33
        raw_filtered = bytes([
            0, 10, 20, 30,
            2, 1, 2, 3,
        ])
        reconstructed = _apply_png_predictor(raw_filtered, columns=3)
        self.assertEqual(reconstructed, bytes([10, 20, 30, 11, 22, 33]))


if __name__ == "__main__":
    unittest.main()
