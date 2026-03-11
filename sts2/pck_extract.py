from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class PckExtractError(Exception):
    """Godot PCK 解析异常。"""


@dataclass(slots=True)
class GodotPckHeader:
    path: Path
    pack_version: int
    engine_major: int
    engine_minor: int
    engine_patch: int
    engine_status: int
    file_base: int
    dir_offset: int


@dataclass(slots=True)
class GodotPckEntry:
    path: str
    offset: int
    size: int
    md5: bytes
    flags: int

    @property
    def md5_hex(self) -> str:
        return self.md5.hex()


def _normalize_resource_path(resource_path: str) -> str:
    normalized = resource_path.replace("\\", "/").strip()
    if normalized.startswith("res://"):
        normalized = normalized[6:]
    return normalized.lstrip("/")


class GodotPckReader:
    """Godot PCK 最小读取器：支持读取头部、列举文件表和提取文件内容。"""

    def __init__(self, pck_path: str | Path):
        self.pck_path = Path(pck_path).expanduser().resolve()
        if not self.pck_path.exists():
            raise FileNotFoundError(f"PCK 文件不存在：{self.pck_path}")
        if not self.pck_path.is_file():
            raise ValueError(f"PCK 路径不是文件：{self.pck_path}")
        self._header: GodotPckHeader | None = None
        self._entries: list[GodotPckEntry] | None = None

    def read_header(self) -> GodotPckHeader:
        if self._header is not None:
            return self._header

        with self.pck_path.open("rb") as handle:
            magic = handle.read(4)
            if magic != b"GDPC":
                raise PckExtractError(f"不是有效的 Godot PCK 文件：{self.pck_path}")

            pack_version = struct.unpack("<I", handle.read(4))[0]
            engine_major = struct.unpack("<I", handle.read(4))[0]
            engine_minor = struct.unpack("<I", handle.read(4))[0]
            engine_patch = struct.unpack("<I", handle.read(4))[0]
            engine_status = struct.unpack("<I", handle.read(4))[0]
            file_base = struct.unpack("<Q", handle.read(8))[0]
            dir_offset = struct.unpack("<Q", handle.read(8))[0]

        self._header = GodotPckHeader(
            path=self.pck_path,
            pack_version=pack_version,
            engine_major=engine_major,
            engine_minor=engine_minor,
            engine_patch=engine_patch,
            engine_status=engine_status,
            file_base=file_base,
            dir_offset=dir_offset,
        )
        return self._header

    def list_entries(self) -> list[GodotPckEntry]:
        if self._entries is not None:
            return list(self._entries)

        header = self.read_header()
        entries: list[GodotPckEntry] = []

        with self.pck_path.open("rb") as handle:
            handle.seek(header.dir_offset)
            raw_count = handle.read(4)
            if len(raw_count) != 4:
                raise PckExtractError("无法读取 PCK 文件表数量")
            file_count = struct.unpack("<I", raw_count)[0]

            for index in range(file_count):
                raw_name_len = handle.read(4)
                if len(raw_name_len) != 4:
                    raise PckExtractError(f"读取第 {index} 个条目的名称长度失败")
                name_len = struct.unpack("<I", raw_name_len)[0]
                if name_len <= 0 or name_len > 4096:
                    raise PckExtractError(f"第 {index} 个条目的名称长度异常：{name_len}")

                raw_name = handle.read(name_len)
                if len(raw_name) != name_len:
                    raise PckExtractError(f"读取第 {index} 个条目的名称内容失败")
                name = raw_name.rstrip(b"\x00").decode("utf-8", errors="replace")

                raw_offset = handle.read(8)
                raw_size = handle.read(8)
                raw_md5 = handle.read(16)
                raw_flags = handle.read(4)
                if not (len(raw_offset) == 8 and len(raw_size) == 8 and len(raw_md5) == 16 and len(raw_flags) == 4):
                    raise PckExtractError(f"读取第 {index} 个条目的元数据失败")

                offset = struct.unpack("<Q", raw_offset)[0]
                size = struct.unpack("<Q", raw_size)[0]
                flags = struct.unpack("<I", raw_flags)[0]

                entries.append(
                    GodotPckEntry(
                        path=name,
                        offset=offset,
                        size=size,
                        md5=raw_md5,
                        flags=flags,
                    )
                )

        self._entries = entries
        return list(entries)

    def find_entry(self, resource_path: str) -> GodotPckEntry | None:
        normalized = _normalize_resource_path(resource_path)
        for entry in self.list_entries():
            if _normalize_resource_path(entry.path) == normalized:
                return entry
        return None

    def read_entry_bytes(self, entry_or_path: GodotPckEntry | str) -> bytes:
        entry = entry_or_path if isinstance(entry_or_path, GodotPckEntry) else self.find_entry(entry_or_path)
        if entry is None:
            raise FileNotFoundError(f"PCK 中不存在目标资源：{entry_or_path}")

        header = self.read_header()
        absolute_offset = header.file_base + entry.offset
        with self.pck_path.open("rb") as handle:
            handle.seek(absolute_offset)
            data = handle.read(entry.size)

        if len(data) != entry.size:
            raise PckExtractError(
                f"读取资源内容长度不完整：{entry.path}（期望 {entry.size}，实际 {len(data)}）"
            )
        return data

