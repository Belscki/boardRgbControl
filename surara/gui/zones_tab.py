from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from ..config import STYLE_KEYS, ZONE_DEFAULT, zone_style
from .. import grid
from .grid_dialog import METHODS, GridDialog
from .widgets import KeyboardWidget, ScreenPreview

class StyleWidgets:
    """Cálculo da cor, suavização, saturação e intensidade (usado no global e por espaço)."""

    def __init__(self, on_change):
        self.method = QComboBox()
        for k, label in METHODS:
            self.method.addItem(label, k)
        self.smooth = QSlider(Qt.Horizontal)
        self.smooth.setRange(0, 95)
        self.smooth.setMinimumWidth(90)
        self.smooth_label = QLabel()
        self.smooth_label.setMinimumWidth(34)
        self.smooth.valueChanged.connect(lambda v: self.smooth_label.setText(f"{v}%"))
        self.sat = QDoubleSpinBox()
        self.sat.setRange(0, 3)
        self.sat.setSingleStep(0.1)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0, 3)
        self.gain.setSingleStep(0.1)
        self.method.setToolTip("Média: média da região. Mais viva: favorece cores saturadas e claras. "
                               "Predominante: a cor que mais aparece.")
        self.smooth.setToolTip("Quanto a cor demora para acompanhar a tela (0% = instantâneo).")
        self.sat.setToolTip("1,0 = cor original; acima de 1 deixa as cores mais vivas.")
        self.gain.setToolTip("Multiplica o brilho da cor (1,0 = original).")
        self.method.currentIndexChanged.connect(on_change)
        self.smooth.valueChanged.connect(on_change)
        self.sat.valueChanged.connect(on_change)
        self.gain.valueChanged.connect(on_change)

    def smooth_row(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.smooth, 1)
        lay.addWidget(self.smooth_label)
        return w

    def set(self, st: dict):
        self.method.setCurrentIndex(max(0, [k for k, _ in METHODS].index(st["method"])))
        self.smooth.setValue(int(round(float(st["smoothing"]) * 100)))
        self.smooth_label.setText(f"{self.smooth.value()}%")
        self.sat.setValue(float(st["saturation"]))
        self.gain.setValue(float(st["gain"]))

    def get(self) -> dict:
        return {"method": self.method.currentData(), "smoothing": self.smooth.value() / 100,
                "saturation": self.sat.value(), "gain": self.gain.value()}

    def setEnabled(self, on: bool):
        for w in (self.method, self.smooth, self.sat, self.gain):
            w.setEnabled(on)


PALETTE = ["#ff5252", "#40c4ff", "#69f0ae", "#ffd740", "#e040fb", "#ff6e40", "#b2ff59", "#18ffff"]


class ZonesTab(QWidget):
    changed = Signal()
    ambientToggled = Signal(bool)
    captureRequested = Signal(bool)      # True = iniciar, False = parar
    reselectRequested = Signal()

    def __init__(self, cfg, app, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.app = app
        self.cur = -1
        self._loading = False
        root = QVBoxLayout(self)

        # ---- barra superior
        top = QHBoxLayout()
        self.enable = QCheckBox("Ativar espaços de tela")
        self.enable.setChecked(bool(cfg["ambient"]["enabled"]))
        self.enable.toggled.connect(self.ambientToggled.emit)
        self.cap_btn = QPushButton("Iniciar captura")
        self.cap_btn.clicked.connect(lambda: self.captureRequested.emit(not self.app.capture.running))
        resel = QPushButton("Escolher monitores de novo")
        resel.clicked.connect(self.reselectRequested.emit)
        self.monitor = QComboBox()
        self.monitor.currentIndexChanged.connect(self._monitor_changed)
        top.addWidget(self.enable)
        top.addWidget(self.cap_btn)
        top.addWidget(resel)
        top.addWidget(QLabel("Monitor:"))
        top.addWidget(self.monitor, 1)
        root.addLayout(top)

        lim = QHBoxLayout()
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.1, 60)
        self.fps.setDecimals(1)
        self.fps.setSingleStep(0.5)
        self.fps.setValue(float(cfg["ambient"]["min_interval"]))
        self.fps.setSuffix(" s")
        self.fps.setToolTip("Tempo mínimo entre duas trocas de cor. Cada troca faz o teclado piscar "
                            "(limitação do firmware), então valores maiores = menos piscadas.")
        self.thr = QSpinBox()
        self.thr.setRange(0, 765)
        self.thr.setValue(int(cfg["ambient"]["threshold"]))
        self.thr.setToolTip("Quanto a cor precisa mudar (soma das diferenças de R, G e B, 0–765) "
                            "para a tecla trocar. Valores maiores ignoram variações pequenas da tela.")
        self.fps.valueChanged.connect(self._limits_changed)
        self.thr.valueChanged.connect(self._limits_changed)
        self.cap_status = QLabel("")
        self.cap_status.setStyleSheet("color:#888")
        lim.addWidget(QLabel("Intervalo mínimo entre trocas:"))
        lim.addWidget(self.fps)
        lim.addWidget(QLabel("Mudança mínima de cor:"))
        lim.addWidget(self.thr)
        lim.addWidget(self.cap_status, 1)
        root.addLayout(lim)

        glob = QGroupBox("Ajustes globais (todos os espaços sem ajustes próprios)")
        gl = QHBoxLayout(glob)
        self.g_style = StyleWidgets(self._global_changed)
        self._loading = True
        self.g_style.set(zone_style(cfg["ambient"], {}))
        self._loading = False
        gl.addWidget(QLabel("Cálculo da cor:"))
        gl.addWidget(self.g_style.method)
        gl.addWidget(QLabel("Suavização:"))
        gl.addWidget(self.g_style.smooth_row(), 1)
        gl.addWidget(QLabel("Saturação:"))
        gl.addWidget(self.g_style.sat)
        gl.addWidget(QLabel("Intensidade:"))
        gl.addWidget(self.g_style.gain)
        self.all_global = QPushButton("Todos seguem o global")
        self.all_global.setToolTip("Remove os ajustes próprios de todos os espaços")
        self.all_global.clicked.connect(self._all_follow_global)
        gl.addWidget(self.all_global)
        root.addWidget(glob)

        split = QSplitter(Qt.Vertical)
        root.addWidget(split, 1)

        # ---- prévia + lista
        upper = QSplitter()
        self.preview = ScreenPreview()
        self.preview.zoneSelected.connect(self._select_row)
        self.preview.zoneCreated.connect(self._create_zone)
        self.preview.zonesChanged.connect(self.changed.emit)
        upper.addWidget(self.preview)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        sl.addWidget(QLabel("Espaços (arraste na prévia para criar):"))
        sl.addWidget(self.list, 1)
        row = QHBoxLayout()
        for txt, fn in (("+ Novo", lambda: self._create_zone([0.4, 0.4, 0.2, 0.2])), ("Duplicar", self._dup),
                        ("Remover", self._remove)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        sl.addLayout(row)
        row2 = QHBoxLayout()
        for txt, fn in (("▦ Gerar grade…", self._grid), ("Remover grade", self._remove_grid)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row2.addWidget(b)
        sl.addLayout(row2)

        self.props = QGroupBox("Propriedades do espaço")
        f = QFormLayout(self.props)
        self.name = QLineEdit()
        self.name.textEdited.connect(self._edited)
        self.z_en = QCheckBox("Ativado")
        self.z_en.toggled.connect(self._edited)
        self.custom = QCheckBox("Usar ajustes próprios")
        self.custom.setToolTip("Desmarcado: este espaço segue os ajustes globais")
        self.custom.toggled.connect(self._custom_toggled)
        self.z_style = StyleWidgets(self._edited)
        self.swatch = QLabel()
        self.swatch.setFixedHeight(22)
        f.addRow("Nome:", self.name)
        f.addRow("", self.z_en)
        f.addRow("", self.custom)
        f.addRow("Cálculo da cor:", self.z_style.method)
        f.addRow("Suavização:", self.z_style.smooth_row())
        f.addRow("Saturação:", self.z_style.sat)
        f.addRow("Intensidade:", self.z_style.gain)
        f.addRow("Cor atual:", self.swatch)
        sl.addWidget(self.props)
        upper.addWidget(side)
        upper.setSizes([700, 320])
        split.addWidget(upper)

        # ---- teclado (atribuição de teclas)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        self.kb_label = QLabel("Clique nas teclas para incluí-las/removê-las do espaço selecionado "
                               "(arrastar seleciona várias).")
        self.kb = KeyboardWidget(app.keys, self._key_color, toggle_mode=True)
        self.kb.selectionChanged.connect(self._keys_changed)
        ll.addWidget(self.kb_label)
        ll.addWidget(self.kb, 1)
        split.addWidget(lower)
        split.setSizes([420, 260])

        self._reload_list()

    # ----------------------------------------------------------------- monitores
    def refresh_monitors(self):
        cap = self.app.capture
        self.monitor.blockSignals(True)
        cur = self.monitor.currentIndex()
        self.monitor.clear()
        for i, s in enumerate(cap.streams):
            self.monitor.addItem(f"Monitor {i + 1}: {s.describe()}", i)
        if not cap.streams:
            self.monitor.addItem("(sem captura)", 0)
        self.monitor.setCurrentIndex(max(0, min(cur, self.monitor.count() - 1)))
        self.monitor.blockSignals(False)
        self.cap_btn.setText("Parar captura" if cap.running else "Iniciar captura")

    def current_monitor(self) -> int:
        return int(self.monitor.currentData() or 0)

    def _monitor_changed(self):
        # ao trocar de monitor, seleciona o primeiro espaço daquele monitor
        mon = self.current_monitor()
        for i, z in enumerate(self.cfg["zones"]):
            if self._zone_monitor(z) == mon:
                self.list.setCurrentRow(i)
                return

    def _zone_monitor(self, z) -> int:
        idx = self.app.capture.find_stream(z.get("monitor_pos"))
        return idx if idx is not None else int(z.get("monitor", 0))

    # ----------------------------------------------------------------- lista
    def _reload_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for z in self.cfg["zones"]:
            self.list.addItem(self._item_text(z))
        self.list.blockSignals(False)
        n = len(self.cfg["zones"])
        row = -1 if not n else min(select if select is not None else 0, n - 1)
        self.list.setCurrentRow(row)
        self._select(row)

    @staticmethod
    def _item_text(z) -> str:
        own = "  ✎" if z.get("custom") else ""
        return f"{'✔' if z['enabled'] else '✖'}  {z['name']}  ({len(z['keys'])} teclas){own}"

    def _refresh_item(self):
        if 0 <= self.cur < len(self.cfg["zones"]):
            z = self.cfg["zones"][self.cur]
            self.list.item(self.cur).setText(self._item_text(z))

    def _select_row(self, idx):
        self.list.setCurrentRow(idx)

    def _select(self, row):
        self.cur = row
        zones = self.cfg["zones"]
        valid = 0 <= row < len(zones)
        self.props.setEnabled(valid)
        self.kb.setEnabled(valid)
        self.preview.current = row
        if not valid:
            self.kb.selected = set()
            self.kb.update()
            return
        z = zones[row]
        self._loading = True
        self.name.setText(z["name"])
        self.z_en.setChecked(z["enabled"])
        self.custom.setChecked(bool(z.get("custom")))
        self.z_style.set(zone_style(self.cfg["ambient"], z))
        self.z_style.setEnabled(bool(z.get("custom")))
        self._loading = False
        self.kb.selected = set(z["keys"])
        self.kb.update()
        mon = self._zone_monitor(z)
        if mon != self.current_monitor() and mon < self.monitor.count():
            self.monitor.blockSignals(True)
            self.monitor.setCurrentIndex(mon)
            self.monitor.blockSignals(False)

    def _create_zone(self, rect):
        z = copy.deepcopy(ZONE_DEFAULT)
        n = len(self.cfg["zones"]) + 1
        z["name"] = f"Espaço {n}"
        z["rect"] = [float(v) for v in rect]
        mon = self.current_monitor()
        z["monitor"] = mon
        if mon < len(self.app.capture.streams):
            z["monitor_pos"] = list(self.app.capture.streams[mon].position)
        self.cfg["zones"].append(z)
        self._reload_list(len(self.cfg["zones"]) - 1)
        self.changed.emit()

    def _dup(self):
        if 0 <= self.cur < len(self.cfg["zones"]):
            z = copy.deepcopy(self.cfg["zones"][self.cur])
            z["name"] += " (cópia)"
            z["rect"][0] = min(1 - z["rect"][2], z["rect"][0] + 0.03)
            z["rect"][1] = min(1 - z["rect"][3], z["rect"][1] + 0.03)
            z["keys"] = []
            self.cfg["zones"].append(z)
            self._reload_list(len(self.cfg["zones"]) - 1)
            self.changed.emit()

    def _remove(self):
        if 0 <= self.cur < len(self.cfg["zones"]):
            if QMessageBox.question(self, "Remover", f"Remover “{self.cfg['zones'][self.cur]['name']}”?") \
                    != QMessageBox.StandardButton.Yes:
                return
            del self.cfg["zones"][self.cur]
            self.app.sampler.state.clear()
            self._reload_list(self.cur)
            self.changed.emit()

    def _grid(self):
        d = GridDialog(self.app.keys, set(self.kb.selected), self)
        if not d.exec():
            return
        base = d.base()
        mon = self.current_monitor()
        base["monitor"] = mon
        if mon < len(self.app.capture.streams):
            base["monitor_pos"] = list(self.app.capture.streams[mon].position)
        new = d.generate(base)
        self.cfg["zones"] = grid.apply(self.cfg["zones"], new, d.replace.isChecked())
        self.app.sampler.state.clear()
        self._reload_list(len(self.cfg["zones"]) - len(new))
        self.changed.emit()

    def _remove_grid(self):
        n = sum(1 for z in self.cfg["zones"] if z.get("group") == grid.GRID_GROUP)
        if not n or QMessageBox.question(self, "Remover grade", f"Remover os {n} espaços da grade?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.cfg["zones"] = [z for z in self.cfg["zones"] if z.get("group") != grid.GRID_GROUP]
        self.app.sampler.state.clear()
        self._reload_list(0)
        self.changed.emit()

    # ----------------------------------------------------------------- edição
    def _edited(self, *_):
        if self._loading or not 0 <= self.cur < len(self.cfg["zones"]):
            return
        z = self.cfg["zones"][self.cur]
        z["name"] = self.name.text()
        z["enabled"] = self.z_en.isChecked()
        if z.get("custom"):
            z.update(self.z_style.get())
        self._refresh_item()
        self.changed.emit()

    def _custom_toggled(self, on):
        if self._loading or not 0 <= self.cur < len(self.cfg["zones"]):
            return
        z = self.cfg["zones"][self.cur]
        if on:  # começa a partir do que está valendo agora (o global)
            z.update(zone_style(self.cfg["ambient"], {}))
        z["custom"] = on
        self._loading = True
        self.z_style.set(zone_style(self.cfg["ambient"], z))
        self._loading = False
        self.z_style.setEnabled(on)
        self._refresh_item()
        self.changed.emit()

    def _global_changed(self, *_):
        if self._loading:
            return
        self.cfg["ambient"].update(self.g_style.get())
        if 0 <= self.cur < len(self.cfg["zones"]) and not self.cfg["zones"][self.cur].get("custom"):
            self._loading = True
            self.z_style.set(zone_style(self.cfg["ambient"], {}))
            self._loading = False
        self.changed.emit()

    def _all_follow_global(self):
        n = sum(1 for z in self.cfg["zones"] if z.get("custom"))
        if not n:
            QMessageBox.information(self, "Ajustes globais", "Todos os espaços já seguem os ajustes globais.")
            return
        if QMessageBox.question(self, "Ajustes globais",
                                f"{n} espaço(s) têm ajustes próprios. Fazer todos seguirem o global?") \
                != QMessageBox.StandardButton.Yes:
            return
        for z in self.cfg["zones"]:
            z["custom"] = False
        self._reload_list(self.cur)
        self.changed.emit()

    def _keys_changed(self):
        if not 0 <= self.cur < len(self.cfg["zones"]):
            return
        keys = self.kb.selected
        # uma tecla pertence a um espaço só: remove dos outros
        for i, z in enumerate(self.cfg["zones"]):
            if i != self.cur:
                z["keys"] = [k for k in z["keys"] if k not in keys]
        self.cfg["zones"][self.cur]["keys"] = sorted(keys)
        for i in range(self.list.count()):
            z = self.cfg["zones"][i]
            self.list.item(i).setText(self._item_text(z))
        self.changed.emit()

    def _limits_changed(self):
        self.cfg["ambient"]["min_interval"] = self.fps.value()
        self.cfg["ambient"]["threshold"] = self.thr.value()
        self.changed.emit()

    # ----------------------------------------------------------------- atualização periódica
    def _zone_color(self, i) -> QColor:
        c = self.app.sampler.zone_rgb.get(i)
        return QColor(*c) if c else QColor(PALETTE[i % len(PALETTE)])

    def _key_color(self, k) -> QColor:
        for i, z in enumerate(self.cfg["zones"]):
            if k.code in z["keys"]:
                c = self._zone_color(i)
                return c if i == self.cur else c.darker(160)
        return QColor("#333")

    def tick(self):
        mon = self.current_monitor()
        self.preview.set_frame(self.app.capture.get_frame(mon))
        self.preview.zones = [(i, z, self._zone_color(i)) for i, z in enumerate(self.cfg["zones"])
                              if self._zone_monitor(z) == mon]
        self.preview.update()
        self.kb.update()
        if 0 <= self.cur < len(self.cfg["zones"]):
            c = self._zone_color(self.cur)
            self.swatch.setStyleSheet(f"background:{c.name()}; border:1px solid #555")
        cap = self.app.capture
        st = self.app.capture_state
        self.cap_status.setText(f"{st}  •  pacotes escritos no teclado: {self.app.lighting.writes}")
        self.cap_btn.setText("Parar captura" if cap.running else "Iniciar captura")

    def refresh_keys(self):
        self.kb.set_keys(self.app.keys)
