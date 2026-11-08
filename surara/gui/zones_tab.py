from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from ..config import ZONE_DEFAULT
from .widgets import KeyboardWidget, ScreenPreview

METHODS = [("average", "Média"), ("vivid", "Cor mais viva"), ("dominant", "Cor predominante")]
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

        self.props = QGroupBox("Propriedades do espaço")
        f = QFormLayout(self.props)
        self.name = QLineEdit()
        self.name.textEdited.connect(self._edited)
        self.z_en = QCheckBox("Ativado")
        self.z_en.toggled.connect(self._edited)
        self.method = QComboBox()
        for k, label in METHODS:
            self.method.addItem(label, k)
        self.method.currentIndexChanged.connect(self._edited)
        self.smooth = QSlider(Qt.Horizontal)
        self.smooth.setRange(0, 95)
        self.smooth.valueChanged.connect(self._edited)
        self.sat = QDoubleSpinBox()
        self.sat.setRange(0, 3)
        self.sat.setSingleStep(0.1)
        self.sat.valueChanged.connect(self._edited)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0, 3)
        self.gain.setSingleStep(0.1)
        self.gain.valueChanged.connect(self._edited)
        self.swatch = QLabel()
        self.swatch.setFixedHeight(22)
        f.addRow("Nome:", self.name)
        f.addRow("", self.z_en)
        f.addRow("Cálculo da cor:", self.method)
        f.addRow("Suavização:", self.smooth)
        f.addRow("Saturação:", self.sat)
        f.addRow("Intensidade:", self.gain)
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
            self.list.addItem(f"{'✔' if z['enabled'] else '✖'}  {z['name']}  ({len(z['keys'])} teclas)")
        self.list.blockSignals(False)
        n = len(self.cfg["zones"])
        row = -1 if not n else min(select if select is not None else 0, n - 1)
        self.list.setCurrentRow(row)
        self._select(row)

    def _refresh_item(self):
        if 0 <= self.cur < len(self.cfg["zones"]):
            z = self.cfg["zones"][self.cur]
            self.list.item(self.cur).setText(f"{'✔' if z['enabled'] else '✖'}  {z['name']}  ({len(z['keys'])} teclas)")

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
        self.method.setCurrentIndex([k for k, _ in METHODS].index(z["method"]))
        self.smooth.setValue(int(float(z["smoothing"]) * 100))
        self.sat.setValue(float(z["saturation"]))
        self.gain.setValue(float(z["gain"]))
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

    # ----------------------------------------------------------------- edição
    def _edited(self, *_):
        if self._loading or not 0 <= self.cur < len(self.cfg["zones"]):
            return
        z = self.cfg["zones"][self.cur]
        z["name"] = self.name.text()
        z["enabled"] = self.z_en.isChecked()
        z["method"] = self.method.currentData()
        z["smoothing"] = self.smooth.value() / 100
        z["saturation"] = self.sat.value()
        z["gain"] = self.gain.value()
        self._refresh_item()
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
            self.list.item(i).setText(f"{'✔' if z['enabled'] else '✖'}  {z['name']}  ({len(z['keys'])} teclas)")
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
