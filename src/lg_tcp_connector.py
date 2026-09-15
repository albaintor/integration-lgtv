"""aiohttp connector with separate TCP and TLS diagnostics for LG webOS."""

import asyncio
import logging
import sys
import time
from typing import Any

import aiohappyeyeballs
from aiohttp import TCPConnector
from aiohttp.client_exceptions import (
    ClientConnectorCertificateError,
    ClientConnectorError,
    ClientConnectorSSLError,
)
from aiohttp.connector import cert_errors, ssl_errors
from aiohttp.helpers import ceil_timeout

_LOG = logging.getLogger("lg")


class LGDiagnosticTCPConnector(TCPConnector):
    """TCPConnector that exposes the boundary between TCP and TLS setup.

    aiohttp's public TraceConfig reports connection creation as one combined
    stage. For the LG reconnect investigation we need to know whether the TV
    stops answering the TCP connect itself or whether TCP succeeds and the TLS
    handshake stalls. This override mirrors aiohttp 3.14.x
    ``TCPConnector._wrap_create_connection`` and adds logging only; it does not
    create any additional diagnostic socket.
    """

    async def _wrap_create_connection(
        self,
        *args: Any,
        addr_infos: list[Any],
        req: Any,
        timeout: Any,
        client_error: type[Exception] = ClientConnectorError,
        **kwargs: Any,
    ) -> tuple[asyncio.Transport, Any]:
        host = req.host
        port = req.port
        tcp_started = time.monotonic()
        using_tls = bool(kwargs.get("ssl"))

        try:
            async with ceil_timeout(
                timeout.sock_connect, ceil_threshold=timeout.ceil_threshold
            ):
                try:
                    sock = await aiohappyeyeballs.start_connection(
                        addr_infos=addr_infos,
                        local_addr_infos=self._local_addr_infos,
                        happy_eyeballs_delay=self._happy_eyeballs_delay,
                        interleave=self._interleave,
                        loop=self._loop,
                        socket_factory=self._socket_factory,
                    )
                except BaseException as ex:
                    _LOG.warning(
                        "LG NET TCP connect failed: %s:%s after %.3fs: %s: %r",
                        host,
                        port,
                        time.monotonic() - tcp_started,
                        type(ex).__name__,
                        ex,
                    )
                    raise

                _LOG.debug(
                    "LG NET TCP connected: %s:%s in %.3fs local=%r peer=%r",
                    host,
                    port,
                    time.monotonic() - tcp_started,
                    sock.getsockname(),
                    sock.getpeername(),
                )

                # Match aiohttp 3.14.x behaviour for SSL shutdown handling.
                if (
                    using_tls
                    and self._ssl_shutdown_timeout
                    and sys.version_info >= (3, 11)
                ):
                    kwargs["ssl_shutdown_timeout"] = self._ssl_shutdown_timeout

                tls_started: float | None = None
                if using_tls:
                    tls_started = time.monotonic()
                    _LOG.debug("LG NET TLS handshake start: %s:%s", host, port)

                try:
                    transport, protocol = await self._loop.create_connection(
                        *args, **kwargs, sock=sock
                    )
                except BaseException as ex:
                    if using_tls:
                        _LOG.warning(
                            "LG NET TLS handshake failed: %s:%s after %.3fs: %s: %r",
                            host,
                            port,
                            time.monotonic() - (tls_started or time.monotonic()),
                            type(ex).__name__,
                            ex,
                        )
                    raise

                if using_tls:
                    ssl_object = transport.get_extra_info("ssl_object")
                    _LOG.debug(
                        "LG NET TLS ready: %s:%s in %.3fs version=%s cipher=%r",
                        host,
                        port,
                        time.monotonic() - (tls_started or time.monotonic()),
                        ssl_object.version() if ssl_object is not None else None,
                        ssl_object.cipher() if ssl_object is not None else None,
                    )

                return transport, protocol
        except cert_errors as exc:
            raise ClientConnectorCertificateError(req.connection_key, exc) from exc
        except ssl_errors as exc:
            raise ClientConnectorSSLError(req.connection_key, exc) from exc
        except OSError as exc:
            if exc.errno is None and isinstance(exc, asyncio.TimeoutError):
                raise
            raise client_error(req.connection_key, exc) from exc
