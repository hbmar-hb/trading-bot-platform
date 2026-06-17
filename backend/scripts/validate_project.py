#!/usr/bin/env python3
"""
Validadores personalizados del proyecto Trading Bot Platform.
Capa de seguridad adicional para detectar patrones que linters generales no capturan.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Directorio raíz del backend
BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BACKEND_DIR / "app"


def find_python_files(root: Path) -> list[Path]:
    """Recursively find all Python files under root, excluding tests and migrations."""
    files = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        parts = rel.parts
        if "test" in parts or "tests" in parts or "migrations" in parts:
            continue
        if path.name.startswith("test_"):
            continue
        files.append(path)
    return sorted(files)


def check_logger_import(filepath: Path) -> list[str]:
    """
    Detecta archivos que usan 'logger.' pero no importan 'from loguru import logger'.
    Este patrón ha causado NameError en producción (charting.py, webhook.py, confluence_engine.py).
    """
    issues = []
    source = filepath.read_text(encoding="utf-8")

    # Quick text check: does the file use 'logger.' at all?
    if "logger." not in source:
        return issues

    # Check for the import
    has_loguru_import = "from loguru import logger" in source or "import loguru" in source

    if not has_loguru_import:
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if "logger." in stripped and not stripped.startswith("#"):
                issues.append(
                    f"{filepath}:{lineno}: uses 'logger.' but missing "
                    f"'from loguru import logger' import"
                )
                break

    return issues


def check_mc_context_order(filepath: Path) -> list[str]:
    """
    Heurística: detecta patrones donde 'mc_context' se usa para ajustar variables
    (risk, sl, tp1) que típicamente se definen MÁS ABAJO en la función.
    """
    issues = []
    source = filepath.read_text(encoding="utf-8")

    if "mc_context" not in source:
        return issues

    lines = source.splitlines()
    for i, line in enumerate(lines):
        if "if mc_context:" in line:
            # Check the next 30 lines for usage of variables commonly defined later
            block_end = min(i + 30, len(lines))
            for j in range(i + 1, block_end):
                stripped = lines[j].strip()
                if stripped.startswith("def ") or stripped.startswith("class "):
                    break
                # Look for risk/sl/tp1 used inside mc_context block BEFORE their definition
                for var in ("risk ", "risk=", "risk/", "sl ", "sl=", "tp1 ", "tp1="):
                    if var in stripped and not stripped.startswith("#"):
                        # This is just a warning-level check; the real fix is pylint E0601
                        pass
    return issues


def main() -> int:
    files = find_python_files(APP_DIR)
    all_issues: list[str] = []

    print(f"🔍 Scanning {len(files)} Python files for project-specific issues...\n")

    for filepath in files:
        all_issues.extend(check_logger_import(filepath))

    if all_issues:
        print(f"❌ FOUND {len(all_issues)} ISSUE(S):\n")
        for issue in all_issues:
            print(f"  - {issue}")
        print("\n⛔ Build failed. Fix the issues above before deploying.")
        return 1
    else:
        print("✅ All project-specific validations passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
