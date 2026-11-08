"""Protocolo HID "EVision" usado pelo Redragon Surara PRO (SONiX 0c45:5004).

Pacotes de 64 bytes enviados pela interface 1 (usage page 0xFF1C, report id 0x04):

    [0]    0x04            report id
    [1:3]  checksum        soma (uint16 LE) dos bytes 3..63
    [3]    comando         0x01 begin, 0x02 end, 0x06 set parameter, 0x11 write custom colors
    [4]    tamanho dos dados
    [5:7]  offset (LE)     (para 0x06 é o id do parâmetro)
    [8:]   dados

Baseado na engenharia reversa do projeto OpenRGB (EVisionKeyboardController).
"""
from __future__ import annotations

import glob
import os
import select
import threading
import time

VID = 0x0C45
PID = 0x5004
REPORT_ID = 0x04
NUM_LEDS = 126
CHUNK = 0x36  # 54 bytes = 18 LEDs por pacote

CMD_BEGIN = 0x01
CMD_END = 0x02
CMD_SET_PARAMETER = 0x06
CMD_READ_CUSTOM = 0x10
CMD_WRITE_CUSTOM = 0x11

PARAM_MODE = 0x00
PARAM_BRIGHTNESS = 0x01
PARAM_SPEED = 0x02
PARAM_DIRECTION = 0x03
PARAM_RANDOM = 0x04
PARAM_COLOR = 0x05
PARAM_POLLING = 0x0F

# Efeitos de hardware (nome exibido, valor, usa_cor, usa_velocidade, usa_direcao)
MODE_CUSTOM = 0x14
EFFECTS = [
    ("Personalizado (por tecla)", MODE_CUSTOM, False, False, False),
    ("Estático", 0x06, True, False, False),
    ("Respiração", 0x05, True, True, False),
    ("Ciclo de espectro", 0x04, False, True, False),
    ("Onda de cor (longa)", 0x02, True, True, True),
    ("Onda de cor (curta)", 0x01, True, True, True),
    ("Roda de cores", 0x03, True, True, True),
    ("Arco-íris vertical", 0x0C, True, True, True),
    ("Arco-íris circular", 0x12, False, False, False),
    ("Furacão", 0x0D, True, True, False),
    ("Acumular", 0x0E, True, True, False),
    ("Estrelas", 0x0A, True, True, False),
    ("Florescer", 0x0B, False, True, False),
    ("Visor", 0x10, True, False, False),
    ("Reativo", 0x07, True, True, False),
    ("Reativo ondulação", 0x08, True, True, False),
    ("Reativo linha", 0x09, True, True, False),
]
BRIGHTNESS_MAX = 4
SPEED_FASTEST = 0
SPEED_SLOWEST = 5


class DeviceNotFound(RuntimeError):
    pass


def find_hidraw(vid: int = VID, pid: int = PID) -> str:
    """Encontra o /dev/hidrawN da interface vendor (usage page 0xFF1C)."""
    wanted = f"HID_ID=0003:{vid:08X}:{pid:08X}"
    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device/uevent")) as f:
                if wanted not in f.read().upper():
                    continue
            with open(os.path.join(sys_path, "device/report_descriptor"), "rb") as f:
                desc = f.read()
        except OSError:
            continue
        if b"\x06\x1c\xff" in desc:  # Usage Page (0xFF1C)
            return "/dev/" + os.path.basename(sys_path)
    raise DeviceNotFound("Redragon Surara (0c45:5004) não encontrado")


class EVisionKeyboard:
    def __init__(self, path: str | None = None, signed_checksum: bool = False):
        self.path = path or find_hidraw()
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as e:
            raise PermissionError(
                f"Sem permissão para {self.path}. Instale a regra udev (packaging/70-surara.rules)."
            ) from e
        self.signed_checksum = signed_checksum
        self.lock = threading.Lock()
        self.timeout = 0.25

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    # ------------------------------------------------------------------ baixo nível
    def _checksum(self, buf: bytearray):
        if self.signed_checksum:  # comportamento literal do OpenRGB (char com sinal)
            s = sum(b - 256 if b > 127 else b for b in buf[3:64]) & 0xFFFF
        else:
            s = sum(buf[3:64]) & 0xFFFF
        buf[1] = s & 0xFF
        buf[2] = s >> 8

    def _drain(self):
        while True:
            try:
                os.read(self.fd, 64)
            except (BlockingIOError, OSError):
                return

    def transfer(self, cmd: int, size: int = 0, offset: int = 0, data: bytes = b"") -> bytes | None:
        buf = bytearray(64)
        buf[0] = REPORT_ID
        buf[3] = cmd
        buf[4] = size
        buf[5] = offset & 0xFF
        buf[6] = (offset >> 8) & 0xFF
        buf[8:8 + len(data)] = data
        self._checksum(buf)
        with self.lock:
            self._drain()
            os.write(self.fd, bytes(buf))
            # A mesma interface também envia relatórios de teclas (ids 1..3);
            # espera especificamente a resposta com id 0x04.
            deadline = time.monotonic() + self.timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                r, _, _ = select.select([self.fd], [], [], left)
                if not r:
                    return None
                try:
                    resp = os.read(self.fd, 64)
                except BlockingIOError:
                    continue
                if resp and resp[0] == REPORT_ID:
                    return resp

    # ------------------------------------------------------------------ comandos
    def begin(self):
        return self.transfer(CMD_BEGIN)

    def end(self):
        return self.transfer(CMD_END)

    def set_parameter(self, param: int, data: bytes):
        return self.transfer(CMD_SET_PARAMETER, len(data), param, data)

    def set_mode(self, mode: int, brightness: int = BRIGHTNESS_MAX, speed: int = 3,
                 direction: int = 0, random: bool = False, color=(255, 255, 255)):
        data = bytes([mode, brightness, speed, direction, 1 if random else 0, *color])
        return self.set_parameter(PARAM_MODE, data)

    def set_brightness(self, brightness: int):
        return self.set_parameter(PARAM_BRIGHTNESS, bytes([max(0, min(BRIGHTNESS_MAX, brightness))]))

    def write_colors(self, colors: bytes | bytearray):
        """colors: 126*3 bytes RGB, na ordem dos índices de LED."""
        data = bytes(colors).ljust(NUM_LEDS * 3, b"\0")[: NUM_LEDS * 3]
        ok = True
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            if self.transfer(CMD_WRITE_CUSTOM, len(chunk), off, chunk) is None:
                ok = False
        return ok

    def read_colors(self) -> bytes:
        out = bytearray()
        for off in range(0, NUM_LEDS * 3, CHUNK):
            resp = self.transfer(CMD_READ_CUSTOM, CHUNK, off)
            out += (resp[8:8 + CHUNK] if resp else bytes(CHUNK))
        return bytes(out)
