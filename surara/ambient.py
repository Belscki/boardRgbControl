"""Amostrador dos "espaços": lê a cor de regiões da tela e aplica nas teclas."""
from __future__ import annotations

import threading
import time

import numpy as np

from .capture import ScreenCapture
from .config import Config, zone_style


def region_color(frame: np.ndarray, rect, method: str) -> np.ndarray | None:
    h, w, _ = frame.shape
    x, y, rw, rh = rect
    x0, y0 = int(max(0, min(1, x)) * w), int(max(0, min(1, y)) * h)
    x1, y1 = int(max(0, min(1, x + rw)) * w), int(max(0, min(1, y + rh)) * h)
    if x1 <= x0:
        x1 = min(w, x0 + 1)
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    px = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if px.size == 0:
        return None
    if method == "vivid":
        # pondera pixels saturados e claros (ignora fundo cinza/preto)
        mx, mn = px.max(1), px.min(1)
        wgt = (mx - mn) * (mx / 255.0) + 1.0
        return (px * wgt[:, None]).sum(0) / wgt.sum()
    if method == "dominant":
        q = (px // 32).astype(np.int32)  # 8 níveis por canal
        idx = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
        bright = px.max(1) > 24
        if bright.any():
            idx_b = idx[bright]
            top = np.bincount(idx_b, minlength=512).argmax()
            return px[bright][idx_b == top].mean(0)
        return px.mean(0)
    return px.mean(0)


def adjust(c: np.ndarray, saturation: float, gain: float) -> np.ndarray:
    gray = c.mean()
    c = gray + (c - gray) * saturation
    return np.clip(c * gain, 0, 255)


class AmbientSampler(threading.Thread):
    def __init__(self, cfg: Config, capture: ScreenCapture, on_colors, rate_hz: float = 30.0):
        super().__init__(daemon=True, name="ambient")
        self.cfg = cfg
        self.capture = capture
        self.on_colors = on_colors   # callback(dict code -> (r,g,b))
        self.rate = rate_hz
        self.state: dict[int, np.ndarray] = {}   # cor suavizada por zona (índice)
        self.zone_rgb: dict[int, tuple[int, int, int]] = {}
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        period = 1.0 / self.rate
        while not self._stop:
            t0 = time.monotonic()
            if self.capture.running and self.cfg["ambient"]["enabled"]:
                self.on_colors(self.sample())
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

    def sample(self) -> dict[str, tuple[int, int, int]]:
        out: dict[str, tuple[int, int, int]] = {}
        for i, z in enumerate(self.cfg["zones"]):
            if not z["enabled"] or not z["keys"]:
                continue
            idx = self.capture.find_stream(z.get("monitor_pos"))
            if idx is None:
                idx = int(z.get("monitor", 0))
            frame = self.capture.get_frame(idx)
            if frame is None:
                continue
            st = zone_style(self.cfg["ambient"], z)
            c = region_color(frame, z["rect"], st["method"])
            if c is None:
                continue
            c = adjust(c, float(st["saturation"]), float(st["gain"]))
            s = min(0.98, max(0.0, float(st["smoothing"])))
            prev = self.state.get(i)
            c = c if prev is None else prev * s + c * (1 - s)
            self.state[i] = c
            rgb = tuple(int(round(v)) for v in c)
            self.zone_rgb[i] = rgb
            for k in z["keys"]:
                out[k] = rgb  # zonas posteriores têm prioridade
        return out
