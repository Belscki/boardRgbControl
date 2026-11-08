"""Motor de iluminação: compõe as cores por tecla e envia ao teclado.

Proteção da flash: as escritas de cor no Surara parecem ir para a memória flash
(cada pacote leva ~7 ms, leitura ~1 ms). Por isso:
  * só os pacotes (18 LEDs cada) que mudaram são reenviados;
  * no modo "espaços de tela" há um intervalo mínimo entre trocas e um limiar de mudança;
  * cada escrita faz o teclado inteiro piscar (não há modo direto: o comando 0x12 de
    cores dinâmicas da V2 é aceito, mas ignorado por este firmware), então fade por
    software não é viável.
  * há um contador de pacotes escritos (self.writes).
"""
from __future__ import annotations

import threading
import time

from .config import Config, hex_to_rgb
from .hid import CHUNK, MODE_CUSTOM, NUM_LEDS, EVisionKeyboard
from .keymap import Key


class LightingEngine(threading.Thread):
    def __init__(self, cfg: Config, keys: list[Key]):
        super().__init__(daemon=True, name="lighting")
        self.cfg = cfg
        self.keys = keys
        self.dev: EVisionKeyboard | None = None
        self.zone_colors: dict[str, tuple[int, int, int]] = {}
        self.override: bytes | None = None   # calibração / testes
        self.sent: bytearray | None = None
        self.writes = 0
        self.status = "Iniciando…"
        self._wake = threading.Event()
        self._mode_dirty = True
        self._force = True
        self._stop = False
        self._last_ambient_write = 0.0
        self.lock = threading.Lock()
        self._wake.set()  # conecta e aplica o estado salvo logo ao iniciar

    # ------------------------------------------------------------- API (qualquer thread)
    def colors_changed(self):
        """Cores manuais mudaram: envia sem limiar."""
        self._force = True
        self._wake.set()

    def mode_changed(self):
        self._mode_dirty = True
        self._force = True
        self._wake.set()

    def set_keys(self, keys: list[Key]):
        with self.lock:
            self.keys = keys
        self.colors_changed()

    def set_zone_colors(self, colors: dict[str, tuple[int, int, int]]):
        with self.lock:
            self.zone_colors = colors
        self._wake.set()

    def set_override(self, data: bytes | None):
        with self.lock:
            toggled = (self.override is None) != (data is None)
            self.override = data
        if toggled:
            self.mode_changed()  # calibração exige o modo personalizado
        else:
            self.colors_changed()

    def stop(self):
        self._stop = True
        self._wake.set()

    @property
    def ambient_active(self) -> bool:
        return bool(self.cfg["ambient"]["enabled"]) and bool(self.zone_colors)

    # ------------------------------------------------------------- composição
    def compose(self) -> bytearray:
        with self.lock:
            if self.override is not None:
                return bytearray(self.override)
            base = hex_to_rgb(self.cfg["base_color"])
            frame = bytearray(bytes(base) * NUM_LEDS)
            key_colors = self.cfg["key_colors"]
            zones = self.zone_colors if self.cfg["ambient"]["enabled"] else {}
            for k in self.keys:
                if k.led is None or not 0 <= k.led < NUM_LEDS:
                    continue
                c = zones.get(k.code)
                if c is None:
                    h = key_colors.get(k.code)
                    c = hex_to_rgb(h) if h else base
                frame[k.led * 3:k.led * 3 + 3] = bytes(int(max(0, min(255, v))) for v in c)
            return frame

    # ------------------------------------------------------------- dispositivo
    def _connect(self) -> bool:
        if self.dev:
            return True
        try:
            self.dev = EVisionKeyboard()
            self.sent = None
            self._mode_dirty = True
            self.status = f"Conectado ({self.dev.path})"
            return True
        except Exception as e:  # noqa: BLE001
            self.status = f"Teclado indisponível: {e}"
            self.dev = None
            return False

    def _drop(self, err: Exception):
        self.status = f"Erro de comunicação: {err}"
        if self.dev:
            self.dev.close()
        self.dev = None

    def _apply_mode(self):
        eff = self.cfg["effect"]
        mode = eff["mode"]
        if self.override is not None or self.cfg["ambient"]["enabled"]:
            mode = MODE_CUSTOM
        self.dev.set_mode(mode, int(self.cfg["brightness"]), int(eff["speed"]), int(eff["direction"]),
                          bool(eff["random"]), hex_to_rgb(eff["color"]))
        self.writes += 1
        self._current_mode = mode
        self._mode_dirty = False

    def _send_frame(self, frame: bytearray, threshold: int):
        prev = self.sent
        for off in range(0, NUM_LEDS * 3, CHUNK):
            new = frame[off:off + CHUNK]
            if prev is not None:
                old = prev[off:off + CHUNK]
                if new == old:
                    continue
                if threshold > 0:
                    worst = max(sum(abs(new[i + j] - old[i + j]) for j in range(3))
                                for i in range(0, len(new), 3))
                    if worst < threshold:
                        continue
            self.dev.transfer(0x11, len(new), off, bytes(new))
            self.writes += 1
            if self.sent is None:
                self.sent = bytearray(NUM_LEDS * 3)
            self.sent[off:off + CHUNK] = new

    # ------------------------------------------------------------- loop
    def run(self):
        self._current_mode = None
        timeout = 2.0
        while not self._stop:
            self._wake.wait(timeout=timeout)
            self._wake.clear()
            timeout = 2.0
            if self._stop:
                break
            if not self._connect():
                time.sleep(1.0)
                continue
            try:
                if self._mode_dirty:
                    self._apply_mode()
                if self._current_mode != MODE_CUSTOM:
                    continue
                force = self._force
                ambient = self.ambient_active and self.override is None
                if ambient and not force:
                    amb = self.cfg["ambient"]
                    min_dt = max(0.05, float(amb["min_interval"]))
                    dt = time.monotonic() - self._last_ambient_write
                    if dt < min_dt:
                        timeout = min_dt - dt  # tenta de novo quando o intervalo vencer
                        continue
                    threshold = int(amb["threshold"])
                else:
                    threshold = 0
                self._force = False
                self._send_frame(self.compose(), threshold)
                if ambient:
                    self._last_ambient_write = time.monotonic()
            except OSError as e:
                self._drop(e)
