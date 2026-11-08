"""Gera espaços em grade: mapeia uma área do monitor sobre o teclado inteiro.

A posição física de cada tecla (centro, normalizado pela caixa que envolve as teclas
incluídas) decide de qual parte da tela ela recebe a cor.
"""
from __future__ import annotations

import copy

from .config import ZONE_DEFAULT
from .keymap import NAV_X, Key

GRID_GROUP = "grade"


def select_keys(keys: list[Key], include: str, selected: set[str] | None = None) -> list[Key]:
    keys = [k for k in keys if k.led is not None]
    if include == "main":
        return [k for k in keys if k.x < NAV_X - 0.1]
    if include == "selected":
        return [k for k in keys if k.code in (selected or set())]
    return keys


def _bbox(keys: list[Key]):
    x0 = min(k.x for k in keys)
    y0 = min(k.y for k in keys)
    x1 = max(k.x + k.w for k in keys)
    y1 = max(k.y + k.h for k in keys)
    return x0, y0, max(1e-6, x1 - x0), max(1e-6, y1 - y0)


def _zone(name, rect, base: dict) -> dict:
    z = copy.deepcopy(ZONE_DEFAULT)
    z.update(copy.deepcopy(base))
    z["name"] = name
    z["rect"] = [round(float(v), 5) for v in rect]
    z["group"] = GRID_GROUP
    return z


def generate(keys: list[Key], mode: str, rows: int, cols: int, area, base: dict) -> list[dict]:
    """mode: "grid" (linhas × colunas) ou "perkey" (uma região por tecla).
    area: [x, y, w, h] normalizado do monitor. base: campos comuns (monitor, método…)."""
    if not keys:
        return []
    ax, ay, aw, ah = area
    bx, by, bw, bh = _bbox(keys)
    zones: list[dict] = []

    if mode == "perkey":
        for k in sorted(keys, key=lambda k: (k.y, k.x)):
            rect = (ax + (k.x - bx) / bw * aw, ay + (k.y - by) / bh * ah, k.w / bw * aw, k.h / bh * ah)
            z = _zone(f"Tecla {k.label}", rect, base)
            z["keys"] = [k.code]
            zones.append(z)
        return zones

    rows, cols = max(1, int(rows)), max(1, int(cols))
    cells: dict[tuple[int, int], list[str]] = {}
    for k in keys:
        cx = (k.x + k.w / 2 - bx) / bw
        cy = (k.y + k.h / 2 - by) / bh
        c = min(cols - 1, int(cx * cols))
        r = min(rows - 1, int(cy * rows))
        cells.setdefault((r, c), []).append(k.code)
    cw, ch = aw / cols, ah / rows
    for (r, c) in sorted(cells):
        z = _zone(f"Grade L{r + 1} C{c + 1}", (ax + c * cw, ay + r * ch, cw, ch), base)
        z["keys"] = sorted(cells[(r, c)])
        zones.append(z)
    return zones


def apply(cfg_zones: list[dict], new: list[dict], replace: bool) -> list[dict]:
    """Junta a grade nova às zonas existentes. Cada tecla fica em um único espaço."""
    if replace:
        cfg_zones = [z for z in cfg_zones if z.get("group") != GRID_GROUP]
    taken = {k for z in new for k in z["keys"]}
    for z in cfg_zones:
        z["keys"] = [k for k in z["keys"] if k not in taken]
    return cfg_zones + new
