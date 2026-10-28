#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python}"

echo "============================================================"
echo "anyconvert Local Developer Quality Gate"
echo "Repository: ${REPO_ROOT}"
echo "Python interpreter: $("${PYTHON}" --version 2>&1)"
echo "============================================================"

echo ""
echo "[1/4] Compiling Python byte-code (syntax audit)..."
"${PYTHON}" -m compileall -q src/ tests/
echo "Syntax audit passed."

echo ""
echo "[2/4] Running Ruff linter..."
"${PYTHON}" -m ruff check src/ tests/
echo "Ruff lint checks passed."

echo ""
echo "[3/4] Running Mypy strict type checker..."
"${PYTHON}" -m mypy --strict src/ tests/
echo "Mypy strict type checks passed."

echo ""
echo "[4/4] Running Pytest test suite..."
"${PYTHON}" -m pytest -v --tb=short
echo "Pytest suite passed."

echo ""
echo "============================================================"
echo "All quality gate checks passed successfully."
echo "============================================================"
