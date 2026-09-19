"""Unit tests for Phase 5: XRef indexing, XRef streams, ObjStm unpacker, and PDFDocument."""

from __future__ import annotations

import unittest
import zlib

from anyconvert.common.reader import ByteReader
from anyconvert.pdf.document import PDFDocument
from anyconvert.pdf.parser import (
    PDFArray,
    PDFDict,
    PDFIndirectRef,
    PDFName,
    PDFStream,
    PDFString,
)
from anyconvert.pdf.xref import (
    XRefEntry,
    XRefResolver,
    XRefTable,
    reverse_png_predictor,
)


class TestPNGPredictors(unittest.TestCase):
    """Tests for PNG predictor reversal."""

    def test_sub_predictor(self) -> None:
        # Row 1: tag 1 (Sub), deltas [10, 5, 2] -> values [10, 15, 17]
        raw = bytes([1, 10, 5, 2])
        decoded = reverse_png_predictor(raw, columns=3, bpp=1)
        self.assertEqual(decoded, bytes([10, 15, 17]))

    def test_up_predictor(self) -> None:
        # Row 1: tag 0 (None), [10, 20]
        # Row 2: tag 2 (Up), deltas [5, 10] -> [15, 30]
        raw = bytes([0, 10, 20, 2, 5, 10])
        decoded = reverse_png_predictor(raw, columns=2, bpp=1)
        self.assertEqual(decoded, bytes([10, 20, 15, 30]))


class TestClassicXRef(unittest.TestCase):
    """Tests for classic ASCII xref table parsing and object resolution."""

    def test_classic_xref_parsing(self) -> None:
        # Build synthetic PDF with classic xref
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"  # offset ~9
            b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n"  # offset ~55
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"  # offset ~115
        )
        # Calculate exact offsets
        off1 = pdf_bytes.find(b"1 0 obj")
        off2 = pdf_bytes.find(b"2 0 obj")
        off3 = pdf_bytes.find(b"3 0 obj")

        xref_pos = len(pdf_bytes)
        xref_bytes = (
            b"xref\n"
            b"0 4\n"
            b"0000000000 65535 f\r\n"
            + f"{off1:010d} 00000 n\r\n".encode("ascii")
            + f"{off2:010d} 00000 n\r\n".encode("ascii")
            + f"{off3:010d} 00000 n\r\n".encode("ascii")
            + b"trailer\n"
            b"<< /Size 4 /Root 1 0 R >>\n"
            b"startxref\n"
            + f"{xref_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )
        full_pdf = pdf_bytes + xref_bytes

        resolver = XRefResolver(full_pdf)
        table = resolver.table

        self.assertEqual(len(table.entries), 4)
        self.assertEqual(table.trailer.get("Root"), PDFIndirectRef(1, 0))

        # Resolve objects
        obj1 = resolver.resolve_object(1)
        self.assertIsInstance(obj1, PDFDict)
        assert isinstance(obj1, PDFDict)
        self.assertEqual(obj1["Type"], PDFName("Catalog"))

        obj3 = resolver.resolve_object(3)
        self.assertIsInstance(obj3, PDFDict)
        assert isinstance(obj3, PDFDict)
        self.assertEqual(obj3["Type"], PDFName("Page"))

    def test_incremental_update_prev(self) -> None:
        # Revision 1
        pdf_rev1 = (
            b"%PDF-1.4\n"
            b"1 0 obj\n(Original Version)\nendobj\n"
        )
        off1 = pdf_rev1.find(b"1 0 obj")
        xref1_pos = len(pdf_rev1)
        pdf_rev1 += (
            b"xref\n0 2\n"
            b"0000000000 65535 f\r\n"
            + f"{off1:010d} 00000 n\r\n".encode("ascii")
            + b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
            b"startxref\n"
            + f"{xref1_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )

        # Revision 2 updates object 1
        pdf_rev2 = (
            b"1 0 obj\n(Updated Version)\nendobj\n"
        )
        off1_updated = len(pdf_rev1) + pdf_rev2.find(b"1 0 obj")
        xref2_pos = len(pdf_rev1) + len(pdf_rev2)
        pdf_rev2 += (
            b"xref\n1 1\n"
            + f"{off1_updated:010d} 00000 n\r\n".encode("ascii")
            + b"trailer\n"
            + f"<< /Size 2 /Prev {xref1_pos} >>\n".encode("ascii")
            + b"startxref\n"
            + f"{xref2_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )

        full_pdf = pdf_rev1 + pdf_rev2
        resolver = XRefResolver(full_pdf)
        obj1 = resolver.resolve_object(1)
        self.assertIsInstance(obj1, PDFString)
        assert isinstance(obj1, PDFString)
        # Should resolve the updated version
        self.assertEqual(obj1.value, b"Updated Version")


class TestXRefStreamAndObjStm(unittest.TestCase):
    """Tests for PDF 1.5+ XRef streams and /ObjStm object streams."""

    def test_obj_stm_resolution(self) -> None:
        # Construct an /ObjStm stream containing 2 objects:
        # Obj 10: 12345
        # Obj 11: (Inside Stream)
        # Header: N=2, First=9
        # "10 0 11 6 " (length 9 bytes)
        # Body: "12345 (Inside Stream)"
        #   Offset 0: "12345"
        #   Offset 6: "(Inside Stream)"
        stream_payload = b"10 0 11 6 12345 (Inside Stream)"
        first_offset = 10  # len("10 0 11 6 ")
        compressed_payload = zlib.compress(stream_payload)

        # Build PDF
        pdf_header = b"%PDF-1.5\n"
        obj_stm_bytes = (
            b"5 0 obj\n"
            + f"<< /Type /ObjStm /N 2 /First {first_offset} /Length {len(compressed_payload)} /Filter /FlateDecode >>\n".encode("ascii")
            + b"stream\n"
            + compressed_payload
            + b"\nendstream\nendobj\n"
        )
        off5 = len(pdf_header)
        xref_pos = len(pdf_header) + len(obj_stm_bytes)

        # XRef table pointing 5 to file, and 10, 11 to ObjStm 5
        # Using XRef stream (/Type /XRef)
        # W = [1, 2, 1]
        # Entries:
        # Obj 0: type 0, off 0, gen 65535 -> [0, 0, 0, 255]
        # Obj 5: type 1, off off5, gen 0 -> [1, off5_hi, off5_lo, 0]
        # Obj 10: type 2, stm 5, idx 0 -> [2, 0, 5, 0]
        # Obj 11: type 2, stm 5, idx 1 -> [2, 0, 5, 1]
        raw_xref_data = bytearray()
        # Obj 0
        raw_xref_data.extend(bytes([0, 0, 0, 255]))
        # Obj 5
        raw_xref_data.extend(bytes([1, (off5 >> 8) & 0xFF, off5 & 0xFF, 0]))
        # Obj 10
        raw_xref_data.extend(bytes([2, 0, 5, 0]))
        # Obj 11
        raw_xref_data.extend(bytes([2, 0, 5, 1]))

        compressed_xref = zlib.compress(raw_xref_data)
        xref_stream_obj = (
            f"6 0 obj\n<< /Type /XRef /Size 12 /W [1 2 1] /Index [0 1 5 1 10 2] /Filter /FlateDecode /Length {len(compressed_xref)} >>\n".encode("ascii")
            + b"stream\n"
            + compressed_xref
            + b"\nendstream\nendobj\n"
            + b"startxref\n"
            + f"{xref_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )

        full_doc = pdf_header + obj_stm_bytes + xref_stream_obj
        resolver = XRefResolver(full_doc)

        # Resolve Obj 10 from ObjStm
        res10 = resolver.resolve_object(10)
        self.assertEqual(res10, 12345)

        # Resolve Obj 11 from ObjStm
        res11 = resolver.resolve_object(11)
        self.assertIsInstance(res11, PDFString)
        assert isinstance(res11, PDFString)
        self.assertEqual(res11.value, b"Inside Stream")


class TestPDFDocument(unittest.TestCase):
    """Tests for PDFDocument high-level page tree and metadata traversal."""

    def test_synthetic_document(self) -> None:
        # Build synthetic 2-page document with attribute inheritance
        content1 = b"BT /F1 12 Tf 72 712 Td (Page 1 Text) Tj ET"
        content2 = b"BT /F1 12 Tf 72 712 Td (Page 2 Text) Tj ET"
        c1_comp = zlib.compress(content1)
        c2_comp = zlib.compress(content2)

        pdf_body = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            # Parent Pages defines MediaBox inherited by both children
            b"2 0 obj\n<< /Type /Pages /Count 2 /MediaBox [0 0 595.28 841.89] /Kids [3 0 R 4 0 R] >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 5 0 R >>\nendobj\n"
            b"4 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 6 0 R /Rotate 90 >>\nendobj\n"
            + f"5 0 obj\n<< /Length {len(c1_comp)} /Filter /FlateDecode >>\nstream\n".encode("ascii")
            + c1_comp + b"\nendstream\nendobj\n"
            + f"6 0 obj\n<< /Length {len(c2_comp)} /Filter /FlateDecode >>\nstream\n".encode("ascii")
            + c2_comp + b"\nendstream\nendobj\n"
        )

        off1 = pdf_body.find(b"1 0 obj")
        off2 = pdf_body.find(b"2 0 obj")
        off3 = pdf_body.find(b"3 0 obj")
        off4 = pdf_body.find(b"4 0 obj")
        off5 = pdf_body.find(b"5 0 obj")
        off6 = pdf_body.find(b"6 0 obj")

        xref_pos = len(pdf_body)
        xref_bytes = (
            b"xref\n0 7\n"
            b"0000000000 65535 f\r\n"
            + f"{off1:010d} 00000 n\r\n".encode("ascii")
            + f"{off2:010d} 00000 n\r\n".encode("ascii")
            + f"{off3:010d} 00000 n\r\n".encode("ascii")
            + f"{off4:010d} 00000 n\r\n".encode("ascii")
            + f"{off5:010d} 00000 n\r\n".encode("ascii")
            + f"{off6:010d} 00000 n\r\n".encode("ascii")
            + b"trailer\n"
            b"<< /Size 7 /Root 1 0 R >>\n"
            b"startxref\n"
            + f"{xref_pos}\n".encode("ascii")
            + b"%%EOF\n"
        )
        full_pdf = pdf_body + xref_bytes

        doc = PDFDocument(full_pdf)
        self.assertEqual(doc.page_count, 2)

        # Page 1
        page1 = doc.get_page(0)
        # Inherited MediaBox (A4: 595.28 x 841.89)
        box1 = doc.get_page_box(page1, "MediaBox")
        self.assertAlmostEqual(box1[2], 595.28, places=2)
        self.assertAlmostEqual(box1[3], 841.89, places=2)
        self.assertEqual(doc.get_page_rotation(page1), 0)
        c1 = doc.get_page_content_bytes(page1)
        self.assertIn(b"Page 1 Text", c1)

        # Page 2
        page2 = doc.get_page(1)
        self.assertEqual(doc.get_page_rotation(page2), 90)
        c2 = doc.get_page_content_bytes(page2)
        self.assertIn(b"Page 2 Text", c2)


if __name__ == "__main__":
    unittest.main()
