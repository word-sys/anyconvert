"""
Command-line interface (CLI) for anyconvert.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from anyconvert import (
    __version__,
    batch_convert,
    convert,
    inspect_file,
    supported_conversions,
)
from anyconvert.core.exceptions import AnyConvertError
from anyconvert.core.options import ConversionOptions


def print_banner() -> None:
    print(f"anyconvert v{__version__} - Universal Lossless Document & File Converter")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anyconvert",
        description="Universal lossless document and file conversion library",
    )
    parser.add_argument("-v", "--version", action="version", version=f"anyconvert {__version__}")
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List all currently registered and supported conversion pairs",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: convert
    convert_parser = subparsers.add_parser("convert", help="Convert a single file")
    convert_parser.add_argument("source", type=str, help="Path to input source file")
    convert_parser.add_argument("target", type=str, help="Path to desired output file")
    convert_parser.add_argument("--from", dest="from_format", type=str, default=None, help="Force source format")
    convert_parser.add_argument("--to", dest="to_format", type=str, default=None, help="Force target format")
    convert_parser.add_argument(
        "--mode",
        choices=["flow", "precise"],
        default="flow",
        help="Conversion mode: 'flow' (reflowable) or 'precise' (spatial)",
    )
    convert_parser.add_argument("--pages", type=str, default=None, help="Page range (e.g. '1-5, 8')")
    convert_parser.add_argument("--dpi", type=int, default=300, help="DPI resolution for raster elements (default: 300)")
    convert_parser.add_argument("--no-images", action="store_true", help="Skip extracting embedded images")
    convert_parser.add_argument("--no-tables", action="store_true", help="Skip table detection")

    # Command: batch
    batch_parser = subparsers.add_parser("batch", help="Batch convert multiple files")
    batch_parser.add_argument("sources", nargs="+", type=str, help="Input file paths")
    batch_parser.add_argument("-o", "--output-dir", required=True, type=str, help="Directory to save output files")
    batch_parser.add_argument("--to", dest="to_format", required=True, type=str, help="Target format (e.g. docx, pptx)")
    batch_parser.add_argument("--workers", type=int, default=None, help="Number of parallel worker threads")

    # Command: inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect file structure and metadata")
    inspect_parser.add_argument("source", type=str, help="Path to file to inspect")

    return parser


def handle_list_formats() -> int:
    conversions = supported_conversions()
    if not conversions:
        print("No converters are currently registered.")
        return 0

    print("Registered Conversion Matrix:")
    print("----------------------------------------")
    for src, targets in conversions.items():
        print(f"  {src.upper():<8} -> {', '.join(t.upper() for t in targets)}")
    print("----------------------------------------")
    return 0


def handle_inspect(source: str) -> int:
    try:
        info = inspect_file(source)
        print("Document Information:")
        print(f"  Format:      {info.format.upper()}")
        print(f"  Pages:       {info.page_count}")
        print(f"  File Size:   {info.file_size_bytes:,} bytes")
        print(f"  Has Text:    {'Yes' if info.has_text else 'No'}")
        print(f"  Has Images:  {'Yes' if info.has_images else 'No'}")
        print(f"  Encrypted:   {'Yes' if info.is_encrypted else 'No'}")
        if info.title:
            print(f"  Title:       {info.title}")
        if info.author:
            print(f"  Author:      {info.author}")
        if info.creator:
            print(f"  Creator:     {info.creator}")
        return 0
    except AnyConvertError as e:
        print(f"Error inspecting file: {e}", file=sys.stderr)
        return 1


def handle_convert(args: argparse.Namespace) -> int:
    def cli_progress(current: int, total: int, stage: str) -> None:
        print(f"[{current}/{total}] {stage}...")

    options = ConversionOptions(
        mode=args.mode,
        page_range=args.pages,
        dpi=args.dpi,
        extract_images=not args.no_images,
        detect_tables=not args.no_tables,
        progress_callback=cli_progress,
    )

    try:
        print(f"Converting '{args.source}' -> '{args.target}'...")
        result = convert(
            args.source,
            args.target,
            from_format=args.from_format,
            to_format=args.to_format,
            options=options,
        )
        if result.success:
            print(
                f"Success: Converted {result.page_count} page(s) in {result.elapsed_seconds:.2f}s "
                f"(Tables: {result.tables_count}, Images: {result.images_count})"
            )
            return 0
        else:
            print("Error: Conversion failed.", file=sys.stderr)
            for warning in result.warnings:
                print(f"  Warning: {warning}", file=sys.stderr)
            return 1
    except AnyConvertError as e:
        print(f"Conversion Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        return 1


def handle_batch(args: argparse.Namespace) -> int:
    try:
        print(f"Batch converting {len(args.sources)} file(s) to {args.to_format.upper()}...")
        results = batch_convert(
            args.sources,
            args.output_dir,
            to_format=args.to_format,
            workers=args.workers,
        )
        successful = sum(1 for r in results if r.success)
        print(f"Completed {successful}/{len(results)} file(s) successfully.")
        return 0 if successful == len(results) else 1
    except AnyConvertError as e:
        print(f"Batch Error: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_formats:
        return handle_list_formats()

    if not args.command:
        # Default behavior if two positional arguments are supplied without subcommand
        raw_args = sys.argv[1:] if argv is None else argv
        if len(raw_args) == 2 and not raw_args[0].startswith("-") and not raw_args[1].startswith("-"):
            fake_args = argparse.Namespace(
                source=raw_args[0],
                target=raw_args[1],
                from_format=None,
                to_format=None,
                mode="flow",
                pages=None,
                dpi=300,
                no_images=False,
                no_tables=False,
            )
            return handle_convert(fake_args)

        parser.print_help()
        return 0

    if args.command == "convert":
        return handle_convert(args)
    elif args.command == "batch":
        return handle_batch(args)
    elif args.command == "inspect":
        return handle_inspect(args.source)

    return 0


if __name__ == "__main__":
    sys.exit(main())
