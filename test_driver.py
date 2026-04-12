"""
Test connection script for Kodi integration driver.

:copyright: (c) 2025 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

# pylint: disable=all
# flake8: noqa

import asyncio
import base64
import datetime
import io
import json
import logging
import math
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from asyncio import AbstractEventLoop, Future, Queue, Task
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from tkinter import ttk
from typing import Any, Callable

import aiohttp

sys.path.insert(1, "src")
import requests
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from PIL import Image, ImageTk
from pyee.asyncio import AsyncIOEventEmitter
from rich import print_json


def debounce(wait: float):
    """Debounce function."""

    def decorator(func):
        task: Task | None = None

        @wraps(func)
        async def debounced(*args, **kwargs):
            nonlocal task

            async def call_func():
                """Call wrapped function."""
                await asyncio.sleep(wait)
                await func(*args, **kwargs)

            if task and not task.done():
                task.cancel()
            task = asyncio.create_task(call_func())
            return task

        return debounced

    return decorator


# localization_cfg = {
#     "country_code": "EN",
#     "language_code": "en_US",
#     "measurement_unit": "METRIC",
#     "time_format_24h": True,
#     "time_zone": "Europe/Paris",
# }

localization_cfg = {
    "country_code": "FR",
    "language_code": "fr_FR",
    "measurement_unit": "METRIC",
    "time_format_24h": True,
    "time_zone": "Europe/Paris",
}


class Events(StrEnum):
    """Internal events."""

    EXITING = "EXITING"


@dataclass
class Selector:
    name: str
    current_option: str
    options: list[str]


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def get_locale(data: dict[str, str], locale="en") -> str | None:
    for language in data:
        if language == locale or language.startswith(locale):
            return data[language]
    return None


def get_entity_name(entity: dict[str, Any]) -> str:
    entity_id = entity.get("entity_id")
    name = get_locale(entity["name"])
    if name:
        return f"{name} {entity_id}"
    return entity_id


def load_image_from_url(url: str, max_size=(500, 500)) -> ImageTk.PhotoImage:
    if url.startswith("data:image/"):
        # Buffer image base64
        header, b64_data = url.split(",", 1)
        image_bytes = base64.b64decode(b64_data)
    else:
        # Image URL to download
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        image_bytes = resp.content

    # Open image from bytes data
    img = Image.open(io.BytesIO(image_bytes))
    # Resize image
    img.thumbnail(max_size)
    return ImageTk.PhotoImage(img)


if sys.platform == "win32":
    _LOOP = asyncio.SelectorEventLoop()
else:
    _LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

DRIVER_PORT = os.getenv("UC_INTEGRATION_HTTP_PORT", 9090)
DRIVER_INTERFACE = os.getenv("UC_INTEGRATION_INTERFACE", get_local_ip())
DRIVER_URL = f"ws://{DRIVER_INTERFACE}:{DRIVER_PORT}/ws"
MAIN_WS_MAX_MSG_SIZE = 8 * 1024 * 1024  # 8Mb
WS_TIMEOUT = 5
BROWSING_PAGINATION = 12
BROWSING_CELL_WIDTH = 60
DUMP_MAX_LENGTH = 100


class RemoteWebsocket:

    def __init__(self, loop: AbstractEventLoop | None = None):
        self.client_session: ClientSession | None = None
        self.client_websocket: ClientWebSocketResponse | None = None
        self._rx_tasks = set()
        self._id = 0
        self.callback_queues: dict[str, Queue[dict[str, Any]]] = {}
        self.callback_tasks: dict[int, Task] = {}
        self.futures: dict[int, Future[dict[str, Any]]] = {}
        self._loop = loop if loop else asyncio.get_event_loop()

    async def websocket_connect(self):
        self.client_session = ClientSession(connector=aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver()))
        async with asyncio.timeout(5):
            self.client_websocket = await self.client_session.ws_connect(
                DRIVER_URL,
                heartbeat=5,
                ssl=False,
                max_msg_size=MAIN_WS_MAX_MSG_SIZE,
            )
        if self.client_websocket is None:
            _LOG.error("Websocket connection failed")
            return
        self._rx_tasks.add(asyncio.create_task(self._rx_msgs_main_ws(self.client_websocket)))
        # await asyncio.wait(self._rx_tasks, return_when=asyncio.FIRST_COMPLETED)

    async def disconnect(self):
        await self._closeout_tasks()

    async def get_driver_vertion(self):
        try:
            response = await self.send_request_and_wait(
                {"msg": "get_driver_version"},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while extracting driver version")
            return None

    async def get_entity_states(self):
        try:
            response = await self.send_request_and_wait(
                {"msg": "get_entity_states"},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while extracting entities states")
            return None

    async def start_setup(self, reconfigure=False):
        try:
            response = await self.send_request_and_wait(
                {"msg": "setup_driver", "msg_data": {"reconfigure": reconfigure, "setup_data": {}}},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while starting setup")
            return None
        except Exception as ex:
            _LOG.error("Error while starting setup", ex)

    async def subscribe_entities(self, entity_ids: list[str]):
        try:
            response = await self.send_request_and_wait(
                {"msg": "subscribe_events", "msg_data": {"entity_ids": entity_ids}},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while subscribing entities")
            return None

    async def get_available_entities(self):
        try:
            response = await self.send_request_and_wait(
                {"msg": "get_available_entities"},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while getting available entities")
            return None

    def subscribe_events(self, event_type: str, callback: Callable):
        uid = self._id
        self._id += 1
        self._create_subscription_handler(uid, event_type, callback)

    async def send_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        # {"kind":"req","id":35,"msg":"entity_command","msg_data":{"cmd_id":"on","entity_id":"media_player.192.168.1.20","entity_type":"media_player","params":{}}}
        try:
            response = await self.send_request_and_wait(
                {"msg": "entity_command", "msg_data": command},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while sending command")
            return None
        except Exception as ex:
            _LOG.error("Command error %s", ex)
            return None

    async def browse_media_entity(
        self,
        entity_id: str,
        media_id: str | None = None,
        media_type: str | None = None,
        paging: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self.browse_media(
            {"entity_id": entity_id, "media_id": media_id, "media_type": media_type, "paging": paging}
        )

    async def search_media_entity(
        self,
        entity_id: str,
        query: str,
        media_id: str | None = None,
        media_type: str | None = None,
        paging: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self.search_media(
            {"entity_id": entity_id, "query": query, "media_id": media_id, "media_type": media_type, "paging": paging}
        )

    async def browse_media(self, msg_data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            _LOG.debug("Browse media: %s", msg_data)
            response = await self.send_request_and_wait(
                {"msg": "browse_media", "msg_data": msg_data},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while browsing media")
            return None
        except Exception as ex:
            _LOG.error("Browsing error %s", ex)
            return None

    async def search_media(self, msg_data: dict[str, Any]) -> dict[str, Any] | None:
        try:
            _LOG.debug("Search media: %s", msg_data)
            response = await self.send_request_and_wait(
                {"msg": "search_media", "msg_data": msg_data},
                timeout=WS_TIMEOUT,
            )
            return response
        except asyncio.TimeoutError:
            _LOG.error("Timeout while browsing media")
            return None
        except Exception as ex:
            _LOG.error("Browsing error %s", ex)
            return None

    async def _rx_msgs_main_ws(self, web_socket: ClientWebSocketResponse) -> None:
        """Receive messages from main websocket connection."""
        async for raw_msg in web_socket:
            # _LOG.debug("receive: %s", raw_msg)
            if raw_msg.type is not WSMsgType.TEXT:
                break
            self._process_text_message(raw_msg.data)

    async def _handle_auth(self):
        # {"kind": "event", "msg": "auth_required","msg_data": {"name":"my-integration","version":{"api":"0.5.0","driver":"1.0.0"}}}
        await self._send_json(
            {"kind": "resp", "req_id": self._id, "code": 200, "msg": "authentication", "msg_data": {}}
        )
        self._id += 1

    async def _handle_request(self, msg: dict[str, Any]):
        # {"kind": "req", "msg": "get_supported_entity_types"}
        msg_type = msg.get("msg", "")
        req_id = msg.get("id", "")
        if msg_type == "get_supported_entity_types":
            await self._send_json(
                {
                    "kind": "resp",
                    "req_id": req_id,
                    "code": 200,
                    "msg": "supported_entity_types",
                    "msg_data": [
                        "cover",
                        "button",
                        "climate",
                        "light",
                        "media_player",
                        "remote",
                        "select",
                        "sensor",
                        "switch",
                        "ir_emitter",
                        "voice_assistant",
                    ],
                }
            )
        elif msg_type == "get_version":
            await self._send_json(
                {
                    "kind": "resp",
                    "req_id": req_id,
                    "code": 200,
                    "msg": "version",
                    "msg_data": {
                        "address": "AA:BB:CC:DD:EE:FF",
                        "api": "0.16.0",
                        "core": "0.69.1-bt",
                        "device_name": "Remote 3",
                        "hostname": "Remote3-aabbccdd.local",
                        "model": "UCR3",
                        "os": "2.8.3",
                        "ui": "0.69.1",
                    },
                }
            )
        elif msg_type == "get_localization_cfg":
            await self._send_json(
                {
                    "kind": "resp",
                    "req_id": req_id,
                    "code": 200,
                    "msg": "localization_cfg",
                    "msg_data": localization_cfg,
                }
            )
        elif msg_type == "get_driver_metadata":
            # {"id":2,"kind":"req","msg":"get_driver_metadata"}
            with open("driver.json", "r") as file:
                file_content = json.load(file)
                await self._send_json(
                    {
                        "kind": "resp",
                        "req_id": req_id,
                        "code": 200,
                        "msg": "driver_metadata",
                        "msg_data": json.dumps(file_content),
                    }
                )

        elif msg_type == "setup_driver":
            # {"kind":"req","id":3,"msg":"setup_driver","msg_data":{"reconfigure":false,"setup_data":{}}}
            await self._send_json(
                {
                    "kind": "resp",
                    "req_id": req_id,
                    "code": 200,
                    "msg": "result",
                    "msg_data": {},
                }
            )
            await asyncio.sleep(1)
            await self._send_json(
                {
                    "kind": "event",
                    "msg": "driver_setup_change",
                    "msg_data": {"event_type": "SETUP", "state": "SETUP"},
                    "cat": "DEVICE",
                }
            )
            await asyncio.sleep(1)
            await self._send_json(
                {
                    "kind": "event",
                    "msg": "driver_setup_change",
                    "msg_data": {"event_type": "SETUP", "state": "OK"},
                    "cat": "DEVICE",
                }
            )
        else:
            await self._send_json(
                {
                    "kind": "resp",
                    "req_id": req_id,
                    "code": 400,
                    "msg": f"{msg_type}",
                    "msg_data": f"Unknown message type: {msg_type}",
                }
            )

    async def _send_json(self, msg: dict) -> None:
        _LOG.debug("Send json: %s", msg)
        await self.client_websocket.send_json(msg)

    async def send_request_and_wait(
        self,
        msg: dict,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """
        Envoie une requête et attend la réponse associée au req_id.
        """
        req_id = self._id
        self._id += 1

        msg["id"] = req_id
        msg["kind"] = "req"

        future = self._loop.create_future()
        self.futures[req_id] = future

        await self._send_json(msg)

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            pass
        finally:
            try:
                # Nettoyage dans tous les cas
                await self.futures.pop(req_id, None)
            except KeyError:
                pass

    def _process_text_message(self, data: str) -> None:
        """Process text message."""
        msg = json.loads(data)
        msg_type = msg.get("msg", "")
        if msg_type == "auth_required":
            asyncio.create_task(self._handle_auth())

        kind = msg.get("kind", "")
        if kind == "event" and (callback_queue := self.callback_queues.get(msg_type)):
            callback_queue.put_nowait(msg)
        elif kind == "req":
            asyncio.create_task(self._handle_request(msg))
        else:
            uid = msg.get("req_id", None)
            if uid is None:
                return
            if future := self.futures.get(uid):
                future.set_result(msg)

    @staticmethod
    async def callback_handler(
        handler_queue: Queue[dict[str, Any]],
        callback: Callable,
        future: Future[dict[str, Any]],
    ) -> None:
        """Handle callbacks."""
        with suppress(asyncio.CancelledError):
            while True:
                msg = await handler_queue.get()
                # payload = msg.get("payload")
                try:
                    await callback(msg)
                except Exception as ex:
                    _LOG.error("Exception in callback: %s", ex)
                    pass
                if not future.done():
                    future.set_result(msg)

    def _create_subscription_handler(self, uid: int, msg_type: str, callback: Callable) -> None:
        """Create a subscription handler for a given uid.

        Create a queue to store the messages, a task to handle the messages
        and a future to signal first subscription update processed.
        """
        self.futures[uid] = future = self._loop.create_future()
        subscription_queue: Queue[dict[str, Any]] = asyncio.Queue()
        self.callback_queues[msg_type] = subscription_queue
        self.callback_tasks[uid] = asyncio.create_task(self.callback_handler(subscription_queue, callback, future))

    async def _delete_subscription_handler(self, uid: int, msg_type: str) -> None:
        """Delete a subscription handler for a given id."""
        task = self.callback_tasks.pop(uid)
        if not task.done():
            task.cancel()
        while not task.done():
            with suppress(asyncio.CancelledError):
                await task
        del self.callback_queues[msg_type]

    def _cancel_tasks(self) -> None:
        """Cancel all tasks."""
        for callback_task in self.callback_tasks.values():
            if not callback_task.done():
                callback_task.cancel()

        for task in self._rx_tasks:
            if not task.done():
                task.cancel()

        for future in self.futures.values():
            future.cancel()

    async def close_client_session(self) -> None:
        await self.client_session.close()
        self.client_session = None

    async def _closeout_tasks(self) -> None:
        """Cancel all tasks and close connections."""
        closeout = set()
        self._cancel_tasks()
        if callback_tasks := set(self.callback_tasks.values()):
            closeout.update(callback_tasks)
        closeout.update(self._rx_tasks)
        closeout.add(asyncio.create_task(self.close_client_session()))
        if not closeout:
            return
        closeout_task = asyncio.create_task(asyncio.wait(closeout))
        while not closeout_task.done():
            with suppress(asyncio.CancelledError):
                await asyncio.shield(closeout_task)


class BrowsingData:
    window: tk.Toplevel | None = None
    media_id: str | None = None
    media_type: str | None = None
    page: int = 1
    limit: int = BROWSING_PAGINATION
    count = 0
    items: list[dict[str, Any]] | None = None
    main: dict[str, Any] | None = None
    search_mode = False


class SetupData:
    window: tk.Toplevel | None = None
    mapping: dict[str, ttk.Widget | tk.IntVar | tk.StringVar | tk.Widget] = {}
    mapping_type: dict[str, str] = {}
    data: dict[str, Any] | None = None


async def load_item_image_url(button: ttk.Button, item: dict[str, Any]):
    try:
        photo = load_image_from_url(item.get("thumbnail"), max_size=(BROWSING_CELL_WIDTH, BROWSING_CELL_WIDTH))
        button.configure(image=photo, compound="top")
        button.image = photo
    except Exception as e:
        _LOG.exception("Image load error %s : %s", item.get("thumbnail"), e)


class RemoteInterface(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self._worker: WorkerThread | None = None
        self.title("Remote Interface")
        # self.geometry("800x600")
        self.maxsize(1920, 1080)
        self._row = 0
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._left_frame = ttk.Frame(self, width=300, height=600)
        self._left_frame.pack(side="left", fill="both", padx=10, pady=5, expand=True)
        self._left_frame.grid_columnconfigure(0, weight=1)
        self._left_frame.grid_columnconfigure(1, weight=1)
        self._left_frame.grid_columnconfigure(2, weight=1)
        self._right_frame = ttk.Frame(self, width=650, height=600)
        self._right_frame.pack(side="right", fill="both", padx=10, pady=5, expand=True)
        tool_bar2 = ttk.Frame(self._right_frame, width=650, height=80)
        label = ttk.Label(tool_bar2, text="Volume")
        label.pack(anchor="w", side="left", pady=(0, 10))
        self._volume_bar: tk.Scale = tk.Scale(
            tool_bar2,
            from_=0,
            to=100,
            state="disabled",
            orient="horizontal",
            # command=lambda event: self.media_player_command("volume", {"volume": event.widget.get()}),
        )
        self._volume_bar.bind(
            "<ButtonRelease-1>", lambda event: self.media_player_command("volume", {"volume": event.widget.get()})
        )
        self._volume_bar.pack(side="right", fill="x", expand=True)
        tool_bar2.pack(side="bottom", fill="x", expand=True)
        tool_bar = ttk.Frame(self._right_frame, width=650, height=40)
        self._title_field = ttk.Label(tool_bar, text="Title")
        self._title_field.pack(anchor="w", pady=(0, 10))
        self._artist = ttk.Label(tool_bar, text="Artist")
        self._artist.pack(anchor="w", pady=(0, 10))
        self._state = ttk.Label(tool_bar, text="State")
        self._state.pack(anchor="w", pady=(0, 10))
        self._progress = ttk.Progressbar(
            tool_bar, orient="horizontal", length=200, mode="determinate", takefocus=True, maximum=100
        )
        self._progress["value"] = 0
        self._progress.pack(side="left", fill="x", expand=True)
        self._progress_label = ttk.Label(tool_bar, text="00:00:00")
        self._progress_label.pack(side="right", fill="x", expand=True)
        tool_bar.pack(side="bottom", fill="x", expand=True)

        start_setup_button = ttk.Button(self._left_frame, text="Start setup", command=lambda: self.setup_open())
        start_setup_button.grid(row=self._row, column=0)

        self._setup_reconfigure = tk.IntVar(value=1)
        reconfigure_checkbox = tk.Checkbutton(self._left_frame, variable=self._setup_reconfigure, onvalue=1, offvalue=0)
        reconfigure_checkbox.grid(row=self._row, column=1, sticky="e")
        label_setup = ttk.Label(self._left_frame, text="Reconfigure devices")
        label_setup.grid(row=self._row, column=2, sticky="w")
        self._setup_data = SetupData()
        self._row += 1

        reconnect_button = ttk.Button(self._left_frame, text="Reconnect driver", command=lambda: self.reconnect())
        reconnect_button.grid(row=self._row, column=0)

        self._media_browse_button = ttk.Button(
            self._left_frame, text="Browse media", command=lambda: self.media_browse_open()
        )
        self._media_browse_data = BrowsingData()
        self._media_browse_button.grid(row=self._row, column=1)
        self._row += 1

        label = ttk.Label(self._left_frame, text="Search media :")
        label.grid(row=self._row, column=0)
        self._media_search_text = ttk.Entry(self._left_frame)
        self._media_search_text.grid(row=self._row, column=1)
        self._media_search_button = ttk.Button(
            self._left_frame, text="Search", command=lambda: self.media_search_open()
        )
        self._media_search_button.grid(row=self._row, column=2)
        self._row += 1
        self._media_search_window: tk.Toplevel | None = None
        self._media_search_data = BrowsingData()
        self._media_search_data.search_mode = True

        label = ttk.Label(self._left_frame, text="Media Players")
        label.grid(row=self._row, column=0, columnspan=1)
        self._media_players = ttk.Combobox(self._left_frame, state="readonly")
        self._media_players.bind(
            "<<ComboboxSelected>>",
            lambda event, cmd_id="select_option": self.change_media_player(event),
        )
        self._media_players.grid(row=self._row, column=1, columnspan=2)
        self._row += 1
        self._volume = ttk.Label(self._left_frame, text="Volume")
        self._volume.grid(row=self._row, column=2)  # .pack(anchor="w", pady=(0, 10))
        self._row += 1
        command = ttk.Button(self._left_frame, text="Off", command=lambda: self.media_player_command("off"))
        command.grid(row=self._row, column=0)
        self._command_on = ttk.Button(self._left_frame, text="On", command=lambda: self.media_player_command("on"))
        self._command_on.grid(row=self._row, column=1)
        self._input_source = ttk.Combobox(self._left_frame, state="readonly", justify="left")
        self._input_source.bind(
            "<<ComboboxSelected>>",
            lambda event: self.select_input_source(event),
        )
        self._input_source.grid(row=self._row, column=2)
        self._row += 1
        self._command_play_pause = ttk.Button(
            self._left_frame, text="Play/pause", command=lambda: self.media_player_command("play_pause")
        )
        self._command_stop = ttk.Button(
            self._left_frame, text="Stop", command=lambda: self.media_player_command("stop")
        )
        self._command_stop.grid(row=self._row, column=0)
        self._command_play_pause.grid(row=self._row, column=1)
        self._sound_mode = ttk.Combobox(self._left_frame, state="readonly", justify="left")
        self._sound_mode.bind(
            "<<ComboboxSelected>>",
            lambda event: self.select_sound_mode(event),
        )
        self._sound_mode.grid(row=self._row, column=2)
        self._row += 1
        command = ttk.Button(self._left_frame, text="Mute", command=lambda: self.media_player_command("mute_toggle"))
        command.grid(row=self._row, column=0)
        command = ttk.Button(self._left_frame, text="Vol-", command=lambda: self.media_player_command("volume_down"))
        command.grid(row=self._row, column=1)
        command = ttk.Button(self._left_frame, text="Vol+", command=lambda: self.media_player_command("volume_up"))
        command.grid(row=self._row, column=2)
        self._row += 1
        command = ttk.Button(self._left_frame, text="Back", command=lambda: self.media_player_command("back"))
        command.grid(row=self._row, column=0)
        command = ttk.Button(self._left_frame, text="Up", command=lambda: self.media_player_command("cursor_up"))
        command.grid(row=self._row, column=1)
        command = ttk.Button(self._left_frame, text="Home", command=lambda: self.media_player_command("home"))
        command.grid(row=self._row, column=2)
        self._row += 1
        command = ttk.Button(self._left_frame, text="Left", command=lambda: self.media_player_command("cursor_left"))
        command.grid(row=self._row, column=0)
        command = ttk.Button(self._left_frame, text="OK", command=lambda: self.media_player_command("cursor_enter"))
        command.grid(row=self._row, column=1)
        command = ttk.Button(self._left_frame, text="Right", command=lambda: self.media_player_command("cursor_right"))
        command.grid(row=self._row, column=2)
        self._row += 1
        command = ttk.Button(self._left_frame, text="Down", command=lambda: self.media_player_command("cursor_down"))
        command.grid(row=self._row, column=1)
        self._row += 1
        self._sensors: dict[str, ttk.Label] = {}
        self._selectors: dict[str, ttk.Combobox] = {}
        self._info_label = ttk.Label(self._left_frame, text="")
        self._info_label.grid(row=self._row, column=0, columnspan=3)
        self._row += 1
        self._loop = asyncio.get_event_loop()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self.poll_queue)
        self._photo: tk.PhotoImage | None = None
        self._artwork: ttk.Label | None = None
        self._events = AsyncIOEventEmitter(asyncio.get_event_loop())
        self._position = 0
        self._duration = 0
        self._media_position_task: Future | None = None
        self._browsing_support = False
        self._media_search_support = False

    @property
    def media_player_entity(self) -> dict[str, Any] | None:
        for entity in self._worker._entities:
            if entity.get("entity_type", "") != "media_player":
                continue
            name = get_entity_name(entity)
            if self._media_players.get() == name:
                return entity
        return None

    def set_worker(self, worker: Any) -> None:
        self._worker = worker

    def select_input_source(self, event: tk.Event):
        self.media_player_command("select_source", {"source": event.widget.get()})

    def select_sound_mode(self, event: tk.Event):
        self.media_player_command("select_sound_mode", {"mode": event.widget.get()})

    def media_player_command(self, cmd_id: str, params: dict[str, Any] | None = None) -> None:
        _LOG.debug("Media Player Command %s", cmd_id)
        if self._worker is None:
            _LOG.error("Media Player Command undefined worker")
            return
        # entity_id = next(
        #     (x.get("entity_id", "") for x in self._worker._entities if x.get("entity_type", "") == "media_player")
        # )
        media_player_entity = self.media_player_entity
        if media_player_entity is None:
            _LOG.error("No Media Player entity not found for command %s (%s)", cmd_id, self._worker.entity_ids)
            return
        entity_id = media_player_entity.get("entity_id")
        try:
            if params is None:
                params = {}
            asyncio.run_coroutine_threadsafe(
                self.send_command(
                    {
                        "cmd_id": cmd_id,
                        "entity_id": entity_id,
                        "entity_type": "media_player",
                        "params": params,
                    }
                ),
                self._worker._loop,
            )
        except Exception as ex:
            _LOG.exception("Send command error %s", ex)

    def selector_command(self, event: Any, entity_id: str, cmd_id: str) -> None:
        _LOG.debug(
            "Selector Command %s",
            {
                "cmd_id": cmd_id,
                "entity_id": entity_id,
                "entity_type": "select",
                "params": {"option": event.widget.get()},
            },
        )
        if self._worker is None:
            _LOG.error("Selector Command undefined worker")
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_command(
                    {
                        "cmd_id": cmd_id,
                        "entity_id": entity_id,
                        "entity_type": "select",
                        "params": {"option": event.widget.get()},
                    }
                ),
                self._worker._loop,
            )
        except Exception as ex:
            _LOG.exception("Send command error %s", ex)

    async def send_command(self, command: dict[str, Any]):
        try:
            result = await self._worker.send_command(command)

            if (code := result.get("code", None)) and code != 200:
                self._info_label["text"] = f"Command failed {code}"
                _LOG.error("Command error : %s", result)
                self.update()
            else:
                self._info_label["text"] = f"Command succeeded"
                _LOG.debug("Command result : %s", result)

        except Exception as ex:
            _LOG.exception("Send command error %s", ex)

    def on_close(self):
        self._events.emit(Events.EXITING)
        self.destroy()
        self._loop.call_soon_threadsafe(self._loop.stop)

    def poll_queue(self):
        try:
            while True:
                action = self._ui_queue.get_nowait()
                action()
        except Exception:  # queue.Empty:
            pass
        self.after(50, self.poll_queue)

    def load_image(self, url: str) -> None:
        if self._artwork and (url is None or url == ""):
            self._artwork.configure(image="")
            return
        try:
            _LOG.debug("Loading new image from URL: %s", url)
            self._photo = load_image_from_url(url)
            if self._artwork is None:
                self._artwork = ttk.Label(self._right_frame)
                self._artwork.pack(anchor="w", side="top", fill="both", expand=True)
            self._artwork.configure(image=self._photo)
            self.update()
        except Exception as e:
            self._info_label.text = str(f"Erreur de chargement de l'image : {e}")

    def set_title(self, title: str) -> None:
        self._title_field["text"] = title
        self.update()

    def set_artist(self, artist: str) -> None:
        self._artist["text"] = artist
        self.update()

    def set_state(self, state: str) -> None:
        self._state["text"] = state
        self.update()

    def set_volume(self, volume: float) -> None:
        self._volume["text"] = volume
        self._volume_bar.set(int(volume))
        self.update()

    def browsing_support(self, value: bool):
        self._browsing_support = value
        self.update()

    def media_search_support(self, value: bool):
        self._media_search_support = value
        self.update()

    async def update_position_task(self):
        while True:
            await asyncio.sleep(1)
            entity = self.media_player_entity
            if entity is None:
                _LOG.debug("Stopping update position task, no media entity")
                self._media_position_task = None
                return
            attributes = self._worker._attributes.get(entity.get("entity_id"), {})
            state = attributes.get("state", "")
            if state == "PLAYING":
                self._ui_queue.put(lambda: self.update_position())
            else:
                _LOG.debug("Stopping update position task, media is not playing")
                self._media_position_task = None
                return

    # @debounce(1)
    def update_position(self):
        entity = self.media_player_entity
        if entity is None:
            _LOG.debug("Update position : no media entity")
            return

        attributes = self._worker._attributes.get(entity.get("entity_id"), {})
        position = attributes.get("media_position", 0)
        duration = attributes.get("media_duration", 0)
        state = attributes.get("state", "")
        media_position_updated_at = attributes.get("media_position_updated_at", None)
        if media_position_updated_at is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            media_position_updated_at = now.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
            attributes["media_position_updated_at"] = media_position_updated_at
        if state == "PLAYING":
            try:
                offset = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(
                    media_position_updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                )
                position += offset.total_seconds()
            except Exception as ex:
                _LOG.error("Update position error : %s", ex)
        # position = self._position
        if position < 0:
            position = 0
        # duration = self._duration
        if duration < 0:
            duration = 0

        self._progress_label["text"] = (
            f"{time.strftime('%H:%M:%S', time.gmtime(position))} / {time.strftime('%H:%M:%S', time.gmtime(duration))}"
        )
        self.update()
        if duration <= 0 or duration < position:
            self._progress["value"] = 0
        else:
            self._progress["value"] = abs(int(position * 100 / duration))
        self.update()
        if state == "PLAYING" and (self._media_position_task is None or self._media_position_task.done()):
            self._media_position_task = asyncio.run_coroutine_threadsafe(
                self.update_position_task(),
                self._worker._loop,
            )

    def update_input_source(self):
        entity_id = self._worker.get_media_player_entity_id()
        attributes = self._worker.get_attributes(entity_id)
        if attributes is None:
            attributes = {}
        if self._worker.has_feature(entity_id, "select_source"):
            self._input_source.configure(state="normal")
            self._input_source["values"] = attributes.get("source_list", [])
            self._input_source.set(attributes.get("source", ""))
        else:
            self._input_source.configure(state="disabled")
            self._input_source["values"] = []

    def update_sound_mode(self):
        entity_id = self._worker.get_media_player_entity_id()
        attributes = self._worker.get_attributes(entity_id)
        if attributes is None:
            attributes = {}
        if self._worker.has_feature(entity_id, "sound_mode"):
            self._sound_mode.configure(state="normal")
            self._sound_mode["values"] = attributes.get("sound_mode_list", [])
            self._sound_mode.set(attributes.get("source", ""))
        else:
            self._sound_mode.configure(state="disabled")
            self._sound_mode["values"] = []

    def set_position(self, position: int) -> None:
        # _LOG.debug("Setting position %s", position)
        self._position = position
        self.update_position()

    def set_duration(self, duration: int) -> None:
        # _LOG.debug("Setting duration %s", duration)
        self._duration = duration
        self.update_position()

    def set_sensor(self, entity_id: str, name: str, value: str, state: str) -> None:
        # _LOG.debug("Setting sensor %s %s", entity_id, value)
        if entity_id not in self._sensors:
            label = self._sensors[entity_id] = ttk.Label(self._left_frame, text="")
            label.grid(row=self._row, column=0, columnspan=3, sticky="we")
            self._row += 1
            self._sensors[entity_id] = label
        self._sensors[entity_id]["text"] = f"{name}({state}): {value}"
        self.update()

    def set_selector(self, entity_id: str, name: str, selector: Selector) -> None:
        _LOG.debug("Setting selector %s %s", entity_id, selector)
        if entity_id not in self._selectors:
            label = ttk.Label(self._left_frame, text=f"{name} :", justify="left", anchor="w")
            label.grid(row=self._row, column=0, sticky="we")
            # self._row += 1
            combo = self._selectors[entity_id] = ttk.Combobox(self._left_frame, state="readonly", justify="left")
            combo.bind(
                "<<ComboboxSelected>>",
                lambda event, eid=entity_id, cmd_id="select_option": self.selector_command(event, eid, cmd_id),
            )
            combo.grid(row=self._row, column=1, columnspan=2, sticky="we")
            self._row += 1
            self._selectors[entity_id] = combo
        combo = self._selectors[entity_id]
        combo["values"] = selector.options
        combo.set(selector.current_option)
        self.update()

    def set_media_players(self, entity_names: list[str]) -> None:
        _LOG.debug("Setting media players list %s", entity_names)
        self._media_players["values"] = entity_names
        self.update()

    def set_media_player(self, entity_id: str):
        self._media_players.set(entity_id)
        self.update()

    def get_media_player(self) -> str:
        return self._media_players.get()

    def change_media_player(self, event: Any):
        new_entity = event.widget.get()
        self._worker.change_media_player(new_entity)
        entity_id = self._worker.get_media_player_entity_id()
        attributes = self._worker.get_attributes(entity_id)
        if attributes is None:
            attributes = {}
        if self._browsing_support:
            self._media_browse_button.configure(state="normal")
        else:
            self._media_browse_button.configure(state="disabled")
        if self._media_search_support:
            self._media_search_button.configure(state="normal")
        else:
            self._media_search_button.configure(state="disabled")
        if self._worker.has_feature(entity_id, "volume"):
            self._volume_bar.configure(state="normal")
            self._volume_bar.set(attributes.get("volume", 50))
        else:
            self._volume_bar.configure(state="disabled")
            self._volume_bar.set(0)
        self.update_input_source()
        self.update_sound_mode()

    async def browse_media(self, browsing_data: BrowsingData, entity_id):
        results = await self._worker.browse_media(
            entity_id,
            browsing_data.media_id,
            browsing_data.media_type,
            {
                "page": browsing_data.page,
                "limit": browsing_data.limit,
            },
        )
        dump_msg = json.loads(json.dumps(results))
        if media := dump_msg.get("msg_data", {}).get("media"):
            for item in media.get("items", []):
                if (url := item.get("thumbnail")) and len(url) > DUMP_MAX_LENGTH:
                    item["thumbnail"] = url[:DUMP_MAX_LENGTH] + "..."

        print_json(json=json.dumps(dump_msg))
        if results and (msg_data := results.get("msg_data", {})):
            pagination = msg_data.get("pagination", {})
            media = msg_data.get("media", {})
            if not media or not pagination:
                return
            browsing_data.main = media
            browsing_data.items = media.get("items", [])
            browsing_data.page = pagination.get("page", 1)
            browsing_data.limit = pagination.get("limit", BROWSING_PAGINATION)
            browsing_data.count = pagination.get("count", 0)
            if browsing_data.count is None:
                browsing_data.count = 0
            try:
                self.update_browsing_grid(browsing_data, "Media Browser")
            except Exception as e:
                _LOG.exception("Error while updating browsing grid: %s", e)

    async def search_media(self, entity_id):
        results = await self._worker.search_media(
            entity_id,
            self._media_search_text.get(),
            self._media_search_data.media_id,
            self._media_search_data.media_type,
            {
                "page": self._media_search_data.page,
                "limit": self._media_search_data.limit,
            },
        )
        dump_msg = json.loads(json.dumps(results))
        if media := dump_msg.get("msg_data", {}).get("media"):
            for item in media:
                if (url := item.get("thumbnail")) and len(url) > DUMP_MAX_LENGTH:
                    item["thumbnail"] = url[:DUMP_MAX_LENGTH] + "..."
        print_json(json=json.dumps(dump_msg))
        if results and (msg_data := results.get("msg_data", {})):
            pagination = msg_data.get("pagination", {})
            media = msg_data.get("media", [])
            if not media or not pagination:
                return
            self._media_search_data.items = media
            self._media_search_data.page = pagination.get("page", 1)
            self._media_search_data.limit = pagination.get("limit", BROWSING_PAGINATION)
            self._media_search_data.count = pagination.get("count", 0)
            if self._media_search_data.count is None:
                self._media_search_data.count = 0
            try:
                self.update_browsing_grid(self._media_search_data, "Search Media")
            except Exception as e:
                _LOG.exception("Error while updating search media grid: %s", e)

    def browse(self, event: Any, item: dict[str, Any], browsing_data: BrowsingData):
        if not item.get("can_browse", False):
            if item.get("can_play", False):
                _LOG.debug("Play item %s", item)
                self.media_player_command(
                    "play_media",
                    {"media_id": item.get("media_id", ""), "media_type": item.get("media_type", "")},
                )
            elif item.get("can_search", False):
                _LOG.debug("Search item %s", item)
                entity_id = self._worker.get_media_player_entity_id()
                browsing_data.page = 1
                browsing_data.limit = BROWSING_PAGINATION
                browsing_data.count = 0
                browsing_data.media_id = item.get("media_id", "")
                browsing_data.media_type = item.get("media_type", "")
                asyncio.run_coroutine_threadsafe(
                    self.search_media(entity_id),
                    self._worker._loop,
                )
            return
        dump_item = json.loads(json.dumps(item))
        if dump_item and (url := item.get("thumbnail")) and len(url) > DUMP_MAX_LENGTH:
            dump_item["thumbnail"] = url[:DUMP_MAX_LENGTH] + "..."

        _LOG.debug("Browse item %s", dump_item)
        entity_id = self._worker.get_media_player_entity_id()
        browsing_data.page = 1
        browsing_data.limit = BROWSING_PAGINATION
        browsing_data.count = 0
        browsing_data.media_id = item.get("media_id", "")
        browsing_data.media_type = item.get("media_type", "")

        asyncio.run_coroutine_threadsafe(
            self.browse_media(browsing_data, entity_id),
            self._worker._loop,
        )

    def paging(self, browsing_data: BrowsingData, page: int):
        browsing_data.page = page
        entity_id = self._worker.get_media_player_entity_id()
        if browsing_data.search_mode:
            asyncio.run_coroutine_threadsafe(
                self.search_media(entity_id),
                self._worker._loop,
            )
        else:
            asyncio.run_coroutine_threadsafe(
                self.browse_media(browsing_data, entity_id),
                self._worker._loop,
            )

    def change_page(self, event: Any, data: BrowsingData):
        self.paging(data, int(event.widget.get()))

    def update_browsing_grid(self, browsing_data: BrowsingData, title: str):
        for widget in browsing_data.window.winfo_children():
            widget.destroy()
        row = 0
        column = 0
        label = ttk.Label(
            browsing_data.window,
            text=title,
        )
        label.grid(row=row, column=column, columnspan=4)
        row += 1

        button = ttk.Button(
            browsing_data.window,
            text="<<",
            command=lambda data=browsing_data: self.paging(data, browsing_data.page - 1),
        )
        button.grid(row=row, column=column)
        column += 1
        if browsing_data.page == 1:
            button.configure(state="disabled")
        if browsing_data.count > 0:
            page = ttk.Combobox(
                browsing_data.window,
                state="readonly",
                justify="right",
                values=[str(x) for x in range(1, math.ceil(browsing_data.count / BROWSING_PAGINATION) + 1)],
            )
            page.set(str(browsing_data.page))
            page.bind("<<ComboboxSelected>>", lambda event, data=browsing_data: self.change_page(event, data))
            page.grid(row=row, column=column, sticky="e")
            column += 1
            label = ttk.Label(
                browsing_data.window,
                text=f" / {math.ceil(browsing_data.count / BROWSING_PAGINATION)} ({browsing_data.count})",
            )
            label.grid(row=row, column=column, sticky="w")
            column += 1
        button = ttk.Button(
            browsing_data.window,
            text=">>",
            command=lambda data=browsing_data: self.paging(data, browsing_data.page + 1),
        )
        button.grid(row=row, column=column)
        if browsing_data.count != 0 and (browsing_data.count == 0 or browsing_data.count <= BROWSING_PAGINATION):
            button.configure(state="disabled")
        column += 1
        row += 1
        column = 0
        if browsing_data.main:
            label = ttk.Label(
                browsing_data.window,
                text=f"{browsing_data.main.get('title', '')} ({browsing_data.main.get('media_class', '')})",
            )
            label.grid(row=row, column=column, columnspan=4)
            row += 1

        for item in browsing_data.items:
            title = item.get("title", "")
            if item.get("subtitle"):
                title += "\n" + item.get("subtitle")
            button = ttk.Button(
                browsing_data.window,
                text=title,
                width=BROWSING_CELL_WIDTH,
                command=lambda item=item.copy(), data=browsing_data: self.browse(None, item, data),
                # height=200,
            )
            # button.bind("<Button-1>", lambda e, item=item.copy(): self.browse(e, item))
            if item.get("thumbnail", None):
                asyncio.run_coroutine_threadsafe(
                    load_item_image_url(button, item),
                    self._worker._loop,
                )
            button.grid(row=row, column=column, sticky="we")
            column += 1
            if column == 4:
                column = 0
                row += 1
        self.update()

    def media_search_open(self):
        entity_id = self._worker.get_media_player_entity_id()
        if entity_id is None:
            return
        if self._media_search_data.window is None or not self._media_search_data.window.winfo_exists():
            self._media_search_data.window = tk.Toplevel(self, width=600, height=600)
            self._media_search_data.window.grid_columnconfigure(0, weight=1)
            self._media_search_data.window.grid_columnconfigure(1, weight=1)
            self._media_search_data.window.grid_columnconfigure(2, weight=1)
            self._media_search_data.window.grid_columnconfigure(3, weight=1)
            self._media_search_data.media_id = None
            self._media_search_data.media_type = None
            self._media_search_data.page = 1
            self._media_search_data.limit = BROWSING_PAGINATION
            self._media_search_data.count = 0
            self._media_search_data.items = None
            self._media_search_data.main = None

        asyncio.run_coroutine_threadsafe(
            self.search_media(entity_id),
            self._worker._loop,
        )

    def media_browse_open(self):
        entity_id = self._worker.get_media_player_entity_id()
        if entity_id is None:
            return
        if self._media_browse_data.window is None or not self._media_browse_data.window.winfo_exists():
            self._media_browse_data.window = tk.Toplevel(self, width=600, height=600)
            self._media_browse_data.window.grid_columnconfigure(0, weight=1)
            self._media_browse_data.window.grid_columnconfigure(1, weight=1)
            self._media_browse_data.window.grid_columnconfigure(2, weight=1)
            self._media_browse_data.window.grid_columnconfigure(3, weight=1)
            self._media_browse_data.media_id = None
            self._media_browse_data.media_type = None
            self._media_browse_data.page = 1
            self._media_browse_data.limit = BROWSING_PAGINATION
            self._media_browse_data.count = 0
            self._media_browse_data.items = None
            self._media_browse_data.main = None

        asyncio.run_coroutine_threadsafe(
            self.browse_media(self._media_browse_data, entity_id),
            self._worker._loop,
        )
        # else:
        #     self._media_browse_window.destroy()

    def reconnect(self):
        asyncio.run_coroutine_threadsafe(
            self._worker.reconnect(),
            self._worker._loop,
        )

    def setup_open(self):
        if self._setup_data.window is None or not self._setup_data.window.winfo_exists():
            self._setup_data.window = tk.Toplevel(self, width=600, height=600)
            self._setup_data.window.grid_columnconfigure(0, weight=1)
            self._setup_data.window.grid_columnconfigure(1, weight=1)
            self._setup_data.window.grid_columnconfigure(2, weight=1)
            self._setup_data.window.grid_columnconfigure(3, weight=1)
        asyncio.run_coroutine_threadsafe(
            self._worker.start_setup(self._setup_reconfigure.get() == 1),
            self._worker._loop,
        )

    def setup_confirmation(self, confirm: bool):
        message = {"msg": "set_driver_user_data", "msg_data": {"confirm": confirm}}
        asyncio.run_coroutine_threadsafe(
            self._worker.send_request(message),
            self._worker._loop,
        )
        for widget in self._setup_data.window.winfo_children():
            widget.destroy()

    def setup_next(self):
        message = {"msg": "set_driver_user_data", "msg_data": {"input_values": {}}}
        settings: list[dict[str, Any]] = (
            self._setup_data.data.get("require_user_action", {}).get("input").get("settings")
        )
        for key, widget in self._setup_data.mapping.items():
            if isinstance(widget, tk.IntVar):
                if self._setup_data.mapping_type.get(key, "") == "number":
                    message["msg_data"]["input_values"][key] = widget.get()
                else:
                    message["msg_data"]["input_values"][key] = "true" if widget.get() == 1 else "false"
            elif isinstance(widget, ttk.Combobox):
                entries = [x for x in settings if x.get("id", "") == key]
                if len(entries) == 0:
                    continue
                entry = entries[0]
                selected_entry = [
                    x
                    for x in entry.get("field", {}).get("dropdown", {}).get("items", [])
                    if get_locale(x.get("label", {})) == widget.get()
                ]
                if len(selected_entry) == 0:
                    _LOG.error("No matching entries found in dropdown %s for selected value %s", entry, widget.get())
                    continue
                message["msg_data"]["input_values"][key] = selected_entry[0].get("id", "")
            elif isinstance(widget, tk.Text):
                message["msg_data"]["input_values"][key] = widget.get("1.0", tk.END)
            else:
                message["msg_data"]["input_values"][key] = widget.get()
        asyncio.run_coroutine_threadsafe(
            self._worker.send_request(message),
            self._worker._loop,
        )
        for widget in self._setup_data.window.winfo_children():
            widget.destroy()

    def setup_action(self, data: dict[str, Any]):
        try:
            if self._setup_data.window is None or not self._setup_data.window.winfo_exists():
                self._setup_data.window = tk.Toplevel(self, width=650, height=600)
                self._setup_data.window.grid_columnconfigure(0, weight=1, pad=2)
                self._setup_data.window.grid_columnconfigure(1, weight=1, pad=2)
                self._setup_data.window.grid_columnconfigure(2, weight=1, pad=2)
                self._setup_data.window.grid_columnconfigure(3, weight=1, pad=2)
                self._setup_data.window.grid_propagate(False)
                self._setup_data.window.minsize(650, 600)
            if self._setup_data.window is not None:
                for widget in self._setup_data.window.winfo_children():
                    widget.destroy()
                self._setup_data.window.grid_propagate(False)
                self._setup_data.window.minsize(650, 600)
            self._setup_data.mapping = {}
            self._setup_data.mapping_type = {}
            row = 0
            column = 0
            input_data = data.get("require_user_action", {}).get("input")
            if input_data is None and (confirmation := data.get("require_user_action", {}).get("confirmation")):
                if title := get_locale(confirmation.get("title", {})):
                    label = tk.Label(self._setup_data.window, text=title, wraplength=300)
                    label.grid(row=row, column=column, columnspan=4, sticky="we")
                    row += 1
                if message1 := get_locale(confirmation.get("message1", {})):
                    label = tk.Label(self._setup_data.window, text=message1, wraplength=300)
                    label.grid(row=row, column=column, columnspan=4, sticky="we")
                    row += 1
                submit_button = ttk.Button(
                    self._setup_data.window, text="Yes", command=lambda: self.setup_confirmation(True)
                )
                submit_button.grid(row=row, column=0)
                cancel_button = ttk.Button(
                    self._setup_data.window, text="No", command=lambda: self.setup_confirmation(False)
                )
                cancel_button.grid(row=row, column=1)
                self.update()
                return

            if input_data is None:
                if state := data.get("state"):
                    label = tk.Label(self._setup_data.window, text=state)
                    label.grid(row=row, column=column, columnspan=4)
                    row += 1
                if error := data.get("error"):
                    label = tk.Label(self._setup_data.window, text=error)
                    label.grid(row=row, column=column, columnspan=4)
                    row += 1
                self.update()
                return

            if input_field := input_data.get("title"):
                label = tk.Label(self._setup_data.window, text=get_locale(input_field), wraplength=300)
                label.grid(row=row, column=column, columnspan=4, sticky="we")
                row += 1
            if settings := input_data.get("settings"):
                self._setup_data.data = data
                for setting in settings:
                    column = 0
                    field_id = setting.get("id", "")
                    if field := setting.get("label"):
                        label = tk.Label(self._setup_data.window, text=get_locale(field), wraplength=300)
                        label.grid(row=row, column=column, columnspan=2, sticky="w")
                        column += 2
                    if field := setting.get("field"):
                        if dropdown := field.get("dropdown"):
                            combo = ttk.Combobox(self._setup_data.window, state="readonly", justify="left")
                            combo.grid(row=row, column=column, columnspan=2, sticky="we")
                            combo["values"] = [get_locale(x.get("label", {})) for x in dropdown.get("items", [])]
                            current_value = [
                                x for x in dropdown.get("items", []) if x.get("id") == dropdown.get("value", "")
                            ]
                            if len(current_value) > 0:
                                combo.set(get_locale(current_value[0].get("label", {})))
                            else:
                                _LOG.warning(
                                    "No default entry found in dropdown %s for selected value %s",
                                    dropdown,
                                    dropdown.get("value", ""),
                                )
                            self._setup_data.mapping[field_id] = combo
                            self._setup_data.mapping_type[field_id] = "dropdown"
                        elif text := field.get("text"):
                            entry_text = tk.StringVar()
                            text_field = ttk.Entry(self._setup_data.window, textvariable=entry_text)
                            value = text.get("value", "")
                            if value is None:
                                value = ""
                            entry_text.set(value)
                            text_field.grid(row=row, column=column, columnspan=2, sticky="we")
                            self._setup_data.mapping[field_id] = entry_text
                            self._setup_data.mapping_type[field_id] = "text"
                        elif text := field.get("password"):
                            entry_text = tk.StringVar()
                            text_field = ttk.Entry(self._setup_data.window, textvariable=entry_text)
                            value = text.get("value", "")
                            if value is None:
                                value = ""
                            entry_text.set(value)
                            text_field.grid(row=row, column=column, columnspan=2, sticky="we")
                            self._setup_data.mapping[field_id] = entry_text
                            self._setup_data.mapping_type[field_id] = "password"
                        elif text := field.get("textarea"):
                            text_area = tk.Text(self._setup_data.window, height=10)
                            value = text.get("value", "")
                            if value is None:
                                value = ""
                            text_area.insert("1.0", value)
                            text_area.grid(row=row, column=column, columnspan=2, sticky="we")
                            self._setup_data.mapping[field_id] = text_area
                            self._setup_data.mapping_type[field_id] = "textarea"
                        elif checkbox := field.get("checkbox"):
                            var = tk.IntVar(value=1 if checkbox.get("value", "false") == "true" else 0)
                            checkbox_button = tk.Checkbutton(
                                self._setup_data.window, variable=var, onvalue=1, offvalue=0
                            )
                            checkbox_button.grid(row=row, column=column, columnspan=2, sticky="w")
                            self._setup_data.mapping[field_id] = var
                            self._setup_data.mapping_type[field_id] = "checkbox"
                        elif label := field.get("label"):
                            label_field = ttk.Label(
                                self._setup_data.window, text=get_locale(label.get("value", {})), wraplength=300
                            )
                            label_field.grid(row=row, column=column, columnspan=4 - column, sticky="we")
                        elif text := field.get("number"):
                            entry_text = tk.IntVar()
                            text_field = ttk.Entry(self._setup_data.window, textvariable=entry_text)
                            entry_text.set(text.get("value", 0))
                            text_field.grid(row=row, column=column, columnspan=2, sticky="we")
                            self._setup_data.mapping[field_id] = entry_text
                            self._setup_data.mapping_type[field_id] = "number"
                    row += 1

                submit_button = ttk.Button(self._setup_data.window, text="Next", command=lambda: self.setup_next())
                submit_button.grid(row=row, column=0)
                self.update()
        except Exception as ex:
            _LOG.exception("Error %s", ex)


class WorkerThread(threading.Thread):

    def __init__(self, interface: RemoteInterface) -> None:
        super().__init__(daemon=True)
        self._interface = interface
        self._loop: AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._ws: RemoteWebsocket | None = None
        self._entity_ids: list[str] = []
        self._sensors: dict[str, dict[str, Any]] = {}
        self._selectors: dict[str, Selector] = {}
        self._entities: list[dict[str, Any]] = []
        self._attributes: dict[str, dict[str, Any]] = {}
        # self.start()

    @property
    def entity_ids(self) -> list[str]:
        return self._entity_ids

    async def reconnect(self):
        await self.disconnect()
        try:
            self._loop.create_task(self.launch_server())
        except Exception as e:
            _LOG.exception("Error initialising server %s", e)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        try:
            self._loop.create_task(self.launch_server())
        except Exception as e:
            _LOG.exception("Error initialising server %s", e)
            return
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        res = [x for x in self._entities if x.get("entity_id") == entity_id]
        if len(res) > 0:
            return res[0]
        return None

    def has_feature(self, entity_id: str, feature: str) -> bool:
        entity = self.get_entity(entity_id)
        if entity is None:
            return False
        if feature in entity["features"]:
            return True
        return False

    async def send_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if self._ws is None:
            _LOG.error("Command %s error : no websocket connected", command)
            return None
        return await self._ws.send_command(command)

    async def send_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if self._ws is None:
            _LOG.error("Send message %s error : no websocket connected", message)
            return None
        return await self._ws.send_request_and_wait(message)

    async def start_setup(self, reconfigure=False):
        return await self._ws.start_setup(reconfigure)

    async def browse_media(
        self,
        entity_id: str,
        media_id: str | None = None,
        media_type: str | None = None,
        paging: dict[str, Any] | None = None,
    ):
        if self._ws is None:
            _LOG.error("Browse %s error : no websocket connected", media_id)
            return None
        return await self._ws.browse_media_entity(entity_id, media_id, media_type, paging)

    async def search_media(
        self,
        entity_id: str,
        query: str,
        media_id: str | None = None,
        media_type: str | None = None,
        paging: dict[str, Any] | None = None,
    ):
        if self._ws is None:
            _LOG.error("Search media %s error : no websocket connected", media_id)
            return None
        return await self._ws.search_media_entity(entity_id, query, media_id, media_type, paging)

    def get_media_player_entity(self) -> dict[str, Any] | None:
        media_entity = self._interface.get_media_player()
        if media_entity is None or media_entity == "":
            return None
        for entity in self._entities:
            name = get_entity_name(entity)
            if name == media_entity:
                return entity
        return None

    def get_media_player_entity_id(self) -> str | None:
        entity = self.get_media_player_entity()
        if entity:
            return entity.get("entity_id")
        return None

    def get_attributes(self, entity_id: str) -> dict[str, Any] | None:
        return self._attributes.get(entity_id)

    async def update_attributes(self, updated_data: dict[str, Any]):
        if "attributes" not in updated_data:
            return
        attributes: dict[str, Any] = updated_data["attributes"]
        entity_id = updated_data["entity_id"]
        if self._attributes.get(entity_id) is None:
            self._attributes[entity_id] = {}
        self._attributes[entity_id] = self._attributes[entity_id] | attributes
        if updated_data.get("entity_type", "") == "sensor" and entity_id in self._sensors:
            current_attributes = self._sensors[entity_id]
            name = attributes.get("name", current_attributes.get("name", ""))
            value = attributes.get("value", current_attributes.get("value", ""))
            state = attributes.get("state", current_attributes.get("state", ""))
            current_attributes["value"] = value
            current_attributes["state"] = state
            self._interface._ui_queue.put(
                lambda eid=entity_id, n=name, v=value, s=state: self._interface.set_sensor(eid, n, v, s)
            )
            return

        if updated_data.get("entity_type", "") == "select" and entity_id in self._selectors:
            entry = self._selectors[entity_id]
            if "current_option" in attributes:
                entry.current_option = attributes["current_option"]
            if "options" in attributes:
                entry.options = attributes["options"]
            self._interface._ui_queue.put(
                lambda eid=entity_id, name=entry.name: self._interface.set_selector(eid, name, entry)
            )
            return

        if updated_data.get("entity_type", "") != "media_player":
            return
        # Find selected media entity and update only this one
        media_entity = self._interface.get_media_player()
        if media_entity is None or media_entity == "":
            return
        match = False
        for entity in self._entities:
            local_entity_id = entity.get("entity_id")
            if local_entity_id != entity_id:
                continue
            name = get_entity_name(entity)
            if name == media_entity:
                match = True
                break
        if not match:
            return
        _LOG.debug("Current media entity %s (%s)", media_entity, entity_id)

        # _LOG.debug("Update media entity %s", entity_id)
        if "media_image_url" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_image_url"]: self._interface.load_image(u))
        if "media_title" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_title"]: self._interface.set_title(u))
        if "media_artist" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_artist"]: self._interface.set_artist(u))
        if "state" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["state"]: self._interface.set_state(u))
            self._interface._ui_queue.put(lambda: self._interface.update_position())
        if "volume" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["volume"]: self._interface.set_volume(u))
        if "media_position" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_position"]: self._interface.set_position(u))
        if "source_list" in attributes or "source" in attributes:
            self._interface._ui_queue.put(lambda: self._interface.update_input_source())
        if "sound_mode" in attributes or "sound_mode_list" in attributes:
            self._interface._ui_queue.put(lambda: self._interface.update_sound_mode())
        await asyncio.sleep(0)

    async def entity_changed(self, msg: dict[str, Any]) -> None:
        dump_msg = json.loads(json.dumps(msg))
        if (
            (attributes := dump_msg.get("msg_data", {}).get("attributes", {}))
            and (url := attributes.get("media_image_url"))
            and len(url) > DUMP_MAX_LENGTH
        ):
            attributes["media_image_url"] = url[:DUMP_MAX_LENGTH]
        _LOG.debug("Entity changed : %s", dump_msg)
        updated_data: dict[str, Any] | None = msg.get("msg_data", None)
        if updated_data is None:
            return
        print_json(json=json.dumps(dump_msg))
        await self.update_attributes(updated_data)

    async def driver_setup_changed(self, msg: dict[str, Any]) -> None:
        _LOG.debug("Driver setup changed : %s", msg)
        print_json(json=json.dumps(msg))
        msg_data = msg.get("msg_data", None)
        if msg_data is None:  # or msg_data.get("state") != "WAIT_USER_ACTION":
            return
        self._interface._ui_queue.put(lambda data=msg_data: self._interface.setup_action(data))

    def change_media_player(self, new_entity: str):
        self._interface.set_title("")
        self._interface.set_artist("")
        self._interface.set_volume(0)
        self._interface.load_image("")
        self._interface.update_position()
        self._interface.browsing_support(False)
        self._interface.media_search_support(False)
        for entity in self._entities:
            entity_id = entity.get("entity_id")
            name = get_entity_name(entity)
            if name == new_entity:
                attributes = self._attributes.get(entity_id, None)
                if attributes is None:
                    return
                _LOG.debug("Reloading attributes for new entity %s : %s", entity_id, attributes)
                browsing_support = self.has_feature(entity_id, "browse_media")
                self._interface.browsing_support(browsing_support)
                self._interface.media_search_support(self.has_feature(entity_id, "search_media"))
                asyncio.run_coroutine_threadsafe(
                    self.update_attributes(entity | {"attributes": attributes}),
                    self._loop,
                )

    async def launch_server(self):
        _LOG.debug("Start connection")
        media_player_entity_id = ""
        try:
            self._ws = RemoteWebsocket(self._loop)
            self._ws.subscribe_events("entity_change", self.entity_changed)
            self._ws.subscribe_events("driver_setup_change", self.driver_setup_changed)
            await self._ws.websocket_connect()
            await asyncio.sleep(1)
            data = await self._ws.get_driver_vertion()
            _LOG.debug("Driver version : %s", data)
            data = await self._ws.get_available_entities()
            _LOG.debug("Available entities")
            print_json(json=json.dumps(data))
            self._entity_ids = []
            self._entities = []
            media_players: list[str] = []
            for entity in data["msg_data"]["available_entities"]:
                self._entities.append(entity)
                entity_id: str = entity["entity_id"]
                self._entity_ids.append(entity_id)
                if entity.get("entity_type", "") == "media_player":
                    media_players.append(get_entity_name(entity))
                if entity.get("entity_type", "") == "sensor":
                    self._sensors[entity_id] = {
                        "name": get_locale(entity["name"]) if get_locale(entity["name"]) else entity_id,
                        "state": "",
                    }
                if entity.get("entity_type", "") == "select":
                    self._selectors[entity_id] = Selector(
                        name=get_locale(entity["name"]) if get_locale(entity["name"]) else entity_id,
                        current_option="",
                        options=[],
                    )

            data = await self._ws.subscribe_entities(self._entity_ids)
            _LOG.debug("Subscribed entities : %s", data)
            await asyncio.sleep(2)
            # data = await self._ws.send_command(
            #     {"cmd_id": "on", "entity_id": media_player_entity_id, "entity_type": "media_player", "params": {}}
            # )
            # _LOG.debug("Command result : %s", data)
            data = await self._ws.get_entity_states()
            _LOG.debug("Entities states : %s", data)
            for entity_state in data["msg_data"]:
                self._loop.create_task(self.update_attributes(entity_state))
            self._interface.set_media_players(media_players)
            if len(media_players) > 0:
                self._interface.set_media_player(media_players[0])
                event = tk.Event()
                event.widget = self._interface._media_players
                self._interface.change_media_player(event)

        except Exception as e:
            _LOG.exception("Error launching websocket server %s", e)

    async def disconnect(self) -> None:
        _LOG.debug("Disconnect")
        if self._ws is not None:
            await self._ws.disconnect()


async def main():
    interface = RemoteInterface()
    worker: WorkerThread = WorkerThread(interface)
    interface.set_worker(worker)
    events = AsyncIOEventEmitter(_LOOP)
    events.on(Events.EXITING, worker.disconnect)
    worker.start()
    interface.mainloop()


if __name__ == "__main__":
    _LOG = logging.getLogger(__name__)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logging.basicConfig(handlers=[ch])
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    _LOOP.run_until_complete(main())
