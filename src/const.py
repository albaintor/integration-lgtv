"""Constants used for LG webOS Smart TV."""

import asyncio
from xmlrpc.client import ProtocolError

from aiohttp import ServerTimeoutError
from aiowebostv import WebOsTvCommandError
from aiowebostv.exceptions import WebOsTvError
from httpx import TransportError
from ucapi.media_player import Features
from ucapi.ui import Buttons, DeviceButtonMapping, UiPage
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

LIVE_TV_APP_ID = "com.webos.app.livetv"

LG_ADDITIONAL_ENDPOINTS = {
    "TAKE_SCREENSHOT": "tv/executeOneShot",
    "TURN_OFF_SCREEN_WO4": "com.webos.service.tv.power/turnOffScreen",
    "TURN_ON_SCREEN_WO4": "com.webos.service.tv.power/turnOnScreen",
    "LIST_DEVICES": "com.webos.service.attachedstoragemanager/listDevices",
    "LUNA_REBOOT_TV": "com.webos.service.tvpower/power/reboot",
    "LUNA_REBOOT_TV_WO4": "com.webos.service.tv.power/reboot",
    "LUNA_SET_DEVICE_INFO": "com.webos.service.eim/setDeviceInfo",
    "LUNA_EJECT_DEVICE": "com.webos.service.attachedstoragemanager/ejectDevice",
    "LUNA_SET_TPC": "com.webos.service.oledepl/setTemporalPeakControl",
    "LUNA_SET_GSR": "com.webos.service.oledepl/setGlobalStressReduction",
    "LUNA_SET_WHITE_BALANCE": "com.webos.service.pqcontroller/setWhiteBalance",
}

LG_FEATURES = [
    Features.ON_OFF,
    Features.TOGGLE,
    Features.VOLUME,
    Features.VOLUME_UP_DOWN,
    Features.MUTE_TOGGLE,
    Features.MUTE,
    Features.UNMUTE,
    Features.PLAY_PAUSE,
    Features.STOP,
    Features.NEXT,
    Features.PREVIOUS,
    Features.FAST_FORWARD,
    Features.REWIND,
    Features.MEDIA_TITLE,
    Features.MEDIA_IMAGE_URL,
    Features.MEDIA_TYPE,
    Features.DPAD,
    Features.NUMPAD,
    Features.HOME,
    Features.MENU,
    Features.CONTEXT_MENU,
    Features.GUIDE,
    Features.INFO,
    Features.COLOR_BUTTONS,
    Features.CHANNEL_SWITCHER,
    Features.SELECT_SOURCE,
    Features.AUDIO_TRACK,
    Features.SUBTITLE,
    Features.RECORD,
    Features.SETTINGS,
    Features.SELECT_SOUND_MODE,
]

WEBOSTV_EXCEPTIONS = (
    OSError,
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionRefusedError,
    WebOsTvCommandError,
    WebOsTvError,
    TimeoutError,
    asyncio.CancelledError,
    TransportError,
    ProtocolError,
    ServerTimeoutError,
)

LG_SOUND_OUTPUTS: dict[str, str] = {
    "tv_speaker": "Internal TV speaker",
    "external_optical": "Optical",
    "external_arc": "HDMI Arc",
    "lineout": "Line out",
    "headphone": "Headphones",
    "external_speaker": "Audio out (optical/hdmi arc)",
    "tv_external_speaker": "TV speaker and optical",
    "tv_speaker_headphone": "TV speaker and headphones",
    "bt_soundbar": "Bluetooth soundbar and bluetooth devices",
    "soundbar": "Soundbar optical",
}

# Custom commands to be handled specifically
LG_SIMPLE_COMMANDS_CUSTOM = [
    "INPUT_SOURCE",  # Next input source
    "TURN_SCREEN_ON",  # Turn screen On
    "TURN_SCREEN_OFF",  # Turn screen Off
    "TURN_SCREEN_ON4",  # Turn screen On WebOS4
    "TURN_SCREEN_OFF4",  # Turn screen Off WebOS4
]

# Simple commands for both media and remote entities
LG_SIMPLE_COMMANDS = [
    "ASTERISK",
    "3D_MODE",
    "AD",  # Audio Description toggle
    "AMAZON",
    "ASPECT_RATIO",  # Quick Settings Menu - Aspect Ratio
    "CC",  # Closed Captions
    "DASH",  # Live TV
    "EXIT",
    "GUIDE",
    "INPUT_HUB",  # Home Dashboard
    "LIST",  # Live TV
    "LIVE_ZOOM",  # Live Zoom
    "MAGNIFIER_ZOOM",  # Focus Zoom
    "MYAPPS",  # Home Dashboard
    "NETFLIX",
    "PAUSE",
    "PLAY",
    "POWER",  # Power button
    "PROGRAM",  # TV Guide
    "RECENT",  # Home Dashboard - Recent Apps
    "SAP",  # Multi Audio Setting
    "SCREEN_REMOTE",  # Screen Remote
    "TELETEXT",
    "TEXTOPTION",
    *LG_SIMPLE_COMMANDS_CUSTOM,
]

LG_REMOTE_BUTTONS_MAPPING: list[DeviceButtonMapping] = [
    DeviceButtonMapping(**{"button": Buttons.BACK, "short_press": {"cmd_id": "BACK"}}),
    DeviceButtonMapping(**{"button": Buttons.HOME, "short_press": {"cmd_id": "HOME"}}),
    DeviceButtonMapping(**{"button": Buttons.CHANNEL_DOWN, "short_press": {"cmd_id": "CHANNELDOWN"}}),
    DeviceButtonMapping(**{"button": Buttons.CHANNEL_UP, "short_press": {"cmd_id": "CHANNELUP"}}),
    DeviceButtonMapping(**{"button": Buttons.DPAD_UP, "short_press": {"cmd_id": "UP"}}),
    DeviceButtonMapping(**{"button": Buttons.DPAD_DOWN, "short_press": {"cmd_id": "DOWN"}}),
    DeviceButtonMapping(**{"button": Buttons.DPAD_LEFT, "short_press": {"cmd_id": "LEFT"}}),
    DeviceButtonMapping(**{"button": Buttons.DPAD_RIGHT, "short_press": {"cmd_id": "RIGHT"}}),
    DeviceButtonMapping(**{"button": Buttons.DPAD_MIDDLE, "short_press": {"cmd_id": "ENTER"}}),
    DeviceButtonMapping(**{"button": Buttons.PLAY, "short_press": {"cmd_id": "PAUSE"}}),
    DeviceButtonMapping(**{"button": Buttons.PREV, "short_press": {"cmd_id": "REWIND"}}),
    DeviceButtonMapping(**{"button": Buttons.NEXT, "short_press": {"cmd_id": "FASTFORWARD"}}),
    DeviceButtonMapping(**{"button": Buttons.VOLUME_UP, "short_press": {"cmd_id": "VOLUMEUP"}}),
    DeviceButtonMapping(**{"button": Buttons.VOLUME_DOWN, "short_press": {"cmd_id": "VOLUMEDOWN"}}),
    DeviceButtonMapping(**{"button": Buttons.MUTE, "short_press": {"cmd_id": "MUTE"}}),
]

LG_REMOTE_UI_PAGES: list[UiPage] = [
    UiPage(**{
        "page_id": "LG commands",
        "name": "LG commands",
        "grid": {"width": 4, "height": 6},
        "items": [
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "toggle"}},
                "icon": "uc:power-on",
                "location": {"x": 0, "y": 0},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "INFO"}},
                "icon": "uc:info",
                "location": {"x": 1, "y": 0},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "AD"}},
                "icon": "uc:language",
                "location": {"x": 2, "y": 0},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "CC"}},
                "icon": "uc:cc",
                "location": {"x": 3, "y": 0},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "MYAPPS"}},
                "icon": "uc:home",
                "location": {"x": 0, "y": 1},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "MENU"}},
                "text": "Settings",
                "location": {"x": 1, "y": 1},
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "INPUT_SOURCE"}},
                "text": "Input",
                "location": {"x": 2, "y": 1},
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "3D_MODE"}},
                "text": "3D",
                "location": {"x": 3, "y": 1},
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "REWIND"}},
                "icon": "uc:bw",
                "location": {"x": 0, "y": 2},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "PLAY"}},
                "icon": "uc:play",
                "location": {"x": 1, "y": 2},
                "size": {"height": 1, "width": 2},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "FASTFORWARD"}},
                "icon": "uc:ff",
                "location": {"x": 3, "y": 2},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "STOP"}},
                "icon": "uc:stop",
                "location": {"x": 0, "y": 3},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "PAUSE"}},
                "icon": "uc:pause",
                "location": {"x": 1, "y": 3},
                "size": {"height": 1, "width": 2},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "CHANNELUP"}},
                "icon": "uc:up-arrow",
                "location": {"x": 3, "y": 3},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "CHANNELDOWN"}},
                "icon": "uc:down-arrow",
                "location": {"x": 3, "y": 4},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "ASPECT_RATIO"}},
                "icon": "uc:arrows-maximize",
                "location": {"x": 0, "y": 4},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "MUTE"}},
                "icon": "uc:mute",
                "location": {"x": 0, "y": 5},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "VOLUMEDOWN"}},
                "icon": "uc:minus",
                "location": {"x": 1, "y": 5},
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "VOLUMEUP"}},
                "icon": "uc:plus",
                "location": {"x": 2, "y": 5},
                "type": "icon",
            },
        ],
    }),
    UiPage(**{
        "page_id": "LG numbers",
        "name": "LG numbers",
        "grid": {"height": 4, "width": 3},
        "items": [
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "1"}},
                "location": {"x": 0, "y": 0},
                "text": "1",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "2"}},
                "location": {"x": 1, "y": 0},
                "text": "2",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "3"}},
                "location": {"x": 2, "y": 0},
                "text": "3",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "4"}},
                "location": {"x": 0, "y": 1},
                "text": "4",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "5"}},
                "location": {"x": 1, "y": 1},
                "text": "5",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "6"}},
                "location": {"x": 2, "y": 1},
                "text": "6",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "7"}},
                "location": {"x": 0, "y": 2},
                "text": "7",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "8"}},
                "location": {"x": 1, "y": 2},
                "text": "8",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "9"}},
                "location": {"x": 2, "y": 2},
                "text": "9",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "0"}},
                "location": {"x": 1, "y": 3},
                "text": "0",
                "type": "text",
            },
        ],
    }),
    UiPage(**{
        "page_id": "LG direction pad",
        "name": "LG direction pad",
        "grid": {"height": 3, "width": 3},
        "items": [
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "BACK"}},
                "location": {"x": 0, "y": 0},
                "icon": "uc:back",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "UP"}},
                "location": {"x": 1, "y": 0},
                "icon": "uc:up-arrow",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "HOME"}},
                "location": {"x": 2, "y": 0},
                "icon": "uc:home",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "LEFT"}},
                "location": {"x": 0, "y": 1},
                "icon": "uc:left-arrow",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "ENTER"}},
                "location": {"x": 1, "y": 1},
                "text": "OK",
                "type": "text",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "RIGHT"}},
                "location": {"x": 2, "y": 1},
                "icon": "uc:right-arrow",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "DOWN"}},
                "location": {"x": 1, "y": 2},
                "icon": "uc:down-arrow",
                "type": "icon",
            },
            {
                "command": {"cmd_id": "remote.send", "params": {"command": "EXIT"}},
                "location": {"x": 2, "y": 2},
                "text": "Exit",
                "type": "text",
            },
        ],
    }),
]
