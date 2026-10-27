"""Guarda secretos (clave de API, código de autenticación, token de sesión) cifrados con DPAPI de Windows.

Solo tu usuario de Windows en esta PC puede descifrarlos.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

PREFIX = "dpapi:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _call(function, data: bytes) -> bytes:
    source, out = _blob(data), _Blob()
    if not function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI no pudo procesar el dato")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    if not text:
        return ""
    return PREFIX + base64.b64encode(_call(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))).decode()


def unprotect(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    try:
        return _call(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(value[len(PREFIX):])).decode("utf-8")
    except (OSError, ValueError):
        return ""
