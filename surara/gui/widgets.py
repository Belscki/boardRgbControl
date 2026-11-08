from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QColorDialog, QLineEdit, QPushButton, QWidget

from ..keymap import MODIFIERS, Key, layout_size, pretty_key
from ..macros import code_name


def qt_event_key(event) -> str | None:
    """Converte um QKeyEvent em nome evdev (o scancode nativo no Linux é evdev + 8)."""
    sc = event.nativeScanCode()
    if sc <= 8:
        return None
    return code_name(sc - 8)


# ----------------------------------------------------------------------------- cor
class ColorButton(QPushButton):
    colorChanged = Signal(QColor)

    def __init__(self, color="#ffffff", parent=None):
        super().__init__(parent)
        self.setFixedWidth(64)
        self._color = QColor(color)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> QColor:
        return self._color

    def setColor(self, c):
        self._color = QColor(c)
        self._refresh()

    def _refresh(self):
        fg = "#000" if self._color.lightness() > 140 else "#fff"
        self.setStyleSheet(f"background:{self._color.name()}; color:{fg}; border:1px solid #555; padding:4px")
        self.setText(self._color.name())

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "Escolher cor")
        if c.isValid():
            self.setColor(c)
            self.colorChanged.emit(c)


# ----------------------------------------------------------------------------- teclado
class KeyboardWidget(QWidget):
    """Desenha o teclado. Clique seleciona, Ctrl+clique soma, arrastar seleciona área.
    Em toggle_mode, cada clique alterna a tecla (usado para atribuir teclas a espaços)."""
    selectionChanged = Signal()
    keyClicked = Signal(str)

    def __init__(self, keys: list[Key], color_fn, toggle_mode=False, parent=None):
        super().__init__(parent)
        self.keys = keys
        self.color_fn = color_fn
        self.toggle_mode = toggle_mode
        self.selected: set[str] = set()
        self.highlight: set[str] = set()
        self._press = None
        self._band: QRectF | None = None
        self.setMinimumSize(560, 200)

    def set_keys(self, keys):
        self.keys = keys
        self.update()

    def _transform(self):
        W, H = layout_size(self.keys)
        m = 8
        s = min((self.width() - 2 * m) / W, (self.height() - 2 * m) / H)
        ox = (self.width() - W * s) / 2
        oy = (self.height() - H * s) / 2
        return s, ox, oy

    def key_rect(self, k: Key) -> QRectF:
        s, ox, oy = self._transform()
        p = max(1.5, s * 0.05)
        return QRectF(ox + k.x * s + p, oy + k.y * s + p, k.w * s - 2 * p, k.h * s - 2 * p)

    def key_at(self, pos) -> Key | None:
        for k in self.keys:
            if self.key_rect(k).contains(QPointF(pos)):
                return k
        return None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1b1f"))
        s, _, _ = self._transform()
        font = QFont(self.font())
        font.setPixelSize(max(8, int(s * 0.26)))
        p.setFont(font)
        seen = set()
        for k in self.keys:
            r = self.key_rect(k)
            c = self.color_fn(k)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 4, 4)
            if k.code in self.selected:
                p.setPen(QPen(QColor("#ffffff"), 3))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
                p.setPen(QPen(QColor("#2a7fff"), 1.5))
                p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 3, 3)
            if k.code in self.highlight:
                p.setPen(QPen(QColor("#ffcc00"), 3, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#000") if c.lightness() > 140 else QColor("#eee"))
            label = k.label if k.led is not None else k.label + "\n(sem LED)"
            p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, label)
            seen.add(k.code)
        if self._band:
            p.setPen(QPen(QColor("#2a7fff"), 1, Qt.DashLine))
            p.setBrush(QColor(42, 127, 255, 40))
            p.drawRect(self._band)

    def mousePressEvent(self, e):
        self._press = e.position()
        self._band = None

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position() - self._press).manhattanLength() > 6:
            self._band = QRectF(self._press, e.position()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        add = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if self._band is not None:
            hit = {k.code for k in self.keys if self.key_rect(k).intersects(self._band)}
            if self.toggle_mode:
                if hit and hit <= self.selected:
                    self.selected -= hit
                else:
                    self.selected |= hit
            else:
                self.selected = (self.selected | hit) if add else hit
            self._band = None
            self.selectionChanged.emit()
        else:
            k = self.key_at(e.position())
            if k:
                if self.toggle_mode or add:
                    self.selected ^= {k.code}
                else:
                    self.selected = {k.code}
                self.keyClicked.emit(k.code)
                self.selectionChanged.emit()
            elif not add and not self.toggle_mode:
                self.selected = set()
                self.selectionChanged.emit()
        self._press = None
        self.update()


# ----------------------------------------------------------------------------- prévia
class ScreenPreview(QWidget):
    """Mostra o quadro capturado e os espaços (retângulos). Arrastar numa área vazia cria
    um espaço; arrastar dentro move; arrastar o canto inferior direito redimensiona."""
    zoneSelected = Signal(int)
    zoneCreated = Signal(list)      # rect normalizado
    zonesChanged = Signal()

    HANDLE = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame: np.ndarray | None = None
        self._img: QImage | None = None
        self.aspect = 16 / 9
        self.zones: list[tuple[int, dict, QColor]] = []   # (índice, zona, cor ao vivo)
        self.current = -1
        self._drag = None
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)

    def set_frame(self, frame):
        self.frame = frame
        if frame is not None:
            h, w, _ = frame.shape
            self.aspect = w / h
            self._img = QImage(frame.data, w, h, 3 * w, QImage.Format_RGB888)
        else:
            self._img = None
        self.update()

    def area(self) -> QRectF:
        W, H = self.width(), self.height()
        if W / H > self.aspect:
            h = H
            w = h * self.aspect
        else:
            w = W
            h = w / self.aspect
        return QRectF((W - w) / 2, (H - h) / 2, w, h)

    def _to_px(self, rect) -> QRectF:
        a = self.area()
        x, y, w, h = rect
        return QRectF(a.x() + x * a.width(), a.y() + y * a.height(), w * a.width(), h * a.height())

    def _to_norm(self, pt: QPointF):
        a = self.area()
        return (min(1, max(0, (pt.x() - a.x()) / a.width())), min(1, max(0, (pt.y() - a.y()) / a.height())))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#111"))
        a = self.area()
        if self._img is not None:
            p.drawImage(a, self._img)
        else:
            p.fillRect(a, QColor("#2a2a30"))
            p.setPen(QColor("#999"))
            p.drawText(a, Qt.AlignCenter, "Sem captura — clique em “Iniciar captura”.\n"
                                          "Você ainda pode desenhar os espaços aqui.")
        for idx, z, live in self.zones:
            r = self._to_px(z["rect"])
            sel = idx == self.current
            p.setBrush(QColor(live.red(), live.green(), live.blue(), 70))
            p.setPen(QPen(QColor("#ffffff") if sel else live, 3 if sel else 2,
                          Qt.SolidLine if z["enabled"] else Qt.DashLine))
            p.drawRect(r)
            p.setPen(QColor("#fff"))
            p.drawText(r.adjusted(4, 2, -2, -2), Qt.AlignLeft | Qt.AlignTop, z["name"])
            if sel:
                p.fillRect(QRectF(r.right() - self.HANDLE, r.bottom() - self.HANDLE, self.HANDLE, self.HANDLE),
                           QColor("#fff"))
        if self._drag and self._drag[0] == "new":
            p.setPen(QPen(QColor("#2a7fff"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self._drag[1], self._drag[2]).normalized())

    def _zone_at(self, pos):
        for idx, z, _ in reversed(self.zones):
            if self._to_px(z["rect"]).contains(pos):
                return idx, z
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        cur = next((z for i, z, _ in self.zones if i == self.current), None)
        if cur is not None:
            r = self._to_px(cur["rect"])
            if abs(pos.x() - r.right()) < self.HANDLE and abs(pos.y() - r.bottom()) < self.HANDLE:
                self._drag = ("resize", cur)
                return
        hit = self._zone_at(pos)
        if hit:
            self.current = hit[0]
            self.zoneSelected.emit(hit[0])
            self._drag = ("move", hit[1], self._to_norm(pos), list(hit[1]["rect"]))
        else:
            self._drag = ("new", pos, pos)
        self.update()

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        pos = e.position()
        kind = self._drag[0]
        if kind == "new":
            self._drag = ("new", self._drag[1], pos)
        elif kind == "move":
            _, z, start, orig = self._drag
            nx, ny = self._to_norm(pos)
            dx, dy = nx - start[0], ny - start[1]
            z["rect"][0] = min(1 - orig[2], max(0, orig[0] + dx))
            z["rect"][1] = min(1 - orig[3], max(0, orig[1] + dy))
        elif kind == "resize":
            z = self._drag[1]
            nx, ny = self._to_norm(pos)
            z["rect"][2] = max(0.005, nx - z["rect"][0])
            z["rect"][3] = max(0.005, ny - z["rect"][1])
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            kind = self._drag[0]
            if kind == "new":
                a, b = self._to_norm(self._drag[1]), self._to_norm(e.position())
                x0, y0 = min(a[0], b[0]), min(a[1], b[1])
                w, h = abs(a[0] - b[0]), abs(a[1] - b[1])
                if w > 0.01 and h > 0.01:
                    self.zoneCreated.emit([x0, y0, w, h])
            else:
                self.zonesChanged.emit()
        self._drag = None
        self.update()


# ----------------------------------------------------------------------------- captura de tecla
class KeyCaptureEdit(QLineEdit):
    """Campo que grava uma combinação (ex.: Ctrl+Shift+F1) ou uma tecla única."""
    captured = Signal(list)

    def __init__(self, single=False, parent=None):
        super().__init__(parent)
        self.single = single
        self.setReadOnly(True)
        self.setPlaceholderText("Clique e pressione a tecla" if single else "Clique e pressione a combinação")
        self.keys: list[str] = []
        self._held: list[str] = []

    def set_keys(self, keys):
        self.keys = list(keys)
        self.setText(" + ".join(pretty_key(k) for k in self.keys))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._held = []
        self.setText("… pressione …")
        self.grabKeyboard()

    def focusOutEvent(self, e):
        self.releaseKeyboard()
        self.set_keys(self.keys)
        super().focusOutEvent(e)

    def event(self, e):
        # impede que Tab mude o foco durante a captura
        if e.type() == e.Type.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        name = qt_event_key(e)
        if not name:
            return
        if self.single:
            self._finish([name])
            return
        if name in MODIFIERS:
            if name not in self._held:
                self._held.append(name)
            self.setText(" + ".join(pretty_key(k) for k in self._held) + " + …")
            return
        self._finish(self._held + [name])

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat() or self.single:
            return
        name = qt_event_key(e)
        # só modificadores e soltou: usa o próprio modificador como gatilho
        if name in MODIFIERS and self._held and self._held[-1] == name:
            self._finish(self._held)

    def _finish(self, keys):
        self.set_keys(keys)
        self.captured.emit(self.keys)
        self.clearFocus()
