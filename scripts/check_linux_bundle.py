"""Reject Linux bundles that exceed the previous Remote build ABI baseline."""
import argparse
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--max-glibc", default="2.31")
    args = parser.parse_args()
    ceiling = tuple(map(int, args.max_glibc.split(".")))
    failures = []
    checked = 0
    for path in sorted(args.bundle.rglob("*")):
        if not path.is_file():
            continue
        with path.open("rb") as file:
            if file.read(4) != b"\x7fELF":
                continue
        checked += 1
        header = subprocess.check_output(["readelf", "-h", str(path)], text=True)
        if not re.search(r"Machine:\s+AArch64", header):
            failures.append(f"{path}: not AArch64")
        versions = subprocess.check_output(
            ["readelf", "--version-info", str(path)], text=True
        )
        # Check required versions only, not versions exported by the library.
        needs = versions.split("Version needs section", 1)
        if len(needs) == 2:
            for version in set(re.findall(r"\bGLIBC_(\d+(?:\.\d+)+)\b", needs[1])):
                if tuple(map(int, version.split("."))) > ceiling:
                    failures.append(f"{path}: requires GLIBC_{version}")
    if not checked:
        failures.append("No ELF files found")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Checked {checked} AArch64 ELF files against glibc {args.max_glibc}")


if __name__ == "__main__":
    main()
