"""Motor de macros.

Captura com exclusividade (EVIOCGRAB) os dispositivos de entrada do Surara e
repassa todos os eventos para teclados virtuais (uinput). Quando a combinação de
uma macro é pressionada, a tecla de disparo NÃO é repassada e a macro é executada.

Saída de emergência: Ctrl + Alt + Pause desliga o motor (libera o teclado).
"""
from __future__ import annotations

import select
import subprocess
import threading
import time

import evdev
from evdev import UInput, ecodes as E

from .config import Config
from .hid import PID, VID
from .keymap import GENERIC_MODIFIERS, MODIFIERS
from .textmap import text_to_chords


def code_name(code: int) -> str | None:
    n = E.KEY.get(code) or E.BTN.get(code)
    if isinstance(n, (list, tuple)):
        n = [x for x in n if x != "KEY_MIN_INTERESTING"][-1]
    return n


def name_code(name: str) -> int | None:
    v = E.ecodes.get(name)
    return v if isinstance(v, int) else None


def find_devices() -> list[evdev.InputDevice]:
    out = []
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.info.vendor == VID and d.info.product == PID and E.EV_KEY in d.capabilities():
            out.append(d)
        else:
            d.close()
    return out


def _expand(k: str) -> set[str]:
    return GENERIC_MODIFIERS.get(k, {k})


PANIC = ({"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}, {"KEY_LEFTALT"}, "KEY_PAUSE")
EXTRA_KEYS = list(range(1, 249))  # KEY_ESC .. KEY_MICMUTE (sem botões de mouse)


class MacroEngine(threading.Thread):
    def __init__(self, cfg: Config, on_status=None, on_fire=None):
        super().__init__(daemon=True, name="macros")
        self.cfg = cfg
        self.on_status = on_status or (lambda s: None)
        self.on_fire = on_fire or (lambda name: None)
        self.devices: list[evdev.InputDevice] = []
        self.uinputs: list[UInput] = []
        self.out: UInput | None = None
        self.out_lock = threading.Lock()
        self.pressed: set[str] = set()          # teclas físicas pressionadas
        self.consumed: dict[int, dict] = {}     # código -> macro que consumiu o press
        self.virtual_down: dict[int, UInput] = {}  # teclas "down" emitidas -> em qual virtual
        self.toggles: dict[int, threading.Event] = {}  # id(macro) -> stop
        self.holds: dict[int, threading.Event] = {}    # código -> stop (modo repeat)
        self._stop = threading.Event()
        self.status = "Parado"

    # ------------------------------------------------------------------ ciclo de vida
    def stop(self):
        self._stop.set()

    def _set_status(self, s):
        self.status = s
        self.on_status(s)

    def run(self):
        while not self._stop.is_set():
            try:
                if not self._open():
                    self._stop.wait(2.0)
                    continue
                self._loop()
            except OSError as e:
                self._set_status(f"Teclado desconectado ({e}); aguardando…")
            except Exception as e:  # noqa: BLE001
                self._set_status(f"Erro no motor de macros: {e}")
                self._close()
                return
            finally:
                self._close()
            self._stop.wait(1.0)
        self._set_status("Parado")

    def _open(self) -> bool:
        self.devices = find_devices()
        if not self.devices:
            self._set_status("Teclado não encontrado (ou sem permissão em /dev/input)")
            return False
        for i, d in enumerate(self.devices):
            caps = d.capabilities(absinfo=True)
            caps.pop(E.EV_SYN, None)
            caps.pop(E.EV_FF, None)
            if i == 0:
                caps[E.EV_KEY] = sorted(set(caps.get(E.EV_KEY, [])) | set(EXTRA_KEYS))
            ui = UInput(caps, name=f"Surara Control virtual {i}", vendor=0x1209, product=0x5004 + i)
            self.uinputs.append(ui)
        self.out = self.uinputs[0]
        time.sleep(0.2)  # deixa o compositor enxergar o dispositivo virtual
        for d in self.devices:
            d.grab()
        self.pressed.clear()
        self.consumed.clear()
        self._set_status(f"Ativo — {len(self.devices)} dispositivo(s) capturado(s). "
                         "Emergência: Ctrl+Alt+Pause")
        return True

    def _close(self):
        for ev in list(self.toggles.values()) + list(self.holds.values()):
            ev.set()
        self.toggles.clear()
        self.holds.clear()
        with self.out_lock:
            for code, ui in list(self.virtual_down.items()):
                try:
                    ui.write(E.EV_KEY, code, 0)
                    ui.syn()
                except OSError:
                    pass
            self.virtual_down.clear()
        for d in self.devices:
            try:
                d.ungrab()
            except OSError:
                pass
            d.close()
        for ui in self.uinputs:
            ui.close()
        self.devices, self.uinputs, self.out = [], [], None

    # ------------------------------------------------------------------ loop de eventos
    def _loop(self):
        fdmap = {d.fd: (d, self.uinputs[i]) for i, d in enumerate(self.devices)}
        uimap = {ui.fd: ui for ui in self.uinputs}
        while not self._stop.is_set():
            r, _, _ = select.select(list(fdmap) + list(uimap), [], [], 0.5)
            for fd in r:
                if fd in uimap:
                    self._forward_leds(uimap[fd])
                    continue
                dev, ui = fdmap[fd]
                for ev in dev.read():
                    if ev.type == E.EV_KEY:
                        if self._handle_key(ev, ui):
                            return
                    elif ev.type == E.EV_MSC:
                        continue  # scancodes brutos: desnecessários
                    else:
                        with self.out_lock:
                            ui.write(ev.type, ev.code, ev.value)

    def _forward_leds(self, ui: UInput):
        try:
            for ev in ui.read():
                if ev.type == E.EV_LED:
                    for d in self.devices:
                        if E.EV_LED in d.capabilities():
                            d.set_led(ev.code, ev.value)
        except (BlockingIOError, OSError):
            pass

    def _emit(self, ui: UInput, code: int, value: int):
        with self.out_lock:
            ui.write(E.EV_KEY, code, value)
            ui.syn()
            if value:
                self.virtual_down[code] = ui
            else:
                self.virtual_down.pop(code, None)

    def _handle_key(self, ev, ui: UInput) -> bool:
        """Retorna True se o motor deve parar (combinação de emergência)."""
        name = code_name(ev.code)
        if ev.value == 1:
            if name:
                self.pressed.add(name)
            if name == PANIC[2] and self.pressed & PANIC[0] and self.pressed & PANIC[1]:
                self._set_status("Desligado pela combinação de emergência")
                self.cfg["macros_enabled"] = False
                self._stop.set()
                return True
            macro = self._match(name) if name else None
            if macro:
                self.consumed[ev.code] = macro
                self._fire(macro, ev.code)
                return False
            self._emit(ui, ev.code, 1)
        elif ev.value == 2:
            macro = self.consumed.get(ev.code)
            if macro is None:
                with self.out_lock:
                    ui.write(E.EV_KEY, ev.code, 2)
                    ui.syn()
            elif macro["mode"] == "remap":
                tgt = name_code(macro.get("remap_to", ""))
                if tgt:
                    self._emit(self.out, tgt, 2)
        else:
            if name:
                self.pressed.discard(name)
            macro = self.consumed.pop(ev.code, None)
            if macro is None:
                self._emit(ui, ev.code, 0)
            elif macro["mode"] == "remap":
                tgt = name_code(macro.get("remap_to", ""))
                if tgt:
                    self._emit(self.out, tgt, 0)
            elif macro["mode"] == "repeat":
                stop = self.holds.pop(ev.code, None)
                if stop:
                    stop.set()
        return False

    def _match(self, name: str) -> dict | None:
        held_mods = self.pressed & MODIFIERS
        best = None
        for m in self.cfg["macros"]:
            trig = m.get("trigger") or []
            if not m.get("enabled", True) or not trig or trig[-1] != name:
                continue
            req = trig[:-1]
            if not all(_expand(k) & self.pressed for k in req):
                continue
            allowed = set().union(*(_expand(k) for k in req)) if req else set()
            if held_mods - allowed - {name}:
                continue
            if best is None or len(trig) > len(best["trigger"]):
                best = m
        return best

    # ------------------------------------------------------------------ execução
    def _fire(self, macro: dict, code: int):
        mode = macro.get("mode", "once")
        self.on_fire(macro.get("name", ""))
        if mode == "remap":
            tgt = name_code(macro.get("remap_to", ""))
            if tgt:
                self._emit(self.out, tgt, 1)
            return
        trig_mods = {k for t in macro["trigger"][:-1] for k in _expand(t)} & self.pressed
        if mode == "once":
            threading.Thread(target=self._run_steps, args=(macro, trig_mods, None), daemon=True).start()
        elif mode == "repeat":
            stop = threading.Event()
            self.holds[code] = stop
            threading.Thread(target=self._run_loop, args=(macro, trig_mods, stop), daemon=True).start()
        elif mode == "toggle":
            key = id(macro)
            if key in self.toggles:
                self.toggles.pop(key).set()
            else:
                stop = threading.Event()
                self.toggles[key] = stop
                threading.Thread(target=self._run_loop, args=(macro, trig_mods, stop), daemon=True).start()

    def _run_loop(self, macro, trig_mods, stop: threading.Event):
        interval = max(1, int(macro.get("repeat_interval_ms", 50))) / 1000
        while not stop.is_set() and not self._stop.is_set():
            self._run_steps(macro, trig_mods, stop)
            trig_mods = set()  # só solta os modificadores na primeira volta
            stop.wait(interval)

    def _sleep(self, sec: float, stop: threading.Event | None):
        if stop:
            stop.wait(sec)
        else:
            self._stop.wait(sec)

    def _run_steps(self, macro: dict, trig_mods: set[str], stop: threading.Event | None):
        out = self.out
        if out is None:
            return
        delay = max(0, int(self.cfg["macro_step_delay_ms"])) / 1000
        # solta os modificadores do gatilho para não "contaminar" a macro
        released = [(name_code(k), self.virtual_down[name_code(k)])
                    for k in trig_mods if name_code(k) in self.virtual_down]
        for c, ui in released:
            self._emit(ui, c, 0)
        try:
            for step in macro.get("steps", []):
                if (stop and stop.is_set()) or self._stop.is_set():
                    break
                t = step.get("type")
                if t == "key":
                    c = name_code(step.get("key", ""))
                    if c is None:
                        continue
                    action = step.get("action", "tap")
                    if action in ("tap", "down"):
                        self._emit(out, c, 1)
                    if action == "tap":
                        self._sleep(delay, stop)
                    if action in ("tap", "up"):
                        self._emit(out, c, 0)
                elif t == "delay":
                    self._sleep(max(0, int(step.get("ms", 0))) / 1000, stop)
                    continue
                elif t == "text":
                    for mods, key in text_to_chords(step.get("text", ""), self.cfg["text_layout"]):
                        mc = [name_code(m) for m in mods]
                        kc = name_code(key)
                        for c in mc:
                            self._emit(out, c, 1)
                        self._emit(out, kc, 1)
                        self._sleep(delay / 2, stop)
                        self._emit(out, kc, 0)
                        for c in mc:
                            self._emit(out, c, 0)
                        self._sleep(delay / 2, stop)
                elif t == "command":
                    cmd = step.get("command", "").strip()
                    if cmd:
                        subprocess.Popen(cmd, shell=True, start_new_session=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._sleep(delay, stop)
        finally:
            # reaplica modificadores que o usuário ainda segura
            for c, ui in released:
                if code_name(c) in self.pressed and c not in self.virtual_down:
                    self._emit(ui, c, 1)
