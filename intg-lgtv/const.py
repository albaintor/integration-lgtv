"""Constants used for LG webOS Smart TV."""

import asyncio
from xmlrpc.client import ProtocolError

from aiohttp import ServerTimeoutError
from aiowebostv import WebOsTvCommandError
from httpx import TransportError
from ucapi.media_player import Features
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
