#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from build_version import (
    resolve_build_version,
    write_installer_defines,
    write_pyinstaller_version_file,
)

PROJECT_ROOT = Path(__file__).resolve().parent
BUILD_ARTIFACT_DIR = PROJECT_ROOT / ".build"
DEFAULT_SPEC_PATH = PROJECT_ROOT / "editor_sts2.spec"
DEFAULT_DIST_DIR = PROJECT_ROOT / "dist"
SUPPORTED_COMMANDS = {"build", "build_exe", "pyinstaller", "py2exe"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建《杀戮尖塔 2》存档修改器的 Windows 单文件可执行程序"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="build_exe",
        help="兼容旧命令：build / build_exe / pyinstaller / py2exe",
    )
    parser.add_argument(
        "--spec",
        default=str(DEFAULT_SPEC_PATH),
        help="指定 PyInstaller spec 文件路径",
    )
    parser.add_argument(
        "--build-version",
        default=None,
        help="覆盖自动解析版本号，格式示例：0.2.1 或 v0.2.1",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="不要传递 --clean 给 PyInstaller",
    )
    parser.add_argument(
        "--no-noconfirm",
        action="store_true",
        help="不要传递 --noconfirm 给 PyInstaller",
    )
    parser.add_argument(
        "pyinstaller_args",
        nargs=argparse.REMAINDER,
        help="透传给 PyInstaller 的额外参数；如需传递选项，请放在 -- 之后",
    )
    return parser



def ensure_pyinstaller_available() -> bool:
    return importlib.util.find_spec("PyInstaller") is not None



def normalize_passthrough_args(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args



def write_build_metadata(metadata: dict[str, object], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = str(args.command).strip().lower()
    if command not in SUPPORTED_COMMANDS:
        parser.error(f"不支持的命令：{args.command}。可用命令：{', '.join(sorted(SUPPORTED_COMMANDS))}")

    if command == "py2exe":
        print("检测到旧的 py2exe 调用，已自动切换为 PyInstaller 构建流程。")

    if not ensure_pyinstaller_available():
        print("未检测到 PyInstaller，无法继续打包。")
        print("请先执行：python -m pip install -U -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-build.txt")
        return 1

    spec_path = Path(args.spec).expanduser().resolve()
    if not spec_path.exists():
        print(f"指定的 spec 文件不存在：{spec_path}")
        return 1

    version_info = resolve_build_version(PROJECT_ROOT, args.build_version)
    BUILD_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    version_file_path = write_pyinstaller_version_file(
        version_info,
        BUILD_ARTIFACT_DIR / "pyinstaller_version_info.txt",
    )
    installer_defines_path = write_installer_defines(
        version_info,
        BUILD_ARTIFACT_DIR / "installer_version.iss",
    )
    expected_output = DEFAULT_DIST_DIR / version_info.exe_filename

    metadata = version_info.to_metadata()
    metadata.update(
        {
            "spec_path": str(spec_path),
            "version_file_path": str(version_file_path),
            "installer_defines_path": str(installer_defines_path),
            "dist_dir": str(DEFAULT_DIST_DIR),
            "dist_relpath": str(Path("dist") / version_info.exe_filename),
            "expected_output": str(expected_output),
        }
    )
    metadata_path = write_build_metadata(metadata, BUILD_ARTIFACT_DIR / "sts2_build_metadata.json")

    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    if not args.no_clean:
        pyinstaller_cmd.append("--clean")
    if not args.no_noconfirm:
        pyinstaller_cmd.append("--noconfirm")
    pyinstaller_cmd.extend(normalize_passthrough_args(args.pyinstaller_args))
    pyinstaller_cmd.append(str(spec_path))

    env = os.environ.copy()
    env["STS2_EXE_BASENAME"] = version_info.exe_basename
    env["STS2_EXE_FILENAME"] = version_info.exe_filename
    env["STS2_DISPLAY_VERSION"] = version_info.display_version
    env["STS2_WINDOWS_FILE_VERSION"] = version_info.windows_file_version
    env["STS2_PYINSTALLER_VERSION_FILE"] = str(version_file_path)
    if args.build_version:
        env["BUILD_VERSION"] = str(args.build_version).strip()

    print("开始构建《杀戮尖塔 2》存档修改器 exe...")
    print(f"项目目录：{PROJECT_ROOT}")
    print(f"Spec 文件：{spec_path}")
    print(f"版本来源：{version_info.source}")
    print(f"Git 描述：{version_info.git_describe or '无'}")
    print(f"显示版本：{version_info.display_version}")
    print(f"Windows 文件版本：{version_info.windows_file_version}")
    print(f"输出文件名：{version_info.exe_filename}")
    print(f"预期输出文件：{expected_output}")
    print(f"版本资源文件：{version_file_path}")
    print(f"安装器定义文件：{installer_defines_path}")
    print(f"构建元数据：{metadata_path}")
    print("执行命令：")
    print(" ".join(f'"{part}"' if " " in part else part for part in pyinstaller_cmd))

    completed = subprocess.run(pyinstaller_cmd, cwd=str(PROJECT_ROOT), env=env)
    if completed.returncode != 0:
        return int(completed.returncode)

    if not expected_output.exists():
        print(f"构建完成，但未找到预期产物：{expected_output}")
        return 1

    print(f"构建成功：{expected_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
