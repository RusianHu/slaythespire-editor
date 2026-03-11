#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC_PATH = PROJECT_ROOT / "editor_sts2.spec"
DEFAULT_DIST_PATH = PROJECT_ROOT / "dist" / "slaythespire-editor-sts2.exe"
SUPPORTED_COMMANDS = {"build", "build_exe", "pyinstaller", "py2exe"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建《杀戮尖塔 2》存档修改器的 Windows 可执行文件"
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
        print("请先执行：python -m pip install -U -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller")
        return 1

    spec_path = Path(args.spec).expanduser().resolve()
    if not spec_path.exists():
        print(f"指定的 spec 文件不存在：{spec_path}")
        return 1

    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
    if not args.no_clean:
        pyinstaller_cmd.append("--clean")
    if not args.no_noconfirm:
        pyinstaller_cmd.append("--noconfirm")
    pyinstaller_cmd.extend(normalize_passthrough_args(args.pyinstaller_args))
    pyinstaller_cmd.append(str(spec_path))

    print("开始构建《杀戮尖塔 2》存档修改器 exe...")
    print(f"项目目录：{PROJECT_ROOT}")
    print(f"Spec 文件：{spec_path}")
    print(f"预期输出文件：{DEFAULT_DIST_PATH}")
    print("执行命令：")
    print(" ".join(f'"{part}"' if " " in part else part for part in pyinstaller_cmd))

    completed = subprocess.run(pyinstaller_cmd, cwd=str(PROJECT_ROOT))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
