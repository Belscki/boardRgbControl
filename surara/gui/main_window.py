from __future__ import annotations

import json
import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from .. import profiles
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

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 0)
        root.addLayout(self._build_profile_bar())
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._build_tabs()

        # salvar com atraso (agrupa várias mudanças)
        self.save_timer = QTimer(self, singleShot=True, interval=600)
        self.save_timer.timeout.connect(self.cfg.save)
        # atualização periódica da UI
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.dirty_timer = QTimer(self, interval=700)
        self.dirty_timer.timeout.connect(self._update_dirty)
        self.dirty_timer.start()
        self._n_streams = -1

        self._setup_tray()
        self._refresh_profiles()

    # ------------------------------------------------------------------ abas
    def _build_tabs(self):
        """(Re)cria as abas a partir do config — usado ao carregar um perfil."""
        ctl = self.ctl
        current = self.tabs.currentIndex()
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        self.lighting = LightingTab(self.cfg, ctl)
        self.zones = ZonesTab(self.cfg, ctl)
        self.macros = MacroTab(self.cfg)
        self.tabs.addTab(self.lighting, "Iluminação")
        self.tabs.addTab(self.zones, "Espaços de tela")
        self.tabs.addTab(self.macros, "Macros")
        if current >= 0:
            self.tabs.setCurrentIndex(current)
        self._n_streams = -1

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

    # ------------------------------------------------------------------ perfis
    def _build_profile_bar(self):
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Perfil:</b>"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.activated.connect(self._profile_chosen)
        bar.addWidget(self.profile_combo)
        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet("color:#e0a000")
        bar.addWidget(self.dirty_label)
        bar.addStretch()
        for txt, tip, fn in (
                ("Salvar", "Salva o estado atual no perfil selecionado", self._profile_save),
                ("Salvar como…", "Cria um novo perfil com o estado atual", self._profile_save_as),
                ("Renomear…", "", self._profile_rename),
                ("Excluir", "", self._profile_delete),
                ("Importar…", "Carrega um perfil de um arquivo .json", self._profile_import),
                ("Exportar…", "Salva o estado atual num arquivo .json", self._profile_export)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            if txt == "Salvar":
                self.btn_save = b
        return bar

    def _refresh_profiles(self):
        names = profiles.list_profiles()
        active = self.cfg["active_profile"]
        if active and active not in names:
            active = self.cfg["active_profile"] = ""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(nenhum perfil)", "")
        for n in names:
            self.profile_combo.addItem(n, n)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(active)))
        self.profile_combo.blockSignals(False)
        if self.tray:
            self._rebuild_tray_profiles(names, active)
        self._update_dirty()

    def _update_dirty(self):
        dirty = profiles.is_dirty(self.cfg)
        self.dirty_label.setText("● alterações não salvas" if dirty else "")
        self.btn_save.setEnabled(bool(self.cfg["active_profile"]) and dirty)

    def _confirm_discard(self) -> bool:
        if not profiles.is_dirty(self.cfg):
            return True
        r = QMessageBox.question(
            self, "Alterações não salvas",
            f"O perfil “{self.cfg['active_profile']}” tem alterações não salvas. Salvar antes de trocar?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            profiles.save(self.cfg, self.cfg["active_profile"])
        return r != QMessageBox.Cancel

    def load_profile(self, name: str):
        if name == self.cfg["active_profile"] and not profiles.is_dirty(self.cfg):
            return
        if not self._confirm_discard():
            self._refresh_profiles()
            return
        if not name:  # "(nenhum perfil)": mantém o estado, só desvincula
            self.cfg["active_profile"] = ""
        else:
            try:
                self.ctl.load_profile(name)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Perfil", f"Não foi possível carregar “{name}”:\n{e}")
                self._refresh_profiles()
                return
            self._build_tabs()
        self.cfg.save()
        self._refresh_profiles()
        self._sync_tray_toggles()
        self.statusBar().showMessage(f"Perfil “{name}” carregado" if name else "Sem perfil", 3000)

    def _profile_chosen(self, idx):
        self.load_profile(self.profile_combo.itemData(idx) or "")

    def _profile_save(self):
        name = self.cfg["active_profile"]
        if not name:
            return self._profile_save_as()
        profiles.save(self.cfg, name)
        self.statusBar().showMessage(f"Perfil “{name}” salvo", 3000)
        self._update_dirty()

    def _ask_name(self, title, default=""):
        name, ok = QInputDialog.getText(self, title, "Nome do perfil:", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if name in profiles.list_profiles() and name != default and QMessageBox.question(
                self, title, f"Já existe um perfil “{name}”. Substituir?") != QMessageBox.StandardButton.Yes:
            return None
        return name

    def _profile_save_as(self):
        name = self._ask_name("Salvar perfil como")
        if not name:
            return
        profiles.save(self.cfg, name)
        self.cfg["active_profile"] = name
        self.cfg.save()
        self._refresh_profiles()
        self.statusBar().showMessage(f"Perfil “{name}” criado", 3000)

    def _profile_rename(self):
        old = self.cfg["active_profile"]
        if not old:
            return
        new = self._ask_name("Renomear perfil", old)
        if not new or new == old:
            return
        profiles.rename(old, new, self.cfg)
        self.cfg.save()
        self._refresh_profiles()

    def _profile_delete(self):
        name = self.cfg["active_profile"]
        if not name or QMessageBox.question(
                self, "Excluir perfil", f"Excluir o perfil “{name}”? (o estado atual do teclado não muda)") \
                != QMessageBox.StandardButton.Yes:
            return
        profiles.delete(name)
        self.cfg["active_profile"] = ""
        self.cfg.save()
        self._refresh_profiles()

    def _profile_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar perfil", os.path.expanduser("~"), "Perfis (*.json)")
        if not path:
            return
        try:
            data = profiles.read(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Importar", f"Arquivo inválido:\n{e}")
            return
        default = data.get("name") or os.path.splitext(os.path.basename(path))[0]
        name = self._ask_name("Importar perfil", default)
        if not name or not self._confirm_discard():
            return
        self.ctl.load_profile(name, data)
        profiles.save(self.cfg, name)
        self._build_tabs()
        self.cfg.save()
        self._refresh_profiles()
        self._sync_tray_toggles()

    def _profile_export(self):
        default = (self.cfg["active_profile"] or "perfil") + ".json"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar perfil", os.path.join(os.path.expanduser("~"), default),
                                              "Perfis (*.json)")
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        name = self.cfg["active_profile"] or os.path.splitext(os.path.basename(path))[0]
        profiles.save(self.cfg, name, path)
        self.statusBar().showMessage(f"Exportado para {path}", 4000)

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
        self.act_amb.toggled.connect(lambda on: self.zones.enable.setChecked(on))
        self.act_mac = QAction("Macros", self, checkable=True)
        self.act_mac.setChecked(bool(self.cfg["macros_enabled"]))
        self.act_mac.toggled.connect(lambda on: self.macros.enable.setChecked(on))
        self.tray_profiles = QMenu("Perfis")
        quit_ = QAction("Sair", self)
        quit_.triggered.connect(self.quit)
        for a in (show, None, self.tray_profiles, None, self.act_amb, self.act_mac, None, quit_):
            if a is None:
                menu.addSeparator()
            elif isinstance(a, QMenu):
                menu.addMenu(a)
            else:
                menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Surara Control")
        self.tray.show()
        self._tray_menu = menu

    def _rebuild_tray_profiles(self, names, active):
        self.tray_profiles.clear()
        group = QActionGroup(self.tray_profiles)
        if not names:
            a = self.tray_profiles.addAction("(nenhum perfil salvo)")
            a.setEnabled(False)
        for n in names:
            a = self.tray_profiles.addAction(n)
            a.setCheckable(True)
            a.setChecked(n == active)
            group.addAction(a)
            a.triggered.connect(lambda _=False, n=n: self.load_profile(n))

    def _sync_tray_toggles(self):
        if not self.tray:
            return
        for act, on in ((self.act_amb, self.cfg["ambient"]["enabled"]), (self.act_mac, self.cfg["macros_enabled"])):
            act.blockSignals(True)
            act.setChecked(bool(on))
            act.blockSignals(False)

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
