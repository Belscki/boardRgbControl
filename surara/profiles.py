"""Perfis: salvam/carregam o "cenário" (cores, efeito, espaços de tela e macros).

Ficam fora do perfil (valem para todos): layout, calibração de LEDs, permissão de
captura, layout do texto e o liga/desliga do motor de macros.
Arquivos: ~/.config/surara-control/profiles/<nome>.json
"""
from __future__ import annotations

import copy
import json
import os
import re

from .config import CONFIG_DIR, DEFAULTS, MACRO_DEFAULT, STYLE_KEYS, ZONE_DEFAULT, Config, _merge, migrate_style

PROFILE_DIR = os.path.join(CONFIG_DIR, "profiles")
PROFILE_KEYS = ["brightness", "effect", "base_color", "key_colors", "zones", "macros", "macro_step_delay_ms"]
AMBIENT_KEYS = ["enabled", "min_interval", "threshold", *STYLE_KEYS]


def _path(name: str) -> str:
    safe = re.sub(r'[/\\\0]', "_", name).strip() or "perfil"
    return os.path.join(PROFILE_DIR, safe + ".json")


def list_profiles() -> list[str]:
    try:
        names = []
        for f in os.listdir(PROFILE_DIR):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(PROFILE_DIR, f)) as fh:
                        names.append(json.load(fh).get("name") or f[:-5])
                except (OSError, json.JSONDecodeError):
                    continue
        return sorted(names, key=str.lower)
    except FileNotFoundError:
        return []


def snapshot(cfg: Config) -> dict:
    """Extrai do config os campos que pertencem a um perfil."""
    data = {k: copy.deepcopy(cfg[k]) for k in PROFILE_KEYS}
    data["ambient"] = {k: cfg["ambient"][k] for k in AMBIENT_KEYS}
    return data


def save(cfg: Config, name: str, path: str | None = None):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    data = {"name": name, "surara_profile": 1, **snapshot(cfg)}
    path = path or _path(name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read(name_or_path: str) -> dict:
    path = name_or_path if os.path.isfile(name_or_path) else _path(name_or_path)
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or not any(k in data for k in PROFILE_KEYS):
        raise ValueError("arquivo não parece um perfil do Surara Control")
    return data


def normalized(data: dict) -> dict:
    """Completa campos ausentes com os padrões (perfis antigos/importados)."""
    data = copy.deepcopy(data)
    migrate_style(data.setdefault("ambient", {}), data.get("zones", []))
    out = {k: copy.deepcopy(data.get(k, DEFAULTS[k])) for k in PROFILE_KEYS}
    out["effect"] = _merge(DEFAULTS["effect"], out["effect"])
    out["zones"] = [_merge(ZONE_DEFAULT, z) for z in out["zones"]]
    out["macros"] = [_merge(MACRO_DEFAULT, m) for m in out["macros"]]
    amb = data.get("ambient", {})
    out["ambient"] = {k: amb.get(k, DEFAULTS["ambient"][k]) for k in AMBIENT_KEYS}
    return out


def apply(cfg: Config, data: dict, name: str | None):
    data = normalized(data)
    with cfg.lock:
        for k in PROFILE_KEYS:
            cfg[k] = data[k]
        cfg["ambient"].update(data["ambient"])
        cfg["active_profile"] = name or ""


def delete(name: str):
    os.remove(_path(name))


def rename(old: str, new: str, cfg: Config):
    data = read(old)
    data["name"] = new
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(_path(new), "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if _path(new) != _path(old):
        os.remove(_path(old))
    if cfg["active_profile"] == old:
        cfg["active_profile"] = new


_cache: dict[str, tuple[float, dict]] = {}


def is_dirty(cfg: Config) -> bool:
    """O estado atual difere do perfil salvo?"""
    name = cfg["active_profile"]
    if not name:
        return False
    path = _path(name)
    try:
        mtime = os.path.getmtime(path)
        if path not in _cache or _cache[path][0] != mtime:
            _cache[path] = (mtime, normalized(read(path)))
        return _cache[path][1] != normalized(snapshot(cfg))
    except (OSError, ValueError, json.JSONDecodeError):
        return True
