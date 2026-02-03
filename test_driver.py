"""
Test connection script for Kodi integration driver.

:copyright: (c) 2025 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

# pylint: disable=all
# flake8: noqa

import asyncio
import io
import json
import logging
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from asyncio import AbstractEventLoop, Future, Queue, Task
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from tkinter import ttk
from typing import Any, Callable

sys.path.insert(1, "src")
import requests
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from PIL import Image, ImageTk
from pyee.asyncio import AsyncIOEventEmitter
from rich import print_json

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


def load_image_from_url(url: str, max_size=(500, 500)) -> ImageTk.PhotoImage:
    # Télécharge l'image
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    # Ouvre l'image depuis les bytes
    img = Image.open(io.BytesIO(resp.content))

    # Optionnel : redimensionne pour rentrer dans la fenêtre
    img.thumbnail(max_size)

    return ImageTk.PhotoImage(img)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

DRIVER_PORT = os.getenv("UC_INTEGRATION_HTTP_PORT", 9090)
DRIVER_URL = f"ws://{get_local_ip()}:{DRIVER_PORT}/ws"
MAIN_WS_MAX_MSG_SIZE = 8 * 1024 * 1024  # 8Mb
WS_TIMEOUT = 5


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
        self.client_session = ClientSession()
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

    async def _rx_msgs_main_ws(self, web_socket: ClientWebSocketResponse) -> None:
        """Receive messages from main websocket connection."""
        async for raw_msg in web_socket:
            _LOG.debug("receive: %s", raw_msg)
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


class RemoteInterface(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self._worker: WorkerThread | None = None
        self.title("Remote Interface")
        # self.geometry("800x600")
        self.maxsize(1920, 1080)
        self._row = 0
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        # self.container = ttk.Frame(self, padding=12)
        # self.container.pack(fill="both", expand=True)
        self._left_frame = ttk.Frame(self, width=300, height=600)
        self._left_frame.pack(side="left", fill="both", padx=10, pady=5, expand=True)
        # self._left_frame.grid(row=0, column=3, padx=10, pady=5)
        self._right_frame = ttk.Frame(self, width=650, height=600)
        self._right_frame.pack(side="right", fill="both", padx=10, pady=5, expand=True)
        self._image_label = ttk.Label(self._right_frame, text="Artwork")
        self._image_label.pack(anchor="w")
        # self._right_frame.grid(row=0, column=1, padx=10, pady=5)

        self._title_field = ttk.Label(self._left_frame, text="Title")
        self._title_field.grid(row=self._row, column=0, columnspan=3)  # pack(anchor="w", pady=(0, 10))
        self._row += 1
        self._artist = ttk.Label(self._left_frame, text="Artist")
        self._artist.grid(row=self._row, column=0, columnspan=3)  # .pack(anchor="w", pady=(0, 10))
        self._row += 1
        self._state = ttk.Label(self._left_frame, text="State")
        self._state.grid(row=self._row, column=0, columnspan=2)  # .pack(anchor="w", pady=(0, 10))
        self._volume = ttk.Label(self._left_frame, text="Volume")
        self._volume.grid(row=self._row, column=2)  # .pack(anchor="w", pady=(0, 10))
        self._row += 1
        command = ttk.Button(self._left_frame, text="Off", command=lambda: self.media_player_command("off"))
        command.grid(row=self._row, column=0)
        self._command_on = ttk.Button(self._left_frame, text="On", command=lambda: self.media_player_command("on"))
        self._command_on.grid(row=self._row, column=1)
        self._row += 1
        self._command_play_pause = ttk.Button(
            self._left_frame, text="Play/pause", command=lambda: self.media_player_command("play_pause")
        )
        self._command_stop = ttk.Button(
            self._left_frame, text="Stop", command=lambda: self.media_player_command("stop")
        )
        self._command_stop.grid(row=self._row, column=0)
        self._command_play_pause.grid(row=self._row, column=1)
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
        self._loop = asyncio.get_running_loop()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self.poll_queue)
        self._photo: tk.PhotoImage | None = None
        self._artwork: ttk.Label | None = None
        self._events = AsyncIOEventEmitter(self._loop)

    def set_worker(self, worker: Any) -> None:
        self._worker = worker

    def media_player_command(self, cmd_id: str) -> None:
        _LOG.debug("Media Player Command %s", cmd_id)
        if self._worker is None:
            _LOG.error("Media Player Command undefined worker")
            return
        entity_id = next(
            (x.get("entity_id", "") for x in self._worker._entities if x.get("entity_type", "") == "media_player")
        )
        if entity_id is None:
            _LOG.error("No Media Player entity not found for command %s (%s)", cmd_id, self._worker.entity_ids)
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_command(
                    {
                        "cmd_id": cmd_id,
                        "entity_id": entity_id,
                        "entity_type": "media_player",
                        "params": {},
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
        try:
            _LOG.debug("Loading new image from URL: %s", url)
            self._photo = load_image_from_url(url)
            if self._artwork is None:
                self._artwork = ttk.Label(self._right_frame)
                self._artwork.pack(anchor="w", fill="both", expand=True)
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
        self.update()

    def set_sensor(self, entity_id: str, name: str, value: str, state: str) -> None:
        _LOG.debug("Setting sensor %s %s", entity_id, value)
        if entity_id not in self._sensors:
            label = self._sensors[entity_id] = ttk.Label(self._left_frame, text="")
            label.grid(row=self._row, column=0, columnspan=3)
            self._row += 1
            self._sensors[entity_id] = label
        self._sensors[entity_id]["text"] = f"{name}({state}): {value}"
        self.update()

    def set_selector(self, entity_id: str, name: str, selector: Selector) -> None:
        _LOG.debug("Setting selector %s %s", entity_id, selector)
        if entity_id not in self._selectors:
            label = ttk.Label(self._left_frame, text=f"{name} :")
            label.grid(row=self._row, column=0, columnspan=3)
            self._row += 1
            combo = self._selectors[entity_id] = ttk.Combobox(self._left_frame, state="readonly")
            combo.bind(
                "<<ComboboxSelected>>",
                lambda event, eid=entity_id, cmd_id="select_option": self.selector_command(event, eid, cmd_id),
            )
            combo.grid(row=self._row, column=0, columnspan=3)
            self._row += 1
            self._selectors[entity_id] = combo
        combo = self._selectors[entity_id]
        combo["values"] = selector.options
        combo.set(selector.current_option)
        self.update()


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
        # self.start()

    @property
    def entity_ids(self) -> list[str]:
        return self._entity_ids

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

    async def send_command(self, command: dict[str, Any]) -> dict[str, Any] | None:
        if self._ws is None:
            _LOG.error("Command %s error : no websocket connected", command)
            return None
        return await self._ws.send_command(command)

    async def entity_changed(self, msg: dict[str, Any]) -> None:
        _LOG.debug("Entity changed : %s", msg)
        updated_data: dict[str, Any] | None = msg.get("msg_data", None)
        if updated_data is None:
            return
        print_json(json=json.dumps(msg))
        if "attributes" not in updated_data:
            return
        attributes: dict[str, Any] = updated_data["attributes"]
        entity_id = updated_data["entity_id"]
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
        if "media_image_url" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_image_url"]: self._interface.load_image(u))
        if "media_title" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_title"]: self._interface.set_title(u))
        if "media_artist" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["media_artist"]: self._interface.set_artist(u))
        if "state" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["state"]: self._interface.set_state(u))
        if "volume" in attributes:
            self._interface._ui_queue.put(lambda u=attributes["volume"]: self._interface.set_volume(u))

    async def launch_server(self):
        _LOG.debug("Start connection")
        media_player_entity_id = ""
        try:
            self._ws = RemoteWebsocket(self._loop)
            self._ws.subscribe_events("entity_change", self.entity_changed)
            await self._ws.websocket_connect()
            await asyncio.sleep(1)
            data = await self._ws.get_driver_vertion()
            _LOG.debug("Driver version : %s", data)
            data = await self._ws.get_available_entities()
            _LOG.debug("Available entities")
            print_json(json=json.dumps(data))
            self._entity_ids = []
            self._entities = []
            for entity in data["msg_data"]["available_entities"]:
                self._entities.append(entity)
                entity_id: str = entity["entity_id"]
                self._entity_ids.append(entity_id)
                if entity_id.startswith("media_player"):
                    media_player_entity_id = entity_id
                if entity.get("entity_type", "") == "sensor":
                    self._sensors[entity_id] = {"name": entity["name"].get("en", entity_id), "state": ""}
                if entity.get("entity_type", "") == "select":
                    self._selectors[entity_id] = Selector(
                        name=entity["name"].get("en", entity_id), current_option="", options=[]
                    )

            data = await self._ws.subscribe_entities(self._entity_ids)
            _LOG.debug("Subscribed entities : %s", data)
            await asyncio.sleep(5)
            # data = await self._ws.send_command(
            #     {"cmd_id": "on", "entity_id": media_player_entity_id, "entity_type": "media_player", "params": {}}
            # )
            # _LOG.debug("Command result : %s", data)
            data = await self._ws.get_entity_states()
            _LOG.debug("Entities states : %s", data)
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
