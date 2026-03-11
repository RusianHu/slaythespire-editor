from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


STS2_STEAM_APP_ID = "2868840"
STS2_GAME_FOLDER_NAME = "Slay the Spire 2"
STS2_PCK_FILENAME = "SlayTheSpire2.pck"
CONFIG_DIRNAME = "slaythespire-editor"
CONFIG_FILENAME = "sts2_paths.json"


def _default_appdata_root() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata).expanduser().resolve()
    return (Path.home() / "AppData" / "Roaming").resolve()


STS2_CONFIG_DIR = _default_appdata_root() / CONFIG_DIRNAME
STS2_CONFIG_FILE = STS2_CONFIG_DIR / CONFIG_FILENAME


@dataclass(slots=True)
class StS2PathConfig:
    save_dir: str | None = None
    pck_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "save_dir": self.save_dir,
            "pck_path": self.pck_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StS2PathConfig":
        if not isinstance(data, dict):
            return cls()
        save_dir = data.get("save_dir")
        pck_path = data.get("pck_path")
        return cls(
            save_dir=save_dir if isinstance(save_dir, str) and save_dir.strip() else None,
            pck_path=pck_path if isinstance(pck_path, str) and pck_path.strip() else None,
        )


@dataclass(slots=True)
class ResolvedExternalPath:
    path: Path | None
    source: str
    candidates: list[Path] = field(default_factory=list)

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.exists()


@dataclass(slots=True)
class PathValidationResult:
    ok: bool
    normalized_path: Path | None
    message: str
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_optional_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def load_sts2_path_config() -> StS2PathConfig:
    if not STS2_CONFIG_FILE.exists():
        return StS2PathConfig()

    try:
        data = json.loads(STS2_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return StS2PathConfig()
    return StS2PathConfig.from_dict(data)


def save_sts2_path_config(config: StS2PathConfig) -> Path:
    STS2_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STS2_CONFIG_FILE.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return STS2_CONFIG_FILE


def update_sts2_path_config(
    *,
    save_dir: str | Path | None | object = ...,  # type: ignore[assignment]
    pck_path: str | Path | None | object = ...,  # type: ignore[assignment]
) -> StS2PathConfig:
    config = load_sts2_path_config()

    if save_dir is not ...:
        normalized_save_dir = _normalize_optional_path(save_dir if save_dir is not None else None)
        config.save_dir = str(normalized_save_dir) if normalized_save_dir is not None else None

    if pck_path is not ...:
        normalized_pck_path = _normalize_optional_path(pck_path if pck_path is not None else None)
        config.pck_path = str(normalized_pck_path) if normalized_pck_path is not None else None

    save_sts2_path_config(config)
    return config


def clear_sts2_path_config() -> StS2PathConfig:
    return update_sts2_path_config(save_dir=None, pck_path=None)


def external_path_source_label(source: str) -> str:
    labels = {
        "explicit": "命令行/调用参数",
        "config": "已保存设置",
        "auto": "自动探测",
        "missing": "未找到",
    }
    return labels.get(source, source)


def _read_registry_steam_roots() -> list[Path]:
    if winreg is None:
        return []

    registry_queries: list[tuple[Any, str, str]] = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]

    results: list[Path] = []
    for hive, key_path, value_name in registry_queries:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue

        if not isinstance(value, str) or not value.strip():
            continue

        candidate = Path(value)
        if candidate.suffix.lower() == ".exe":
            candidate = candidate.parent
        results.append(candidate.expanduser().resolve())

    return results


def _default_steam_root_candidates() -> list[Path]:
    candidates: list[Path] = []

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Steam")

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Steam")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Steam")

    candidates.extend(_read_registry_steam_roots())
    return candidates


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


_LIBRARY_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')


def _parse_libraryfolders_vdf(libraryfolders_path: Path) -> list[Path]:
    if not libraryfolders_path.exists() or not libraryfolders_path.is_file():
        return []

    try:
        text = libraryfolders_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    paths: list[Path] = []
    for match in _LIBRARY_PATH_RE.finditer(text):
        raw_path = match.group(1).replace("\\\\", "\\")
        if raw_path.strip():
            paths.append(Path(raw_path).expanduser())
    return paths


def detect_steam_roots() -> list[Path]:
    candidates = _dedupe_paths(_default_steam_root_candidates())
    results: list[Path] = []
    for path in candidates:
        if not path.exists() or not path.is_dir():
            continue
        if (path / "steamapps").exists() or (path / "userdata").exists():
            results.append(path)
    return results


def detect_steam_library_roots() -> list[Path]:
    results: list[Path] = []
    steam_roots = detect_steam_roots()

    for steam_root in steam_roots:
        results.append(steam_root)
        libraryfolders_path = steam_root / "steamapps" / "libraryfolders.vdf"
        results.extend(_parse_libraryfolders_vdf(libraryfolders_path))

    final_results: list[Path] = []
    for path in _dedupe_paths(results):
        if (path / "steamapps").exists() and (path / "steamapps").is_dir():
            final_results.append(path)
    return final_results


def detect_sts2_install_dirs() -> list[Path]:
    candidates: list[Path] = []
    for library_root in detect_steam_library_roots():
        install_dir = library_root / "steamapps" / "common" / STS2_GAME_FOLDER_NAME
        if install_dir.exists() and install_dir.is_dir():
            candidates.append(install_dir)
    return _dedupe_paths(candidates)


def detect_sts2_pck_paths() -> list[Path]:
    candidates: list[Path] = []
    for install_dir in detect_sts2_install_dirs():
        pck_path = install_dir / STS2_PCK_FILENAME
        if pck_path.exists() and pck_path.is_file():
            candidates.append(pck_path)
    return _dedupe_paths(candidates)


def _save_dir_score(path: Path) -> tuple[int, int, str]:
    score = 0
    if (path / "prefs.save").exists():
        score -= 4
    if (path / "progress.save").exists():
        score -= 4
    if (path / "current_run.save").exists():
        score -= 3
    if (path / "current_run.save.backup").exists():
        score -= 2
    if (path / "history").is_dir():
        score -= 1

    profile_name = path.parent.name.lower()
    profile_index = 999
    if profile_name.startswith("profile"):
        suffix = profile_name[len("profile"):]
        if suffix.isdigit():
            profile_index = int(suffix)

    return (score, profile_index, str(path).lower())


def detect_sts2_save_dirs() -> list[Path]:
    candidates: list[Path] = []
    for steam_root in detect_steam_roots():
        userdata_root = steam_root / "userdata"
        if not userdata_root.exists() or not userdata_root.is_dir():
            continue

        for user_dir in userdata_root.iterdir():
            if not user_dir.is_dir():
                continue
            remote_root = user_dir / STS2_STEAM_APP_ID / "remote"
            if not remote_root.exists() or not remote_root.is_dir():
                continue

            for profile_dir in remote_root.glob("profile*"):
                saves_dir = profile_dir / "saves"
                if saves_dir.exists() and saves_dir.is_dir():
                    candidates.append(saves_dir)

    unique_candidates = _dedupe_paths(candidates)
    unique_candidates.sort(key=_save_dir_score)
    return unique_candidates


def resolve_sts2_save_dir(explicit_save_dir: str | Path | None = None) -> ResolvedExternalPath:
    normalized_explicit = _normalize_optional_path(explicit_save_dir)
    if normalized_explicit is not None:
        return ResolvedExternalPath(path=normalized_explicit, source="explicit")

    config = load_sts2_path_config()
    normalized_config = _normalize_optional_path(config.save_dir)
    if normalized_config is not None:
        return ResolvedExternalPath(path=normalized_config, source="config")

    candidates = detect_sts2_save_dirs()
    if candidates:
        return ResolvedExternalPath(path=candidates[0], source="auto", candidates=candidates)

    return ResolvedExternalPath(path=None, source="missing", candidates=[])


def resolve_sts2_pck_path(explicit_pck_path: str | Path | None = None) -> ResolvedExternalPath:
    normalized_explicit = _normalize_optional_path(explicit_pck_path)
    if normalized_explicit is not None:
        return ResolvedExternalPath(path=normalized_explicit, source="explicit")

    config = load_sts2_path_config()
    normalized_config = _normalize_optional_path(config.pck_path)
    if normalized_config is not None:
        return ResolvedExternalPath(path=normalized_config, source="config")

    candidates = detect_sts2_pck_paths()
    if candidates:
        return ResolvedExternalPath(path=candidates[0], source="auto", candidates=candidates)

    return ResolvedExternalPath(path=None, source="missing", candidates=[])


def validate_sts2_save_dir(path: str | Path | None) -> PathValidationResult:
    normalized = _normalize_optional_path(path)
    if normalized is None:
        return PathValidationResult(
            ok=False,
            normalized_path=None,
            message="未设置 2 代存档目录。",
            details=[build_missing_save_dir_help_text()],
        )

    if not normalized.exists():
        return PathValidationResult(
            ok=False,
            normalized_path=normalized,
            message=f"2 代存档目录不存在：{normalized}",
            details=[build_missing_save_dir_help_text()],
        )

    if not normalized.is_dir():
        return PathValidationResult(
            ok=False,
            normalized_path=normalized,
            message=f"2 代存档路径不是目录：{normalized}",
            details=["请重新选择包含 prefs.save / progress.save / history / current_run.save 的 saves 目录。"],
        )

    warnings: list[str] = []
    expected_entries = [
        normalized / "prefs.save",
        normalized / "progress.save",
        normalized / "current_run.save",
        normalized / "current_run.save.backup",
        normalized / "history",
    ]
    if not any(path_item.exists() for path_item in expected_entries):
        warnings.append("所选目录存在，但未发现 prefs.save、progress.save、history、current_run.save 等典型 2 代存档内容。")

    return PathValidationResult(
        ok=True,
        normalized_path=normalized,
        message=f"2 代存档目录可用：{normalized}",
        warnings=warnings,
    )


def validate_sts2_pck_path(path: str | Path | None) -> PathValidationResult:
    normalized = _normalize_optional_path(path)
    if normalized is None:
        return PathValidationResult(
            ok=False,
            normalized_path=None,
            message="未设置 SlayTheSpire2.pck 路径。",
            details=[build_missing_pck_help_text()],
        )

    if not normalized.exists():
        return PathValidationResult(
            ok=False,
            normalized_path=normalized,
            message=f"PCK 文件不存在：{normalized}",
            details=[build_missing_pck_help_text()],
        )

    if not normalized.is_file():
        return PathValidationResult(
            ok=False,
            normalized_path=normalized,
            message=f"PCK 路径不是文件：{normalized}",
            details=["请选择游戏安装目录中的 SlayTheSpire2.pck 文件。"],
        )

    warnings: list[str] = []
    if normalized.name.lower() != STS2_PCK_FILENAME.lower():
        warnings.append("所选文件名不是 SlayTheSpire2.pck，请确认它确实来自《杀戮尖塔 2》游戏目录。")
    if normalized.suffix.lower() != ".pck":
        warnings.append("所选文件扩展名不是 .pck，请确认路径是否正确。")

    return PathValidationResult(
        ok=True,
        normalized_path=normalized,
        message=f"PCK 文件可用：{normalized}",
        warnings=warnings,
    )


def _format_candidate_lines(paths: list[Path], *, empty_text: str) -> list[str]:
    if not paths:
        return [empty_text]
    lines = []
    for index, path in enumerate(paths[:8], start=1):
        lines.append(f"{index}. {path}")
    if len(paths) > 8:
        lines.append(f"... 共 {len(paths)} 个候选路径")
    return lines


def build_missing_save_dir_help_text() -> str:
    candidates = detect_sts2_save_dirs()
    lines = [
        "未自动探测到可用的 2 代存档目录。",
        "可尝试：",
        "- 在 GUI 的“路径”菜单或顶部按钮中手动选择存档目录",
        "- 在 CLI 中传入 --save-dir <绝对路径>",
        "- 检查 Steam 是否已登录对应账号，以及是否存在 userdata/<SteamID>/2868840/remote/profile*/saves",
        "自动探测到的候选存档目录：",
    ]
    lines.extend(_format_candidate_lines(candidates, empty_text="- 当前没有找到任何候选目录"))
    return "\n".join(lines)


def build_missing_pck_help_text() -> str:
    candidates = detect_sts2_pck_paths()
    install_dirs = detect_sts2_install_dirs()
    lines = [
        "未自动探测到 SlayTheSpire2.pck。",
        "可尝试：",
        "- 在 GUI 的“路径”菜单或顶部按钮中手动选择 PCK 文件",
        "- 在 CLI 中传入 --pck-path <绝对路径>",
        "- 检查游戏是否安装在 Steam 库目录中，以及安装目录下是否存在 SlayTheSpire2.pck",
        "自动探测到的候选 PCK 路径：",
    ]
    lines.extend(_format_candidate_lines(candidates, empty_text="- 当前没有找到任何候选 PCK 文件"))
    if install_dirs:
        lines.append("自动探测到的游戏安装目录：")
        lines.extend(_format_candidate_lines(install_dirs, empty_text="- 当前没有找到游戏安装目录"))
    return "\n".join(lines)


def build_external_path_status_text(
    *,
    label: str,
    resolved: ResolvedExternalPath,
    optional: bool = False,
) -> str:
    source_text = external_path_source_label(resolved.source)
    if resolved.path is None:
        if optional:
            return f"{label}：未设置（{source_text}）"
        return f"{label}：未找到（{source_text}）"
    return f"{label}：{resolved.path}（来源：{source_text}）"

