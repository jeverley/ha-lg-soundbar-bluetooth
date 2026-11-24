"""Test build: open the soundbar's link through BlueZ's profile API.

Instead of an RFCOMM socket of our own, Home Assistant registers as a
client of the Serial Port service, asks BlueZ to connect that profile on
the soundbar, and BlueZ hands over the connected socket in a D-Bus call
(Profile1.NewConnection). The opening request is written inside that call,
the earliest moment this route allows, so the test shows whether the
soundbar still reports its input before it moves to Bluetooth.

Only for measuring; to be removed after the test.
"""

# Do not add ``from __future__ import annotations``: dbus-fast reads the
# D-Bus signatures from the method annotations.

import asyncio
from collections.abc import Callable
import contextlib
import logging
import os
import socket
import time
from typing import Any

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.annotations import DBusDict, DBusObjectPath, DBusUnixFd
from dbus_fast.service import ServiceInterface, method

from lg_soundbar_bluetooth import CannotConnect

_LOGGER = logging.getLogger(__name__)

SERIAL_PORT = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/org/homeassistant/lg_soundbar_bluetooth/serial_port"


class _SerialPortProfile(ServiceInterface):
    """The object BlueZ calls with each connected socket."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Profile1")
        # Per device path: the request to write and where to hand the socket.
        self.waiting: dict[str, tuple[bytes, asyncio.Future[tuple[int, float]]]] = {}

    @method()
    def Release(self) -> None:
        _LOGGER.debug("BlueZ released the Serial Port profile")

    @method()
    def NewConnection(
        self, device: DBusObjectPath, fd: DBusUnixFd, properties: DBusDict
    ) -> None:
        written_at = time.monotonic()
        waiting = self.waiting.pop(device, None)
        if waiting is None:
            _LOGGER.debug("Unexpected connection from %s; closing it", device)
            os.close(fd)
            return
        request, future = waiting
        if request:
            # At once, before anything else runs on the event loop.
            os.write(fd, request)
        if future.done():
            os.close(fd)
            return
        future.set_result((fd, written_at))

    @method()
    def RequestDisconnection(self, device: DBusObjectPath) -> None:
        _LOGGER.debug("BlueZ asked to disconnect %s", device)


class _Releasing(asyncio.Protocol):
    """Passes events on, and has BlueZ drop its side when the link closes.

    BlueZ keeps its own reference to a connection it handed over, so closing
    our socket alone leaves the link open.
    """

    def __init__(self, inner: asyncio.Protocol, release: Callable[[], Any]) -> None:
        self.inner = inner
        self._release = release

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.inner.connection_made(transport)

    def data_received(self, data: bytes) -> None:
        self.inner.data_received(data)  # type: ignore[attr-defined]

    def eof_received(self) -> bool | None:
        return self.inner.eof_received()  # type: ignore[attr-defined]

    def pause_writing(self) -> None:
        self.inner.pause_writing()

    def resume_writing(self) -> None:
        self.inner.resume_writing()

    def connection_lost(self, exc: Exception | None) -> None:
        self.inner.connection_lost(exc)
        self._release()


class ProfileConnector:
    """Opens the soundbar's Serial Port service through BlueZ."""

    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._profile = _SerialPortProfile()
        self._lock = asyncio.Lock()

    async def _ready(self) -> MessageBus:
        async with self._lock:
            if self._bus is not None and self._bus.connected:
                return self._bus
            bus = await MessageBus(
                bus_type=BusType.SYSTEM, negotiate_unix_fd=True
            ).connect()
            bus.export(PROFILE_PATH, self._profile)
            reply = await bus.call(
                Message(
                    destination="org.bluez",
                    path="/org/bluez",
                    interface="org.bluez.ProfileManager1",
                    member="RegisterProfile",
                    signature="osa{sv}",
                    body=[
                        PROFILE_PATH,
                        SERIAL_PORT,
                        {
                            "Role": Variant("s", "client"),
                            "AutoConnect": Variant("b", False),
                        },
                    ],
                )
            )
            if reply is None or reply.message_type == MessageType.ERROR:
                bus.disconnect()
                raise CannotConnect(f"BlueZ refused the profile: {_error(reply)}")
            _LOGGER.debug("Registered the Serial Port profile with BlueZ")
            self._bus = bus
            return bus

    async def _device_path(self, bus: MessageBus, address: str) -> str:
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if reply is None or reply.message_type == MessageType.ERROR:
            raise CannotConnect(f"Could not ask BlueZ for devices: {_error(reply)}")
        for path, interfaces in reply.body[0].items():
            device = interfaces.get("org.bluez.Device1")
            if device and device["Address"].value.upper() == address.upper():
                return path
        raise CannotConnect(f"BlueZ does not know {address}")

    async def _disconnect_profile(self, bus: MessageBus, path: str, why: str) -> None:
        """Ask BlueZ to drop its side of the Serial Port connection, if any."""
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface="org.bluez.Device1",
                member="DisconnectProfile",
                signature="s",
                body=[SERIAL_PORT],
            )
        )
        _LOGGER.debug(
            "Asked BlueZ to disconnect the Serial Port profile (%s): %s",
            why,
            "done"
            if reply is not None and reply.message_type != MessageType.ERROR
            else _error(reply),
        )

    async def connect(
        self,
        address: str,
        channel: int | None,
        protocol_factory: Callable[[], asyncio.Protocol],
        timeout: float,
        *,
        write_on_connect: bytes,
    ) -> tuple[asyncio.Transport, asyncio.Protocol]:
        """Open the link through BlueZ; the channel hint is not used."""
        bus = await self._ready()
        path = await self._device_path(bus, address)
        # A link BlueZ still holds from before would block a new one.
        await self._disconnect_profile(bus, path, "before connecting")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[int, float]] = loop.create_future()
        self._profile.waiting[path] = (write_on_connect, future)
        asked_at = time.monotonic()
        _LOGGER.debug("Asking BlueZ to connect the Serial Port profile of %s", address)
        try:
            async with asyncio.timeout(timeout):
                reply_task = asyncio.ensure_future(
                    bus.call(
                        Message(
                            destination="org.bluez",
                            path=path,
                            interface="org.bluez.Device1",
                            member="ConnectProfile",
                            signature="s",
                            body=[SERIAL_PORT],
                        )
                    )
                )
                done, _ = await asyncio.wait(
                    {reply_task, future}, return_when=asyncio.FIRST_COMPLETED
                )
                if future not in done:
                    reply = reply_task.result()
                    if reply is None or reply.message_type == MessageType.ERROR:
                        raise ConnectionRefusedError(
                            f"BlueZ could not connect {address}: {_error(reply)}"
                        )
                    fd, written_at = await future
                else:
                    fd, written_at = future.result()
                    reply_task.add_done_callback(_ignore)
        except BaseException:
            self._profile.waiting.pop(path, None)
            loop.create_task(self._disconnect_profile(bus, path, "connect failed"))
            if future.done() and not future.cancelled():
                os.close(future.result()[0])
            else:
                future.cancel()
            raise
        handed_at = time.monotonic()
        sock = socket.socket(fileno=fd)
        try:
            used = sock.getpeername()[1]
        except OSError:
            used = None
        sock.setblocking(False)
        tasks: set[asyncio.Task[None]] = set()

        def release() -> None:
            task = loop.create_task(self._disconnect_profile(bus, path, "link closed"))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        transport, releasing = await loop.create_connection(
            lambda: _Releasing(protocol_factory(), release), sock=sock
        )
        protocol = releasing.inner
        # As bluetooth-classic's transport reports it.
        transport._extra["rfcomm_channel"] = used  # type: ignore[attr-defined]
        _LOGGER.debug(
            "BlueZ handed over RFCOMM channel %s of %s after %.3f s; opening request"
            " written %.3f s after asking, transport ready %.3f s after asking",
            used,
            address,
            handed_at - asked_at,
            written_at - asked_at,
            time.monotonic() - asked_at,
        )
        return transport, protocol


def _error(reply: Message | None) -> Any:
    if reply is None:
        return "no reply"
    return f"{reply.error_name}: {reply.body}"


def _ignore(task: asyncio.Future[Any]) -> None:
    with contextlib.suppress(BaseException):
        task.result()


CONNECTOR = ProfileConnector()
