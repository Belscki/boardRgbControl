from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget, QGroupBox)

from ..config import MACRO_DEFAULT
from ..keymap import pretty_key
from .widgets import KeyCaptureEdit, qt_event_key

MODES = [("once", "Executar uma vez"), ("repeat", "Repetir enquanto segurar"),
         ("toggle", "Liga/desliga repetição"), ("remap", "Remapear para outra tecla")]
GENERIC = {"KEY_LEFTCTRL": "CTRL", "KEY_RIGHTCTRL": "CTRL", "KEY_LEFTSHIFT": "SHIFT",
           "KEY_RIGHTSHIFT": "SHIFT", "KEY_LEFTMETA": "META", "KEY_RIGHTMETA": "META", "KEY_LEFTALT": "ALT"}
ACTIONS = [("tap", "Tocar (pressiona e solta)"), ("down", "Pressionar (segurar)"), ("up", "Soltar")]


def describe_step(s: dict) -> str:
    t = s.get("type")
    if t == "key":
        act = {"tap": "", "down": " ↓ pressiona", "up": " ↑ solta"}[s.get("action", "tap")]
        return f"⌨  {pretty_key(s.get('key', '?'))}{act}"
    if t == "delay":
        return f"⏱  Esperar {s.get('ms', 0)} ms"
    if t == "text":
        txt = s.get("text", "").replace("\n", "⏎")
        return f"✎  Digitar “{txt[:60]}”"
    if t == "command":
        return f"▶  Executar: {s.get('command', '')}"
    return str(s)


def describe_trigger(trig) -> str:
    return " + ".join(pretty_key(k) for k in trig) if trig else "(sem gatilho)"


class KeyStepDialog(QDialog):
    def __init__(self, step=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Passo: tecla")
        lay = QFormLayout(self)
        self.key = KeyCaptureEdit(single=True)
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("ou digite o nome evdev, ex.: KEY_VOLUMEUP")
        self.action = QComboBox()
        for k, label in ACTIONS:
            self.action.addItem(label, k)
        if step:
            self.key.set_keys([step.get("key", "")])
            self.action.setCurrentIndex([a for a, _ in ACTIONS].index(step.get("action", "tap")))
        lay.addRow("Tecla:", self.key)
        lay.addRow("", self.manual)
        lay.addRow("Ação:", self.action)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def result_step(self):
        key = self.manual.text().strip().upper() or (self.key.keys[0] if self.key.keys else "")
        if key and not key.startswith("KEY_"):
            key = "KEY_" + key
        return {"type": "key", "key": key, "action": self.action.currentData()} if key else None


class RecordDialog(QDialog):
    """Grava uma sequência de teclas (com ou sem os tempos)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gravar sequência")
        self.events: list[tuple[float, str, bool]] = []
        lay = QVBoxLayout(self)
        self.info = QLabel("Pressione as teclas da sequência. Clique em “Parar” ao terminar.\n"
                           "(Teclas usadas pelo KDE, como Super e PrtSc, podem não ser capturadas.)")
        self.view = QLabel("")
        self.view.setWordWrap(True)
        self.view.setMinimumHeight(80)
        self.view.setStyleSheet("background:#222; color:#eee; padding:6px; font-family:monospace")
        self.delays = QCheckBox("Gravar os atrasos entre as teclas")
        self.delays.setChecked(True)
        stop = QPushButton("Parar e usar")
        stop.setFocusPolicy(Qt.NoFocus)
        stop.clicked.connect(self.accept)
        cancel = QPushButton("Cancelar")
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.clicked.connect(self.reject)
        self.delays.setFocusPolicy(Qt.NoFocus)
        row = QHBoxLayout()
        row.addWidget(self.delays)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(stop)
        lay.addWidget(self.info)
        lay.addWidget(self.view)
        lay.addLayout(row)
        self.resize(520, 220)

    def showEvent(self, e):
        super().showEvent(e)
        self.grabKeyboard()

    def done(self, r):
        self.releaseKeyboard()
        super().done(r)

    def _log(self, e, down):
        if e.isAutoRepeat():
            return
        name = qt_event_key(e)
        if name:
            self.events.append((time.monotonic(), name, down))
            self.view.setText(" ".join(("↓" if d else "↑") + pretty_key(n) for _, n, d in self.events[-40:]))

    def keyPressEvent(self, e):
        self._log(e, True)

    def keyReleaseEvent(self, e):
        self._log(e, False)

    def steps(self) -> list[dict]:
        ev = self.events
        out = []
        i = 0
        prev_t = None
        while i < len(ev):
            t, name, down = ev[i]
            if self.delays.isChecked() and prev_t is not None:
                gap = int((t - prev_t) * 1000)
                if gap >= 15:
                    out.append({"type": "delay", "ms": gap})
            if down and i + 1 < len(ev) and ev[i + 1][1] == name and not ev[i + 1][2] \
                    and (not self.delays.isChecked() or ev[i + 1][0] - t < 0.15):
                out.append({"type": "key", "key": name, "action": "tap"})
                prev_t = ev[i + 1][0]
                i += 2
                continue
            out.append({"type": "key", "key": name, "action": "down" if down else "up"})
            prev_t = t
            i += 1
        return out


class MacroTab(QWidget):
    changed = Signal()
    engineToggled = Signal(bool)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.cur: dict | None = None
        self._loading = False

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.enable = QCheckBox("Ativar motor de macros")
        self.enable.setChecked(bool(cfg["macros_enabled"]))
        self.enable.toggled.connect(self.engineToggled.emit)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#888")
        top.addWidget(self.enable)
        top.addWidget(self.status, 1)
        top.addWidget(QLabel("Atraso padrão entre passos (ms):"))
        self.step_delay = QSpinBox()
        self.step_delay.setRange(0, 1000)
        self.step_delay.setValue(int(cfg["macro_step_delay_ms"]))
        self.step_delay.valueChanged.connect(self._global_changed)
        top.addWidget(self.step_delay)
        top.addWidget(QLabel("Layout do texto:"))
        self.text_layout = QComboBox()
        self.text_layout.addItem("ABNT2 (br)", "br")
        self.text_layout.addItem("US", "us")
        self.text_layout.setCurrentIndex(0 if cfg["text_layout"] == "br" else 1)
        self.text_layout.currentIndexChanged.connect(self._global_changed)
        top.addWidget(self.text_layout)
        root.addLayout(top)

        split = QSplitter()
        root.addWidget(split, 1)

        # lista
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        ll.addWidget(self.list)
        row = QHBoxLayout()
        for txt, fn in (("+ Nova", self._add), ("Duplicar", self._dup), ("Remover", self._remove)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        split.addWidget(left)

        # editor
        self.editor = QGroupBox("Macro")
        ed = QVBoxLayout(self.editor)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.textEdited.connect(self._edited)
        self.en = QCheckBox("Ativada")
        self.en.toggled.connect(self._edited)
        self.trigger = KeyCaptureEdit()
        self.trigger.captured.connect(self._trigger_captured)
        self.mode = QComboBox()
        for k, label in MODES:
            self.mode.addItem(label, k)
        self.mode.currentIndexChanged.connect(self._edited)
        self.interval = QSpinBox()
        self.interval.setRange(1, 60000)
        self.interval.setSuffix(" ms")
        self.interval.valueChanged.connect(self._edited)
        self.remap = KeyCaptureEdit(single=True)
        self.remap.captured.connect(lambda _: self._edited())
        form.addRow("Nome:", self.name)
        form.addRow("", self.en)
        form.addRow("Gatilho:", self.trigger)
        form.addRow("Modo:", self.mode)
        self.interval_label = QLabel("Intervalo entre repetições:")
        form.addRow(self.interval_label, self.interval)
        self.remap_label = QLabel("Remapear para:")
        form.addRow(self.remap_label, self.remap)
        ed.addLayout(form)
        hint = QLabel("Dica: o gatilho pode ser uma tecla sozinha (ex.: F13, Pause, ScrLk) ou uma "
                      "combinação (ex.: Ctrl+Shift+1). Ctrl/Shift/Super valem dos dois lados.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888")
        ed.addWidget(hint)

        self.steps_box = QGroupBox("Passos")
        sb = QVBoxLayout(self.steps_box)
        self.steps = QListWidget()
        self.steps.itemDoubleClicked.connect(lambda _: self._edit_step())
        sb.addWidget(self.steps)
        r1 = QHBoxLayout()
        for txt, fn in (("+ Tecla", self._add_key), ("+ Atraso", self._add_delay), ("+ Texto", self._add_text),
                        ("+ Comando", self._add_cmd), ("● Gravar", self._record)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            r1.addWidget(b)
        sb.addLayout(r1)
        r2 = QHBoxLayout()
        for txt, fn in (("Editar", self._edit_step), ("Remover", self._del_step), ("↑", lambda: self._move(-1)),
                        ("↓", lambda: self._move(1)), ("Limpar", self._clear_steps)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            r2.addWidget(b)
        sb.addLayout(r2)
        ed.addWidget(self.steps_box, 1)
        split.addWidget(self.editor)
        split.setSizes([260, 640])

        self._reload_list()

    # ---------------------------------------------------------------- lista
    def _reload_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.cfg["macros"]:
            it = QListWidgetItem(f"{'✔' if m['enabled'] else '✖'}  {m['name']}   [{describe_trigger(m['trigger'])}]")
            self.list.addItem(it)
        self.list.blockSignals(False)
        n = len(self.cfg["macros"])
        if n:
            self.list.setCurrentRow(min(select if select is not None else 0, n - 1))
            self._select(self.list.currentRow())
        else:
            self._select(-1)

    def _refresh_item(self):
        row = self.list.currentRow()
        if self.cur is not None and row >= 0:
            m = self.cur
            self.list.item(row).setText(f"{'✔' if m['enabled'] else '✖'}  {m['name']}   "
                                        f"[{describe_trigger(m['trigger'])}]")

    def _select(self, row):
        macros = self.cfg["macros"]
        self.cur = macros[row] if 0 <= row < len(macros) else None
        self.editor.setEnabled(self.cur is not None)
        if self.cur is None:
            return
        self._loading = True
        m = self.cur
        self.name.setText(m["name"])
        self.en.setChecked(m["enabled"])
        self.trigger.set_keys(m["trigger"])
        self.mode.setCurrentIndex([k for k, _ in MODES].index(m["mode"]))
        self.interval.setValue(int(m["repeat_interval_ms"]))
        self.remap.set_keys([m["remap_to"]] if m["remap_to"] else [])
        self._reload_steps()
        self._update_visibility()
        self._loading = False

    def _update_visibility(self):
        mode = self.mode.currentData()
        rep = mode in ("repeat", "toggle")
        self.interval.setVisible(rep)
        self.interval_label.setVisible(rep)
        self.remap.setVisible(mode == "remap")
        self.remap_label.setVisible(mode == "remap")
        self.steps_box.setVisible(mode != "remap")

    def _add(self):
        m = copy.deepcopy(MACRO_DEFAULT)
        m["name"] = f"Macro {len(self.cfg['macros']) + 1}"
        self.cfg["macros"].append(m)
        self._reload_list(len(self.cfg["macros"]) - 1)
        self.changed.emit()

    def _dup(self):
        if self.cur:
            m = copy.deepcopy(self.cur)
            m["name"] += " (cópia)"
            m["trigger"] = []
            self.cfg["macros"].append(m)
            self._reload_list(len(self.cfg["macros"]) - 1)
            self.changed.emit()

    def _remove(self):
        row = self.list.currentRow()
        if self.cur is None:
            return
        if QMessageBox.question(self, "Remover", f"Remover a macro “{self.cur['name']}”?") \
                != QMessageBox.StandardButton.Yes:
            return
        del self.cfg["macros"][row]
        self._reload_list(row)
        self.changed.emit()

    # ---------------------------------------------------------------- campos
    def _global_changed(self):
        self.cfg["macro_step_delay_ms"] = self.step_delay.value()
        self.cfg["text_layout"] = self.text_layout.currentData()
        self.changed.emit()

    def _edited(self, *_):
        if self._loading or self.cur is None:
            return
        m = self.cur
        m["name"] = self.name.text()
        m["enabled"] = self.en.isChecked()
        m["mode"] = self.mode.currentData()
        m["repeat_interval_ms"] = self.interval.value()
        m["remap_to"] = self.remap.keys[0] if self.remap.keys else ""
        self._update_visibility()
        self._refresh_item()
        self.changed.emit()

    def _trigger_captured(self, keys):
        if self.cur is None:
            return
        keys = [GENERIC.get(k, k) for k in keys[:-1]] + keys[-1:]
        # evita duplicatas (ex.: Ctrl esquerdo + direito)
        seen, trig = set(), []
        for k in keys:
            if k not in seen:
                seen.add(k)
                trig.append(k)
        for other in self.cfg["macros"]:
            if other is not self.cur and other["trigger"] == trig:
                QMessageBox.warning(self, "Gatilho em uso", f"A macro “{other['name']}” já usa esse gatilho.")
        self.cur["trigger"] = trig
        self.trigger.set_keys(trig)
        self._refresh_item()
        self.changed.emit()

    # ---------------------------------------------------------------- passos
    def _reload_steps(self, select=None):
        self.steps.clear()
        for s in (self.cur or {}).get("steps", []):
            self.steps.addItem(describe_step(s))
        if select is not None and self.steps.count():
            self.steps.setCurrentRow(max(0, min(select, self.steps.count() - 1)))

    def _insert(self, steps):
        if self.cur is None or not steps:
            return
        row = self.steps.currentRow()
        pos = row + 1 if row >= 0 else len(self.cur["steps"])
        self.cur["steps"][pos:pos] = steps
        self._reload_steps(pos + len(steps) - 1)
        self.changed.emit()

    def _add_key(self):
        d = KeyStepDialog(parent=self)
        if d.exec() and d.result_step():
            self._insert([d.result_step()])

    def _add_delay(self):
        ms, ok = QInputDialog.getInt(self, "Atraso", "Milissegundos:", 100, 0, 600000)
        if ok:
            self._insert([{"type": "delay", "ms": ms}])

    def _add_text(self):
        txt, ok = QInputDialog.getMultiLineText(self, "Digitar texto", "Texto a digitar:")
        if ok and txt:
            self._insert([{"type": "text", "text": txt}])

    def _add_cmd(self):
        cmd, ok = QInputDialog.getText(self, "Executar comando", "Comando (shell):")
        if ok and cmd.strip():
            self._insert([{"type": "command", "command": cmd.strip()}])

    def _record(self):
        d = RecordDialog(self)
        if d.exec():
            self._insert(d.steps())

    def _edit_step(self):
        row = self.steps.currentRow()
        if self.cur is None or row < 0:
            return
        s = self.cur["steps"][row]
        t = s["type"]
        new = None
        if t == "key":
            d = KeyStepDialog(s, self)
            if d.exec():
                new = d.result_step()
        elif t == "delay":
            ms, ok = QInputDialog.getInt(self, "Atraso", "Milissegundos:", int(s["ms"]), 0, 600000)
            new = {"type": "delay", "ms": ms} if ok else None
        elif t == "text":
            txt, ok = QInputDialog.getMultiLineText(self, "Digitar texto", "Texto:", s["text"])
            new = {"type": "text", "text": txt} if ok else None
        elif t == "command":
            cmd, ok = QInputDialog.getText(self, "Comando", "Comando (shell):", text=s["command"])
            new = {"type": "command", "command": cmd} if ok else None
        if new:
            self.cur["steps"][row] = new
            self._reload_steps(row)
            self.changed.emit()

    def _del_step(self):
        row = self.steps.currentRow()
        if self.cur is not None and row >= 0:
            del self.cur["steps"][row]
            self._reload_steps(row)
            self.changed.emit()

    def _move(self, d):
        row = self.steps.currentRow()
        st = (self.cur or {}).get("steps", [])
        if 0 <= row < len(st) and 0 <= row + d < len(st):
            st[row], st[row + d] = st[row + d], st[row]
            self._reload_steps(row + d)
            self.changed.emit()

    def _clear_steps(self):
        if self.cur and self.cur["steps"] and QMessageBox.question(self, "Limpar", "Remover todos os passos?") \
                == QMessageBox.StandardButton.Yes:
            self.cur["steps"] = []
            self._reload_steps()
            self.changed.emit()
