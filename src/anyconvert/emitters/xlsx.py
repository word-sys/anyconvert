"""Zero-dependency ISO/IEC 29500-2 SpreadsheetML (.xlsx) emitter.

Extracts detected tables from DocumentIR (including multi-page continuous tables)
and serializes them into native Excel/LibreOffice Calc (.xlsx) workbooks with
worksheets, cell grids, column widths, shared strings, and <mergeCell> ranges.
"""

from __future__ import annotations

from typing import List, Optional

from anyconvert.emitters.base import BaseEmitter, ConversionMode
from anyconvert.emitters.csv import ExtractedTable, extract_tables_from_ir
from anyconvert.exceptions import SerializationError
from anyconvert.ir.model import DocumentIR, Paragraph
from anyconvert.packaging.xlsx import XLSXPackage


class XlsxEmitter(BaseEmitter):
    """Pure-Python SpreadsheetML (.xlsx) document and table emitter."""

    __slots__ = (
        "table_index",
        "merge_multipage",
        "export_tables_only",
    )

    def __init__(
        self,
        table_index: Optional[int] = None,
        merge_multipage: bool = True,
        export_tables_only: bool = False,
    ) -> None:
        self.table_index: Optional[int] = table_index
        self.merge_multipage: bool = merge_multipage
        self.export_tables_only: bool = export_tables_only

    def extract_tables(self, doc_ir: DocumentIR) -> List[ExtractedTable]:
        """Extract all normalized tables from DocumentIR."""
        return extract_tables_from_ir(
            doc_ir,
            merge_multipage=self.merge_multipage,
            fill_merged_cells=False,
        )

    def build_package(self, doc_ir: DocumentIR) -> XLSXPackage:
        """Build an XLSXPackage from DocumentIR tables (or fallback document sheet)."""
        if not doc_ir.pages:
            raise SerializationError("Cannot emit XLSX from empty DocumentIR")

        tables = self.extract_tables(doc_ir)
        pkg = XLSXPackage(metadata=doc_ir.metadata)

        if self.table_index is not None:
            if not tables:
                raise SerializationError(
                    f"No tables found in document (requested table_index={self.table_index})"
                )
            if self.table_index < 0 or self.table_index >= len(tables):
                raise SerializationError(
                    f"table_index {self.table_index} out of range (found {len(tables)} table(s): 0..{len(tables) - 1})"
                )
            selected = [tables[self.table_index]]
        else:
            selected = tables

        if selected:
            for tbl in selected:
                sheet_title = f"Table {tbl.index + 1}"
                pkg.add_sheet(
                    name=sheet_title,
                    rows=tbl.rows,
                    header_row_count=max(1, tbl.header_row_count) if tbl.rows else 0,
                    col_widths=tbl.col_widths,
                    merges=tbl.merges,
                )
            return pkg

        if self.export_tables_only:
            raise SerializationError("No tables found in document (--export-tables-only)")

        # Fallback when document has no detected tables: emit a structured Document text sheet
        fallback_rows: List[List[str]] = [["Page", "Content"]]
        for page in doc_ir.pages:
            for block in page.blocks:
                if isinstance(block, Paragraph):
                    txt = block.text.strip()
                    if txt:
                        fallback_rows.append([str(page.page_number), txt])
        pkg.add_sheet(
            name="Document",
            rows=fallback_rows,
            header_row_count=1,
            col_widths=[60.0, 360.0],
        )
        return pkg

    def emit(
        self,
        doc_ir: DocumentIR,
        mode: ConversionMode = ConversionMode.FLOW,
    ) -> bytes:
        """Serialize DocumentIR tables into an ISO/IEC 29500-2 .xlsx archive."""
        return self.build_package(doc_ir).to_bytes()


__all__ = ["XlsxEmitter"]
