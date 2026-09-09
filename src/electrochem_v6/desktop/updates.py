"""Opt-in, read-only checks of the official GitHub release metadata.

This module never downloads or launches an installer. Release notes are untrusted
plain text; callers must not render them as executable HTML or Markdown links.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from functools import total_ordering
from platform import system as _platform_system
from typing import Any
from urllib.parse import unquote, urlsplit

import requests

OFFICIAL_REPOSITORY = "Sunnnnch/electro_data_process_tool"
RELEASES_URL = f"https://github.com/{OFFICIAL_REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{OFFICIAL_REPOSITORY}/releases?per_page=100"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SEMVER = re.compile(r"^[vV]?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,180}$")


@total_ordering
@dataclass(frozen=True)
class _Version:
    core: tuple[int, int, int]
    prerelease: tuple[str, ...]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.prerelease) < len(other.prerelease)


def _parse_version(value: str) -> _Version | None:
    if not isinstance(value, str) or len(value) > 128:
        return None
    match = _SEMVER.fullmatch(value)
    if not match:
        return None
    pre = tuple(match[4].split(".")) if match[4] else ()
    build = tuple(match[5].split(".")) if match[5] else ()
    if any(not part for part in (*pre, *build)):
        return None
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in pre):
        return None
    return _Version((int(match[1]), int(match[2]), int(match[3])), pre)


def _official_url(value: Any, path: str) -> bool:
    if not isinstance(value, str) or len(value) > 2048 or value != value.strip() or any(ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https" and parsed.hostname == "github.com"
            and parsed.username is None and parsed.password is None and parsed.port is None
            and not parsed.query and not parsed.fragment
            and unquote(parsed.path) == path
        )
    except ValueError:
        return False


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(char for char in value[:limit] if char in "\n\t" or ord(char) >= 32).strip()


def _update_target() -> tuple[str, str]:
    system = _platform_system()
    if system == "Darwin":
        from .environment import _platform_facts
        return system, _platform_facts()["native_arch"]
    return system, "x64"


def _installer_names(version: str, system: str, architecture: str) -> tuple[str, ...]:
    if system == "Darwin" and architecture in {"arm64", "x64"}:
        return tuple(f"ElectroChem-{version}-macos-{architecture}.{extension}" for extension in ("dmg", "zip"))
    if system == "Windows":
        return (f"ElectroChem-Setup-{version}.exe", f"ElectroChemV6-Setup-{version}.exe")
    return ()


def _release_candidate(raw: Any, include_prerelease: bool, *, system: str = "Windows",
                       architecture: str = "x64") -> tuple[_Version, dict[str, Any]] | None:
    if not isinstance(raw, dict) or raw.get("draft") is not False:
        return None
    tag = raw.get("tag_name")
    if not isinstance(tag, str):
        return None
    version = _parse_version(tag)
    if version is None or (raw.get("prerelease") or version.prerelease) and not include_prerelease:
        return None
    if not _official_url(raw.get("html_url"), f"/{OFFICIAL_REPOSITORY}/releases/tag/{tag}"):
        raise ValueError("Release metadata references an untrusted page")
    assets = raw.get("assets")
    if not isinstance(assets, list) or len(assets) > 200:
        raise ValueError("Invalid release assets")
    names = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Invalid release asset")
        name = asset.get("name")
        if not isinstance(name, str) or not _ASSET_NAME.fullmatch(name):
            raise ValueError("Invalid release asset name")
        if not _official_url(asset.get("browser_download_url"), f"/{OFFICIAL_REPOSITORY}/releases/download/{tag}/{name}"):
            raise ValueError("Release metadata references an untrusted asset")
        if asset.get("state") == "uploaded" and isinstance(asset.get("size"), int) and asset["size"] > 0:
            names.add(name)
    displayed_version = tag.lstrip("vV")
    # Prefer the current public name while accepting previously published assets.
    installer = next((name for name in _installer_names(displayed_version, system, architecture)
                      if name in names and f"{name}.sha256" in names), None)
    if installer is None:
        return None
    return version, {
        "latest_version": displayed_version,
        "release_name": _clean_text(raw.get("name"), 200),
        "release_notes": _clean_text(raw.get("body"), 12000),
        "published_at": _clean_text(raw.get("published_at"), 40),
        "installer_name": installer,
    }


def check_for_updates(current_version: str, *, timeout: float = 5.0, session: Any = None) -> dict[str, Any]:
    """Check on explicit user request; stable clients do not opt into prereleases.

    ``session`` is an injectable HTTP transport for isolated tests. Redirects are
    disabled, response size is bounded, and only the fixed releases page is
    returned as a navigation target. Metadata cannot verify platform signatures.
    """
    result: dict[str, Any] = {
        "status": "error", "state": "invalid_version", "update_available": False,
        "current_version": _clean_text(current_version, 128), "latest_version": None,
        "release_name": "", "release_notes": "", "published_at": "", "installer_name": None,
        "release_url": RELEASES_URL, "message": "Current version is not a valid semantic version.",
    }
    current = _parse_version(current_version)
    if current is None:
        return result
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        result.update(state="invalid_response", message="Update timeout must be between 0 and 30 seconds.")
        return result
    owned = session is None
    transport = requests.Session() if owned else session
    if owned:
        # Public metadata needs no account credentials or ambient .netrc auth.
        transport.trust_env = False
    try:
        started = time.monotonic()
        with transport.get(
            API_URL,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ElectroChem-Desktop-UpdateCheck"},
            timeout=(min(float(timeout), 3.0), float(timeout)), allow_redirects=False, stream=True,
        ) as response:
            if response.status_code in (403, 429):
                result.update(state="rate_limited", message="GitHub temporarily limited update checks. Try again later.")
                return result
            if response.status_code == 404:
                result.update(status="success", state="no_release", message="No public release is currently available.")
                return result
            if response.status_code != 200 or response.url != API_URL:
                result.update(state="invalid_response", message="The official release service returned an unexpected response.")
                return result
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if time.monotonic() - started > timeout:
                    raise requests.Timeout("Update metadata exceeded its time limit")
                payload.extend(chunk)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError("Release metadata exceeds the size limit")
            releases = json.loads(payload)
        if not isinstance(releases, list) or len(releases) > 100:
            raise ValueError("Invalid release list")
        candidates = []
        system, architecture = _update_target()
        for raw in releases:
            candidate = _release_candidate(raw, bool(current.prerelease), system=system, architecture=architecture)
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            target = f"macOS {architecture}" if system == "Darwin" else system
            result.update(status="success", state="no_release", message=f"No eligible {target} installer and checksum are published yet.")
            return result
        latest, information = max(candidates, key=lambda item: item[0])
        available = current < latest
        result.update(information, status="success", state="update_available" if available else "up_to_date", update_available=available,
                      message="A newer official release is available. Review its notes and download page." if available else "This version is up to date.")
        return result
    except requests.Timeout:
        result.update(state="timeout", message="The update check timed out. Try again later.")
    except requests.RequestException:
        result.update(state="offline", message="The official release service could not be reached. Current work is unaffected.")
    except (ValueError, TypeError, UnicodeError):
        result.update(state="invalid_response", message="Release metadata could not be verified. No download was started.")
    finally:
        if owned:
            transport.close()
    return result
