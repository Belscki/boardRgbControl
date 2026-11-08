"""Surara Control — RGB, espaços de tela e macros para o Redragon Surara PRO no Linux.

Uso:
    python -m surara                 abre a interface gráfica
    python -m surara --minimized     inicia direto na bandeja (para autostart)
    python -m surara daemon          roda macros/espaços/cores sem interface
    python -m surara apply           aplica cores/efeito salvos e sai
    python -m surara flashtest write|check   teste: as cores sobrevivem a desconectar?
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from .config import CONFIG_DIR, Config

FLASHTEST = os.path.join(CONFIG_DIR, "flashtest.bin")


def cmd_flashtest(action: str):
    from .hid import NUM_LEDS, EVisionKeyboard
    kb = EVisionKeyboard()
    if action == "write":
        pat = bytearray()
        for i in range(NUM_LEDS):
            pat += bytes([i * 2 % 256, 255 - i * 2 % 256, 0x5A])
        os.makedirs(CONFIG_DIR, exist_ok=True)
        open(FLASHTEST + ".orig", "wb").write(kb.read_colors())
        kb.write_colors(pat)
        open(FLASHTEST, "wb").write(pat)
        print("Padrão gravado (sem comando de salvar). Desconecte e reconecte o teclado e rode:\n"
              "    python -m surara flashtest check")
    else:
        pat = open(FLASHTEST, "rb").read()
        now = kb.read_colors()
        if now == pat:
            print("O padrão SOBREVIVEU à reconexão → as cores são gravadas na flash a cada escrita.\n"
                  "Mantenha limites baixos no modo espaços de tela.")
        else:
            print("O padrão NÃO sobreviveu → as escritas ficam só na RAM; atualizar rápido é seguro.")
        try:
            kb.write_colors(open(FLASHTEST + ".orig", "rb").read())
        except OSError:
            pass


def cmd_apply():
    from .controller import Controller
    cfg = Config()
    cfg["macros_enabled"] = False
    cfg["ambient"]["enabled"] = False
    ctl = Controller(cfg)
    ctl.lighting.mode_changed()
    time.sleep(1.5)
    print(ctl.lighting.status)
    ctl.shutdown()


def cmd_daemon():
    from gi.repository import GLib  # noqa: F401  (garante GLib disponível)
    from .controller import Controller
    cfg = Config()
    ctl = Controller(cfg)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    print("Surara Control (daemon) rodando. Ctrl+C para sair.")
    last = ""
    while not stop:
        time.sleep(0.5)
        if ctl.save_pending:
            ctl.save_pending = False
            cfg.save()
        st = f"teclado: {ctl.lighting.status} | captura: {ctl.capture_state} | macros: {ctl.macro_status}"
        if st != last:
            print(st)
            last = st
    ctl.shutdown()


def cmd_gui(minimized: bool):
    from PySide6.QtWidgets import QApplication
    from .controller import Controller
    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("surara-control")
    app.setDesktopFileName("surara-control")
    app.setQuitOnLastWindowClosed(False)
    cfg = Config()
    ctl = Controller(cfg)
    win = MainWindow(ctl)
    if not minimized or not win.tray:
        win.show()
    signal.signal(signal.SIGINT, lambda *_: win.quit())
    code = app.exec()
    if not win._really_quit:
        cfg.save()
        ctl.shutdown()
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(prog="surara", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="gui", choices=["gui", "daemon", "apply", "flashtest"])
    ap.add_argument("action", nargs="?", choices=["write", "check"])
    ap.add_argument("--minimized", action="store_true", help="iniciar na bandeja")
    a = ap.parse_args()
    if a.command == "flashtest":
        cmd_flashtest(a.action or "check")
    elif a.command == "apply":
        cmd_apply()
    elif a.command == "daemon":
        cmd_daemon()
    else:
        cmd_gui(a.minimized)


if __name__ == "__main__":
    main()
