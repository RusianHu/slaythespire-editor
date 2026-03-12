from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "杀戮尖塔 2 存档修改器"
APP_URL = "https://github.com/RusianHu/slaythespire-editor"
APP_PUBLISHER = "RusianHu"
BASE_EXE_NAME = "slaythespire-editor-sts2"
INSTALLER_BASE_NAME = "slaythespire-editor-sts2-setup"
TAG_SUFFIX = "-sts2-onefile"
DEFAULT_BASE_VERSION = "0.0.0"

_EXACT_VERSION_PATTERN = re.compile(r"^v?(?P<version>\d+\.\d+\.\d+)(?:" + re.escape(TAG_SUFFIX) + r")?$")
_DESCRIBE_PATTERN = re.compile(
    r"^v?(?P<version>\d+\.\d+\.\d+)"
    + re.escape(TAG_SUFFIX)
    + r"-(?P<distance>\d+)-g(?P<sha>[0-9a-f]+)(?P<dirty>-dirty)?$"
)


@dataclass(frozen=True, slots=True)
class BuildVersionInfo:
    base_version: str
    display_version: str
    filename_version: str
    windows_version_tuple: tuple[int, int, int, int]
    windows_file_version: str
    git_commit: str
    git_describe: str
    exact_tag: bool
    dirty: bool
    source: str
    exe_basename: str
    exe_filename: str
    installer_output_basename: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "app_name": APP_NAME,
            "app_url": APP_URL,
            "app_publisher": APP_PUBLISHER,
            "base_version": self.base_version,
            "display_version": self.display_version,
            "filename_version": self.filename_version,
            "windows_version_tuple": list(self.windows_version_tuple),
            "windows_file_version": self.windows_file_version,
            "git_commit": self.git_commit,
            "git_describe": self.git_describe,
            "exact_tag": self.exact_tag,
            "dirty": self.dirty,
            "source": self.source,
            "exe_basename": self.exe_basename,
            "exe_filename": self.exe_filename,
            "installer_output_basename": self.installer_output_basename,
        }


def _run_git(project_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()



def _normalize_exact_version(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    matched = _EXACT_VERSION_PATTERN.fullmatch(raw_value.strip())
    if matched is None:
        return None
    return matched.group("version")



def _build_display_version(base_version: str, distance: int, git_commit: str, dirty: bool) -> str:
    if distance <= 0 and not dirty:
        return base_version

    suffix_parts: list[str] = []
    if distance > 0:
        suffix_parts.append(str(distance))
    if git_commit:
        suffix_parts.append(f"g{git_commit}")
    if dirty:
        suffix_parts.append("dirty")
    suffix = ".".join(suffix_parts) if suffix_parts else "local"
    return f"{base_version}+{suffix}"



def _build_filename_version(base_version: str, distance: int, git_commit: str, dirty: bool) -> str:
    label = f"v{base_version}"
    if distance > 0:
        label += f"-{distance}"
    if git_commit and (distance > 0 or dirty):
        label += f"-g{git_commit}"
    if dirty:
        label += "-dirty"
    return label



def resolve_build_version(project_root: str | Path, override_version: str | None = None) -> BuildVersionInfo:
    project_root = Path(project_root).expanduser().resolve()

    normalized_override = _normalize_exact_version(
        override_version or os.environ.get("BUILD_VERSION")
    )
    git_commit = _run_git(project_root, "rev-parse", "--short", "HEAD") or "unknown"

    if normalized_override is not None:
        base_version = normalized_override
        distance = 0
        dirty = False
        git_describe = f"override:{normalized_override}"
        source = "环境变量或命令行覆盖版本"
    else:
        git_describe = _run_git(
            project_root,
            "describe",
            "--tags",
            "--match",
            f"v*{TAG_SUFFIX}",
            "--dirty",
            "--always",
            "--long",
        )
        matched = _DESCRIBE_PATTERN.fullmatch(git_describe)
        if matched is not None:
            base_version = matched.group("version")
            distance = int(matched.group("distance"))
            dirty = bool(matched.group("dirty"))
            source = "Git tag 自动解析"
            git_commit = matched.group("sha") or git_commit
        else:
            base_version = DEFAULT_BASE_VERSION
            distance = 0
            dirty = git_describe.endswith("-dirty")
            source = "未命中 sts2 Git tag，使用默认版本回退"

    version_numbers = [int(part) for part in base_version.split(".")]
    build_number = max(distance, 0)
    if dirty and build_number == 0:
        build_number = 1

    windows_version_tuple = (
        version_numbers[0],
        version_numbers[1],
        version_numbers[2],
        build_number,
    )
    windows_file_version = ".".join(str(part) for part in windows_version_tuple)
    display_version = _build_display_version(base_version, distance, git_commit, dirty)
    filename_version = _build_filename_version(base_version, distance, git_commit, dirty)
    exe_basename = f"{BASE_EXE_NAME}-{filename_version}"
    exe_filename = f"{exe_basename}.exe"
    installer_output_basename = f"{INSTALLER_BASE_NAME}-{filename_version}"

    return BuildVersionInfo(
        base_version=base_version,
        display_version=display_version,
        filename_version=filename_version,
        windows_version_tuple=windows_version_tuple,
        windows_file_version=windows_file_version,
        git_commit=git_commit,
        git_describe=git_describe,
        exact_tag=(distance == 0 and not dirty),
        dirty=dirty,
        source=source,
        exe_basename=exe_basename,
        exe_filename=exe_filename,
        installer_output_basename=installer_output_basename,
    )



def write_pyinstaller_version_file(version_info: BuildVersionInfo, output_path: str | Path) -> Path:
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filevers = version_info.windows_version_tuple
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404B0',
          [
            StringStruct('CompanyName', {APP_PUBLISHER!r}),
            StringStruct('FileDescription', {APP_NAME!r}),
            StringStruct('FileVersion', {version_info.windows_file_version!r}),
            StringStruct('InternalName', {BASE_EXE_NAME!r}),
            StringStruct('OriginalFilename', {version_info.exe_filename!r}),
            StringStruct('ProductName', {APP_NAME!r}),
            StringStruct('ProductVersion', {version_info.display_version!r}),
            StringStruct('Comments', {version_info.source!r})
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    output_path.write_text(content, encoding="utf-8")
    return output_path



def write_installer_defines(version_info: BuildVersionInfo, output_path: str | Path) -> Path:
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dist_file = f"dist\\\\{version_info.exe_filename}"
    content = (
        f'#define MyAppVersion "{version_info.display_version}"\n'
        f'#define MyAppExeName "{version_info.exe_filename}"\n'
        f'#define MyDistFile "{dist_file}"\n'
        f'#define MyOutputBaseFilename "{version_info.installer_output_basename}"\n'
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path

