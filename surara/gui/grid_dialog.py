from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget)

from .. import grid
METHODS = [("average", "Média"), ("vivid", "Cor mais viva"), ("dominant", "Cor predominante")]


class GridDialog(QDialog):
    """Configura a grade: modo, linhas × colunas, área do monitor e teclas incluídas."""

    def __init__(self, keys, selected: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gerar grade de espaços")
        self.keys = keys
        self.selected = selected
        outer = QVBoxLayout(self)

        intro = QLabel("Divide o monitor atual em regiões e liga cada uma às teclas que estão na mesma "
                       "posição no teclado (canto superior esquerdo da tela → Esc, inferior direito → "
                       "Enter do numérico). Os espaços gerados podem ser editados depois.")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        f = QFormLayout()
        outer.addLayout(f)

        self.mode = QComboBox()
        self.mode.addItem("Grade (linhas × colunas)", "grid")
        self.mode.addItem("Uma região por tecla (máximo detalhe)", "perkey")
        self.mode.currentIndexChanged.connect(self._update)
        f.addRow("Modo:", self.mode)

        rc = QWidget()
        rl = QHBoxLayout(rc)
        rl.setContentsMargins(0, 0, 0, 0)
        self.rows = QSpinBox()
        self.rows.setRange(1, 12)
        self.rows.setValue(6)
        self.cols = QSpinBox()
        self.cols.setRange(1, 40)
        self.cols.setValue(12)
        for w in (self.rows, self.cols):
            w.valueChanged.connect(self._update)
        rl.addWidget(self.rows)
        rl.addWidget(QLabel("linhas ×"))
        rl.addWidget(self.cols)
        rl.addWidget(QLabel("colunas"))
        rl.addStretch()
        self.rc_label = QLabel("Tamanho:")
        f.addRow(self.rc_label, rc)

        self.include = QComboBox()
        self.include.addItem("Teclado inteiro", "all")
        self.include.addItem("Só o bloco principal (sem setas/numérico)", "main")
        self.include.addItem(f"Só as teclas selecionadas no desenho ({len(selected)})", "selected")
        self.include.currentIndexChanged.connect(self._update)
        f.addRow("Teclas:", self.include)

        area = QWidget()
        al = QHBoxLayout(area)
        al.setContentsMargins(0, 0, 0, 0)
        self.area = []
        for label, val in (("x", 0), ("y", 0), ("larg.", 100), ("alt.", 100)):
            s = QDoubleSpinBox()
            s.setRange(0, 100)
            s.setDecimals(1)
            s.setSuffix(" %")
            s.setValue(val)
            al.addWidget(QLabel(label))
            al.addWidget(s)
            self.area.append(s)
        f.addRow("Área do monitor:", area)

        style = QLabel("Os espaços gerados seguem os ajustes globais (cálculo da cor, suavização, "
                       "saturação e intensidade).")
        style.setWordWrap(True)
        style.setStyleSheet("color:#888")
        f.addRow(style)

        self.replace = QCheckBox("Substituir a grade gerada anteriormente")
        self.replace.setChecked(True)
        f.addRow("", self.replace)
        note = QLabel("As teclas da grade saem dos outros espaços (cada tecla pertence a um só).")
        note.setStyleSheet("color:#888")
        f.addRow(note)

        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight:bold")
        f.addRow(self.summary)

        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("Gerar")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        f.addRow(self.bb)
        self.setMinimumWidth(580)
        self._update()

    def _keys(self):
        return grid.select_keys(self.keys, self.include.currentData(), self.selected)

    def _area(self):
        x, y, w, h = (s.value() / 100 for s in self.area)
        return [x, y, max(0.01, min(w, 1 - x)), max(0.01, min(h, 1 - y))]

    def _update(self):
        perkey = self.mode.currentData() == "perkey"
        self.rows.setEnabled(not perkey)
        self.cols.setEnabled(not perkey)
        n = len(self.generate({}))
        self.summary.setText(f"Serão criados {n} espaço(s) com {len(self._keys())} tecla(s).")
        self.bb.button(QDialogButtonBox.Ok).setEnabled(n > 0)

    def generate(self, base: dict) -> list[dict]:
        return grid.generate(self._keys(), self.mode.currentData(), self.rows.value(), self.cols.value(),
                             self._area(), base)

    def base(self) -> dict:
        return {"custom": False}
