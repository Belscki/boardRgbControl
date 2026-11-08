"""Captura de tela no Wayland via xdg-desktop-portal (ScreenCast) + PipeWire/GStreamer.

Na primeira vez o KDE mostra um diálogo para escolher os monitores; depois disso o
restore_token salvo na config faz a sessão ser restaurada sem perguntar.
Os quadros são reduzidos (ex.: 320 px de largura) — suficiente para médias de cor.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import numpy as np

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from dbus_next import BusType, Message, MessageType, Variant  # noqa: E402
from dbus_next.aio import MessageBus  # noqa: E402

Gst.init(None)

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SC_IFACE = "org.freedesktop.portal.ScreenCast"


class Stream:
    def __init__(self, node_id: int, props: dict, width: int):
        self.node_id = node_id
        pos = props.get("position")
        size = props.get("size")
        self.position = tuple(pos.value) if pos else (0, 0)
        self.size = tuple(size.value) if size else (1920, 1080)
        self.width = width
        self.height = max(2, round(width * self.size[1] / max(1, self.size[0])) // 2 * 2)
        self.frame: np.ndarray | None = None
        self.frame_time = 0.0
        self.pipeline = None

    def describe(self) -> str:
        return f"{self.size[0]}x{self.size[1]} em ({self.position[0]}, {self.position[1]})"


class ScreenCapture:
    def __init__(self, restore_token: str = "", width: int = 320, on_token=None, on_state=None):
        self.restore_token = restore_token
        self.width = width
        self.on_token = on_token      # callback(token) para salvar na config
        self.on_state = on_state      # callback(texto)
        self.streams: list[Stream] = []
        self.running = False
        self.error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._readers: list[threading.Thread] = []
        self._fd = -1

    # ----------------------------------------------------------------- público
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.error = None
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="portal")
        self._thread.start()

    def stop(self):
        self.running = False
        for s in self.streams:
            if s.pipeline:
                s.pipeline.set_state(Gst.State.NULL)
                s.pipeline = None
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._fd >= 0:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        self.streams = []
        self._state("Captura parada")

    def get_frame(self, idx: int) -> np.ndarray | None:
        if 0 <= idx < len(self.streams):
            return self.streams[idx].frame
        return None

    def find_stream(self, position) -> int | None:
        if position is None:
            return None
        for i, s in enumerate(self.streams):
            if list(s.position) == list(position):
                return i
        return None

    # ----------------------------------------------------------------- interno
    def _state(self, txt: str):
        if self.on_state:
            self.on_state(txt)

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._open_session())
            self._loop.run_forever()  # mantém a sessão do portal viva
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.running = False
            self._state(f"Falha na captura: {e}")
        finally:
            self._loop.close()
            self._loop = None

    async def _open_session(self):
        self._state("Abrindo sessão de captura (confirme no diálogo do KDE se aparecer)…")
        bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()
        self._bus = bus
        sender = bus.unique_name[1:].replace(".", "_")
        counter = [0]

        async def call(method, signature, body):
            reply = await bus.call(Message(destination=PORTAL, path=PORTAL_PATH, interface=SC_IFACE,
                                           member=method, signature=signature, body=body))
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError(f"{method}: {reply.error_name} {reply.body}")
            return reply

        async def request(method, signature, args, options):
            counter[0] += 1
            token = f"surara{os.getpid()}_{counter[0]}"
            path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
            fut = asyncio.get_running_loop().create_future()

            def handler(msg):
                if (msg.message_type == MessageType.SIGNAL and msg.path == path
                        and msg.member == "Response" and not fut.done()):
                    fut.set_result(msg.body)

            bus.add_message_handler(handler)
            await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                   interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                                   body=[f"type='signal',interface='org.freedesktop.portal.Request',"
                                         f"member='Response',path='{path}'"]))
            options = dict(options)
            options["handle_token"] = Variant("s", token)
            await call(method, signature, [*args, options])
            code, results = await fut
            bus.remove_message_handler(handler)
            if code != 0:
                raise RuntimeError(f"{method} cancelado/negado (código {code})")
            return results

        res = await request("CreateSession", "a{sv}", [],
                            {"session_handle_token": Variant("s", f"surara_s{os.getpid()}")})
        session = res["session_handle"].value

        opts = {
            "types": Variant("u", 1),          # monitores
            "multiple": Variant("b", True),
            "cursor_mode": Variant("u", 1),    # sem cursor
            "persist_mode": Variant("u", 2),   # lembrar até ser revogado
        }
        if self.restore_token:
            opts["restore_token"] = Variant("s", self.restore_token)
        await request("SelectSources", "oa{sv}", [session], opts)
        res = await request("Start", "osa{sv}", [session, ""], {})

        token = res.get("restore_token")
        if token and self.on_token:
            self.restore_token = token.value
            self.on_token(token.value)

        streams = res["streams"].value
        reply = await call("OpenPipeWireRemote", "oa{sv}", [session, {}])
        fd = reply.body[0]
        if reply.unix_fds:
            fd = reply.unix_fds[fd] if isinstance(fd, int) and fd < len(reply.unix_fds) else reply.unix_fds[0]
        self._fd = fd

        self.streams = [Stream(node, props, self.width) for node, props in streams]
        # ordena por posição (esquerda→direita, cima→baixo) para índices estáveis
        self.streams.sort(key=lambda s: (s.position[1], s.position[0]))
        for s in self.streams:
            self._start_pipeline(s)
        self.running = True
        self._state(f"Capturando {len(self.streams)} monitor(es)")

    def _start_pipeline(self, s: Stream):
        desc = (f"pipewiresrc fd={os.dup(self._fd)} path={s.node_id} always-copy=true do-timestamp=true ! "
                f"video/x-raw ! videoscale method=1 ! video/x-raw,width={s.width},height={s.height} ! "
                f"videoconvert ! video/x-raw,format=RGB ! "
                f"appsink name=sink drop=true max-buffers=1 sync=false emit-signals=false")
        s.pipeline = Gst.parse_launch(desc)
        sink = s.pipeline.get_by_name("sink")
        s.pipeline.set_state(Gst.State.PLAYING)
        t = threading.Thread(target=self._reader, args=(s, sink), daemon=True, name=f"pw{s.node_id}")
        t.start()
        self._readers.append(t)

    def _reader(self, s: Stream, sink):
        while s.pipeline is not None:
            sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
            if sample is None:
                continue
            buf = sample.get_buffer()
            caps = sample.get_caps().get_structure(0)
            w, h = caps.get_value("width"), caps.get_value("height")
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                stride = len(info.data) // h
                arr = np.frombuffer(info.data, dtype=np.uint8).reshape(h, stride)[:, : w * 3]
                s.frame = arr.reshape(h, w, 3).copy()
                s.frame_time = time.monotonic()
            finally:
                buf.unmap(info)
