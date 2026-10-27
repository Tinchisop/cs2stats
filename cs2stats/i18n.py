"""Idioma de la app: español (el original) o inglés.

Los textos se escriben en español y t() devuelve la traducción del idioma elegido. Las traducciones al inglés están en
i18n_en.py, con el texto en español como clave. Los textos con datos usan {nombres}: t("Ganaste {a} a {b}", a=13, b=5).
"""

from __future__ import annotations

import sys

from .i18n_en import EN

LANGUAGES = {"es": "Español", "en": "English"}
_current = "es"


def system_language() -> str:
    """Español si Windows está en español; si no, inglés."""
    if sys.platform == "win32":
        try:
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "es" if primary == 0x0A else "en"
        except (AttributeError, OSError):
            pass
    return "es"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else system_language()


def language() -> str:
    return _current


def t(text: str, **values) -> str:
    out = EN.get(text, text) if _current == "en" else text
    return out.format(**values) if values else out
