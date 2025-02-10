"""Constants used for LG webOS Smart TV."""

import asyncio
from enum import IntEnum
from xmlrpc.client import ProtocolError

from aiohttp import ServerTimeoutError
from aiowebostv import WebOsTvCommandError
from httpx import TransportError
from ucapi.media_player import Features
from ucapi.ui import DeviceButtonMapping, Buttons, UiPage
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

LIVE_TV_APP_ID = "com.webos.app.livetv"

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
    Features.SELECT_SOUND_MODE
]

WEBOSTV_EXCEPTIONS = (
    OSError,
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionRefusedError,
    WebOsTvCommandError,
    TimeoutError,
    asyncio.CancelledError,
    TransportError,
    ProtocolError,
    ServerTimeoutError,
)

LG_SOUND_OUTPUTS: dict[str, str] = {
    "tv_speaker":"Internal TV speaker",
    "external_optical":"Optical",
    "external_arc":"HDMI Arc",
    "lineout":"Line out",
    "headphone":"Headphones",
    "external_speaker":"Audio out (optical/hdmi arc)",
    "tv_external_speaker":"TV speaker and optical",
    "tv_speaker_headphone":"TV speaker and headphones",
    "bt_soundbar":"Bluetooth soundbar and bluetooth devices",
    "soundbar":"Soundbar optical"
}

# Custom commands to be handled specifically
LG_SIMPLE_COMMANDS_CUSTOM = [
    "INPUT_SOURCE"  # Next input source
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
    *LG_SIMPLE_COMMANDS_CUSTOM
]

LG_REMOTE_BUTTONS_MAPPING: [DeviceButtonMapping] = [
    {"button": Buttons.BACK, "short_press": {"cmd_id": "BACK"}},
    {"button": Buttons.HOME, "short_press": {"cmd_id": "HOME"}},
    {"button": Buttons.CHANNEL_DOWN, "short_press": {"cmd_id": "CHANNELDOWN"}},
    {"button": Buttons.CHANNEL_UP, "short_press": {"cmd_id": "CHANNELUP"}},
    {"button": Buttons.DPAD_UP, "short_press": {"cmd_id": "UP"}},
    {"button": Buttons.DPAD_DOWN, "short_press": {"cmd_id": "DOWN"}},
    {"button": Buttons.DPAD_LEFT, "short_press": {"cmd_id": "LEFT"}},
    {"button": Buttons.DPAD_RIGHT, "short_press": {"cmd_id": "RIGHT"}},
    {"button": Buttons.DPAD_MIDDLE, "short_press": {"cmd_id": "ENTER"}},
    {"button": Buttons.PLAY, "short_press": {"cmd_id": "PAUSE"}},
    {"button": Buttons.PREV, "short_press": {"cmd_id": "REWIND"}},
    {"button": Buttons.NEXT, "short_press": {"cmd_id": "FASTFORWARD"}},
    {"button": Buttons.VOLUME_UP, "short_press": {"cmd_id": "VOLUMEUP"}},
    {"button": Buttons.VOLUME_DOWN, "short_press": {"cmd_id": "VOLUMEDOWN"}},
    {"button": Buttons.MUTE, "short_press": {"cmd_id": "MUTE"}},
]

LG_REMOTE_UI_PAGES: [UiPage] = [
    {
        "page_id": "LG commands",
        "name": "LG commands",
        "grid": {"width": 4, "height": 6},
        "items": [
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "toggle", "repeat": 1}
                },
                "icon": "uc:power-on",
                "location": {
                    "x": 0,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "INFO", "repeat": 1}
                },
                "icon": "uc:info",
                "location": {
                    "x": 1,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "AD", "repeat": 1}
                },
                "icon": "uc:language",
                "location": {
                    "x": 2,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "CC", "repeat": 1}
                },
                "icon": "uc:cc",
                "location": {
                    "x": 3,
                    "y": 0
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "MYAPPS", "repeat": 1}
                },
                "icon": "uc:home",
                "location": {
                    "x": 0,
                    "y": 1
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "MENU", "repeat": 1}
                },
                "text": "Settings",
                "location": {
                    "x": 1,
                    "y": 1
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "INPUT_SOURCE", "repeat": 1}
                },
                "text": "Input",
                "location": {
                    "x": 2,
                    "y": 1
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "3D_MODE", "repeat": 1}
                },
                "text": "3D",
                "location": {
                    "x": 3,
                    "y": 1
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "text"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "REWIND", "repeat": 1}
                },
                "icon": "uc:bw",
                "location": {
                    "x": 0,
                    "y": 2
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "PLAY", "repeat": 1}
                },
                "icon": "uc:play",
                "location": {
                    "x": 1,
                    "y": 2
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "FASTFORWARD", "repeat": 1}
                },
                "icon": "uc:ff",
                "location": {
                    "x": 3,
                    "y": 2
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "STOP", "repeat": 1}
                },
                "icon": "uc:stop",
                "location": {
                    "x": 0,
                    "y": 3
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "PAUSE", "repeat": 1}
                },
                "icon": "uc:pause",
                "location": {
                    "x": 1,
                    "y": 3
                },
                "size": {
                    "height": 1,
                    "width": 2
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "CHANNELUP", "repeat": 1}
                },
                "icon": "uc:up-arrow",
                "location": {
                    "x": 3,
                    "y": 3
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "CHANNELDOWN", "repeat": 1}
                },
                "icon": "uc:down-arrow",
                "location": {
                    "x": 3,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "ASPECT_RATIO", "repeat": 1}
                },
                "icon": "uc:arrows-maximize",
                "location": {
                    "x": 0,
                    "y": 4
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "MUTE", "repeat": 1}
                },
                "icon": "uc:mute",
                "location": {
                    "x": 0,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "VOLUMEDOWN", "repeat": 1}
                },
                "icon": "uc:minus",
                "location": {
                    "x": 1,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
            {
                "command": {
                    "cmd_id": "remote.send",
                    "params": {"command": "VOLUMEUP", "repeat": 1}
                },
                "icon": "uc:plus",
                "location": {
                    "x": 2,
                    "y": 5
                },
                "size": {
                    "height": 1,
                    "width": 1
                },
                "type": "icon"
            },
        ]
    },
    {
        "page_id": "LG numbers",
        "name": "LG numbers",
        "grid": {"height": 4, "width": 3},
        "items": [{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "1", "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "1",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "2", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "2",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "3", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "3",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "4", "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "4",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "5", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "5",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "6", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "6",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "7", "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "7",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "8", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "8",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "9", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "9",
            "type": "text"
        }, {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "0", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 3
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "0",
            "type": "text"
        }
        ]
    },
    {
        "page_id": "LG direction pad",
        "name": "LG direction pad",
        "grid": {"height": 3, "width": 3},
        "items": [{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "BACK", "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:back",
            "type": "icon"
        },{
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "UP", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:up-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "HOME", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 0
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:home",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "LEFT", "repeat": 1}
            },
            "location": {
                "x": 0,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:left-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "ENTER", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "OK",
            "type": "text"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "RIGHT", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 1
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:right-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "DOWN", "repeat": 1}
            },
            "location": {
                "x": 1,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "icon": "uc:down-arrow",
            "type": "icon"
        },
        {
            "command": {
                "cmd_id": "remote.send",
                "params": {"command": "EXIT", "repeat": 1}
            },
            "location": {
                "x": 2,
                "y": 2
            },
            "size": {
                "height": 1,
                "width": 1
            },
            "text": "Exit",
            "type": "text"
        },
        ]
    }
]