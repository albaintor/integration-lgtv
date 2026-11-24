"""Discover, validate, and select HDMI-CEC child devices on LG webOS."""

from dataclasses import dataclass
from typing import Any

CEC_EIM_STATUS = "com.webos.service.eim/getAllInputStatus"
CEC_LAUNCH_ENDPOINT = "com.webos.applicationManager/launch"
MAX_CEC_CHILDREN = 128
MAX_SOURCE_NAME_LENGTH = 256


@dataclass(frozen=True, slots=True)
class CecSelection:
    """Stable identity and parent context required to launch a CEC child."""

    parent_input_id: str
    parent_app_id: str
    unique_id: str


def scalar(value: Any) -> str | None:
    """Normalize a safe string or integer identifier."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        if value and len(value) <= 128 and not any(ord(char) < 32 for char in value):
            return value
    return None


def row_input_id(row: dict[str, Any]) -> str | None:
    """Return the physical input ID across known EIM response variants."""
    return scalar(row.get("inputId")) or scalar(row.get("id"))


def _identity(row: dict[str, Any]) -> tuple[str, str] | None:
    vendor = scalar(row.get("vendorId"))
    address = scalar(row.get("physicalAddress"))
    if not vendor or not address or address.lower() in {"0", "0x0", "0x0000"}:
        return None
    return vendor, address


def _parent_context(parent_id: str, label: Any) -> str:
    if parent_id.startswith("HDMI_"):
        port = parent_id.removeprefix("HDMI_")
        if port and port.isalnum():
            return f"HDMI {port}"
    safe_label = label.strip() if isinstance(label, str) else ""
    return safe_label or parent_id


def _safe_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if (
        not name
        or len(name) > MAX_SOURCE_NAME_LENGTH
        or any(ord(char) < 32 for char in name)
    ):
        return None
    return name


def discover_children(
    external_inputs: list[dict[str, Any]],
    eim_devices: list[dict[str, Any]],
    existing_names: set[str] | None = None,
) -> list[tuple[str, CecSelection]]:
    """Build stable, collision-safe labels and parent-scoped child selections.

    When sibling devices share an OSD name, every sibling receives its CEC ID
    suffix. This keeps labels attached to the same unique ID if EIM changes
    the order of its child records between refreshes.
    """
    existing = set(existing_names or ())
    top_level_names = {
        label.strip().casefold()
        for row in external_inputs
        if isinstance((label := row.get("label")), str) and label.strip()
    }
    top_level_identities = {
        value for row in external_inputs if (value := _identity(row)) is not None
    }
    discovered: list[tuple[str, CecSelection]] = []
    seen_children: set[tuple[str, str]] = set()
    seen_parent_identities: set[tuple[str, str, str]] = set()
    for parent in eim_devices:
        if not isinstance(parent, dict):
            continue
        parent_id = row_input_id(parent)
        if not parent_id:
            continue
        external_parent = next(
            (row for row in external_inputs if scalar(row.get("id")) == parent_id),
            None,
        )
        if external_parent is None:
            continue
        parent_app_id = scalar(parent.get("appId")) or scalar(
            external_parent.get("appId")
        )
        if not parent_app_id:
            continue
        children = parent.get("subList")
        if not isinstance(children, list):
            continue

        parent_label = parent.get("label") or external_parent.get("label")
        context = _parent_context(parent_id, parent_label)
        candidates: list[tuple[str, str, dict[str, Any]]] = []
        seen_unique_ids: set[str] = set()
        seen_identities: set[tuple[str, str]] = set()
        for child in children:
            if not isinstance(child, dict):
                continue
            unique_id = scalar(child.get("uniqueId"))
            if (
                not unique_id
                or unique_id in seen_unique_ids
                or (parent_id, unique_id) in seen_children
            ):
                continue
            depth = child.get("depth")
            if depth is not None and (
                isinstance(depth, bool) or not isinstance(depth, int) or depth < 1
            ):
                continue

            name = _safe_name(child.get("osdName")) or unique_id
            if depth == 1 and name.casefold() in top_level_names:
                continue

            child_identity = _identity(child)
            if child_identity is not None:
                if (
                    child_identity in seen_identities
                    or (parent_id, *child_identity) in seen_parent_identities
                ):
                    continue
                seen_identities.add(child_identity)
                if child_identity in top_level_identities:
                    continue

            seen_unique_ids.add(unique_id)
            seen_children.add((parent_id, unique_id))
            if child_identity is not None:
                seen_parent_identities.add((parent_id, *child_identity))
            candidates.append((unique_id, name, child))

        # Count the final base labels before assigning any names. If siblings
        # share an OSD name, suffix all of them rather than letting response
        # ordering decide which device gets the unsuffixed label.
        base_counts: dict[str, int] = {}
        for unique_id, name, _child in candidates:
            base = f"{name} · {context}"
            if len(base) > MAX_SOURCE_NAME_LENGTH:
                base = f"{unique_id} · {context}"
            base_counts[base] = base_counts.get(base, 0) + 1

        for unique_id, name, _child in candidates:
            display_name = f"{name} · {context}"
            if len(display_name) > MAX_SOURCE_NAME_LENGTH:
                display_name = f"{unique_id} · {context}"
            if base_counts.get(display_name, 0) > 1 or display_name in existing:
                display_name = f"{display_name} [CEC {unique_id}]"
            suffix = 2
            base_name = display_name
            while display_name in existing:
                display_name = f"{base_name} ({suffix})"
                suffix += 1
            if len(display_name) > MAX_SOURCE_NAME_LENGTH:
                continue

            existing.add(display_name)
            discovered.append(
                (
                    display_name,
                    CecSelection(
                        parent_input_id=parent_id,
                        parent_app_id=parent_app_id,
                        unique_id=unique_id,
                    ),
                )
            )
            if len(discovered) >= MAX_CEC_CHILDREN:
                return discovered
    return discovered


def _matching_parent(
    response: dict[str, Any], selection: CecSelection
) -> dict[str, Any] | None:
    devices = response.get("devices")
    if not isinstance(devices, list):
        return None
    for parent in devices:
        if not isinstance(parent, dict):
            continue
        if row_input_id(parent) != selection.parent_input_id:
            continue
        app_id = scalar(parent.get("appId"))
        if app_id and app_id != selection.parent_app_id:
            return None
        return parent
    return None


def contains_unique_id(response: dict[str, Any], selection: CecSelection) -> bool:
    """Verify the selected child is still attached to the expected HDMI parent."""
    parent = _matching_parent(response, selection)
    children = parent.get("subList") if parent else None
    return isinstance(children, list) and any(
        isinstance(child, dict) and scalar(child.get("uniqueId")) == selection.unique_id
        for child in children
    )


def last_unique_id(response: dict[str, Any], selection: CecSelection) -> str | None:
    """Read the last-selected child for the expected physical HDMI parent."""
    parent = _matching_parent(response, selection)
    return scalar(parent.get("lastUniqueId")) if parent else None
