from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QLabel, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon, QTabWidget

from ..controller import Controller
from .lighting_tab import CalibrationDialog, LightingTab
from .macro_tab import MacroTab
from .zones_tab import ZonesTab


class MainWindow(QMainWindow):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.cfg = ctl.cfg
        self.setWindowTitle("Surara Control — Redragon Surara PRO")
        self.setWindowIcon(QIcon.fromTheme("input-keyboard"))
        self.resize(1200, 760)
        self._really_quit = False

        self.tabs = QTabWidget()
        self.lighting = LightingTab(self.cfg, ctl)
        self.zones = ZonesTab(self.cfg, ctl)
        self.macros = MacroTab(self.cfg)
        self.tabs.addTab(self.lighting, "Iluminação")
        self.tabs.addTab(self.zones, "Espaços de tela")
        self.tabs.addTab(self.macros, "Macros")
        self.setCentralWidget(self.tabs)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)

        # sinais
        self.lighting.changed.connect(self.schedule_save)
        self.lighting.colorsChanged.connect(ctl.lighting.colors_changed)
        self.lighting.modeChanged.connect(ctl.lighting.mode_changed)
        self.lighting.layoutChanged.connect(self._layout_changed)
        self.lighting.calibrateRequested.connect(self._calibrate)
        self.zones.changed.connect(self.schedule_save)
        self.zones.ambientToggled.connect(self._set_ambient)
        self.zones.captureRequested.connect(self._capture)
        self.zones.reselectRequested.connect(lambda: self._restart_capture(True))
        self.macros.changed.connect(self.schedule_save)
        self.macros.engineToggled.connect(self._set_macros)

        # salvar com atraso (agrupa várias mudanças)
        self.save_timer = QTimer(self, singleShot=True, interval=600)
        self.save_timer.timeout.connect(self.cfg.save)
        # atualização periódica da UI
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._n_streams = -1

        self._setup_tray()

    # ------------------------------------------------------------------ bandeja
    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon.fromTheme("input-keyboard"), self)
        menu = QMenu()
        show = QAction("Mostrar janela", self)
        show.triggered.connect(self._show)
        self.act_amb = QAction("Espaços de tela", self, checkable=True)
        self.act_amb.setChecked(bool(self.cfg["ambient"]["enabled"]))
        self.act_amb.toggled.connect(self.zones.enable.setChecked)
        self.act_mac = QAction("Macros", self, checkable=True)
        self.act_mac.setChecked(bool(self.cfg["macros_enabled"]))
        self.act_mac.toggled.connect(self.macros.enable.setChecked)
        quit_ = QAction("Sair", self)
        quit_.triggered.connect(self.quit)
        for a in (show, None, self.act_amb, self.act_mac, None, quit_):
            menu.addSeparator() if a is None else menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Surara Control")
        self.tray.show()
        self._tray_menu = menu

    def _show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if self.tray and not self._really_quit:
            e.ignore()
            self.hide()
            return
        self.cfg.save()
        self.ctl.shutdown()
        e.accept()

    def quit(self):
        self._really_quit = True
        self.close()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ------------------------------------------------------------------ ações
    def schedule_save(self):
        self.save_timer.start()

    def _set_ambient(self, on):
        self.ctl.set_ambient(on)
        if self.tray:
            self.act_amb.blockSignals(True)
            self.act_amb.setChecked(on)
            self.act_amb.blockSignals(False)
        self.schedule_save()

    def _set_macros(self, on):
        self.ctl.set_macros(on)
        if self.tray:
            self.act_mac.blockSignals(True)
            self.act_mac.setChecked(on)
            self.act_mac.blockSignals(False)
        self.schedule_save()

    def _capture(self, start):
        if start:
            self.ctl.capture.start()
        else:
            self.ctl.capture.stop()

    def _restart_capture(self, reselect):
        self.ctl.restart_capture(reselect)
        self.schedule_save()

    def _layout_changed(self):
        self.ctl.rebuild_keys()
        self.lighting.refresh_keys()
        self.zones.refresh_keys()

    def _calibrate(self):
        if self.cfg["led_map"] and QMessageBox.question(
                self, "Calibrar", "Já existe uma calibração salva. Começar uma nova? "
                                  "(teclas não identificadas mantêm o mapeamento atual)") \
                != QMessageBox.StandardButton.Yes:
            return
        d = CalibrationDialog(self.ctl, self)
        if d.exec():
            self.cfg.save()
            self._layout_changed()

    # ------------------------------------------------------------------ periódico
    def _tick(self):
        ctl = self.ctl
        if ctl.save_pending:
            ctl.save_pending = False
            self.schedule_save()
        if self._n_streams != len(ctl.capture.streams):
            self._n_streams = len(ctl.capture.streams)
            self.zones.refresh_monitors()
        if self.isVisible():
            current = self.tabs.currentWidget()
            if current is self.zones:
                self.zones.tick()
            elif current is self.lighting and self.cfg["ambient"]["enabled"]:
                self.lighting.kb.update()
        self.lighting.status.setText(f"{ctl.lighting.status}  •  pacotes escritos: {ctl.lighting.writes}")
        st = ctl.macros.status if ctl.macros else "Parado"
        if ctl.last_macro:
            st += f"  •  última macro: {ctl.last_macro}"
        self.macros.status.setText(st)
        # o motor pode ter sido desligado pela combinação de emergência
        if self.macros.enable.isChecked() != bool(self.cfg["macros_enabled"]):
            self.macros.enable.blockSignals(True)
            self.macros.enable.setChecked(bool(self.cfg["macros_enabled"]))
            self.macros.enable.blockSignals(False)
        self.status.setText(f"Teclado: {ctl.lighting.status}   |   Captura: {ctl.capture_state}   |   "
                            f"Macros: {st}")
