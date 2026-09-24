"""Command Line Interface (CLI) entrypoint for anyconvert."""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Sequence


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the command-line argument parser.

    Returns:
        argparse.ArgumentParser: Configured argument parser instance.
    """
    from anyconvert import __version__

    parser = argparse.ArgumentParser(
        prog="anyconvert",
        description=(
            "anyconvert: Pure-Python enterprise-grade document conversion engine.\n"
            "Converts PDF documents into DOCX, PPTX, ODT, ODP, and TXT."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="Path to the input PDF file to convert.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["docx", "pptx", "odt", "odp", "txt"],
        default="docx",
        help="Target document format.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Path to save the converted output file. Defaults to input base name with target extension.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["flow", "canvas"],
        default="flow",
        help="Conversion layout mode: 'flow' (semantic reflowable) or 'canvas' (fixed absolute coordinates).",
    )
    parser.add_argument(
        "-p",
        "--password",
        default="",
        help="Decryption password if the PDF is password-protected.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose diagnostic output.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI execution entrypoint.

    Args:
        argv: Optional list of command-line arguments. If None, uses sys.argv[1:].

    Returns:
        int: Exit status code (0 for success, non-zero for error).
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.input:
        parser.print_help(sys.stderr)
        return 1

    input_path = pathlib.Path(args.input)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input file '{args.input}' not found.\n")
        return 1

    # Determine output path
    if args.output:
        output_path = pathlib.Path(args.output)
    else:
        output_path = input_path.with_suffix(f".{args.format.lower()}")

    if args.verbose:
        sys.stderr.write(
            f"[anyconvert] Input: {input_path}, Output: {output_path}, "
            f"Format: {args.format}, Mode: {args.mode}\n"
        )

    try:
        from anyconvert.api import convert
        from anyconvert.exceptions import AnyConvertError

        res_bytes = convert(
            input_path=input_path,
            output_format=args.format,
            output_path=output_path,
            mode=args.mode,
            password=args.password,
        )

        if args.verbose:
            sys.stderr.write(
                f"[anyconvert] Successfully converted {len(res_bytes)} bytes to '{output_path}'.\n"
            )
        return 0

    except AnyConvertError as err:
        sys.stderr.write(f"Conversion error: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
