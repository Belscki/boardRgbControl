from __future__ import annotations

import copy
import json
import os
import threading

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "surara-control")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "layout": "abnt2",
    "text_layout": "br",
    "led_map": {},                 # correções de calibração {"KEY_X": led | null}
    "brightness": 4,
    "effect": {"mode": 0x14, "speed": 3, "direction": 0, "color": "#ffffff", "random": False},
    "base_color": "#ffffff",
    "key_colors": {},              # {"KEY_A": "#ff0000"}
    "ambient": {
        "enabled": False,
        # Cada escrita faz o teclado inteiro piscar (o firmware grava na flash e não tem
        # modo direto), então as trocas são espaçadas e só acontecem em mudanças visíveis.
        "min_interval": 2.0,       # segundos mínimos entre trocas de cor
        "threshold": 48,           # diferença mínima (soma |ΔR|+|ΔG|+|ΔB|) para trocar a cor de uma tecla
        "restore_token": "",
    },
    "zones": [],
    "macros_enabled": False,
    "macro_step_delay_ms": 8,
    "macros": [],
}

ZONE_DEFAULT = {
    "name": "Espaço",
    "enabled": True,
    "monitor": 0,                  # índice do stream do portal
    "monitor_pos": None,           # [x, y] do monitor, para reencontrar o stream
    "rect": [0.0, 0.0, 0.25, 0.25],  # x, y, w, h normalizados (0..1)
    "keys": [],
    "method": "average",           # average | vivid | dominant
    "smoothing": 0.5,              # 0 = instantâneo, 0.95 = muito suave
    "saturation": 1.2,
    "gain": 1.0,
}

MACRO_DEFAULT = {
    "name": "Nova macro",
    "enabled": True,
    "trigger": [],                 # ex.: ["CTRL", "KEY_F1"] — última = tecla de disparo
    "mode": "once",                # once | repeat | toggle | remap
    "repeat_interval_ms": 50,
    "steps": [],                   # {"type": "key", "key": "KEY_A", "action": "tap|down|up"}
                                   # {"type": "delay", "ms": 100}
                                   # {"type": "text", "text": "olá"}
                                   # {"type": "command", "command": "konsole"}
    "remap_to": "",
}


def _merge(defaults, data):
    out = copy.deepcopy(defaults)
    for k, v in (data or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path) as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] erro lendo {self.path}: {e}; usando padrões")
        amb = self.data["ambient"]
        if "max_fps" in amb:  # config antiga (limite em atualizações/s)
            amb.pop("max_fps")
            amb["min_interval"] = DEFAULTS["ambient"]["min_interval"]
            amb["threshold"] = max(int(amb.get("threshold", 0)), DEFAULTS["ambient"]["threshold"])
        self.data["zones"] = [_merge(ZONE_DEFAULT, z) for z in self.data["zones"]]
        self.data["macros"] = [_merge(MACRO_DEFAULT, m) for m in self.data["macros"]]

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])
