# LG TV integration for Remote Two Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed
- Prefer the modern secure LG webOS WebSocket endpoint on port 3001, with legacy port 3000 fallback only when the secure endpoint is explicitly refused or rejects the WebSocket handshake.
- Increase the LG WebSocket connect timeout from 2 seconds to 6 seconds to allow slower TCP/TLS/WebSocket setup observed after Remote standby.
- Use a fresh unverified TLS context for every secure WebSocket connection, matching LG ConnectSDK's per-connect SSL context and avoiding TLS session state reuse across Remote standby/resume cycles.
- Increase the LG WebSocket heartbeat from 5 seconds to 30 seconds to tolerate short Remote Wi-Fi transitions while retaining dead-connection detection.
- Keep a single reconnect loop active and ignore duplicate reconnect triggers instead of forcing immediate retries from button presses.
- Make Wake-on-LAN best-effort during Remote wake: a transient `ENETUNREACH` can no longer terminate the reconnect loop, and `EXIT_STANDBY` keeps WOL armed for subsequent retries until the TV becomes reachable.

### Diagnostics
- Add detailed LG connection-stage logging for raw TCP connect, TLS handshake, negotiated TLS version/cipher, HTTP WebSocket upgrade, SSAP HELLO, pre-registration system information, and REGISTER.
- Log whether Wake-on-LAN is deferred because the Remote network is not ready or successfully sent on a reconnect retry.

---

## v1.17.1 - 2026-09-15
### Fixed
- Close the LG input and main WebSocket sessions gracefully before cancelling receive tasks, avoiding abnormal close code 1006 and temporary reconnect blocking on some webOS TVs after Remote standby/network loss.

---

## v1.0.0 - 2024-04-25
### Initial release