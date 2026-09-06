"""Aspect ratio presets per LG model generation.

:copyright: (c) 2026 by Albaintor.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

DEFAULT_ASPECT_RATIO_GENERATION = "G5"

# webOS exposes the current value but not the choices supported by the active
# input. Keep the conservative set documented by LG and allow generations to
# override it as model-specific values are verified.
COMMON_ASPECT_RATIOS: tuple[tuple[str, str], ...] = (
    ("16:9", "16x9"),
    ("Original", "original"),
    ("4:3", "4x3"),
    ("Vertical zoom", "vertZoom"),
    ("All-direction zoom", "allDirZoom"),
)

LG_ASPECT_RATIOS_GENERATION: dict[str, tuple[tuple[str, str], ...]] = {
    "C8": COMMON_ASPECT_RATIOS,
    "C9": COMMON_ASPECT_RATIOS,
    "CX": COMMON_ASPECT_RATIOS,
    "C1": COMMON_ASPECT_RATIOS,
    "C2": COMMON_ASPECT_RATIOS,
    "G3": COMMON_ASPECT_RATIOS,
    "G4": COMMON_ASPECT_RATIOS,
    "G5": COMMON_ASPECT_RATIOS,
    "G6": COMMON_ASPECT_RATIOS,
}
