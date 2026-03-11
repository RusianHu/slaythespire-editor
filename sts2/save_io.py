from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import SaveFileInfo, SaveFileKind
from .path_manager import (
    build_missing_save_dir_help_text,
    resolve_sts2_save_dir,
    validate_sts2_save_dir,
)


class SaveIOError(Exception):
    """2 代存档读写基础异常。"""


class SaveValidationError(SaveIOError):
    """存档结构或路径不满足预期。"""


DEFAULT_STS2_INSTALL_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2")
DEFAULT_STS2_PROFILE_SAVE_DIR = Path(r"C:\Program Files (x86)\Steam\userdata")

JSON_INDENT = 2
JSON_ENCODING = "utf-8"


class StS2SaveIO:
    """负责《杀戮尖塔 2》JSON 存档文件的发现、读取、备份和安全写回。"""

    def __init__(self, save_dir: str | Path | None = None):
        result = resolve_sts2_save_dir(save_dir)
        self.save_dir = result.path
        self.save_dir_source = result.source
        self.save_dir_candidates = result.candidates

    def set_save_dir(self, save_dir: str | Path | None) -> Path | None:
        """设置存档目录并更新相关属性。"""
        result = resolve_sts2_save_dir(save_dir)
        self.save_dir = result.path
        self.save_dir_source = result.source
        self.save_dir_candidates = result.candidates
        return self.save_dir

    def ensure_save_dir(self) -> Path:
        validation = validate_sts2_save_dir(self.save_dir)
        
        if not validation.ok:
            # 组合友好的异常信息
            error_message = validation.message
            
            if validation.details:
                error_message += "\n" + "\n".join(validation.details)
            else:
                # 如果没有 details，回退拼接帮助文本
                help_text = build_missing_save_dir_help_text()
                error_message += "\n\n" + help_text
            
            raise SaveValidationError(error_message)
        
        # 校验成功，更新为规范化路径
        if validation.normalized_path is not None:
            self.save_dir = validation.normalized_path
            return validation.normalized_path
        else:
            raise SaveValidationError("2 代存档目录解析失败：校验通过但未返回规范化路径")

    def detect_kind(self, path: str | Path) -> SaveFileKind:
        file_path = Path(path)
        name = file_path.name.lower()
        if name == "prefs.save":
            return SaveFileKind.PREFS
        if name == "progress.save":
            return SaveFileKind.PROGRESS
        if name in ("current_run.save", "current_run.save.backup"):
            return SaveFileKind.CURRENT_RUN
        if file_path.suffix.lower() == ".run" and file_path.parent.name.lower() == "history":
            return SaveFileKind.RUN_HISTORY
        return SaveFileKind.UNKNOWN

    def list_save_files(self) -> list[SaveFileInfo]:
        save_dir = self.ensure_save_dir()
        files: list[SaveFileInfo] = []

        for child in sorted(save_dir.iterdir(), key=lambda p: (p.is_file() is False, p.name.lower())):
            if not child.is_file():
                continue
            kind = self.detect_kind(child)
            if kind is SaveFileKind.UNKNOWN:
                continue
            files.append(self._build_file_info(child, kind))

        history_dir = save_dir / "history"
        if history_dir.is_dir():
            for child in sorted(history_dir.glob("*.run"), key=lambda p: p.name.lower()):
                files.append(self._build_file_info(child, SaveFileKind.RUN_HISTORY))

        # 尝试从本地 AppData 中发现 current_run.save.backup
        backup_path = self._find_local_current_run_backup()
        if backup_path:
            # 只有当它不在已有列表中时才追加
            resolved_backup = backup_path.resolve()
            existing_paths = {info.path.resolve() for info in files}
            if resolved_backup not in existing_paths:
                backup_info = self._build_file_info(backup_path, SaveFileKind.CURRENT_RUN)
                
                # 查找是否已存在真实的 current_run.save
                live_run_index = None
                for i, info in enumerate(files):
                    if info.kind is SaveFileKind.CURRENT_RUN and info.path.name.lower() == "current_run.save":
                        live_run_index = i
                        break
                
                # 如果存在真实 current_run.save，将备份插入到其后一位；否则插入到最前面
                if live_run_index is not None:
                    files.insert(live_run_index + 1, backup_info)
                else:
                    files.insert(0, backup_info)

        return files

    def _find_local_current_run_backup(self) -> Path | None:
        """从本地 AppData 中查找 current_run.save.backup 文件。"""
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None

        steam_root = Path(appdata) / "SlayTheSpire2" / "steam"
        if not steam_root.exists() or not steam_root.is_dir():
            return None

        # 尝试从当前 save_dir 提取 profile 名
        profile_name = None
        current_save_dir = self.save_dir if isinstance(self.save_dir, Path) else None
        if current_save_dir and current_save_dir.name.lower() == "saves":
            profile_name = current_save_dir.parent.name

        # 递归搜索所有 current_run.save.backup 文件
        backup_files = list(steam_root.rglob("current_run.save.backup"))
        if not backup_files:
            return None

        # 如果有 profile 名，优先返回匹配的文件
        if profile_name:
            for backup_file in backup_files:
                parts = backup_file.parts
                # 检查路径中是否包含 \<profile名>\saves\current_run.save.backup
                for i in range(len(parts) - 2):
                    if parts[i] == profile_name and parts[i + 1] == "saves":
                        return backup_file

        # 没有匹配的 profile，返回第一个按路径排序的结果
        return sorted(backup_files, key=lambda p: str(p))[0]

    def read_json_file(self, path: str | Path) -> Any:
        file_path = Path(path).resolve()
        if not file_path.exists():
            raise SaveValidationError(f"文件不存在：{file_path}")
        if not file_path.is_file():
            raise SaveValidationError(f"路径不是文件：{file_path}")

        try:
            text = file_path.read_text(encoding=JSON_ENCODING)
        except UnicodeDecodeError as exc:
            raise SaveIOError(f"文件不是有效的 UTF-8 文本：{file_path}") from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SaveIOError(f"文件不是有效的 JSON：{file_path}") from exc

    def write_json_file(
        self,
        path: str | Path,
        data: Any,
        *,
        create_backup: bool = True,
        validate_kind: bool = True,
    ) -> Path | None:
        file_path = Path(path).resolve()
        if validate_kind and self.detect_kind(file_path) is SaveFileKind.UNKNOWN:
            raise SaveValidationError(f"不是当前已支持的 2 代存档文件：{file_path}")

        if not file_path.exists():
            raise SaveValidationError(f"待写回文件不存在：{file_path}")
        if not file_path.is_file():
            raise SaveValidationError(f"待写回路径不是文件：{file_path}")

        backup_path = self.create_backup(file_path) if create_backup else None
        serialized = json.dumps(data, ensure_ascii=False, indent=JSON_INDENT, sort_keys=False)
        file_path.write_text(serialized + "\n", encoding=JSON_ENCODING, newline="\n")
        return backup_path

    def load_save_file(self, path: str | Path) -> tuple[SaveFileInfo, Any]:
        file_path = Path(path).resolve()
        kind = self.detect_kind(file_path)
        info = self._build_file_info(file_path, kind)
        data = self.read_json_file(file_path)
        return info, data

    def create_backup(self, path: str | Path) -> Path:
        file_path = Path(path).resolve()
        if not file_path.exists() or not file_path.is_file():
            raise SaveValidationError(f"无法为不存在的文件创建备份：{file_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = file_path.with_name(f"{file_path.name}.{timestamp}.bak")
        counter = 1
        while backup_path.exists():
            backup_path = file_path.with_name(f"{file_path.name}.{timestamp}.{counter}.bak")
            counter += 1

        shutil.copy2(file_path, backup_path)
        return backup_path

    def _build_file_info(self, path: Path, kind: SaveFileKind | None = None) -> SaveFileInfo:
        resolved = path.resolve()
        detected_kind = kind or self.detect_kind(resolved)
        display_name = self._display_name_for(resolved, detected_kind)
        return SaveFileInfo(
            path=resolved,
            kind=detected_kind,
            profile_dir=self.ensure_save_dir(),
            display_name=display_name,
        )

    def _display_name_for(self, path: Path, kind: SaveFileKind) -> str:
        if kind is SaveFileKind.PREFS:
            return "偏好设置"
        if kind is SaveFileKind.PROGRESS:
            return "档案进度"
        if kind is SaveFileKind.CURRENT_RUN:
            if path.name.lower() == "current_run.save.backup":
                return "当前战局备份"
            return "当前战局"
        if kind is SaveFileKind.RUN_HISTORY:
            return f"历史战局 {path.stem}"
        return path.name

