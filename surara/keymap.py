"""Layout físico do Surara (full size) e mapeamento tecla -> índice de LED.

Os índices de LED padrão vêm da matriz 6x21 do OpenRGB (LED = linha*21 + coluna).
Podem estar errados para algumas teclas (sobretudo ABNT2); use o assistente de
calibração da GUI para corrigir — as correções ficam em config["led_map"].
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Key:
    code: str      # nome evdev, ex.: "KEY_A"
    label: str
    x: float       # posição em unidades de tecla (1u)
    y: float
    w: float = 1.0
    h: float = 1.0
    led: int | None = None


# (label, código, largura, led) ; ("", None, largura, None) = espaço vazio
_FUNC_ROW = [
    ("Esc", "KEY_ESC", 1, 0), ("", None, 1, None),
    ("F1", "KEY_F1", 1, 1), ("F2", "KEY_F2", 1, 2), ("F3", "KEY_F3", 1, 3), ("F4", "KEY_F4", 1, 4),
    ("", None, 0.5, None),
    ("F5", "KEY_F5", 1, 5), ("F6", "KEY_F6", 1, 6), ("F7", "KEY_F7", 1, 7), ("F8", "KEY_F8", 1, 8),
    ("", None, 0.5, None),
    ("F9", "KEY_F9", 1, 9), ("F10", "KEY_F10", 1, 10), ("F11", "KEY_F11", 1, 11), ("F12", "KEY_F12", 1, 12),
    ("", None, 0.25, None),
    ("PrtSc", "KEY_SYSRQ", 1, 14), ("ScrLk", "KEY_SCROLLLOCK", 1, 15), ("Pause", "KEY_PAUSE", 1, 16),
]

_NAV_1 = [("Ins", "KEY_INSERT", 1, 35), ("Home", "KEY_HOME", 1, 36), ("PgUp", "KEY_PAGEUP", 1, 37)]
_NAV_2 = [("Del", "KEY_DELETE", 1, 56), ("End", "KEY_END", 1, 57), ("PgDn", "KEY_PAGEDOWN", 1, 58)]
_NUM_1 = [("Num", "KEY_NUMLOCK", 1, 38), ("/", "KEY_KPSLASH", 1, 39), ("*", "KEY_KPASTERISK", 1, 40), ("-", "KEY_KPMINUS", 1, 41)]
_NUM_2 = [("7", "KEY_KP7", 1, 59), ("8", "KEY_KP8", 1, 60), ("9", "KEY_KP9", 1, 61)]
_NUM_3 = [("4", "KEY_KP4", 1, 80), ("5", "KEY_KP5", 1, 81), ("6", "KEY_KP6", 1, 82)]
_NUM_4 = [("1", "KEY_KP1", 1, 101), ("2", "KEY_KP2", 1, 102), ("3", "KEY_KP3", 1, 103)]

_DIGITS = [(str(i % 10), f"KEY_{i % 10}", 1, 21 + i) for i in range(1, 11)]

LAYOUT_ROWS_ANSI = [
    [("`", "KEY_GRAVE", 1, 21), *_DIGITS, ("-", "KEY_MINUS", 1, 32), ("=", "KEY_EQUAL", 1, 33),
     ("Backspace", "KEY_BACKSPACE", 2, 34)],
    [("Tab", "KEY_TAB", 1.5, 42), *[(c, f"KEY_{c}", 1, 43 + i) for i, c in enumerate("QWERTYUIOP")],
     ("[", "KEY_LEFTBRACE", 1, 53), ("]", "KEY_RIGHTBRACE", 1, 54), ("\\", "KEY_BACKSLASH", 1.5, 55)],
    [("Caps", "KEY_CAPSLOCK", 1.75, 63), *[(c, f"KEY_{c}", 1, 64 + i) for i, c in enumerate("ASDFGHJKL")],
     (";", "KEY_SEMICOLON", 1, 73), ("'", "KEY_APOSTROPHE", 1, 74), ("Enter", "KEY_ENTER", 2.25, 76)],
    [("Shift", "KEY_LEFTSHIFT", 2.25, 84), *[(c, f"KEY_{c}", 1, 86 + i) for i, c in enumerate("ZXCVBNM")],
     (",", "KEY_COMMA", 1, 93), (".", "KEY_DOT", 1, 94), ("/", "KEY_SLASH", 1, 95),
     ("Shift", "KEY_RIGHTSHIFT", 2.75, 97)],
]

LAYOUT_ROWS_ABNT2 = [
    [("'", "KEY_GRAVE", 1, 21), *_DIGITS, ("-", "KEY_MINUS", 1, 32), ("=", "KEY_EQUAL", 1, 33),
     ("Backspace", "KEY_BACKSPACE", 2, 34)],
    [("Tab", "KEY_TAB", 1.5, 42), *[(c, f"KEY_{c}", 1, 43 + i) for i, c in enumerate("QWERTYUIOP")],
     ("´", "KEY_LEFTBRACE", 1, 53), ("[", "KEY_RIGHTBRACE", 1, 54)],
    [("Caps", "KEY_CAPSLOCK", 1.75, 63), *[(c, f"KEY_{c}", 1, 64 + i) for i, c in enumerate("ASDFGHJKL")],
     ("Ç", "KEY_SEMICOLON", 1, 73), ("~", "KEY_APOSTROPHE", 1, 74), ("]", "KEY_BACKSLASH", 1, 75)],
    [("Shift", "KEY_LEFTSHIFT", 1.25, 84), ("\\", "KEY_102ND", 1, 85),
     *[(c, f"KEY_{c}", 1, 86 + i) for i, c in enumerate("ZXCVBNM")],
     (",", "KEY_COMMA", 1, 93), (".", "KEY_DOT", 1, 94), (";", "KEY_SLASH", 1, 95), ("/?", "KEY_RO", 1, 96),
     ("Shift", "KEY_RIGHTSHIFT", 1.75, 97)],
]

_BOTTOM = [
    ("Ctrl", "KEY_LEFTCTRL", 1.25, 105), ("Win", "KEY_LEFTMETA", 1.25, 106), ("Alt", "KEY_LEFTALT", 1.25, 107),
    ("Espaço", "KEY_SPACE", 6.25, 108),
    ("AltGr", "KEY_RIGHTALT", 1.25, 109), ("Fn", "FN", 1.25, 110), ("Menu", "KEY_COMPOSE", 1.25, 111),
    ("Ctrl", "KEY_RIGHTCTRL", 1.25, 113),
]

NAV_X = 15.25
NUM_X = 18.5


def _place(keys: list[Key], row, x0: float, y: float):
    x = x0
    for label, code, w, led in row:
        if code is not None:
            keys.append(Key(code, label, x, y, w, 1.0, led))
        x += w


def build_layout(layout: str = "abnt2") -> list[Key]:
    keys: list[Key] = []
    _place(keys, _FUNC_ROW, 0, 0)
    rows = LAYOUT_ROWS_ABNT2 if layout == "abnt2" else LAYOUT_ROWS_ANSI
    for i, row in enumerate(rows):
        _place(keys, row, 0, 1.25 + i)
    _place(keys, _BOTTOM, 0, 5.25)
    if layout == "abnt2":  # Enter ISO (desenhado como bloco de 2 linhas)
        keys.append(Key("KEY_ENTER", "Enter", 13.75, 2.25, 1.25, 2.0, 76))
    # navegação
    _place(keys, _NAV_1, NAV_X, 1.25)
    _place(keys, _NAV_2, NAV_X, 2.25)
    keys.append(Key("KEY_UP", "↑", NAV_X + 1, 4.25, 1, 1, 99))
    _place(keys, [("←", "KEY_LEFT", 1, 119), ("↓", "KEY_DOWN", 1, 120), ("→", "KEY_RIGHT", 1, 121)], NAV_X, 5.25)
    # numérico
    _place(keys, _NUM_1, NUM_X, 1.25)
    _place(keys, _NUM_2, NUM_X, 2.25)
    _place(keys, _NUM_3, NUM_X, 3.25)
    _place(keys, _NUM_4, NUM_X, 4.25)
    keys.append(Key("KEY_KPPLUS", "+", NUM_X + 3, 2.25, 1, 2, 62))
    keys.append(Key("KEY_KPENTER", "Enter", NUM_X + 3, 4.25, 1, 2, 104))
    keys.append(Key("KEY_KP0", "0", NUM_X, 5.25, 2, 1, 123))
    keys.append(Key("KEY_KPDOT", ".", NUM_X + 2, 5.25, 1, 1, 124))
    return keys


def layout_size(keys: list[Key]) -> tuple[float, float]:
    return max(k.x + k.w for k in keys), max(k.y + k.h for k in keys)


def apply_led_overrides(keys: list[Key], overrides: dict[str, int | None]):
    for k in keys:
        if k.code in overrides:
            k.led = overrides[k.code]


MODIFIERS = {
    "KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
    "KEY_LEFTALT", "KEY_RIGHTALT", "KEY_LEFTMETA", "KEY_RIGHTMETA",
}
GENERIC_MODIFIERS = {
    "CTRL": {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"},
    "SHIFT": {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"},
    "ALT": {"KEY_LEFTALT"},           # AltGr fica separado (KEY_RIGHTALT)
    "META": {"KEY_LEFTMETA", "KEY_RIGHTMETA"},
}


def pretty_key(code: str) -> str:
    names = {
        "KEY_LEFTCTRL": "Ctrl", "KEY_RIGHTCTRL": "Ctrl Dir", "KEY_LEFTSHIFT": "Shift",
        "KEY_RIGHTSHIFT": "Shift Dir", "KEY_LEFTALT": "Alt", "KEY_RIGHTALT": "AltGr",
        "KEY_LEFTMETA": "Super", "KEY_RIGHTMETA": "Super Dir", "CTRL": "Ctrl", "SHIFT": "Shift",
        "ALT": "Alt", "META": "Super", "KEY_SPACE": "Espaço", "KEY_SYSRQ": "PrtSc",
    }
    if code in names:
        return names[code]
    return code[4:].capitalize() if code.startswith("KEY_") else code
