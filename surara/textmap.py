"""Converte texto em sequências de teclas evdev, conforme o layout do sistema.

Cada caractere vira uma lista de "acordes": [(modificadores, tecla), ...]
(acentos com tecla morta viram dois acordes, ex.: "á" = ´ + a).
"""
from __future__ import annotations

import unicodedata

S = "KEY_LEFTSHIFT"


def _base_alnum() -> dict[str, list[tuple[tuple[str, ...], str]]]:
    m = {}
    for c in "abcdefghijklmnopqrstuvwxyz":
        m[c] = [((), f"KEY_{c.upper()}")]
        m[c.upper()] = [((S,), f"KEY_{c.upper()}")]
    for d in "0123456789":
        m[d] = [((), f"KEY_{d}")]
    m[" "] = [((), "KEY_SPACE")]
    m["\n"] = [((), "KEY_ENTER")]
    m["\t"] = [((), "KEY_TAB")]
    return m


def _us():
    m = _base_alnum()
    plain = {"-": "KEY_MINUS", "=": "KEY_EQUAL", "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE",
             "\\": "KEY_BACKSLASH", ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE",
             ",": "KEY_COMMA", ".": "KEY_DOT", "/": "KEY_SLASH"}
    shifted = {"_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_LEFTBRACE", "}": "KEY_RIGHTBRACE",
               "|": "KEY_BACKSLASH", ":": "KEY_SEMICOLON", '"': "KEY_APOSTROPHE", "~": "KEY_GRAVE",
               "<": "KEY_COMMA", ">": "KEY_DOT", "?": "KEY_SLASH"}
    for i, c in enumerate(")!@#$%^&*("):
        shifted[c] = f"KEY_{i}"
    for c, k in plain.items():
        m[c] = [((), k)]
    for c, k in shifted.items():
        m[c] = [((S,), k)]
    return m


def _br():
    m = _base_alnum()
    plain = {"'": "KEY_GRAVE", "-": "KEY_MINUS", "=": "KEY_EQUAL", "[": "KEY_RIGHTBRACE",
             "]": "KEY_BACKSLASH", "ç": "KEY_SEMICOLON", "\\": "KEY_102ND", ",": "KEY_COMMA",
             ".": "KEY_DOT", ";": "KEY_SLASH", "/": "KEY_RO"}
    shifted = {'"': "KEY_GRAVE", "_": "KEY_MINUS", "+": "KEY_EQUAL", "{": "KEY_RIGHTBRACE",
               "}": "KEY_BACKSLASH", "Ç": "KEY_SEMICOLON", "|": "KEY_102ND", "<": "KEY_COMMA",
               ">": "KEY_DOT", ":": "KEY_SLASH", "?": "KEY_RO"}
    for i, c in enumerate(")!@#$%"):
        shifted[c] = f"KEY_{i}"
    shifted["&"] = "KEY_7"
    shifted["*"] = "KEY_8"
    shifted["("] = "KEY_9"
    for c, k in plain.items():
        m[c] = [((), k)]
    for c, k in shifted.items():
        m[c] = [((S,), k)]
    # teclas mortas: ´ (LEFTBRACE), ` (Shift+LEFTBRACE), ~ (APOSTROPHE), ^ (Shift+APOSTROPHE)
    dead = {"´": ((), "KEY_LEFTBRACE"), "`": ((S,), "KEY_LEFTBRACE"),
            "~": ((), "KEY_APOSTROPHE"), "^": ((S,), "KEY_APOSTROPHE")}
    for c, chord in dead.items():
        m[c] = [chord, ((), "KEY_SPACE")]
    accents = {"´": "áéíóú", "`": "àèìòù", "~": "ãõñ", "^": "âêîôû"}
    for d, letters in accents.items():
        for ch in letters + letters.upper():
            base = unicodedata.normalize("NFD", ch)[0]
            m[ch] = [dead[d], *m[base]]
    return m


_MAPS = {"us": _us, "br": _br}
_cache: dict[str, dict] = {}


def text_to_chords(text: str, layout: str = "br"):
    if layout not in _cache:
        _cache[layout] = _MAPS.get(layout, _us)()
    table = _cache[layout]
    out = []
    for ch in text:
        if ch in table:
            out.extend(table[ch])
        # caracteres sem mapeamento são ignorados
    return out
