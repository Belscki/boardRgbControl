from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget, QGridLayout)

from ..hid import BRIGHTNESS_MAX, EFFECTS, MODE_CUSTOM, NUM_LEDS, SPEED_SLOWEST
from ..keymap import build_layout
from .widgets import ColorButton, KeyboardWidget, qt_event_key


class LightingTab(QWidget):
    changed = Signal()          # config mudou (salvar)
    colorsChanged = Signal()    # cores por tecla mudaram
    modeChanged = Signal()      # efeito/brilho mudou
    layoutChanged = Signal()
    calibrateRequested = Signal()

    def __init__(self, cfg, app, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.app = app
        root = QVBoxLayout(self)

        self.kb = KeyboardWidget(app.keys, self._key_color)
        self.kb.selectionChanged.connect(self._sel_changed)
        root.addWidget(self.kb, 1)

        # ---- cores por tecla
        colors = QGroupBox("Cores por tecla (modo Personalizado)")
        cl = QHBoxLayout(colors)
        self.sel_label = QLabel("Nenhuma tecla selecionada")
        self.color = ColorButton("#ff0000")
        b_apply = QPushButton("Pintar selecionadas")
        b_apply.clicked.connect(self._paint)
        b_clear = QPushButton("Remover cor (usar base)")
        b_clear.clicked.connect(self._clear_color)
        b_all = QPushButton("Selecionar todas")
        b_all.clicked.connect(self._select_all)
        self.base = ColorButton(cfg["base_color"])
        self.base.colorChanged.connect(self._base_changed)
        b_reset = QPushButton("Resetar todas")
        b_reset.clicked.connect(self._reset_all)
        cl.addWidget(self.sel_label, 1)
        cl.addWidget(QLabel("Cor:"))
        cl.addWidget(self.color)
        cl.addWidget(b_apply)
        cl.addWidget(b_clear)
        cl.addWidget(b_all)
        cl.addSpacing(16)
        cl.addWidget(QLabel("Cor base:"))
        cl.addWidget(self.base)
        cl.addWidget(b_reset)
        root.addWidget(colors)

        # ---- efeito
        eff = QGroupBox("Efeito / brilho")
        g = QGridLayout(eff)
        e = cfg["effect"]
        self.effect = QComboBox()
        for name, val, *_ in EFFECTS:
            self.effect.addItem(name, val)
        self.effect.setCurrentIndex(max(0, self.effect.findData(e["mode"])))
        self.bright = QSlider(Qt.Horizontal)
        self.bright.setRange(0, BRIGHTNESS_MAX)
        self.bright.setValue(int(cfg["brightness"]))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(0, SPEED_SLOWEST)
        self.speed.setValue(SPEED_SLOWEST - int(e["speed"]))  # direita = mais rápido
        self.direction = QComboBox()
        self.direction.addItems(["Direção 1 (esq./cima)", "Direção 2 (dir./baixo)"])
        self.direction.setCurrentIndex(int(e["direction"]) & 1)
        self.eff_color = ColorButton(e["color"])
        self.random = QCheckBox("Cores aleatórias")
        self.random.setChecked(bool(e["random"]))
        g.addWidget(QLabel("Efeito:"), 0, 0)
        g.addWidget(self.effect, 0, 1)
        g.addWidget(QLabel("Brilho:"), 0, 2)
        g.addWidget(self.bright, 0, 3)
        g.addWidget(QLabel("Velocidade:"), 0, 4)
        g.addWidget(self.speed, 0, 5)
        g.addWidget(self.direction, 1, 1)
        g.addWidget(QLabel("Cor do efeito:"), 1, 2)
        g.addWidget(self.eff_color, 1, 3)
        g.addWidget(self.random, 1, 4)
        for w in (self.effect, self.direction):
            w.currentIndexChanged.connect(self._effect_changed)
        for w in (self.bright, self.speed):
            w.sliderReleased.connect(self._effect_changed)
            w.valueChanged.connect(lambda _v, w=w: (not w.isSliderDown()) and self._effect_changed())
        self.eff_color.colorChanged.connect(self._effect_changed)
        self.random.toggled.connect(self._effect_changed)
        root.addWidget(eff)

        # ---- teclado / calibração
        bottom = QHBoxLayout()
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Layout ABNT2", "abnt2")
        self.layout_combo.addItem("Layout ANSI (US)", "ansi")
        self.layout_combo.setCurrentIndex(0 if cfg["layout"] == "abnt2" else 1)
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        calib = QPushButton("Calibrar LEDs…")
        calib.clicked.connect(self.calibrateRequested.emit)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#888")
        bottom.addWidget(self.layout_combo)
        bottom.addWidget(calib)
        bottom.addWidget(self.status, 1)
        root.addLayout(bottom)
        self._update_effect_widgets()

    # ----------------------------------------------------------------
    def _key_color(self, k) -> QColor:
        live = self.app.lighting.zone_colors if self.cfg["ambient"]["enabled"] else {}
        if k.code in live:
            return QColor(*live[k.code])
        return QColor(self.cfg["key_colors"].get(k.code, self.cfg["base_color"]))

    def _sel_changed(self):
        n = len(self.kb.selected)
        self.sel_label.setText(f"{n} tecla(s) selecionada(s)" if n else
                               "Clique/arraste para selecionar teclas (Ctrl soma)")
        if n == 1:
            code = next(iter(self.kb.selected))
            if code in self.cfg["key_colors"]:
                self.color.setColor(self.cfg["key_colors"][code])

    def _paint(self):
        if not self.kb.selected:
            return
        for code in self.kb.selected:
            self.cfg["key_colors"][code] = self.color.color().name()
        self._colors_done()

    def _clear_color(self):
        for code in self.kb.selected:
            self.cfg["key_colors"].pop(code, None)
        self._colors_done()

    def _select_all(self):
        self.kb.selected = {k.code for k in self.app.keys}
        self.kb.update()
        self._sel_changed()

    def _base_changed(self, c):
        self.cfg["base_color"] = c.name()
        self._colors_done()

    def _reset_all(self):
        if QMessageBox.question(self, "Resetar", "Remover a cor de todas as teclas (ficam com a cor base)?") \
                == QMessageBox.StandardButton.Yes:
            self.cfg["key_colors"] = {}
            self._colors_done()

    def _colors_done(self):
        if self.cfg["effect"]["mode"] != MODE_CUSTOM:
            self.effect.setCurrentIndex(self.effect.findData(MODE_CUSTOM))  # dispara _effect_changed
        self.kb.update()
        self.colorsChanged.emit()
        self.changed.emit()

    def _update_effect_widgets(self):
        idx = self.effect.currentIndex()
        _, _, has_color, has_speed, has_dir = EFFECTS[idx]
        self.eff_color.setEnabled(has_color)
        self.random.setEnabled(has_color)
        self.speed.setEnabled(has_speed)
        self.direction.setEnabled(has_dir)

    def _effect_changed(self, *_):
        e = self.cfg["effect"]
        e["mode"] = self.effect.currentData()
        e["speed"] = SPEED_SLOWEST - self.speed.value()
        e["direction"] = self.direction.currentIndex()
        e["color"] = self.eff_color.color().name()
        e["random"] = self.random.isChecked()
        self.cfg["brightness"] = self.bright.value()
        self._update_effect_widgets()
        self.modeChanged.emit()
        self.changed.emit()

    def _layout_changed(self):
        self.cfg["layout"] = self.layout_combo.currentData()
        self.layoutChanged.emit()
        self.changed.emit()

    def refresh_keys(self):
        self.kb.set_keys(self.app.keys)


class CalibrationDialog(QDialog):
    """Acende um LED por vez; o usuário pressiona (ou clica) a tecla que acendeu."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Calibrar LEDs")
        self.keys = build_layout(app.cfg["layout"])  # layout limpo, sem correções
        self.assign: dict[int, str | None] = {}       # led -> código (None = sem tecla)
        self.led = 0
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.kb = KeyboardWidget(self.keys, self._color)
        self.kb.keyClicked.connect(self._assign)
        self.kb.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(self.info)
        lay.addWidget(self.kb, 1)
        row = QHBoxLayout()
        for txt, fn in (("← Voltar", self._back), ("Nenhuma tecla / pular →", lambda: self._assign(None)),
                        ("Concluir e salvar", self._finish), ("Cancelar", self.reject)):
            b = QPushButton(txt)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.resize(1000, 480)
        self._show()

    def _color(self, k):
        for led, code in self.assign.items():
            if code == k.code:
                return QColor("#2e7d32")
        return QColor("#444")

    def _show(self):
        frame = bytearray(bytes([8, 8, 8]) * NUM_LEDS)
        frame[self.led * 3:self.led * 3 + 3] = b"\xff\xff\xff"
        self.app.lighting.set_override(bytes(frame))
        self.info.setText(
            f"<b>LED {self.led} de {NUM_LEDS - 1}</b> está aceso em branco no teclado.<br>"
            "Pressione essa tecla no teclado <i>ou</i> clique nela no desenho. Se nada acendeu, "
            "clique em “Nenhuma tecla / pular”. Teclas verdes já foram identificadas. "
            "(Fn e teclas capturadas pelo KDE: clique no desenho.)")
        self.kb.highlight = {self.assign[self.led]} if self.assign.get(self.led) else set()
        self.kb.update()

    def _assign(self, code):
        if code:
            for led, c in list(self.assign.items()):
                if c == code:
                    del self.assign[led]
        self.assign[self.led] = code
        if self.led < NUM_LEDS - 1:
            self.led += 1
            self._show()
        else:
            self._finish()

    def _back(self):
        if self.led > 0:
            self.led -= 1
            self._show()

    def showEvent(self, e):
        super().showEvent(e)
        self.grabKeyboard()

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        name = qt_event_key(e)
        if name and any(k.code == name for k in self.keys):
            self._assign(name)

    def _finish(self):
        found = {code: led for led, code in self.assign.items() if code}
        overrides = dict(self.app.cfg["led_map"])
        claimed = set(found.values())
        for k in self.keys:
            if k.code in found:
                overrides[k.code] = found[k.code]
            elif k.led in claimed:
                overrides[k.code] = None   # LED padrão pertence a outra tecla
        self.app.cfg["led_map"] = overrides
        self.accept()

    def done(self, r):
        self.releaseKeyboard()
        self.app.lighting.set_override(None)
        super().done(r)
