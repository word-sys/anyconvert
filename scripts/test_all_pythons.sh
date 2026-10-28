#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

KEEP_VENVS=0
CUSTOM_PYTHONS=()

for arg in "$@"; do
    case "${arg}" in
        --keep-venvs)
            KEEP_VENVS=1
            ;;
        *)
            if [ -x "${arg}" ] || command -v "${arg}" >/dev/null 2>&1; then
                CUSTOM_PYTHONS+=("${arg}")
            fi
            ;;
    esac
done

SEARCH_CANDIDATES=(
    "${CUSTOM_PYTHONS[@]}"
    "${PYTHON:-}"
    "python3.10"
    "python3.11"
    "python3.12"
    "python3.13"
    "python3.14"
    "python3.15"
    "/usr/bin/python3.10"
    "/usr/bin/python3.11"
    "/usr/bin/python3.12"
    "/usr/bin/python3.13"
    "/usr/bin/python3.14"
    "/usr/bin/python3.15"
    "/usr/local/bin/python3.10"
    "/usr/local/bin/python3.11"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.14"
    "/usr/local/bin/python3.15"
    "/home/word-sys/anaconda3/bin/python"
    "python3"
    "python"
)

declare -A SEEN_PATHS=()
declare -A TESTED_VERSIONS=()
UNIQUE_PYTHONS=()

for candidate in "${SEARCH_CANDIDATES[@]}"; do
    [ -z "${candidate}" ] && continue
    cmd_path="$(command -v "${candidate}" 2>/dev/null || true)"
    [ -z "${cmd_path}" ] && continue
    [ ! -x "${cmd_path}" ] && continue

    ver_info="$("${cmd_path}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    [ -z "${ver_info}" ] && continue

    major="$(echo "${ver_info}" | cut -d. -f1)"
    minor="$(echo "${ver_info}" | cut -d. -f2)"

    if [ "${major}" -ne 3 ] || [ "${minor}" -lt 10 ] || [ "${minor}" -gt 15 ]; then
        continue
    fi

    real_path="$("${cmd_path}" -c 'import os, sys; print(os.path.realpath(sys.executable))' 2>/dev/null || true)"
    [ -z "${real_path}" ] && continue

    if [ -z "${SEEN_PATHS["${real_path}"]:-}" ]; then
        SEEN_PATHS["${real_path}"]="1"
        UNIQUE_PYTHONS+=("${real_path}")
    fi
done

if [ "${#UNIQUE_PYTHONS[@]}" -eq 0 ]; then
    echo "Error: No compatible Python interpreters (3.10 - 3.15) discovered." >&2
    exit 1
fi

echo "============================================================"
echo "anyconvert Multi-Python Virtualenv Test Runner"
echo "Discovered ${#UNIQUE_PYTHONS[@]} compatible Python interpreter(s)"
echo "Target version range: Python 3.10 - 3.15"
echo "============================================================"

FAILED_BUILDS=()
PASSED_BUILDS=()
TEMP_DIRS=()

cleanup() {
    if [ "${KEEP_VENVS}" -eq 0 ]; then
        for tmp_dir in "${TEMP_DIRS[@]}"; do
            if [ -d "${tmp_dir}" ]; then
                rm -rf "${tmp_dir}"
            fi
        done
    fi
}
trap cleanup EXIT

for py_bin in "${UNIQUE_PYTHONS[@]}"; do
    py_ver="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    py_short="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    echo ""
    echo "------------------------------------------------------------"
    echo "Creating virtual environment for Python ${py_ver}"
    echo "Binary: ${py_bin}"
    echo "------------------------------------------------------------"

    venv_dir="${REPO_ROOT}/.venv_test_${py_short}_$$"
    TEMP_DIRS+=("${venv_dir}")

    if ! "${py_bin}" -m venv --system-site-packages "${venv_dir}" >/dev/null 2>&1; then
        echo "Warning: Standard venv creation failed; attempting with --without-pip"
        if ! "${py_bin}" -m venv --without-pip --system-site-packages "${venv_dir}"; then
            echo "Failed to create virtualenv with ${py_bin}"
            FAILED_BUILDS+=("Python ${py_ver} (${py_bin}) - venv creation failed")
            continue
        fi
    fi

    venv_py="${venv_dir}/bin/python"

    echo "[1/4] Auditing syntax & byte-compilation..."
    if ! "${venv_py}" -m compileall -q src/ tests/; then
        echo "Syntax compilation failed for Python ${py_ver}"
        FAILED_BUILDS+=("Python ${py_ver} - compileall failed")
        continue
    fi
    echo "Syntax audit passed."

    echo "[2/4] Verifying Python 3.10 AST compatibility scanner..."
    if ! PYTHONPATH=src "${venv_py}" tests/test_py310_syntax.py; then
        echo "AST syntax compatibility scanner failed for Python ${py_ver}"
        FAILED_BUILDS+=("Python ${py_ver} - AST check failed")
        continue
    fi
    echo "AST scanner passed."

    echo "[3/4] Running test suite..."
    has_pytest="$("${venv_py}" -c 'import pytest; print("1")' 2>/dev/null || echo "0")"
    if [ "${has_pytest}" = "1" ]; then
        if ! PYTHONPATH=src "${venv_py}" -m pytest -q --tb=short; then
            echo "Pytest suite failed for Python ${py_ver}"
            FAILED_BUILDS+=("Python ${py_ver} - pytest suite failed")
            continue
        fi
    else
        echo "pytest not available in this environment; running standard library unit test suite..."
        test_failed=0
        for test_file in tests/test_*.py; do
            if ! PYTHONPATH=src "${venv_py}" -m unittest "${test_file}" >/dev/null 2>&1; then
                echo "Unit test failed: ${test_file}"
                test_failed=1
                break
            fi
        done
        if [ "${test_failed}" -eq 1 ]; then
            FAILED_BUILDS+=("Python ${py_ver} - unittest suite failed")
            continue
        fi
    fi
    echo "Test suite passed."

    echo "[4/4] Checking typing and lint invariants..."
    has_mypy="$("${venv_py}" -c 'import mypy; print("1")' 2>/dev/null || echo "0")"
    if [ "${has_mypy}" = "1" ]; then
        if ! "${venv_py}" -m mypy; then
            echo "Mypy type check failed for Python ${py_ver}"
            FAILED_BUILDS+=("Python ${py_ver} - mypy failed")
            continue
        fi
    fi

    has_ruff="$("${venv_py}" -c 'import ruff; print("1")' 2>/dev/null || echo "0")"
    if [ "${has_ruff}" = "1" ]; then
        if ! "${venv_py}" -m ruff check src/ tests/; then
            echo "Ruff check failed for Python ${py_ver}"
            FAILED_BUILDS+=("Python ${py_ver} - ruff failed")
            continue
        fi
    fi
    echo "Invariants passed."

    PASSED_BUILDS+=("Python ${py_ver} (${py_bin})")
done

echo ""
echo "============================================================"
echo "Multi-Python Test Execution Summary"
echo "============================================================"
for item in "${PASSED_BUILDS[@]}"; do
    echo "PASSED: ${item}"
done

if [ "${#FAILED_BUILDS[@]}" -gt 0 ]; then
    for item in "${FAILED_BUILDS[@]}"; do
        echo "FAILED: ${item}"
    done
    echo "============================================================"
    echo "Summary: ${#PASSED_BUILDS[@]} passed, ${#FAILED_BUILDS[@]} failed."
    exit 1
fi

echo "============================================================"
echo "All ${#PASSED_BUILDS[@]} Python environment(s) validated successfully."
echo "============================================================"
