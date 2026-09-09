"""Small, platform-independent readers used by the native macOS build gates."""
from __future__ import annotations

import ast
import hashlib
import struct
from pathlib import Path

MIN_MACOS = (13, 0, 0)
CPU_ARCHES = {0x01000007: "x86_64", 0x0100000C: "arm64"}


def read_app_version(root: Path) -> str:
    tree = ast.parse((root / "src/electrochem_v6/config.py").read_text(encoding="utf-8-sig"))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in statement.targets):
            value = ast.literal_eval(statement.value)
            if isinstance(value, str) and len(value.split(".")) == 3 and all(p.isdigit() for p in value.split(".")):
                return value
    raise ValueError("APP_VERSION must be a literal three-part version")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_prefix(version: str, arch: str) -> str:
    if arch not in {"arm64", "x86_64"}:
        raise ValueError("Unsupported macOS architecture")
    return f"ElectroChem-{version}-macos-{'x64' if arch == 'x86_64' else arch}"


def _version(number: int) -> tuple[int, int, int]:
    return number >> 16, (number >> 8) & 255, number & 255


def read_macho(path: Path) -> list[dict]:
    """Read bounded Mach-O headers only; never load or execute candidate code."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        magic = stream.read(4)
        if magic in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}:
            raw_count = stream.read(4)
            if len(raw_count) != 4:
                raise ValueError(f"Truncated universal header: {path}")
            count = struct.unpack(">I", raw_count)[0]
            if not 1 <= count <= 8:
                raise ValueError(f"Invalid universal slice count: {path}")
            wide = magic[-1] == 191
            stride = 32 if wide else 20
            entries = stream.read(stride * count)
            if len(entries) != stride * count:
                raise ValueError(f"Truncated universal slices: {path}")
            slices = []
            for index in range(count):
                entry = entries[index * stride:(index + 1) * stride]
                offset, length = struct.unpack(">QQ" if wide else ">II", entry[8:24] if wide else entry[8:16])
                if offset < 8 + stride * count or length < 32 or offset + length > size:
                    raise ValueError(f"Invalid universal slice range: {path}")
                slices.append((offset, length))
        elif magic in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}:
            slices = [(0, size)]
        elif magic in {b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce"}:
            raise ValueError(f"32-bit Mach-O is unsupported on macOS 13: {path}")
        else:
            return []
        found = []
        for offset, length in slices:
            stream.seek(offset)
            header = stream.read(32)
            if len(header) != 32 or header[:4] not in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}:
                raise ValueError(f"Unsupported Mach-O slice: {path}")
            endian = "<" if header[:4] == b"\xcf\xfa\xed\xfe" else ">"
            _, cpu, _, _, count, command_size, _, _ = struct.unpack(endian + "8I", header)
            if not 1 <= count <= 4096 or command_size > min(length - 32, 16 * 1024 * 1024):
                raise ValueError(f"Invalid Mach-O load commands: {path}")
            commands = stream.read(command_size)
            if len(commands) != command_size:
                raise ValueError(f"Truncated Mach-O load commands: {path}")
            position, minimum = 0, None
            for _ in range(count):
                if position + 8 > len(commands):
                    raise ValueError(f"Truncated Mach-O command: {path}")
                command, command_length = struct.unpack_from(endian + "II", commands, position)
                if command_length < 8 or position + command_length > len(commands):
                    raise ValueError(f"Invalid Mach-O command length: {path}")
                if command == 0x32 and command_length >= 24:  # LC_BUILD_VERSION
                    target, encoded = struct.unpack_from(endian + "II", commands, position + 8)
                    if target != 1:
                        raise ValueError(f"Non-macOS Mach-O target: {path}")
                    minimum = _version(encoded)
                elif command == 0x24 and command_length >= 16:  # LC_VERSION_MIN_MACOSX
                    minimum = _version(struct.unpack_from(endian + "I", commands, position + 8)[0])
                position += command_length
            if position != len(commands) or minimum is None:
                raise ValueError(f"Missing/invalid macOS deployment target: {path}")
            found.append({"architecture": CPU_ARCHES.get(cpu, f"unknown-{cpu}"), "minimum_macos": minimum})
        return found


def check_macho(path: Path, arch: str, *, executable: bool = False) -> list[dict]:
    slices = read_macho(path)
    matched = [entry for entry in slices if entry["architecture"] == arch]
    if slices and (len(matched) != 1 or (executable and len(slices) != 1)):
        raise ValueError(f"Wrong architecture (expected {arch}): {path}")
    if executable and not slices:
        raise ValueError(f"Main executable is not Mach-O: {path}")
    if matched and matched[0]["minimum_macos"] > MIN_MACOS:
        raise ValueError(f"Native dependency requires macOS newer than 13.0: {path}")
    return slices
