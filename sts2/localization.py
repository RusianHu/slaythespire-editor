from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .pck_extract import GodotPckEntry, GodotPckReader
from .save_io import DEFAULT_STS2_INSTALL_DIR
from .path_manager import (
    build_missing_pck_help_text,
    resolve_sts2_pck_path,
    validate_sts2_pck_path,
)

DEFAULT_STS2_PCK_PATH = DEFAULT_STS2_INSTALL_DIR / "SlayTheSpire2.pck"

# Runtime PCK path override for GUI
_RUNTIME_PCK_PATH_OVERRIDE: Path | None = None

_ASCII_STRING_RE = re.compile(rb"[ -~]{8,}")
_LOCALIZATION_PATH_RE = re.compile(
    r"(?:res://)?(?P<path>localization/(?P<locale>[a-z]{3})/[A-Za-z0-9_./\-]+?\.(?:json|md))"
)
_RESOURCE_PATH_RE = re.compile(r"res://[A-Za-z0-9_./@\-]+")

KNOWN_DICTIONARY_FILES = (
    "cards.json",
    "relics.json",
    "potions.json",
    "characters.json",
    "card_keywords.json",
    "powers.json",
    "modifiers.json",
    "enchantments.json",
    "encounters.json",
    "events.json",
    "game_modes.json",
    "intents.json",
    "orbs.json",
    "acts.json",
    "epochs.json",
    "eras.json",
    "monsters.json",
    "map.json",
    "run_history.json",
)


def set_runtime_pck_path_override(pck_path: str | Path | None) -> Path | None:
    """设置运行期 PCK 路径覆盖。若传入为空，则清空覆盖。"""
    global _RUNTIME_PCK_PATH_OVERRIDE
    if pck_path is None:
        _RUNTIME_PCK_PATH_OVERRIDE = None
        return None
    _RUNTIME_PCK_PATH_OVERRIDE = Path(pck_path).expanduser().resolve()
    return _RUNTIME_PCK_PATH_OVERRIDE


def get_runtime_pck_path_override() -> Path | None:
    """获取当前运行期 PCK 路径覆盖。"""
    return _RUNTIME_PCK_PATH_OVERRIDE


def get_effective_pck_cache_key() -> str:
    """返回当前有效 PCK 路径的字符串；若未找到则返回空字符串。"""
    try:
        path = _resolve_effective_pck_path()
        return str(path)
    except (FileNotFoundError, ValueError):
        return ""


def _resolve_effective_pck_path(pck_path: str | Path | None = None) -> Path:
    """
    解析有效的 PCK 路径，优先级：
    1) 显式传入的 pck_path
    2) _RUNTIME_PCK_PATH_OVERRIDE
    3) resolve_sts2_pck_path(None) 的结果
    
    若最终没有路径，抛出 FileNotFoundError。
    对解析到的路径调用 validate_sts2_pck_path 进行校验。
    """
    resolved_path: Path | None = None
    
    if pck_path is not None:
        resolved_path = Path(pck_path).expanduser().resolve()
    elif _RUNTIME_PCK_PATH_OVERRIDE is not None:
        resolved_path = _RUNTIME_PCK_PATH_OVERRIDE
    else:
        result = resolve_sts2_pck_path(None)
        resolved_path = result.path
    
    if resolved_path is None:
        help_text = build_missing_pck_help_text()
        raise FileNotFoundError(f"无法找到 PCK 文件。\n{help_text}")
    
    validation = validate_sts2_pck_path(resolved_path)
    if not validation.ok:
        error_parts = [validation.message]
        if validation.details:
            error_parts.append("\n".join(validation.details))
        else:
            error_parts.append(build_missing_pck_help_text())
        raise FileNotFoundError("\n".join(error_parts))
    
    if validation.normalized_path is None:
        raise FileNotFoundError("PCK 路径校验通过但未返回规范化路径")
    
    return validation.normalized_path


@dataclass(slots=True)
class LocalizationProbeResult:
    pck_path: Path
    locales: list[str] = field(default_factory=list)
    files_by_locale: dict[str, list[str]] = field(default_factory=dict)
    dictionary_files: dict[str, dict[str, str]] = field(default_factory=dict)
    total_localization_files: int = 0
    resource_path_samples: list[str] = field(default_factory=list)
    probe_method: str = "string_scan"
    extraction_supported: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "pck_path": str(self.pck_path),
            "locales": list(self.locales),
            "files_by_locale": {key: list(value) for key, value in self.files_by_locale.items()},
            "dictionary_files": {
                category: dict(locale_map)
                for category, locale_map in self.dictionary_files.items()
            },
            "total_localization_files": self.total_localization_files,
            "resource_path_samples": list(self.resource_path_samples),
            "probe_method": self.probe_method,
            "extraction_supported": self.extraction_supported,
        }


def _trailing_ascii_length(data: bytes) -> int:
    length = 0
    for byte in reversed(data):
        if 32 <= byte <= 126:
            length += 1
        else:
            break
    return length


def iter_ascii_strings(
    path: str | Path,
    *,
    min_length: int = 8,
    chunk_size: int = 8 * 1024 * 1024,
) -> Iterable[str]:
    file_path = Path(path).expanduser().resolve()
    if min_length <= 0:
        raise ValueError("min_length 必须大于 0")
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    tail = b""
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break

            data = tail + chunk
            trailing_ascii_len = _trailing_ascii_length(data)
            if trailing_ascii_len:
                scan_data = data[:-trailing_ascii_len]
                tail = data[-trailing_ascii_len:]
            else:
                scan_data = data
                tail = b""

            for match in _ASCII_STRING_RE.finditer(scan_data):
                yield match.group(0).decode("utf-8", errors="ignore")

    if len(tail) >= min_length:
        yield tail.decode("utf-8", errors="ignore")


def _collect_localization_paths_from_entries(
    entries: Iterable[GodotPckEntry],
) -> tuple[set[str], set[str]]:
    localization_paths: set[str] = set()
    resource_path_samples: set[str] = set()

    for entry in entries:
        normalized = entry.path.replace("\\", "/").lstrip("/")

        match = _LOCALIZATION_PATH_RE.search(normalized)
        if match:
            localization_paths.add(match.group("path"))

        if len(resource_path_samples) < 80:
            resource_path_samples.add(f"res://{normalized}")

    return localization_paths, resource_path_samples


def probe_localization_from_pck(pck_path: str | Path | None = None) -> LocalizationProbeResult:
    target_path = _resolve_effective_pck_path(pck_path)

    localization_paths: set[str] = set()
    resource_path_samples: set[str] = set()
    probe_method = "string_scan"
    extraction_supported = False

    try:
        reader = GodotPckReader(target_path)
        localization_paths, resource_path_samples = _collect_localization_paths_from_entries(reader.list_entries())
        probe_method = "pck_table"
        extraction_supported = True
    except Exception:
        localization_paths.clear()
        resource_path_samples.clear()

    if not localization_paths:
        for text in iter_ascii_strings(target_path):
            for match in _LOCALIZATION_PATH_RE.finditer(text):
                localization_paths.add(match.group("path"))

            if len(resource_path_samples) < 80:
                for match in _RESOURCE_PATH_RE.finditer(text):
                    resource_path_samples.add(match.group(0))
                    if len(resource_path_samples) >= 80:
                        break

    files_by_locale: dict[str, list[str]] = {}
    for localization_path in sorted(localization_paths):
        locale = localization_path.split("/", 2)[1]
        files_by_locale.setdefault(locale, []).append(localization_path)

    dictionary_files: dict[str, dict[str, str]] = {}
    for locale, paths in files_by_locale.items():
        by_name = {Path(path).name.lower(): path for path in paths}
        for filename in KNOWN_DICTIONARY_FILES:
            if filename in by_name:
                category = Path(filename).stem
                dictionary_files.setdefault(category, {})[locale] = by_name[filename]

    return LocalizationProbeResult(
        pck_path=target_path,
        locales=sorted(files_by_locale.keys()),
        files_by_locale=files_by_locale,
        dictionary_files=dictionary_files,
        total_localization_files=sum(len(paths) for paths in files_by_locale.values()),
        resource_path_samples=sorted(resource_path_samples)[:40],
        probe_method=probe_method,
        extraction_supported=extraction_supported,
    )


def extract_localization_json_from_pck(
    resource_path: str,
    pck_path: str | Path | None = None,
) -> Any:
    target_path = _resolve_effective_pck_path(pck_path)
    reader = GodotPckReader(target_path)
    raw = reader.read_entry_bytes(resource_path)
    text = raw.decode("utf-8-sig")
    return json.loads(text)


def build_title_index_from_localization_dict(
    data: dict[str, Any],
    *,
    id_prefix: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not key.endswith(".title"):
            continue
        base = key[: -len(".title")]
        if not base:
            continue
        result[f"{id_prefix}{base}"] = value
    return result


def build_common_localization_indexes_from_pck(
    pck_path: str | Path | None = None,
    *,
    locale: str = "zhs",
) -> dict[str, dict[str, str]]:
    probe_result = probe_localization_from_pck(pck_path)
    category_specs = {
        "cards": ("cards", "CARD."),
        "relics": ("relics", "RELIC."),
        "potions": ("potions", "POTION."),
        "characters": ("characters", "CHARACTER."),
        "enchantments": ("enchantments", "ENCHANTMENT."),
    }

    result: dict[str, dict[str, str]] = {}
    for category, (dictionary_key, prefix) in category_specs.items():
        locale_map = probe_result.dictionary_files.get(dictionary_key, {})
        resource_path = locale_map.get(locale)
        if not resource_path:
            continue

        data = extract_localization_json_from_pck(resource_path, pck_path=probe_result.pck_path)
        if not isinstance(data, dict):
            raise ValueError(f"本地化文件不是 JSON 对象：{resource_path}")

        result[category] = build_title_index_from_localization_dict(data, id_prefix=prefix)

    return result


def build_localization_index_preview_text(
    indexes: dict[str, dict[str, str]],
    *,
    limit_per_category: int = 8,
) -> str:
    lines: list[str] = []
    if not indexes:
        return "未生成任何本地化索引。\n"

    lines.append("【本地化索引样本】")
    for category in sorted(indexes):
        mapping = indexes[category]
        lines.append(f"- {category}: {len(mapping)} 项")
        for key in sorted(mapping)[:limit_per_category]:
            lines.append(f"  - {key} => {mapping[key]}")
        if len(mapping) > limit_per_category:
            lines.append(f"  - ... 共 {len(mapping)} 项")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_localization_probe_text(result: LocalizationProbeResult) -> str:
    lines: list[str] = []
    lines.append(f"PCK 文件：{result.pck_path}")
    lines.append(f"探测方式：{'真实 PCK 文件表' if result.probe_method == 'pck_table' else '字符串扫描'}")
    lines.append(f"支持直接提取：{'是' if result.extraction_supported else '否'}")
    lines.append(f"检测到语言：{', '.join(result.locales) if result.locales else '无'}")
    lines.append(f"本地化文件数量：{result.total_localization_files}")
    lines.append("")

    if result.dictionary_files:
        lines.append("【关键字典文件】")
        for category in sorted(result.dictionary_files):
            locale_map = result.dictionary_files[category]
            pairs = [f"{locale}={path}" for locale, path in sorted(locale_map.items())]
            lines.append(f"- {category}: {' | '.join(pairs)}")
        lines.append("")

    for locale in result.locales:
        lines.append(f"【{locale} 本地化文件】")
        paths = result.files_by_locale.get(locale, [])
        for path in paths[:25]:
            lines.append(f"- {path}")
        if len(paths) > 25:
            lines.append(f"- ... 共 {len(paths)} 个文件")
        lines.append("")

    if result.resource_path_samples:
        lines.append("【资源路径样本】")
        for path in result.resource_path_samples[:20]:
            lines.append(f"- {path}")

    return "\n".join(lines).rstrip() + "\n"

