from __future__ import annotations

from pathlib import Path

import wx

from .path_manager import (
    ResolvedExternalPath,
    build_external_path_status_text,
    detect_sts2_pck_paths,
    detect_sts2_save_dirs,
    validate_sts2_pck_path,
    validate_sts2_save_dir,
)


class StS2PathSettingsDialog(wx.Dialog):
    """统一管理 2 代存档目录与 PCK 路径的设置对话框。"""

    def __init__(
        self,
        parent: wx.Window,
        *,
        save_dir: Path | None,
        save_dir_source: str,
        save_dir_candidates: list[Path] | None,
        pck_path: Path | None,
        pck_path_source: str,
        pck_path_candidates: list[Path] | None,
    ):
        super().__init__(
            parent=parent,
            title="路径设置",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(860, 620),
        )

        self.selected_save_dir = save_dir
        self.selected_save_dir_source = save_dir_source
        self.selected_save_dir_candidates = list(save_dir_candidates or [])

        self.selected_pck_path = pck_path
        self.selected_pck_path_source = pck_path_source
        self.selected_pck_candidates = list(pck_path_candidates or [])

        self._build_ui()
        self._refresh_all_status()
        self.CentreOnParent()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            wx.ID_ANY,
            "在这里统一查看、选择、自动探测并校验 2 代存档目录与 SlayTheSpire2.pck。\n"
            "点击“应用并关闭”后会写入本地配置，后续启动将自动回用。",
        )
        root.Add(intro, 0, wx.EXPAND | wx.ALL, 10)

        root.Add(self._build_save_group(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self._build_pck_group(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttons = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        ok_button = self.FindWindowById(wx.ID_OK)
        if ok_button is not None:
            ok_button.SetLabel("应用并关闭")
        cancel_button = self.FindWindowById(wx.ID_CANCEL)
        if cancel_button is not None:
            cancel_button.SetLabel("取消")
        if buttons is not None:
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(root)
        self.Bind(wx.EVT_BUTTON, self.on_confirm, id=wx.ID_OK)

    def _build_save_group(self, parent: wx.Window) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.VERTICAL, parent, "存档目录")

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.save_dir_ctrl = wx.TextCtrl(parent, wx.ID_ANY, "")
        self.save_dir_browse_button = wx.Button(parent, wx.ID_ANY, "浏览...")
        self.save_dir_detect_button = wx.Button(parent, wx.ID_ANY, "自动探测")

        self.save_dir_browse_button.Bind(wx.EVT_BUTTON, self.on_choose_save_dir)
        self.save_dir_detect_button.Bind(wx.EVT_BUTTON, self.on_auto_detect_save_dir)

        row.Add(self.save_dir_ctrl, 1, wx.RIGHT, 8)
        row.Add(self.save_dir_browse_button, 0, wx.RIGHT, 8)
        row.Add(self.save_dir_detect_button, 0)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.save_dir_status_ctrl = wx.TextCtrl(
            parent,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN,
        )
        self.save_dir_status_ctrl.SetMinSize(wx.Size(-1, 88))
        box.Add(self.save_dir_status_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.save_dir_candidates_ctrl = wx.TextCtrl(
            parent,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN,
        )
        self.save_dir_candidates_ctrl.SetMinSize(wx.Size(-1, 88))
        box.Add(self.save_dir_candidates_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        return box

    def _build_pck_group(self, parent: wx.Window) -> wx.StaticBoxSizer:
        box = wx.StaticBoxSizer(wx.VERTICAL, parent, "PCK 文件")

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.pck_path_ctrl = wx.TextCtrl(parent, wx.ID_ANY, "")
        self.pck_browse_button = wx.Button(parent, wx.ID_ANY, "浏览...")
        self.pck_detect_button = wx.Button(parent, wx.ID_ANY, "自动探测")
        self.pck_clear_button = wx.Button(parent, wx.ID_ANY, "清除")

        self.pck_browse_button.Bind(wx.EVT_BUTTON, self.on_choose_pck_file)
        self.pck_detect_button.Bind(wx.EVT_BUTTON, self.on_auto_detect_pck)
        self.pck_clear_button.Bind(wx.EVT_BUTTON, self.on_clear_pck_file)

        row.Add(self.pck_path_ctrl, 1, wx.RIGHT, 8)
        row.Add(self.pck_browse_button, 0, wx.RIGHT, 8)
        row.Add(self.pck_detect_button, 0, wx.RIGHT, 8)
        row.Add(self.pck_clear_button, 0)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.pck_status_ctrl = wx.TextCtrl(
            parent,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN,
        )
        self.pck_status_ctrl.SetMinSize(wx.Size(-1, 88))
        box.Add(self.pck_status_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.pck_candidates_ctrl = wx.TextCtrl(
            parent,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN,
        )
        self.pck_candidates_ctrl.SetMinSize(wx.Size(-1, 88))
        box.Add(self.pck_candidates_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        return box

    @staticmethod
    def _format_candidates(paths: list[Path], *, empty_text: str) -> str:
        if not paths:
            return empty_text
        lines = [f"{index}. {path}" for index, path in enumerate(paths[:8], start=1)]
        if len(paths) > 8:
            lines.append(f"... 共 {len(paths)} 个候选项")
        return "\n".join(lines)

    def _refresh_all_status(self) -> None:
        self.save_dir_ctrl.SetValue(str(self.selected_save_dir) if self.selected_save_dir else "")
        self.pck_path_ctrl.SetValue(str(self.selected_pck_path) if self.selected_pck_path else "")

        save_resolved = ResolvedExternalPath(
            path=self.selected_save_dir,
            source=self.selected_save_dir_source,
            candidates=self.selected_save_dir_candidates,
        )
        pck_resolved = ResolvedExternalPath(
            path=self.selected_pck_path,
            source=self.selected_pck_path_source,
            candidates=self.selected_pck_candidates,
        )

        save_lines = [build_external_path_status_text(label="存档目录", resolved=save_resolved, optional=False)]
        save_validation = validate_sts2_save_dir(self.selected_save_dir)
        if save_validation.ok and save_validation.warnings:
            save_lines.append("警告：" + "；".join(save_validation.warnings))
        elif not save_validation.ok:
            save_lines.append(save_validation.message)
            if save_validation.details:
                save_lines.extend(save_validation.details)
        self.save_dir_status_ctrl.SetValue("\n".join(save_lines))

        pck_lines = [build_external_path_status_text(label="PCK 文件", resolved=pck_resolved, optional=True)]
        pck_validation = validate_sts2_pck_path(self.selected_pck_path)
        if self.selected_pck_path is None:
            pck_lines.append("未设置时将回退为仅显示内部 ID，但仍可编辑 JSON。")
        elif pck_validation.ok and pck_validation.warnings:
            pck_lines.append("警告：" + "；".join(pck_validation.warnings))
        elif not pck_validation.ok:
            pck_lines.append(pck_validation.message)
            if pck_validation.details:
                pck_lines.extend(pck_validation.details)
        self.pck_status_ctrl.SetValue("\n".join(pck_lines))

        self.save_dir_candidates_ctrl.SetValue(
            self._format_candidates(self.selected_save_dir_candidates, empty_text="当前没有存档目录候选项")
        )
        self.pck_candidates_ctrl.SetValue(
            self._format_candidates(self.selected_pck_candidates, empty_text="当前没有 PCK 候选项")
        )

    def on_choose_save_dir(self, event: wx.CommandEvent | None) -> None:
        initial_dir = str(self.selected_save_dir) if self.selected_save_dir else ""
        with wx.DirDialog(
            self,
            "选择存档目录",
            defaultPath=initial_dir,
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            selected_path = dialog.GetPath()

        validation = validate_sts2_save_dir(selected_path)
        if not validation.ok:
            message = validation.message
            if validation.details:
                message += "\n\n" + "\n".join(validation.details)
            wx.MessageBox(message, "路径无效", wx.OK | wx.ICON_ERROR)
            return

        self.selected_save_dir = validation.normalized_path
        self.selected_save_dir_source = "explicit"
        self.selected_save_dir_candidates = []
        self._refresh_all_status()

    def on_auto_detect_save_dir(self, event: wx.CommandEvent | None) -> None:
        candidates = detect_sts2_save_dirs()
        self.selected_save_dir_candidates = candidates
        if not candidates:
            wx.MessageBox("未自动探测到可用的 2 代存档目录。", "自动探测失败", wx.OK | wx.ICON_WARNING)
            self._refresh_all_status()
            return

        self.selected_save_dir = candidates[0]
        self.selected_save_dir_source = "auto"
        self._refresh_all_status()

    def on_choose_pck_file(self, event: wx.CommandEvent | None) -> None:
        initial_dir = str(self.selected_pck_path.parent) if self.selected_pck_path else ""
        with wx.FileDialog(
            self,
            "选择 PCK 文件",
            defaultDir=initial_dir,
            wildcard="PCK 文件 (*.pck)|*.pck|所有文件 (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            selected_path = dialog.GetPath()

        validation = validate_sts2_pck_path(selected_path)
        if not validation.ok:
            message = validation.message
            if validation.details:
                message += "\n\n" + "\n".join(validation.details)
            wx.MessageBox(message, "PCK 路径无效", wx.OK | wx.ICON_ERROR)
            return

        self.selected_pck_path = validation.normalized_path
        self.selected_pck_path_source = "explicit"
        self.selected_pck_candidates = []
        self._refresh_all_status()

    def on_auto_detect_pck(self, event: wx.CommandEvent | None) -> None:
        candidates = detect_sts2_pck_paths()
        self.selected_pck_candidates = candidates
        if not candidates:
            wx.MessageBox("未自动探测到 SlayTheSpire2.pck。", "自动探测失败", wx.OK | wx.ICON_WARNING)
            self._refresh_all_status()
            return

        self.selected_pck_path = candidates[0]
        self.selected_pck_path_source = "auto"
        self._refresh_all_status()

    def on_clear_pck_file(self, event: wx.CommandEvent | None) -> None:
        self.selected_pck_path = None
        self.selected_pck_path_source = "missing"
        self.selected_pck_candidates = []
        self._refresh_all_status()

    def on_confirm(self, event: wx.CommandEvent) -> None:
        save_validation = validate_sts2_save_dir(self.selected_save_dir)
        if not save_validation.ok:
            message = save_validation.message
            if save_validation.details:
                message += "\n\n" + "\n".join(save_validation.details)
            wx.MessageBox(message, "存档目录无效", wx.OK | wx.ICON_ERROR)
            return

        if self.selected_pck_path is not None:
            pck_validation = validate_sts2_pck_path(self.selected_pck_path)
            if not pck_validation.ok:
                message = pck_validation.message
                if pck_validation.details:
                    message += "\n\n" + "\n".join(pck_validation.details)
                wx.MessageBox(message, "PCK 路径无效", wx.OK | wx.ICON_ERROR)
                return
            self.selected_pck_path = pck_validation.normalized_path

        self.selected_save_dir = save_validation.normalized_path
        self.EndModal(wx.ID_OK)

    def get_result(self) -> dict[str, object]:
        return {
            "save_dir": self.selected_save_dir,
            "save_dir_source": self.selected_save_dir_source,
            "save_dir_candidates": list(self.selected_save_dir_candidates),
            "pck_path": self.selected_pck_path,
            "pck_path_source": self.selected_pck_path_source,
            "pck_path_candidates": list(self.selected_pck_candidates),
        }

