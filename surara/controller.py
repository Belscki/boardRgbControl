"""Junta os motores (iluminação, captura, espaços, macros). Usado pela GUI e pelo modo daemon."""
from __future__ import annotations

from .ambient import AmbientSampler
from .capture import ScreenCapture
from .config import Config
from .keymap import apply_led_overrides, build_layout
from .lighting import LightingEngine
from .macros import MacroEngine


class Controller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.keys = self._make_keys()
        self.save_pending = False
        self.capture_state = "Captura parada"
        self.macro_status = "Parado"
        self.last_macro = ""

        self.lighting = LightingEngine(cfg, self.keys)
        self.lighting.start()
        self.capture = ScreenCapture(cfg["ambient"]["restore_token"], on_token=self._on_token,
                                     on_state=self._on_capture_state)
        self.sampler = AmbientSampler(cfg, self.capture, self.lighting.set_zone_colors)
        self.sampler.start()
        self.macros: MacroEngine | None = None

        if cfg["macros_enabled"]:
            self.start_macros()
        if cfg["ambient"]["enabled"]:
            self.capture.start()

    # ------------------------------------------------------------------ teclas
    def _make_keys(self):
        keys = build_layout(self.cfg["layout"])
        apply_led_overrides(keys, self.cfg["led_map"])
        return keys

    def rebuild_keys(self):
        self.keys = self._make_keys()
        self.lighting.set_keys(self.keys)

    # ------------------------------------------------------------------ captura / espaços
    def _on_token(self, token):
        self.cfg["ambient"]["restore_token"] = token
        self.save_pending = True

    def _on_capture_state(self, s):
        self.capture_state = s

    def set_ambient(self, on: bool):
        self.cfg["ambient"]["enabled"] = on
        if on and not self.capture.running:
            self.capture.start()
        if not on:
            self.lighting.set_zone_colors({})
            self.sampler.state.clear()
        self.lighting.mode_changed()
        self.save_pending = True

    def restart_capture(self, reselect=False):
        self.capture.stop()
        if reselect:
            self.cfg["ambient"]["restore_token"] = ""
            self.capture.restore_token = ""
        self.capture.start()

    # ------------------------------------------------------------------ macros
    def _on_macro_status(self, s):
        self.macro_status = s

    def _on_fire(self, name):
        self.last_macro = name

    def start_macros(self):
        if self.macros and self.macros.is_alive():
            return
        self.macros = MacroEngine(self.cfg, on_status=self._on_macro_status, on_fire=self._on_fire)
        self.macros.start()

    def stop_macros(self):
        if self.macros:
            self.macros.stop()
            self.macros.join(timeout=2)
            self.macros = None

    def set_macros(self, on: bool):
        self.cfg["macros_enabled"] = on
        self.start_macros() if on else self.stop_macros()
        self.save_pending = True

    # ------------------------------------------------------------------ perfis
    def load_profile(self, name: str | None, data: dict | None = None):
        """Carrega um perfil salvo (ou dados importados) e aplica nos motores."""
        from . import profiles
        profiles.apply(self.cfg, data if data is not None else profiles.read(name), name)
        self.sampler.state.clear()
        self.sampler.zone_rgb.clear()
        self.set_ambient(bool(self.cfg["ambient"]["enabled"]))  # também reaplica o modo
        self.lighting.colors_changed()
        self.save_pending = True

    # ------------------------------------------------------------------ encerrar
    def shutdown(self):
        self.stop_macros()
        self.sampler.stop()
        self.capture.stop()
        self.lighting.stop()
