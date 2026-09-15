# LG TV integration for Remote Two Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

_Changes in the next release_

---

## v1.17.1 - 2026-09-15
### Fixed
- Close the LG input and main WebSocket sessions gracefully before cancelling receive tasks, avoiding abnormal close code 1006 and temporary reconnect blocking on some webOS TVs after Remote standby/network loss.

---

## v1.0.0 - 2024-04-25
### Initial release
