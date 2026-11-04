"""Extração de texto de PDF (poppler-utils / pdftotext)."""

from __future__ import annotations

import subprocess


def texto_pdf(caminho: str) -> str:
    """Texto do PDF com o layout preservado (`pdftotext -layout`).

    Lê pela saída padrão, sem arquivo intermediário, para que execuções
    simultâneas não se misturem.
    """
    return subprocess.run(["pdftotext", "-layout", caminho, "-"], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout
