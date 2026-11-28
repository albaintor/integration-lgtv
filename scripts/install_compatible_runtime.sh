#!/usr/bin/env bash
# Use the previous builder's runtime ABI without cross-compiling or Docker.
set -euo pipefail
bundle="$(realpath "$1")"
test "$(uname -m)" = aarch64
test -d "$bundle"
if [[ ! -e "$bundle/libgcc_s.so.1" && ! -e "$bundle/libstdc++.so.6" ]]; then
    exit 0
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Obtain Debian signing keys via the host's authenticated package repository.
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends debian-archive-keyring
mkdir -p "$work/lists/partial"
chmod 755 "$work" "$work/lists"
printf '%s\n' 'deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian bullseye main' > "$work/sources.list"
opts=(-o "Dir::Etc::sourcelist=$work/sources.list" -o Dir::Etc::sourceparts=- -o "Dir::State::lists=$work/lists")
sudo apt-get "${opts[@]}" update
cd "$work"
apt-get "${opts[@]}" download libgcc-s1/bullseye libstdc++6/bullseye
for package in ./*.deb; do
    dpkg-deb -x "$package" extracted
done
for library in libgcc_s.so.1 libstdc++.so.6; do
    if [[ -e "$bundle/$library" ]]; then
        source_file="$(find extracted -name "$library" -print -quit)"
        test -n "$source_file"
        rm -f "$bundle/$library"
        cp -L "$source_file" "$bundle/$library"
    fi
done
