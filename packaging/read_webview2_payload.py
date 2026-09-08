"""Read Runtime metadata from an already signature-verified Evergreen wrapper.

The wrapper's PE version is Edge Update's 1.3.x version, not WebView2's.
Omaha stores an LZMA-compressed BCJ2/tar payload in resource B/102. Its XML
manifest remains ASCII in the BCJ2 main stream. Read only that signed metadata;
do not reconstruct executable code, extract files, or execute the prerequisite.
"""

from __future__ import annotations

import argparse
import json
import lzma
import re
import struct
from pathlib import Path
from xml.etree import ElementTree

APP_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MAX_PAYLOAD = 1024 * 1024 * 1024


def read_manifest_metadata(main_stream: bytes) -> dict:
    matches = []
    for match in re.finditer(rb"<response\b[^>]*>.*?</response>", main_stream, re.DOTALL):
        if len(match[0]) > 256 * 1024:
            continue
        try:
            response = ElementTree.fromstring(match[0])
        except ElementTree.ParseError:
            continue
        if response.get("protocol") != "3.0":
            continue
        for app in response.findall("app"):
            if app.get("appid", "").upper() != APP_ID or app.get("status") != "ok":
                continue
            update = app.find("updatecheck")
            if update is None or update.get("status") != "ok":
                continue
            manifest = update.find("manifest")
            if manifest is None:
                continue
            version = manifest.get("version", "")
            if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
                raise ValueError("Invalid WebView2 version in the signed payload manifest")
            if int(version.split(".")[0]) < 120:
                raise ValueError("Bundled WebView2 Runtime must be version 120 or later")
            expected = f"MicrosoftEdgeWebview_X64_{version}.exe"
            packages = manifest.findall("packages/package")
            package = next((item for item in packages if item.get("name") == expected), None)
            if package is None or not re.fullmatch(r"[a-fA-F0-9]{64}", package.get("hash_sha256", "")):
                raise ValueError("Missing x64 WebView2 package identity in the signed payload manifest")
            actions = manifest.findall("actions/action")
            if not any(item.get("run") == expected and "--msedgewebview" in item.get("arguments", "").split() for item in actions):
                raise ValueError("Missing WebView2 install action in the signed payload manifest")
            matches.append({
                "version": version,
                "versionSource": "signed-wrapper:B/102:Omaha-WebView2-manifest",
                "runtimeAppId": APP_ID,
                "runtimePackage": expected,
                "runtimePackageSha256": package.get("hash_sha256").lower(),
            })
    if not matches or any(item != matches[0] for item in matches):
        raise ValueError("No unique x64 WebView2 Runtime manifest found in the signed wrapper")
    return matches[0]


def inspect_payload(path: Path) -> dict:
    if not 0 < path.stat().st_size <= MAX_PAYLOAD:
        raise ValueError("Unexpected WebView2 installer file size")
    import pefile

    with pefile.PE(str(path), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        roots = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        if roots is None:
            raise ValueError("WebView2 offline installer has no payload resources")
        resource = next((item for item in roots.entries if str(item.name) == "B"), None)
        if resource is None:
            raise ValueError("Unrecognized WebView2 offline wrapper: missing resource B")
        entry = next((item for item in resource.directory.entries if item.id == 102), None)
        if entry is None or len(entry.directory.entries) != 1:
            raise ValueError("Unrecognized WebView2 offline wrapper: missing unique resource B/102")
        info = entry.directory.entries[0].data.struct
        if not 13 <= info.Size <= MAX_PAYLOAD:
            raise ValueError("Unexpected WebView2 compressed resource size")
        compressed = pe.get_data(info.OffsetToData, info.Size)
        if len(compressed) != info.Size or int.from_bytes(compressed[5:13], "little") > MAX_PAYLOAD:
            raise ValueError("Unexpected WebView2 payload size")
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        decoded = decoder.decompress(compressed, max_length=MAX_PAYLOAD + 1)
        if len(decoded) > MAX_PAYLOAD or not decoder.eof or len(decoded) < 20:
            raise ValueError("Invalid or oversized WebView2 compressed payload")
    _original_size, main_size, call_size, jump_size, range_size = struct.unpack("<5I", decoded[:20])
    if 20 + main_size + call_size + jump_size + range_size != len(decoded):
        raise ValueError("Unrecognized WebView2 BCJ2 payload layout")
    return read_manifest_metadata(decoded[20:20 + main_size])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_payload(args.installer), ensure_ascii=True))
