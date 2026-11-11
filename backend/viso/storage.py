"""Sandbox templates: current-user Windows DPAPI, or explicitly memory-only."""

import ctypes
import json
import os
from pathlib import Path

import numpy as np

from .recognition import MODEL_ID, normalized
from .enrollment import validate_circular_profile


def dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Persistent sandbox storage requires Windows DPAPI.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = None
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        description = "Viso sandbox face profile"
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class ProfileStore:
    def __init__(self, folder: Path, ephemeral: bool = False):
        self.path = folder / "profile.dpapi"
        self.persistent = os.name == "nt" and not ephemeral
        self.label = "Windows DPAPI" if self.persistent else "Memory only"
        self.profile: dict | None = None
        self.error: str | None = None
        if self.persistent and self.path.exists():
            try:
                if self.path.stat().st_size > 131072:
                    raise ValueError("Stored profile is too large.")
                profile = json.loads(dpapi(self.path.read_bytes(), decrypt=True))
                if profile.get("model_id") != MODEL_ID:
                    raise ValueError("The stored profile belongs to a different recognition model.")
                embedding = np.asarray(profile["embedding"], dtype=np.float32)
                if embedding.shape != (128,):
                    raise ValueError("Invalid stored embedding.")
                profile["embedding"] = normalized(embedding).tolist()
                if "templates" in profile:
                    templates = np.asarray(profile["templates"], dtype=np.float32)
                    limit = 17 if profile.get("enrollment_version") else 5
                    if type(profile.get("samples")) is not int or templates.shape != (profile["samples"], 128) or not 1 <= len(templates) <= limit:
                        raise ValueError("Invalid stored enrollment views.")
                    profile["templates"] = [normalized(template).tolist() for template in templates]
                if profile.get("enrollment_version") or "template_groups" in profile:
                    validate_circular_profile(profile)
                    if profile.get("source") != "camera" or profile.get("guided") is not True or "templates" not in profile:
                        raise ValueError("Invalid circular camera profile.")
                self.profile = profile
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.error = f"Stored profile could not be opened. Reset the profile to enroll again. ({type(error).__name__})"

    def public(self) -> dict | None:
        if self.profile is None:
            return None
        public = {key: value for key, value in self.profile.items() if key not in ("embedding", "templates")}
        public["matching"] = "multi-view" if len(self.profile.get("templates", [])) >= 2 else "centroid"
        return public

    def save(self, profile: dict) -> None:
        if self.profile is not None or self.error:
            raise ValueError("Remove the existing profile before enrolling again.")
        if self.persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encrypted = dpapi(json.dumps(profile, allow_nan=False).encode())
            temporary = self.path.with_suffix(".tmp")
            try:
                temporary.write_bytes(encrypted)
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        self.profile = profile

    def clear(self) -> None:
        if self.persistent:
            self.path.unlink(missing_ok=True)
        self.profile = None
        self.error = None
