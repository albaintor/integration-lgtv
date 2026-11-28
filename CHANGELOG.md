# LG TV integration for Remote Two Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## v1.17.9 - 2026-11-28

### Changed
- Build self-contained ARM64 packages natively on GitHub Actions with Python 3.14 and PyInstaller, without the Unfolded Circle Docker builder.
- Use official aiowebostv 2.0.0 from PyPI instead of the Python 3.11 compatibility fork; retain the 1.17.8 pairing and connection changes.
- Run CI tests with Python 3.14 and validate ELF architecture, glibc baseline and frozen driver imports before publishing.

## v1.17.8 - 2026-11-27

### Changed
- Upgrade to aiowebostv 2.0.0 using a Python 3.11-compatible fork pinned to an immutable GitHub archive for Unfolded Circle builds.
- Use upstream bounded graceful WebSocket cleanup and retain the Remote-specific TCP/TLS diagnostics, heartbeat and restricted fallback policy.

### Fixed
- Preserve refreshed pairing keys and prevent overlapping registration attempts while waiting for a TV pairing prompt. Include upstream signed/unsigned manifest fallback, improved registration response handling and extended pairing timeout. Repeated prompts on webOS 26 require confirmation on affected hardware.

## v1.17.7 - 2026-11-25

### Fixed
- Cancel pending power-off commands when a newer power-on or input source selection is received, preventing the TV from switching off after reconnecting. Preserve unrelated queued commands and subsequent power-off requests. Cancelled deferred commands remain silent on the Remote (#33).

## v1.17.6 - 2026-11-24

### Added
- Optional HDMI-CEC child source discovery and selection, including devices behind an AV receiver. Enable it per TV in the setup or reconfiguration flow (disabled by default). Thanks to @joemacjr92 for the original contribution (#30).

### Changed
- Discover CEC sources asynchronously with bounded on-demand discovery during activity startup, event-driven refreshes rather than periodic polling, and no fixed selection delay.
- Persist published CEC source names, filter duplicate devices, and retain physical HDMI input cycling.
- Preserve acknowledgement of deferred commands; log subsequent failures without displaying misleading errors on the Remote. Report unavailable connections when commands cannot be retained, and propagate source selection status selectively.

### Fixed
- Prevent power-off commands from being lost during Remote standby recovery: use the registered main SSAP connection when available even if pointer setup is pending, otherwise queue the command immediately with a 60-second lifetime (#28).
- Send power-off without a preliminary power-state request, stop Wake-on-LAN retries, and log deferred-command failures.

---

## Earlier unreleased changes

### Changed
- Prefer the modern secure LG webOS WebSocket endpoint on port 3001, with legacy port 3000 fallback only when the secure endpoint is explicitly refused or rejects the WebSocket handshake.
- Increase the LG WebSocket connect timeout from 2 seconds to 6 seconds to allow slower TCP/TLS/WebSocket setup observed after Remote standby.
- Use a fresh unverified TLS context for every secure WebSocket connection, matching LG ConnectSDK's per-connect SSL context and avoiding TLS session state reuse across Remote standby/resume cycles.
- Increase the LG WebSocket heartbeat from 5 seconds to 30 seconds to tolerate short Remote Wi-Fi transitions while retaining dead-connection detection.
- Keep a single reconnect loop active and ignore duplicate reconnect triggers instead of forcing immediate retries from button presses.
- Make Wake-on-LAN best-effort for explicit power-on recovery: a transient `ENETUNREACH` can no longer terminate the reconnect loop, and WOL remains armed for subsequent retries until the TV becomes reachable.
- After `ENETUNREACH`/`EHOSTUNREACH`, switch to short raw TCP probes of LG ports 3001/3000 before resuming full TLS/WebSocket negotiation, so Remote LAN recovery is detected quickly without repeated multi-second connection attempts.
- Detect LAN-path outages even when `LGDevice.connect()` logs and absorbs the connector exception; a failed reconnect now checks endpoint reachability directly before applying the normal 5-second backoff.

### Fixed
- Prevent `EXIT_STANDBY` from sending Wake-on-LAN packets. Waking the Remote now reconnects to an already-on TV without powering on a sleeping TV (#26).

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