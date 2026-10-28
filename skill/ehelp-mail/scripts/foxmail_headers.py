"""Foxmail 7.2 storage transform reused from mail-assistant, header-only reader.

The block transform is from mail-assistant 6085b6a; no Accounts credential
records or full-message/body decoder are included. Source key stays in memory.
"""
from __future__ import annotations

from pathlib import Path
import os
import re

_IP = (58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8, 57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7)
_FP = (40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25)
_E = (32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11, 12, 13, 12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20, 21, 22, 23, 24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1)
_P = (16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10, 2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25)
_PC1 = (57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36, 63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4)
_PC2 = (14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10, 23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2, 41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48, 44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32)
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
_MASKS = (1, 2, 4, 8, 16, 32, 64, 128)
_SBOXES = tuple(
    bytes.fromhex(value)
    for value in (
        "0e040d01020f0b08030a060c05090007 000f07040e020d010a060c0b09050308 04010e080d06020b0f0c0907030a0500 0f0c080204090107050b030e0a00060d",
        "0f01080e060b03040907020d0c00050a 030d04070f02080e0c00010a06090b05 000e070b0a040d0105080c060903020f 0d080a01030f04020b06070c00050e09",
        "0a00090e06030f05010d0c070b040208 0d0700090304060a0208050e0c0b0f01 0d060409080f03000b01020c050a0e07 010a0d0006090807040f0e030b05020c",
        "070d0e030006090a010208050b0c040f 0d080b05060f00030407020c010a0e09 0a0609000c0b070d0f01030e05020804 030f00060a010d080904050b0c07020e",
        "020c0401070a0b060805030f0d000e09 0e0b020c04070d0105000f0a03090806 0402010b0a0d07080f090c050603000e 0b080c07010e020d060f00090a040503",
        "0c010a0f09020608000d03040e07050b 0a0f0402070c090506010d0e000b0308 090e0f0502080c030700040a010d0b06 0403020c09050f0a0b0e01070600080d",
        "040b020e0f00080d030c0907050a0601 0d000b070409010a0e03050c020f0806 01040b0d0c03070e0a0f060800050902 060b0d0801040a070905000f0e02030c",
        "0d020804060f0b010a09030e05000c07 010f0d080a0307040c05060b000e0902 070b0401090c0e0200060a0d0f030508 02010e07040a080d0f0c09000305060b",
    )
)


def _bits(data: bytes) -> list[int]:
    return [int(bool(value & mask)) for value in data for mask in _MASKS]


def _pack_bits(values: list[int]) -> bytes:
    return bytes(
        sum(_MASKS[index] for index in range(8) if values[offset + index])
        for offset in range(0, len(values), 8)
    )


def _permute(values: list[int], table: tuple[int, ...]) -> list[int]:
    return [values[index - 1] for index in table]


def _round_keys(key: bytes) -> list[list[int]]:
    values = _permute(_bits(key), _PC1)
    result: list[list[int]] = []
    for shift in _SHIFTS:
        values = values[shift:28] + values[:shift] + values[28 + shift :] + values[28 : 28 + shift]
        result.append(_permute(values, _PC2))
    return result


def _feistel(right: list[int], key: list[int]) -> list[int]:
    expanded = [left ^ right_value for left, right_value in zip(_permute(right, _E), key)]
    substituted: list[int] = []
    for box_index, box in enumerate(_SBOXES):
        block = expanded[box_index * 6 : (box_index + 1) * 6]
        row = 2 * block[0] + block[5]
        column = 8 * block[1] + 4 * block[2] + 2 * block[3] + block[4]
        value = box[row * 16 + column]
        substituted.extend(int(bool(value & mask)) for mask in _MASKS[:4])
    return _permute(substituted, _P)


def _foxmail_block_transform(data: bytes, key: bytes, *, decrypt: bool) -> bytes:
    if len(data) != 8 or len(key) != 8:
        raise ValueError("Foxmail block transform requires 8-byte data and key blocks")
    values = _permute(_bits(data), _IP)
    left, right = values[:32], values[32:]
    round_keys = _round_keys(key)
    if decrypt:
        for round_key in reversed(round_keys):
            old_left = left
            left = [a ^ b for a, b in zip(right, _feistel(left, round_key))]
            right = old_left
    else:
        for round_key in round_keys:
            old_right = right
            right = [a ^ b for a, b in zip(left, _feistel(right, round_key))]
            left = old_right
    return _pack_bits(_permute(left + right, _FP))


def _transform_blocks(data: bytes, key: bytes, *, decrypt: bool) -> bytes:
    if len(data) % 8:
        raise ValueError("Foxmail encrypted data length must be a multiple of 8")
    normalized_key = (key + bytes(8))[:8]
    return b"".join(
        _foxmail_block_transform(data[offset : offset + 8], normalized_key, decrypt=decrypt)
        for offset in range(0, len(data), 8)
    )


MAX_HEADER_BYTES = 256 * 1024
_FIRST_HEADER = re.compile(rb"^[!-9;-~]+:$")


def _state(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _checked_path(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise RuntimeError("Foxmail 来源路径无效或越过所选账号。")
    return resolved


def read_metadata(path: Path, root: Path, *, maximum=32 * 1024 * 1024) -> bytes:
    """Read a named index only; never a message/credential directory scan."""
    resolved = _checked_path(path, root)
    before = resolved.stat()
    if before.st_size > maximum:
        raise RuntimeError("Foxmail 索引超过本版安全读取范围。")
    with resolved.open("rb", buffering=0) as stream:
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if _state(before) != _state(after) or _state(after) != _state(resolved.stat()) or len(data) != before.st_size:
        raise RuntimeError("Foxmail 正在同步，索引已变化；请稍后重试。")
    return data


class FoxmailHeaderReader:
    """Decode at most the RFC header, stopping at its first empty line.

    Unbuffered single-byte payload reads deliberately avoid body read-ahead.
    Only the 512-byte container prefix and Mails/Index storage metadata precede
    the header. No Accounts files, MIME body parsing, network or write methods.
    """

    def __init__(self, account_root: Path):
        self.root = (Path(account_root) / "Mails").resolve()
        if not self.root.is_relative_to(Path(account_root).resolve()):
            raise RuntimeError("Foxmail 存储目录越过所选账号。")
        self._key = None
        self._states = {}

    def verify_unchanged(self):
        for path, state in self._states.items():
            if _state(path.stat()) != state:
                raise RuntimeError("Foxmail 在本批读取期间变化；请重新预览。")

    def _storage_key(self):
        if self._key is None:
            path = _checked_path(self.root / "Index", self.root)
            before = path.stat()
            with path.open("rb", buffering=0) as stream:
                data = stream.read(512)
                after = os.fstat(stream.fileno())
            if _state(before) != _state(after) or _state(after) != _state(path.stat()):
                raise RuntimeError("Foxmail 正在同步，请稍后重试。")
            if len(data) != 512 or not data.startswith(b"FXIS") or data[36] == 0:
                raise RuntimeError("Foxmail 邮件存储格式暂不支持。")
            self._key = _transform_blocks(data[37:53], bytes(8), decrypt=True)[8:16]
            self._states[path] = _state(after)
        return self._key

    def read(self, path: Path) -> bytes:
        path = _checked_path(path, self.root)
        before = path.stat()
        with path.open("rb", buffering=0) as stream:
            # Recognize a leading RFC field without ever reading past a header
            # line. Binary containers use the existing Foxmail block transform.
            prefix = bytearray()
            for _ in range(78):
                b = stream.read(1)
                if not b:
                    break
                prefix.extend(b)
                if b == b":" or b[0] < 33 or b[0] > 126:
                    break
            plain = bool(_FIRST_HEADER.fullmatch(prefix))
            stream.seek(0)
            first = inverse = None
            if not plain:
                container = stream.read(512)
                if len(container) != 512:
                    raise RuntimeError("Foxmail 邮件未完整下载或格式不支持。")
                first = _transform_blocks(container[:256], self._storage_key(), decrypt=True)
                substitution = bytes(a ^ b for a, b in zip(container[256:], first))
                if len(set(substitution)) != 256:
                    raise RuntimeError("Foxmail 邮件存储格式暂不支持。")
                inverse = bytearray(256)
                for i, value in enumerate(substitution):
                    inverse[value] = i
            header = bytearray()
            for i in range(MAX_HEADER_BYTES):
                b = stream.read(1)
                if not b:
                    raise RuntimeError("Foxmail 邮件头不完整；没有读取正文。")
                header.append(b[0] if plain else inverse[b[0] ^ first[i % 256]])
                if header.endswith(b"\r\n\r\n") or header.endswith(b"\n\n"):
                    break
            else:
                raise RuntimeError("Foxmail 邮件头超过本版读取上限。")
            after = os.fstat(stream.fileno())
        if _state(before) != _state(after) or _state(after) != _state(path.stat()):
            raise RuntimeError("Foxmail 邮件在读取时变化；请稍后重试。")
        self._states[path] = _state(after)
        return bytes(header)
