from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import wx

from .models import SaveFileInfo, SaveFileKind
from .save_io import SaveIOError, SaveValidationError, StS2SaveIO
from .structured import (
    build_structured_text,
    apply_run_basic_fields,
    extract_run_basic_fields,
    apply_run_player_fields,
    extract_run_player_fields,
    apply_progress_basic_fields,
    extract_progress_basic_fields,
    extract_prefs_basic_fields,
    apply_prefs_basic_fields,
    format_localized_id_text,
    build_localized_preview_text,
    search_localized_ids,
    clear_localization_runtime_cache,
)
from .localization import set_runtime_pck_path_override
from .path_manager import (
    ResolvedExternalPath,
    build_external_path_status_text,
    resolve_sts2_pck_path,
    update_sts2_path_config,
    validate_sts2_save_dir,
    validate_sts2_pck_path,
    detect_sts2_save_dirs,
    detect_sts2_pck_paths,
)
from .path_settings_dialog import StS2PathSettingsDialog

WINDOW_TITLE = "杀戮尖塔 2 存档修改器"
STATUS_READY = "就绪"


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def summarize_json(data: Any) -> str:
    if isinstance(data, dict):
        keys = list(data.keys())
        preview_keys = ", ".join(keys[:12]) if keys else "无"
        return f"对象 | 顶层键数量: {len(keys)} | 键预览: {preview_keys}"
    if isinstance(data, list):
        return f"数组 | 元素数量: {len(data)}"
    return f"标量 | 类型: {type(data).__name__}"


class StS2MainFrame(wx.Frame):
    def __init__(self, parent: wx.Window | None, save_dir: str | Path | None = None, pck_path: str | Path | None = None):
        self.save_io = StS2SaveIO(save_dir=save_dir)
        resolved_pck = resolve_sts2_pck_path(pck_path)
        self.pck_path = resolved_pck.path
        self.pck_path_source = resolved_pck.source
        self.pck_path_candidates = resolved_pck.candidates
        if self.pck_path is not None:
            set_runtime_pck_path_override(self.pck_path)
        else:
            set_runtime_pck_path_override(None)
        clear_localization_runtime_cache()
        self.file_infos: list[SaveFileInfo] = []
        self.current_info: SaveFileInfo | None = None
        self.current_data: Any = None
        self._layout_refresh_pending = False
        self.path_status_hint = ""

        super().__init__(
            parent=parent,
            id=wx.ID_ANY,
            title=WINDOW_TITLE,
            pos=wx.DefaultPosition,
            size=wx.Size(1100, 720),
            style=wx.DEFAULT_FRAME_STYLE | wx.TAB_TRAVERSAL,
        )

        self._build_menu_bar()
        self._build_ui()
        self.Bind(wx.EVT_SIZE, self.on_frame_size)
        self.CreateStatusBar()
        self.SetStatusText(STATUS_READY)
        self._refresh_path_status_labels()

    def _build_menu_bar(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()

        refresh_item = file_menu.Append(wx.ID_ANY, "刷新文件列表(&R)")
        self.Bind(wx.EVT_MENU, self.on_refresh_files, refresh_item)

        reload_item = file_menu.Append(wx.ID_ANY, "重新加载当前文件(&L)")
        self.Bind(wx.EVT_MENU, self.on_reload_current_file, reload_item)

        save_item = file_menu.Append(wx.ID_ANY, "保存当前文件(&S)")
        self.Bind(wx.EVT_MENU, self.on_save_current_file, save_item)

        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "退出(&X)")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        menu_bar.Append(file_menu, "文件(&F)")

        path_menu = wx.Menu()

        open_path_settings_item = path_menu.Append(wx.ID_ANY, "路径设置(&M)...")
        self.Bind(wx.EVT_MENU, self.on_open_path_settings_dialog, open_path_settings_item)
        path_menu.AppendSeparator()

        choose_save_dir_item = path_menu.Append(wx.ID_ANY, "选择存档目录(&S)...")
        self.Bind(wx.EVT_MENU, self.on_choose_save_dir, choose_save_dir_item)

        auto_detect_save_dir_item = path_menu.Append(wx.ID_ANY, "自动探测存档目录(&D)")
        self.Bind(wx.EVT_MENU, self.on_auto_detect_save_dir, auto_detect_save_dir_item)

        path_menu.AppendSeparator()

        choose_pck_item = path_menu.Append(wx.ID_ANY, "选择 PCK 文件(&K)...")
        self.Bind(wx.EVT_MENU, self.on_choose_pck_file, choose_pck_item)

        auto_detect_pck_item = path_menu.Append(wx.ID_ANY, "自动探测 PCK(&A)")
        self.Bind(wx.EVT_MENU, self.on_auto_detect_pck, auto_detect_pck_item)

        menu_bar.Append(path_menu, "路径(&P)")

        self.SetMenuBar(menu_bar)

    def _build_ui(self) -> None:
        self.main_panel = wx.Panel(self, wx.ID_ANY)
        panel = self.main_panel
        root = wx.BoxSizer(wx.VERTICAL)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_button = wx.Button(panel, wx.ID_ANY, "刷新")
        self.reload_button = wx.Button(panel, wx.ID_ANY, "重载")
        self.save_button = wx.Button(panel, wx.ID_ANY, "保存")
        self.choose_save_dir_button = wx.Button(panel, wx.ID_ANY, "选择存档目录")
        self.auto_detect_button = wx.Button(panel, wx.ID_ANY, "自动探测路径")
        self.choose_pck_button = wx.Button(panel, wx.ID_ANY, "选择 PCK")
        self.directory_label = wx.StaticText(panel, wx.ID_ANY, "存档目录：未解析")
        self.pck_label = wx.StaticText(panel, wx.ID_ANY, "PCK 文件：未解析")

        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_files)
        self.reload_button.Bind(wx.EVT_BUTTON, self.on_reload_current_file)
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save_current_file)
        self.choose_save_dir_button.Bind(wx.EVT_BUTTON, self.on_choose_save_dir)
        self.auto_detect_button.Bind(wx.EVT_BUTTON, self.on_auto_detect_all_paths)
        self.choose_pck_button.Bind(wx.EVT_BUTTON, self.on_choose_pck_file)

        toolbar.Add(self.refresh_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.reload_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.save_button, 0, wx.RIGHT, 16)
        toolbar.Add(self.choose_save_dir_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.auto_detect_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.choose_pck_button, 0)
        root.Add(toolbar, 0, wx.EXPAND | wx.ALL, 8)

        path_status_sizer = wx.BoxSizer(wx.VERTICAL)
        path_status_sizer.Add(self.directory_label, 0, wx.BOTTOM, 4)
        path_status_sizer.Add(self.pck_label, 0)
        root.Add(path_status_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        content = wx.BoxSizer(wx.HORIZONTAL)

        left_panel = wx.BoxSizer(wx.VERTICAL)
        left_panel.Add(wx.StaticText(panel, wx.ID_ANY, "可编辑文件"), 0, wx.BOTTOM, 4)
        self.file_list = wx.ListBox(panel, wx.ID_ANY, style=wx.LB_SINGLE)
        self.file_list.Bind(wx.EVT_LISTBOX, self.on_select_file)
        left_panel.Add(self.file_list, 1, wx.EXPAND)
        content.Add(left_panel, 0, wx.EXPAND | wx.ALL, 8)

        right_panel = wx.BoxSizer(wx.VERTICAL)
        self.file_title = wx.StaticText(panel, wx.ID_ANY, "当前文件：未选择")
        self.file_meta = wx.StaticText(panel, wx.ID_ANY, "")
        self.file_summary = wx.StaticText(panel, wx.ID_ANY, "")

        mono_font = wx.Font(
            10,
            wx.FONTFAMILY_TELETYPE,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
        )

        # Create notebook with three tabs
        self.notebook = wx.Notebook(panel, wx.ID_ANY)

        # Tab 1: 结构化视图 (read-only)
        self.structured_view = wx.TextCtrl(
            self.notebook,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2 | wx.TE_READONLY,
        )
        self.structured_view.SetFont(mono_font)
        self.notebook.AddPage(self.structured_view, "结构化视图")

        # Tab 2: 结构化编辑
        self.structured_edit_panel = wx.ScrolledWindow(
            self.notebook,
            wx.ID_ANY,
            style=wx.TAB_TRAVERSAL | wx.VSCROLL,
        )
        structured_edit_panel = self.structured_edit_panel
        structured_edit_panel.SetScrollRate(10, 10)
        structured_edit_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Description text
        desc_text = wx.StaticText(
            structured_edit_panel, 
            wx.ID_ANY, 
            "当前支持战局基础字段、档案进度和偏好设置的第一版结构化编辑"
        )
        structured_edit_sizer.Add(desc_text, 0, wx.ALL, 10)
        
        # Form fields using FlexGridSizer
        form_sizer = wx.FlexGridSizer(4, 2, 10, 10)
        form_sizer.AddGrowableCol(1, 1)
        
        # Ascension field
        form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "飞升等级 (ascension):"),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.run_ascension_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=99,
            initial=0
        )
        form_sizer.Add(self.run_ascension_ctrl, 1, wx.EXPAND)
        
        # Seed field
        form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "种子 (seed):"),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.run_seed_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        form_sizer.Add(self.run_seed_ctrl, 1, wx.EXPAND)
        
        # Game mode field
        form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "游戏模式 (game_mode):"),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.run_game_mode_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        form_sizer.Add(self.run_game_mode_ctrl, 1, wx.EXPAND)
        
        # Win field
        form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "胜利 (win):"),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.run_win_choice = wx.Choice(
            structured_edit_panel,
            wx.ID_ANY,
            choices=["未设置", "是", "否"]
        )
        self.run_win_choice.SetSelection(0)
        form_sizer.Add(self.run_win_choice, 1, wx.EXPAND)
        
        structured_edit_sizer.Add(form_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Progress.save editing section
        progress_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "档案进度编辑")
        
        # Description text
        progress_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "当前支持档案进度的第一版结构化编辑。"
        )
        progress_box.Add(progress_desc, 0, wx.ALL, 8)
        
        # Progress form fields using FlexGridSizer
        progress_form_sizer = wx.FlexGridSizer(0, 2, 8, 8)
        progress_form_sizer.AddGrowableCol(1, 1)
        
        # Current score field
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "当前分数："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.progress_current_score_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0
        )
        progress_form_sizer.Add(self.progress_current_score_ctrl, 1, wx.EXPAND)
        
        # Floors climbed field
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "总爬塔层数："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.progress_floors_climbed_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0
        )
        progress_form_sizer.Add(self.progress_floors_climbed_ctrl, 1, wx.EXPAND)
        
        # Total playtime field
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "总游玩时长："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.progress_total_playtime_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999999,
            initial=0
        )
        progress_form_sizer.Add(self.progress_total_playtime_ctrl, 1, wx.EXPAND)
        
        # Total unlocks field
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "总解锁数："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.progress_total_unlocks_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0
        )
        progress_form_sizer.Add(self.progress_total_unlocks_ctrl, 1, wx.EXPAND)
        
        # Pending character unlock field
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "待解锁角色："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        self.progress_pending_character_unlock_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            ""
        )
        progress_form_sizer.Add(self.progress_pending_character_unlock_ctrl, 1, wx.EXPAND)
        self.progress_pending_character_unlock_ctrl.Bind(wx.EVT_TEXT, self.on_progress_localized_preview_changed)
        
        # Create the preview control for pending character unlock
        self.progress_pending_character_unlock_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_READONLY,
        )
        
        # Pending character unlock Chinese name preview
        progress_form_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "待解锁角色中文名："),
            0,
            wx.ALIGN_CENTER_VERTICAL
        )
        progress_form_sizer.Add(self.progress_pending_character_unlock_preview_ctrl, 1, wx.EXPAND)
        
        progress_box.Add(progress_form_sizer, 0, wx.EXPAND | wx.ALL, 8)
        structured_edit_sizer.Add(progress_box, 0, wx.EXPAND | wx.ALL, 10)

        player_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "玩家编辑")
        player_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "当前支持战局基础字段，以及玩家卡组/遗物/药水的第一版结构化编辑。每行一个内部 ID。"
        )
        player_box.Add(player_desc, 0, wx.ALL, 8)

        self.run_player_choice = wx.Choice(structured_edit_panel, wx.ID_ANY)
        self.run_player_choice.Bind(wx.EVT_CHOICE, self.on_select_run_player)
        self.run_character_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.run_max_potion_slots_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=20,
            initial=0,
        )
        self.run_deck_ids_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2,
        )
        self.run_relic_ids_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2,
        )
        self.run_potion_ids_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2,
        )
        self.run_deck_ids_ctrl.SetFont(mono_font)
        self.run_relic_ids_ctrl.SetFont(mono_font)
        self.run_potion_ids_ctrl.SetFont(mono_font)
        self.run_deck_ids_ctrl.SetMinSize(wx.Size(-1, 72))
        self.run_relic_ids_ctrl.SetMinSize(wx.Size(-1, 72))
        self.run_potion_ids_ctrl.SetMinSize(wx.Size(-1, 72))

        player_form_sizer = wx.FlexGridSizer(0, 2, 8, 8)
        player_form_sizer.AddGrowableCol(1, 1)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "当前玩家："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_form_sizer.Add(self.run_player_choice, 1, wx.EXPAND)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "角色 ID："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_form_sizer.Add(self.run_character_ctrl, 1, wx.EXPAND)
        
        self.run_character_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_READONLY,
        )
        self.run_character_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        
        # Character Chinese name preview
        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "角色中文名："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_form_sizer.Add(self.run_character_preview_ctrl, 1, wx.EXPAND)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "药水槽上限："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_form_sizer.Add(self.run_max_potion_slots_ctrl, 1, wx.EXPAND)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "卡组 ID（每行一个）："), 0, wx.ALIGN_TOP)
        player_form_sizer.Add(self.run_deck_ids_ctrl, 1, wx.EXPAND)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "遗物 ID（每行一个）："), 0, wx.ALIGN_TOP)
        player_form_sizer.Add(self.run_relic_ids_ctrl, 1, wx.EXPAND)

        player_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "药水 ID（每行一个）："), 0, wx.ALIGN_TOP)
        player_form_sizer.Add(self.run_potion_ids_ctrl, 1, wx.EXPAND)
        
        self.run_deck_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        self.run_relic_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        self.run_potion_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)

        player_box.Add(player_form_sizer, 0, wx.EXPAND | wx.ALL, 8)
        
        # Quick candidate editing section
        candidate_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "快捷编辑（候选搜索 / 下拉选择 / 按钮添加删除；仍然只写内部 ID）"
        )
        player_box.Add(candidate_desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        
        def _build_candidate_row(label_text: str, item_kind: str) -> wx.BoxSizer:
            """Build a candidate editing row with search, choice, add and remove buttons."""
            row = wx.BoxSizer(wx.HORIZONTAL)
            
            # Label
            label = wx.StaticText(structured_edit_panel, wx.ID_ANY, label_text)
            row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            
            # Search box
            search_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
            search_ctrl.Bind(
                wx.EVT_TEXT,
                lambda event, current_kind=item_kind: self.on_run_candidate_search_changed(event, current_kind)
            )
            row.Add(search_ctrl, 1, wx.RIGHT, 8)
            
            # Choice dropdown
            choice_ctrl = wx.Choice(structured_edit_panel, wx.ID_ANY)
            row.Add(choice_ctrl, 1, wx.RIGHT, 8)
            
            # Add button
            add_button = wx.Button(structured_edit_panel, wx.ID_ANY, "添加")
            add_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_add_run_candidate(event, current_kind)
            )
            row.Add(add_button, 0, wx.RIGHT, 8)
            
            # Remove button
            remove_button = wx.Button(structured_edit_panel, wx.ID_ANY, "删除一个")
            remove_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_remove_run_candidate(event, current_kind)
            )
            row.Add(remove_button, 0)
            
            # Store controls as instance attributes
            setattr(self, f"run_{item_kind}_candidate_search_ctrl", search_ctrl)
            setattr(self, f"run_{item_kind}_candidate_choice", choice_ctrl)
            setattr(self, f"run_{item_kind}_candidate_add_button", add_button)
            setattr(self, f"run_{item_kind}_candidate_remove_button", remove_button)
            setattr(self, f"run_{item_kind}_candidate_ids", [])
            
            return row
        
        player_box.Add(_build_candidate_row("卡组候选：", "deck"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        player_box.Add(_build_candidate_row("遗物候选：", "relic"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        player_box.Add(_build_candidate_row("药水候选：", "potion"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        current_items_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "当前列表操作（推荐）：支持选中删除、上移下移、用候选替换；原始多行 ID 仍保留供高级手工编辑。"
        )
        player_box.Add(current_items_desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        def _build_current_items_box(label_text: str, item_kind: str) -> wx.StaticBoxSizer:
            box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, label_text)

            listbox = wx.ListBox(structured_edit_panel, wx.ID_ANY, style=wx.LB_SINGLE)
            listbox.SetMinSize(wx.Size(-1, 120))
            box.Add(listbox, 0, wx.EXPAND | wx.ALL, 6)

            actions = wx.BoxSizer(wx.HORIZONTAL)

            remove_selected_button = wx.Button(structured_edit_panel, wx.ID_ANY, "删除选中")
            remove_selected_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_remove_selected_run_item(event, current_kind)
            )
            actions.Add(remove_selected_button, 0, wx.RIGHT, 8)

            move_up_button = wx.Button(structured_edit_panel, wx.ID_ANY, "上移")
            move_up_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_move_run_item_up(event, current_kind)
            )
            actions.Add(move_up_button, 0, wx.RIGHT, 8)

            move_down_button = wx.Button(structured_edit_panel, wx.ID_ANY, "下移")
            move_down_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_move_run_item_down(event, current_kind)
            )
            actions.Add(move_down_button, 0, wx.RIGHT, 8)

            replace_button = wx.Button(structured_edit_panel, wx.ID_ANY, "用候选替换")
            replace_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_replace_selected_run_item(event, current_kind)
            )
            actions.Add(replace_button, 0)

            box.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            setattr(self, f"run_{item_kind}_items_listbox", listbox)
            setattr(self, f"run_{item_kind}_remove_selected_button", remove_selected_button)
            setattr(self, f"run_{item_kind}_move_up_button", move_up_button)
            setattr(self, f"run_{item_kind}_move_down_button", move_down_button)
            setattr(self, f"run_{item_kind}_replace_button", replace_button)

            return box

        player_box.Add(_build_current_items_box("卡组当前列表", "deck"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        player_box.Add(_build_current_items_box("遗物当前列表", "relic"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        player_box.Add(_build_current_items_box("药水当前列表", "potion"), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        localized_preview_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "中文名预览（仅展示，不会写回存档）"
        )
        player_box.Add(localized_preview_desc, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        
        # Add search and filter controls
        preview_filter_sizer = wx.BoxSizer(wx.HORIZONTAL)
        preview_filter_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "搜索："),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )

        self.run_localized_search_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.run_localized_search_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_filter_changed)
        preview_filter_sizer.Add(self.run_localized_search_ctrl, 1, wx.RIGHT, 12)

        preview_filter_sizer.Add(
            wx.StaticText(structured_edit_panel, wx.ID_ANY, "筛选："),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.run_localized_filter_choice = wx.Choice(
            structured_edit_panel,
            wx.ID_ANY,
            choices=["全部", "卡组", "遗物", "药水"],
        )
        self.run_localized_filter_choice.SetSelection(0)
        self.run_localized_filter_choice.Bind(wx.EVT_CHOICE, self.on_run_localized_filter_changed)
        preview_filter_sizer.Add(self.run_localized_filter_choice, 0)

        player_box.Add(preview_filter_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        
        self.run_localized_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2 | wx.TE_READONLY,
        )
        self.run_localized_preview_ctrl.SetFont(mono_font)
        self.run_localized_preview_ctrl.SetMinSize(wx.Size(-1, 180))
        player_box.Add(self.run_localized_preview_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        
        structured_edit_sizer.Add(player_box, 0, wx.EXPAND | wx.ALL, 10)

        prefs_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "偏好设置编辑")
        prefs_desc = wx.StaticText(
            structured_edit_panel,
            wx.ID_ANY,
            "当前支持偏好设置的第一版结构化编辑。"
        )
        prefs_box.Add(prefs_desc, 0, wx.ALL, 8)

        self.prefs_fast_mode_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.prefs_screenshake_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=10,
            initial=0,
        )
        self.prefs_long_press_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")
        self.prefs_mute_in_background_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")
        self.prefs_show_card_indices_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")
        self.prefs_show_run_timer_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")
        self.prefs_text_effects_enabled_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")
        self.prefs_upload_data_ctrl = wx.CheckBox(structured_edit_panel, wx.ID_ANY, "启用")

        prefs_form_sizer = wx.FlexGridSizer(0, 2, 8, 8)
        prefs_form_sizer.AddGrowableCol(1, 1)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "fast_mode："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_fast_mode_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "screenshake："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_screenshake_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "long_press："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_long_press_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "mute_in_background："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_mute_in_background_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "show_card_indices："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_show_card_indices_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "show_run_timer："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_show_run_timer_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "text_effects_enabled："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_text_effects_enabled_ctrl, 1, wx.EXPAND)

        prefs_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "upload_data："), 0, wx.ALIGN_CENTER_VERTICAL)
        prefs_form_sizer.Add(self.prefs_upload_data_ctrl, 1, wx.EXPAND)

        prefs_box.Add(prefs_form_sizer, 0, wx.EXPAND | wx.ALL, 8)
        structured_edit_sizer.Add(prefs_box, 0, wx.EXPAND | wx.ALL, 10)

        # Apply button
        self.apply_structured_button = wx.Button(
            structured_edit_panel,
            wx.ID_ANY,
            "应用到当前 JSON"
        )
        self.apply_structured_button.Bind(wx.EVT_BUTTON, self.on_apply_structured_edits)
        structured_edit_sizer.Add(self.apply_structured_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        structured_edit_panel.SetSizer(structured_edit_sizer)
        structured_edit_panel.FitInside()
        structured_edit_panel.Layout()
        self.notebook.AddPage(structured_edit_panel, "结构化编辑")
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)

        # Tab 3: JSON 编辑
        self.editor = wx.TextCtrl(
            self.notebook,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2,
        )
        self.editor.SetFont(mono_font)
        self.notebook.AddPage(self.editor, "JSON 编辑")

        right_panel.Add(self.file_title, 0, wx.BOTTOM, 4)
        right_panel.Add(self.file_meta, 0, wx.BOTTOM, 4)
        right_panel.Add(self.file_summary, 0, wx.BOTTOM, 8)
        right_panel.Add(self.notebook, 1, wx.EXPAND)
        content.Add(right_panel, 1, wx.EXPAND | wx.ALL, 8)

        root.Add(content, 1, wx.EXPAND)
        panel.SetSizer(root)

    def _refresh_path_status_labels(self) -> None:
        save_resolved = ResolvedExternalPath(
            path=self.save_io.save_dir,
            source=getattr(self.save_io, "save_dir_source", "missing"),
            candidates=getattr(self.save_io, "save_dir_candidates", []),
        )
        pck_resolved = ResolvedExternalPath(
            path=self.pck_path,
            source=getattr(self, "pck_path_source", "missing"),
            candidates=getattr(self, "pck_path_candidates", []),
        )

        save_status = build_external_path_status_text(label="存档目录", resolved=save_resolved, optional=False)
        pck_status = build_external_path_status_text(label="PCK 文件", resolved=pck_resolved, optional=True)

        save_validation = validate_sts2_save_dir(self.save_io.save_dir)
        pck_validation = validate_sts2_pck_path(self.pck_path)

        if save_validation.ok and save_validation.warnings:
            save_status += f" | 警告：{'; '.join(save_validation.warnings)}"
        if (self.pck_path is not None) and pck_validation.ok and pck_validation.warnings:
            pck_status += f" | 警告：{'; '.join(pck_validation.warnings)}"
        if (self.pck_path is None) and self.path_status_hint:
            pck_status += f" | {self.path_status_hint}"

        self.directory_label.SetLabel(save_status)
        self.pck_label.SetLabel(pck_status)

    def on_open_path_settings_dialog(self, event: wx.CommandEvent | None) -> None:
        dialog = StS2PathSettingsDialog(
            self,
            save_dir=self.save_io.save_dir,
            save_dir_source=getattr(self.save_io, "save_dir_source", "missing"),
            save_dir_candidates=getattr(self.save_io, "save_dir_candidates", []),
            pck_path=self.pck_path,
            pck_path_source=getattr(self, "pck_path_source", "missing"),
            pck_path_candidates=getattr(self, "pck_path_candidates", []),
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            result = dialog.get_result()
        finally:
            dialog.Destroy()

        save_dir = result.get("save_dir")
        save_dir_source = result.get("save_dir_source")
        save_dir_candidates = result.get("save_dir_candidates") or []
        pck_path = result.get("pck_path")
        pck_path_source = result.get("pck_path_source")
        pck_path_candidates = result.get("pck_path_candidates") or []

        if save_dir is not None:
            self._apply_save_dir_change(save_dir, source_hint="已通过路径设置应用存档目录")
            if isinstance(save_dir_source, str):
                self.save_io.save_dir_source = save_dir_source
            if isinstance(save_dir_candidates, list):
                self.save_io.save_dir_candidates = save_dir_candidates

        if pck_path is not None:
            self._apply_pck_path_change(pck_path, source_hint="已通过路径设置应用 PCK 文件")
            if isinstance(pck_path_source, str):
                self.pck_path_source = pck_path_source
            if isinstance(pck_path_candidates, list):
                self.pck_path_candidates = pck_path_candidates
        else:
            self._apply_pck_path_change(None, source_hint="已通过路径设置清除 PCK 文件")
            if isinstance(pck_path_source, str):
                self.pck_path_source = pck_path_source
            if isinstance(pck_path_candidates, list):
                self.pck_path_candidates = pck_path_candidates

        self._refresh_path_status_labels()
        self.SetStatusText("已应用路径设置")

    def on_auto_detect_all_paths(self, event: wx.CommandEvent | None) -> None:
        """同时自动探测存档目录与 PCK 文件。"""
        save_candidates = detect_sts2_save_dirs()
        pck_candidates = detect_sts2_pck_paths()

        changed_parts: list[str] = []

        if save_candidates:
            self._apply_save_dir_change(save_candidates[0], source_hint="已自动探测存档目录")
            self.save_io.save_dir_candidates = save_candidates
            self.save_io.save_dir_source = "auto"
            changed_parts.append(f"存档目录：{save_candidates[0]}")

        if pck_candidates:
            self.pck_path_source = "auto"
            self.pck_path_candidates = pck_candidates
            self._apply_pck_path_change(pck_candidates[0], source_hint="已自动探测 PCK 文件")
            self.pck_path_source = "auto"
            self.pck_path_candidates = pck_candidates
            changed_parts.append(f"PCK：{pck_candidates[0]}")

        self._refresh_path_status_labels()

        if changed_parts:
            self.SetStatusText("已自动探测路径：" + " | ".join(changed_parts))
            return

        wx.MessageBox(
            "未自动探测到可用的存档目录或 PCK 文件。",
            "自动探测失败",
            wx.OK | wx.ICON_WARNING,
        )
        self.SetStatusText("未自动探测到可用的存档目录或 PCK 文件")

    def _apply_save_dir_change(self, save_dir: str | Path | None, *, source_hint: str = "") -> None:
        """Apply save directory change and refresh UI."""
        self.save_io.set_save_dir(save_dir)
        if save_dir is not None:
            update_sts2_path_config(save_dir=save_dir)
        # Removed: if source_hint: self.path_status_hint = source_hint
        # This method should not modify path_status_hint to avoid incorrect PCK status display
        self._refresh_path_status_labels()
        self.refresh_file_list(select_first=True)
        self._queue_layout_refresh()

    def _apply_pck_path_change(self, pck_path: str | Path | None, *, source_hint: str = "") -> None:
        """Apply PCK path change and refresh UI."""
        if pck_path is None:
            self.pck_path = None
            self.pck_path_source = "missing"
            self.pck_path_candidates = []
            set_runtime_pck_path_override(None)
            if source_hint:
                self.path_status_hint = source_hint
        else:
            normalized_path = Path(pck_path).expanduser().resolve()
            self.pck_path = normalized_path
            self.pck_path_source = "explicit"
            self.pck_path_candidates = []
            set_runtime_pck_path_override(self.pck_path)
            update_sts2_path_config(pck_path=self.pck_path)
            # Clear old missing hints when PCK is successfully set
            self.path_status_hint = ""
        
        clear_localization_runtime_cache()
        
        self._refresh_path_status_labels()
        
        if self.current_info is not None and self.current_data is not None:
            self._update_current_views(self.current_info, self.current_data)
            # Refresh candidate choices after PCK switch
            self._update_all_run_candidate_choices()
        else:
            self._update_run_localized_preview()
            self._update_progress_localized_preview()
            self._update_all_run_candidate_choices()
            self._queue_layout_refresh()

    def on_choose_save_dir(self, event: wx.CommandEvent | None) -> None:
        """Handle manual save directory selection."""
        initial_dir = str(self.save_io.save_dir) if self.save_io.save_dir else ""
        
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
            wx.MessageBox(
                validation.message + "\n\n" + "\n".join(validation.details),
                "路径无效",
                wx.OK | wx.ICON_ERROR,
            )
            self.SetStatusText(f"存档目录无效：{validation.message}")
            return
        
        self._apply_save_dir_change(validation.normalized_path, source_hint="已手动选择存档目录")
        self.SetStatusText("已切换存档目录")

    def on_auto_detect_save_dir(self, event: wx.CommandEvent | None) -> None:
        """Handle automatic save directory detection."""
        candidates = detect_sts2_save_dirs()
        
        if not candidates:
            wx.MessageBox(
                "未自动探测到可用的 2 代存档目录。",
                "自动探测失败",
                wx.OK | wx.ICON_WARNING,
            )
            self.SetStatusText("未自动探测到可用的存档目录")
            return
        
        self._apply_save_dir_change(candidates[0], source_hint="已自动探测存档目录")
        self.save_io.save_dir_candidates = candidates
        self.save_io.save_dir_source = "auto"
        self._refresh_path_status_labels()
        self.SetStatusText(f"已自动探测存档目录：{candidates[0]}")

    def on_choose_pck_file(self, event: wx.CommandEvent | None) -> None:
        """Handle manual PCK file selection."""
        initial_dir = ""
        if self.pck_path is not None:
            initial_dir = str(self.pck_path.parent)
        
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
            wx.MessageBox(
                validation.message + "\n\n" + "\n".join(validation.details),
                "PCK 路径无效",
                wx.OK | wx.ICON_ERROR,
            )
            self.SetStatusText(f"PCK 路径无效：{validation.message}")
            return
        
        self._apply_pck_path_change(validation.normalized_path, source_hint="已手动选择 PCK 文件")
        self.SetStatusText("已切换 PCK 文件")

    def on_auto_detect_pck(self, event: wx.CommandEvent | None) -> None:
        """Handle automatic PCK detection."""
        candidates = detect_sts2_pck_paths()
        
        if not candidates:
            wx.MessageBox(
                "未自动探测到 SlayTheSpire2.pck。",
                "自动探测失败",
                wx.OK | wx.ICON_WARNING,
            )
            self.SetStatusText("未自动探测到 PCK 文件")
            return
        
        self.pck_path_source = "auto"
        self.pck_path_candidates = candidates
        self._apply_pck_path_change(candidates[0], source_hint="已自动探测 PCK 文件")
        self.pck_path_source = "auto"
        self.pck_path_candidates = candidates
        self._refresh_path_status_labels()
        self.SetStatusText(f"已自动探测 PCK：{candidates[0]}")

    def initialize_after_show(self) -> None:
        """Defer initial data loading until the frame is visible."""
        self.refresh_file_list(select_first=True)
        self._queue_layout_refresh()

    def _queue_layout_refresh(self) -> None:
        """Queue a layout refresh to coalesce multiple UI updates."""
        if self._layout_refresh_pending:
            return
        self._layout_refresh_pending = True
        wx.CallAfter(self._refresh_layout_now)

    def _refresh_layout_now(self) -> None:
        """Force a full layout refresh for the current visible UI."""
        self._layout_refresh_pending = False

        if hasattr(self, "structured_edit_panel") and self.structured_edit_panel is not None:
            self.structured_edit_panel.Layout()
            self.structured_edit_panel.FitInside()

        if hasattr(self, "notebook") and self.notebook is not None:
            current_page = self.notebook.GetCurrentPage()
            if current_page is not None:
                current_page.Layout()
            self.notebook.Layout()

        if hasattr(self, "main_panel") and self.main_panel is not None:
            self.main_panel.Layout()

        self.Layout()
        self.Refresh()
        self.Update()

    def on_frame_size(self, event: wx.SizeEvent) -> None:
        self._queue_layout_refresh()
        event.Skip()

    def on_notebook_page_changed(self, event: wx.BookCtrlEvent) -> None:
        self._queue_layout_refresh()
        event.Skip()

    def _set_structured_editor_enabled(self, enabled: bool) -> None:
        """Enable or disable all structured editor controls."""
        self.run_ascension_ctrl.Enable(enabled)
        self.run_seed_ctrl.Enable(enabled)
        self.run_game_mode_ctrl.Enable(enabled)
        self.run_win_choice.Enable(enabled)
        self.apply_structured_button.Enable(enabled)
        self._set_run_player_editor_enabled(enabled)
        self._set_progress_editor_enabled(enabled)
        self._set_prefs_editor_enabled(enabled)

    def _set_run_player_editor_enabled(self, enabled: bool) -> None:
        """Enable or disable all player editor controls."""
        if hasattr(self, 'run_player_choice'):
            self.run_player_choice.Enable(enabled)
        if hasattr(self, 'run_character_ctrl'):
            self.run_character_ctrl.Enable(enabled)
        if hasattr(self, 'run_max_potion_slots_ctrl'):
            self.run_max_potion_slots_ctrl.Enable(enabled)
        if hasattr(self, 'run_deck_ids_ctrl'):
            self.run_deck_ids_ctrl.Enable(enabled)
        if hasattr(self, 'run_relic_ids_ctrl'):
            self.run_relic_ids_ctrl.Enable(enabled)
        if hasattr(self, 'run_potion_ids_ctrl'):
            self.run_potion_ids_ctrl.Enable(enabled)
        if hasattr(self, 'run_localized_search_ctrl'):
            self.run_localized_search_ctrl.Enable(enabled)
        if hasattr(self, 'run_localized_filter_choice'):
            self.run_localized_filter_choice.Enable(enabled)
        
        # Enable/disable candidate controls
        for item_kind in ("deck", "relic", "potion"):
            config = self._get_run_candidate_config(item_kind)
            if not config:
                continue
            for attr_name in (
                config["search_ctrl_attr"],
                config["choice_ctrl_attr"],
                config["add_button_attr"],
                config["remove_button_attr"],
                f"run_{item_kind}_items_listbox",
                f"run_{item_kind}_remove_selected_button",
                f"run_{item_kind}_move_up_button",
                f"run_{item_kind}_move_down_button",
                f"run_{item_kind}_replace_button",
            ):
                ctrl = getattr(self, attr_name, None)
                if ctrl is not None:
                    ctrl.Enable(enabled)

    def _set_progress_editor_enabled(self, enabled: bool) -> None:
        """Enable or disable all progress editor controls."""
        if hasattr(self, 'progress_current_score_ctrl'):
            self.progress_current_score_ctrl.Enable(enabled)
        if hasattr(self, 'progress_floors_climbed_ctrl'):
            self.progress_floors_climbed_ctrl.Enable(enabled)
        if hasattr(self, 'progress_total_playtime_ctrl'):
            self.progress_total_playtime_ctrl.Enable(enabled)
        if hasattr(self, 'progress_total_unlocks_ctrl'):
            self.progress_total_unlocks_ctrl.Enable(enabled)
        if hasattr(self, 'progress_pending_character_unlock_ctrl'):
            self.progress_pending_character_unlock_ctrl.Enable(enabled)

    def _set_prefs_editor_enabled(self, enabled: bool) -> None:
        """Enable or disable all prefs editor controls."""
        if hasattr(self, 'prefs_fast_mode_ctrl'):
            self.prefs_fast_mode_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_screenshake_ctrl'):
            self.prefs_screenshake_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_long_press_ctrl'):
            self.prefs_long_press_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_mute_in_background_ctrl'):
            self.prefs_mute_in_background_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_show_card_indices_ctrl'):
            self.prefs_show_card_indices_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_show_run_timer_ctrl'):
            self.prefs_show_run_timer_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_text_effects_enabled_ctrl'):
            self.prefs_text_effects_enabled_ctrl.Enable(enabled)
        if hasattr(self, 'prefs_upload_data_ctrl'):
            self.prefs_upload_data_ctrl.Enable(enabled)

    def _clear_run_player_editor(self) -> None:
        """Clear all player editor controls."""
        if hasattr(self, 'run_player_choice'):
            self.run_player_choice.Set([])
        if hasattr(self, 'run_character_ctrl'):
            self.run_character_ctrl.SetValue("")
        if hasattr(self, 'run_max_potion_slots_ctrl'):
            self.run_max_potion_slots_ctrl.SetValue(0)
        if hasattr(self, 'run_deck_ids_ctrl'):
            self.run_deck_ids_ctrl.SetValue("")
        if hasattr(self, 'run_relic_ids_ctrl'):
            self.run_relic_ids_ctrl.SetValue("")
        if hasattr(self, 'run_potion_ids_ctrl'):
            self.run_potion_ids_ctrl.SetValue("")
        if hasattr(self, 'run_character_preview_ctrl'):
            self.run_character_preview_ctrl.SetValue("")
        if hasattr(self, 'run_localized_preview_ctrl'):
            self.run_localized_preview_ctrl.SetValue("")
        if hasattr(self, 'run_localized_search_ctrl'):
            self.run_localized_search_ctrl.SetValue("")
        if hasattr(self, 'run_localized_filter_choice'):
            self.run_localized_filter_choice.SetSelection(0)
        
        # Clear candidate controls
        for item_kind in ("deck", "relic", "potion"):
            config = self._get_run_candidate_config(item_kind)
            if not config:
                continue
            search_ctrl = getattr(self, config["search_ctrl_attr"], None)
            if search_ctrl is not None:
                search_ctrl.ChangeValue("")
            choice_ctrl = getattr(self, config["choice_ctrl_attr"], None)
            if choice_ctrl is not None:
                choice_ctrl.Set([])
            setattr(self, config["candidate_ids_attr"], [])

            items_listbox = getattr(self, f"run_{item_kind}_items_listbox", None)
            if items_listbox is not None:
                items_listbox.Set([])

    def _clear_progress_editor(self) -> None:
        """Clear all progress editor controls."""
        if hasattr(self, 'progress_current_score_ctrl'):
            self.progress_current_score_ctrl.SetValue(0)
        if hasattr(self, 'progress_floors_climbed_ctrl'):
            self.progress_floors_climbed_ctrl.SetValue(0)
        if hasattr(self, 'progress_total_playtime_ctrl'):
            self.progress_total_playtime_ctrl.SetValue(0)
        if hasattr(self, 'progress_total_unlocks_ctrl'):
            self.progress_total_unlocks_ctrl.SetValue(0)
        if hasattr(self, 'progress_pending_character_unlock_ctrl'):
            self.progress_pending_character_unlock_ctrl.SetValue("")
        if hasattr(self, 'progress_pending_character_unlock_preview_ctrl'):
            self.progress_pending_character_unlock_preview_ctrl.SetValue("")

    def _clear_prefs_editor(self) -> None:
        """Clear all prefs editor controls."""
        if hasattr(self, 'prefs_fast_mode_ctrl'):
            self.prefs_fast_mode_ctrl.SetValue("")
        if hasattr(self, 'prefs_screenshake_ctrl'):
            self.prefs_screenshake_ctrl.SetValue(0)
        if hasattr(self, 'prefs_long_press_ctrl'):
            self.prefs_long_press_ctrl.SetValue(False)
        if hasattr(self, 'prefs_mute_in_background_ctrl'):
            self.prefs_mute_in_background_ctrl.SetValue(False)
        if hasattr(self, 'prefs_show_card_indices_ctrl'):
            self.prefs_show_card_indices_ctrl.SetValue(False)
        if hasattr(self, 'prefs_show_run_timer_ctrl'):
            self.prefs_show_run_timer_ctrl.SetValue(False)
        if hasattr(self, 'prefs_text_effects_enabled_ctrl'):
            self.prefs_text_effects_enabled_ctrl.SetValue(False)
        if hasattr(self, 'prefs_upload_data_ctrl'):
            self.prefs_upload_data_ctrl.SetValue(False)

    def _update_run_localized_preview(self) -> None:
        """Update run localized preview controls."""
        if not hasattr(self, 'run_character_preview_ctrl') or not hasattr(self, 'run_localized_preview_ctrl'):
            return
        
        # Check if current file is RUN_HISTORY or CURRENT_RUN
        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            self.run_character_preview_ctrl.SetValue("")
            self.run_localized_preview_ctrl.SetValue("")
            self._update_all_run_item_listboxes()
            return
        
        # Update character preview
        character = self.run_character_ctrl.GetValue().strip() if hasattr(self, 'run_character_ctrl') else ""
        character_preview = format_localized_id_text(character, category="characters")
        self.run_character_preview_ctrl.SetValue(character_preview)
        
        # Read deck, relic, and potion IDs
        deck_ids = []
        relic_ids = []
        potion_ids = []
        
        if hasattr(self, 'run_deck_ids_ctrl'):
            deck_ids = [line.strip() for line in self.run_deck_ids_ctrl.GetValue().splitlines() if line.strip()]
        if hasattr(self, 'run_relic_ids_ctrl'):
            relic_ids = [line.strip() for line in self.run_relic_ids_ctrl.GetValue().splitlines() if line.strip()]
        if hasattr(self, 'run_potion_ids_ctrl'):
            potion_ids = [line.strip() for line in self.run_potion_ids_ctrl.GetValue().splitlines() if line.strip()]
        
        # Read search query and selected filter
        search_query = self.run_localized_search_ctrl.GetValue().strip() if hasattr(self, 'run_localized_search_ctrl') else ""
        selected_filter = "全部"
        if hasattr(self, 'run_localized_filter_choice'):
            selected_filter = self.run_localized_filter_choice.GetStringSelection() or "全部"

        empty_text = "无匹配项" if search_query else "无"
        sections: list[str] = []
        
        # Build sections conditionally based on selected filter
        if selected_filter in ("全部", "卡组"):
            deck_preview = build_localized_preview_text(
                deck_ids,
                category="cards",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【卡组】\n{deck_preview}")

        if selected_filter in ("全部", "遗物"):
            relic_preview = build_localized_preview_text(
                relic_ids,
                category="relics",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【遗物】\n{relic_preview}")

        if selected_filter in ("全部", "药水"):
            potion_preview = build_localized_preview_text(
                potion_ids,
                category="potions",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【药水】\n{potion_preview}")

        preview_text = "\n\n".join(sections) if sections else empty_text
        self.run_localized_preview_ctrl.SetValue(preview_text)
        self._update_all_run_item_listboxes()

    def _update_progress_localized_preview(self) -> None:
        """Update progress localized preview controls."""
        if not hasattr(self, 'progress_pending_character_unlock_preview_ctrl'):
            return
        
        # Check if current file is PROGRESS
        if not (self.current_info and self.current_info.kind is SaveFileKind.PROGRESS):
            self.progress_pending_character_unlock_preview_ctrl.SetValue("")
            return
        
        # Read pending character unlock value
        value = self.progress_pending_character_unlock_ctrl.GetValue().strip() if hasattr(self, 'progress_pending_character_unlock_ctrl') else ""
        
        # Format localized text
        preview = format_localized_id_text(value, category="characters")
        self.progress_pending_character_unlock_preview_ctrl.SetValue(preview)

    def on_run_localized_preview_changed(self, event: wx.CommandEvent) -> None:
        """Handle run localized preview change event."""
        self._update_run_localized_preview()
        event.Skip()

    def on_run_localized_filter_changed(self, event: wx.CommandEvent) -> None:
        """Handle run localized preview search/filter event."""
        self._update_run_localized_preview()
        event.Skip()

    def on_progress_localized_preview_changed(self, event: wx.CommandEvent) -> None:
        """Handle progress localized preview change event."""
        self._update_progress_localized_preview()
        event.Skip()

    def _populate_run_player_choices(self, data: Any) -> None:
        """Populate the player choice dropdown with available players."""
        if not hasattr(self, 'run_player_choice'):
            return
        
        if not isinstance(data, dict):
            self.run_player_choice.Set([])
            return
        
        players = data.get("players")
        if not isinstance(players, list):
            self.run_player_choice.Set([])
            return
        
        self.run_player_choice.Set([f"玩家 {i + 1}" for i in range(len(players))])

    def _load_selected_run_player_fields(self) -> None:
        """Load the selected player's fields into the player editor controls."""
        # Only proceed if we have a run history file and player choice control
        if not (self.current_info and 
                self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN) and 
                hasattr(self, 'run_player_choice')):
            self._clear_run_player_editor()
            return
        
        # Update candidate choices
        self._update_all_run_candidate_choices()
        
        selected_index = self.run_player_choice.GetSelection()
        
        # If no player selected, clear fields but keep the choice list
        if selected_index == wx.NOT_FOUND:
            if hasattr(self, 'run_character_ctrl'):
                self.run_character_ctrl.SetValue("")
            if hasattr(self, 'run_max_potion_slots_ctrl'):
                self.run_max_potion_slots_ctrl.SetValue(0)
            if hasattr(self, 'run_deck_ids_ctrl'):
                self.run_deck_ids_ctrl.SetValue("")
            if hasattr(self, 'run_relic_ids_ctrl'):
                self.run_relic_ids_ctrl.SetValue("")
            if hasattr(self, 'run_potion_ids_ctrl'):
                self.run_potion_ids_ctrl.SetValue("")
            self._update_run_localized_preview()
            return
        
        # Extract player fields using top-level import
        try:
            fields = extract_run_player_fields(self.current_data, selected_index)
            
            # Populate controls with extracted fields
            if hasattr(self, 'run_character_ctrl'):
                self.run_character_ctrl.SetValue(fields.get("character") or "")
            if hasattr(self, 'run_max_potion_slots_ctrl'):
                max_potion_slots = fields.get("max_potion_slot_count", 0)
                if not isinstance(max_potion_slots, int):
                    max_potion_slots = 0
                self.run_max_potion_slots_ctrl.SetValue(max_potion_slots)
            if hasattr(self, 'run_deck_ids_ctrl'):
                self.run_deck_ids_ctrl.SetValue("\n".join(fields.get("deck_ids", [])))
            if hasattr(self, 'run_relic_ids_ctrl'):
                self.run_relic_ids_ctrl.SetValue("\n".join(fields.get("relic_ids", [])))
            if hasattr(self, 'run_potion_ids_ctrl'):
                self.run_potion_ids_ctrl.SetValue("\n".join(fields.get("potion_ids", [])))
            
            self._update_run_localized_preview()
                
        except Exception as exc:
            # Clear fields on error
            if hasattr(self, 'run_character_ctrl'):
                self.run_character_ctrl.SetValue("")
            if hasattr(self, 'run_max_potion_slots_ctrl'):
                self.run_max_potion_slots_ctrl.SetValue(0)
            if hasattr(self, 'run_deck_ids_ctrl'):
                self.run_deck_ids_ctrl.SetValue("")
            if hasattr(self, 'run_relic_ids_ctrl'):
                self.run_relic_ids_ctrl.SetValue("")
            if hasattr(self, 'run_potion_ids_ctrl'):
                self.run_potion_ids_ctrl.SetValue("")
            self._update_run_localized_preview()
            self.SetStatusText(f"加载玩家结构化字段失败：{exc}")

    def _load_structured_editor_from_data(self, info: SaveFileInfo, data: Any) -> None:
        """Load structured editor controls from data if applicable."""
        if info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN):
            # Enable controls
            self._set_structured_editor_enabled(True)
            
            # Extract and populate fields with safer assignments
            fields = extract_run_basic_fields(data)
            
            # Introduce local variables with safer value handling
            ascension_value = fields.get("ascension", 0)
            if not isinstance(ascension_value, int):
                ascension_value = 0
            seed_value = fields.get("seed") or ""
            game_mode_value = fields.get("game_mode") or ""
            
            # Check if keys exist in the original data
            has_seed_key = isinstance(data, dict) and "seed" in data
            has_game_mode_key = isinstance(data, dict) and "game_mode" in data
            has_win_key = isinstance(data, dict) and "win" in data
            
            # Set control values
            self.run_ascension_ctrl.SetValue(ascension_value)
            self.run_seed_ctrl.SetValue(seed_value)
            self.run_game_mode_ctrl.SetValue(game_mode_value)
            
            # Map win to choice
            win_value = fields.get("win")
            if win_value is None:
                self.run_win_choice.SetSelection(0)  # 未设置
            elif win_value is True:
                self.run_win_choice.SetSelection(1)  # 是
            else:
                self.run_win_choice.SetSelection(2)  # 否
            
            # Enable/disable controls based on key existence
            # ascension_ctrl always stays enabled
            self.run_seed_ctrl.Enable(has_seed_key)
            self.run_game_mode_ctrl.Enable(has_game_mode_key)
            self.run_win_choice.Enable(has_win_key)
            
            # Populate player choices and load first player if available
            self._populate_run_player_choices(data)
            if hasattr(self, 'run_player_choice') and self.run_player_choice.GetCount() > 0:
                self.run_player_choice.SetSelection(0)
                self._load_selected_run_player_fields()
            else:
                self._clear_run_player_editor()
                self._set_run_player_editor_enabled(False)
                self._update_run_localized_preview()
            
            # Clear and disable progress editor for run history
            self._clear_progress_editor()
            self._set_progress_editor_enabled(False)
            
            # Clear and disable prefs editor for run history
            self._clear_prefs_editor()
            self._set_prefs_editor_enabled(False)
        elif info.kind is SaveFileKind.PROGRESS:
            self._set_structured_editor_enabled(True)
            
            # Reset run basic fields
            self.run_ascension_ctrl.SetValue(0)
            self.run_seed_ctrl.SetValue("")
            self.run_game_mode_ctrl.SetValue("")
            self.run_win_choice.SetSelection(0)
            
            # Clear and disable run player editor
            self._clear_run_player_editor()
            self._set_run_player_editor_enabled(False)
            
            # Extract and populate progress fields
            fields = extract_progress_basic_fields(data)
            if hasattr(self, 'progress_current_score_ctrl'):
                self.progress_current_score_ctrl.SetValue(fields.get("current_score", 0))
            if hasattr(self, 'progress_floors_climbed_ctrl'):
                self.progress_floors_climbed_ctrl.SetValue(fields.get("floors_climbed", 0))
            if hasattr(self, 'progress_total_playtime_ctrl'):
                self.progress_total_playtime_ctrl.SetValue(fields.get("total_playtime", 0))
            if hasattr(self, 'progress_total_unlocks_ctrl'):
                self.progress_total_unlocks_ctrl.SetValue(fields.get("total_unlocks", 0))
            if hasattr(self, 'progress_pending_character_unlock_ctrl'):
                self.progress_pending_character_unlock_ctrl.SetValue(fields.get("pending_character_unlock", ""))
            
            self._update_progress_localized_preview()
            
            # Clear and disable prefs editor for progress
            self._clear_prefs_editor()
            self._set_prefs_editor_enabled(False)
        elif info.kind is SaveFileKind.PREFS:
            # Enable structured editor
            self._set_structured_editor_enabled(True)
            
            # Reset run basic fields
            self.run_ascension_ctrl.SetValue(0)
            self.run_seed_ctrl.SetValue("")
            self.run_game_mode_ctrl.SetValue("")
            self.run_win_choice.SetSelection(0)
            
            # Clear and disable run player editor
            self._clear_run_player_editor()
            self._set_run_player_editor_enabled(False)
            
            # Clear and disable progress editor
            self._clear_progress_editor()
            self._set_progress_editor_enabled(False)
            
            self._update_run_localized_preview()
            self._update_progress_localized_preview()
            
            # Extract and populate prefs fields
            fields = extract_prefs_basic_fields(data)
            if hasattr(self, 'prefs_fast_mode_ctrl'):
                self.prefs_fast_mode_ctrl.SetValue(fields.get("fast_mode", ""))
            if hasattr(self, 'prefs_screenshake_ctrl'):
                self.prefs_screenshake_ctrl.SetValue(fields.get("screenshake", 0))
            if hasattr(self, 'prefs_long_press_ctrl'):
                self.prefs_long_press_ctrl.SetValue(fields.get("long_press", False))
            if hasattr(self, 'prefs_mute_in_background_ctrl'):
                self.prefs_mute_in_background_ctrl.SetValue(fields.get("mute_in_background", False))
            if hasattr(self, 'prefs_show_card_indices_ctrl'):
                self.prefs_show_card_indices_ctrl.SetValue(fields.get("show_card_indices", False))
            if hasattr(self, 'prefs_show_run_timer_ctrl'):
                self.prefs_show_run_timer_ctrl.SetValue(fields.get("show_run_timer", False))
            if hasattr(self, 'prefs_text_effects_enabled_ctrl'):
                self.prefs_text_effects_enabled_ctrl.SetValue(fields.get("text_effects_enabled", False))
            if hasattr(self, 'prefs_upload_data_ctrl'):
                self.prefs_upload_data_ctrl.SetValue(fields.get("upload_data", False))
        else:
            # Non-run, non-progress, and non-prefs files: disable everything
            self._set_structured_editor_enabled(False)
            self.run_ascension_ctrl.SetValue(0)
            self.run_seed_ctrl.SetValue("")
            self.run_game_mode_ctrl.SetValue("")
            self.run_win_choice.SetSelection(0)
            self._clear_run_player_editor()
            self._set_run_player_editor_enabled(False)
            self._clear_progress_editor()
            self._set_progress_editor_enabled(False)
            self._clear_prefs_editor()
            self._set_prefs_editor_enabled(False)
            self._update_run_localized_preview()
            self._update_progress_localized_preview()

    def _update_current_views(self, info: SaveFileInfo, data: Any) -> None:
        """Update all views with the given file info and data."""
        self.current_info = info
        self.current_data = data
        self.file_title.SetLabel(f"当前文件：{info.display_name}")
        self.file_meta.SetLabel(f"类型：{info.kind.value} | 路径：{info.path}")
        self.file_summary.SetLabel(f"摘要：{summarize_json(data)}")
        self.structured_view.SetValue(build_structured_text(info, data))
        self.editor.SetValue(pretty_json(data))
        self._load_structured_editor_from_data(info, data)
        self.SetStatusText(f"已加载：{info.path.name}")
        self._queue_layout_refresh()

    def refresh_file_list(self, *, select_first: bool = False) -> None:
        try:
            self.file_infos = self.save_io.list_save_files()
        except SaveIOError as exc:
            wx.MessageBox(str(exc), "读取失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"读取文件列表失败：{exc}")
            return

        labels = [self._format_file_list_label(info) for info in self.file_infos]
        self.file_list.Set(labels)
        self._refresh_path_status_labels()
        self._queue_layout_refresh()

        if not self.file_infos:
            self.current_info = None
            self.current_data = None
            self.file_title.SetLabel("当前文件：未找到可编辑文件")
            self.file_meta.SetLabel("")
            self.file_summary.SetLabel("")
            self.structured_view.SetValue("")
            self.editor.SetValue("")
            self._clear_run_player_editor()
            self._set_structured_editor_enabled(False)
            self.SetStatusText("未找到可编辑文件")
            self._queue_layout_refresh()
            return

        if select_first:
            self.file_list.SetSelection(0)
            self.load_file_by_index(0)
        else:
            self.SetStatusText(f"已刷新文件列表，共 {len(self.file_infos)} 个文件")

    def load_file_by_index(self, index: int) -> None:
        if index < 0 or index >= len(self.file_infos):
            return

        info = self.file_infos[index]
        try:
            loaded_info, data = self.save_io.load_save_file(info.path)
        except SaveIOError as exc:
            wx.MessageBox(str(exc), "读取失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"读取失败：{exc}")
            return

        self._update_current_views(loaded_info, data)

    def parse_editor_json(self) -> Any:
        raw_text = self.editor.GetValue()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise SaveValidationError(f"当前编辑内容不是合法 JSON：第 {exc.lineno} 行，第 {exc.colno} 列") from exc

    def on_select_file(self, event: wx.CommandEvent) -> None:
        self.load_file_by_index(event.GetSelection())

    def on_select_run_player(self, event: wx.CommandEvent) -> None:
        self._load_selected_run_player_fields()

    def on_refresh_files(self, event: wx.CommandEvent | None) -> None:
        selected = self.file_list.GetSelection()
        self.refresh_file_list(select_first=selected == wx.NOT_FOUND)
        if selected != wx.NOT_FOUND and selected < len(self.file_infos):
            self.file_list.SetSelection(selected)
            self.load_file_by_index(selected)

    def on_reload_current_file(self, event: wx.CommandEvent | None) -> None:
        if self.current_info is None:
            self.SetStatusText("当前没有已加载文件")
            return
        try:
            loaded_info, data = self.save_io.load_save_file(self.current_info.path)
        except SaveIOError as exc:
            wx.MessageBox(str(exc), "重载失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"重载失败：{exc}")
            return

        self._update_current_views(loaded_info, data)

    def on_save_current_file(self, event: wx.CommandEvent | None) -> None:
        if self.current_info is None:
            self.SetStatusText("当前没有可保存的文件")
            return

        try:
            data = self.parse_editor_json()
            backup_path = self.save_io.write_json_file(self.current_info.path, data, create_backup=True)
        except SaveIOError as exc:
            wx.MessageBox(str(exc), "保存失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"保存失败：{exc}")
            return

        self._update_current_views(self.current_info, data)

        backup_hint = f"，备份：{backup_path.name}" if backup_path else ""
        self.SetStatusText(f"已保存：{self.current_info.path.name}{backup_hint}")
        wx.MessageBox(
            f"保存成功。\n\n文件：{self.current_info.path}\n备份：{backup_path}",
            "保存成功",
            wx.OK | wx.ICON_INFORMATION,
        )

    def on_apply_structured_edits(self, event: wx.CommandEvent | None) -> None:
        """Apply structured edits to current JSON data."""
        if self.current_info is None:
            self.SetStatusText("当前文件不支持结构化编辑")
            return

        if self.current_info.kind not in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN, SaveFileKind.PROGRESS, SaveFileKind.PREFS):
            self.SetStatusText("当前文件不支持结构化编辑")
            return

        try:
            if self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN):
                ascension = self.run_ascension_ctrl.GetValue()
                seed = self.run_seed_ctrl.GetValue()
                game_mode = self.run_game_mode_ctrl.GetValue()

                win_choice = self.run_win_choice.GetSelection()
                if win_choice == 0:
                    win = None
                elif win_choice == 1:
                    win = True
                else:
                    win = False

                updated_data = apply_run_basic_fields(
                    self.current_data,
                    ascension=ascension,
                    seed=seed,
                    game_mode=game_mode,
                    win=win,
                )

                selected_player = self.run_player_choice.GetSelection() if hasattr(self, "run_player_choice") else wx.NOT_FOUND
                if selected_player != wx.NOT_FOUND:
                    character = self.run_character_ctrl.GetValue().strip()
                    max_potion_slot_count = self.run_max_potion_slots_ctrl.GetValue()
                    deck_ids = [line.strip() for line in self.run_deck_ids_ctrl.GetValue().splitlines() if line.strip()]
                    relic_ids = [line.strip() for line in self.run_relic_ids_ctrl.GetValue().splitlines() if line.strip()]
                    potion_ids = [line.strip() for line in self.run_potion_ids_ctrl.GetValue().splitlines() if line.strip()]

                    updated_data = apply_run_player_fields(
                        updated_data,
                        player_index=selected_player,
                        character=character,
                        max_potion_slot_count=max_potion_slot_count,
                        deck_ids=deck_ids,
                        relic_ids=relic_ids,
                        potion_ids=potion_ids,
                    )

                self._update_current_views(self.current_info, updated_data)

                if selected_player != wx.NOT_FOUND and hasattr(self, "run_player_choice"):
                    if selected_player < self.run_player_choice.GetCount():
                        self.run_player_choice.SetSelection(selected_player)
                        self._load_selected_run_player_fields()

            elif self.current_info.kind is SaveFileKind.PROGRESS:
                current_score = self.progress_current_score_ctrl.GetValue()
                floors_climbed = self.progress_floors_climbed_ctrl.GetValue()
                total_playtime = self.progress_total_playtime_ctrl.GetValue()
                total_unlocks = self.progress_total_unlocks_ctrl.GetValue()
                pending_character_unlock = self.progress_pending_character_unlock_ctrl.GetValue().strip()

                updated_data = apply_progress_basic_fields(
                    self.current_data,
                    current_score=current_score,
                    floors_climbed=floors_climbed,
                    total_playtime=total_playtime,
                    total_unlocks=total_unlocks,
                    pending_character_unlock=pending_character_unlock,
                )
                self._update_current_views(self.current_info, updated_data)

            else:
                fast_mode = self.prefs_fast_mode_ctrl.GetValue().strip()
                screenshake = self.prefs_screenshake_ctrl.GetValue()
                long_press = self.prefs_long_press_ctrl.GetValue()
                mute_in_background = self.prefs_mute_in_background_ctrl.GetValue()
                show_card_indices = self.prefs_show_card_indices_ctrl.GetValue()
                show_run_timer = self.prefs_show_run_timer_ctrl.GetValue()
                text_effects_enabled = self.prefs_text_effects_enabled_ctrl.GetValue()
                upload_data = self.prefs_upload_data_ctrl.GetValue()

                updated_data = apply_prefs_basic_fields(
                    self.current_data,
                    fast_mode=fast_mode,
                    screenshake=screenshake,
                    long_press=long_press,
                    mute_in_background=mute_in_background,
                    show_card_indices=show_card_indices,
                    show_run_timer=show_run_timer,
                    text_effects_enabled=text_effects_enabled,
                    upload_data=upload_data,
                )
                self._update_current_views(self.current_info, updated_data)

            self.notebook.SetSelection(2)
            self.SetStatusText("已将结构化修改同步到当前 JSON（尚未保存到文件）")

        except Exception as exc:
            wx.MessageBox(str(exc), "结构化修改失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"结构化修改失败：{exc}")
            return

    def on_exit(self, event: wx.CommandEvent | None) -> None:
        self.Close()

    @staticmethod
    def _format_file_list_label(info: SaveFileInfo) -> str:
        return f"{info.display_name} ({info.filename})"

    @staticmethod
    def _get_run_candidate_config(item_kind: str) -> dict[str, str] | None:
        configs = {
            "deck": {
                "display_name": "卡组",
                "category": "cards",
                "prefix": "CARD.",
                "target_ctrl_attr": "run_deck_ids_ctrl",
                "search_ctrl_attr": "run_deck_candidate_search_ctrl",
                "choice_ctrl_attr": "run_deck_candidate_choice",
                "candidate_ids_attr": "run_deck_candidate_ids",
                "add_button_attr": "run_deck_candidate_add_button",
                "remove_button_attr": "run_deck_candidate_remove_button",
            },
            "relic": {
                "display_name": "遗物",
                "category": "relics",
                "prefix": "RELIC.",
                "target_ctrl_attr": "run_relic_ids_ctrl",
                "search_ctrl_attr": "run_relic_candidate_search_ctrl",
                "choice_ctrl_attr": "run_relic_candidate_choice",
                "candidate_ids_attr": "run_relic_candidate_ids",
                "add_button_attr": "run_relic_candidate_add_button",
                "remove_button_attr": "run_relic_candidate_remove_button",
            },
            "potion": {
                "display_name": "药水",
                "category": "potions",
                "prefix": "POTION.",
                "target_ctrl_attr": "run_potion_ids_ctrl",
                "search_ctrl_attr": "run_potion_candidate_search_ctrl",
                "choice_ctrl_attr": "run_potion_candidate_choice",
                "candidate_ids_attr": "run_potion_candidate_ids",
                "add_button_attr": "run_potion_candidate_add_button",
                "remove_button_attr": "run_potion_candidate_remove_button",
            },
        }
        return configs.get(item_kind)

    def _update_run_candidate_choice(self, item_kind: str) -> None:
        """Update candidate choice dropdown based on search query."""
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return
        
        search_ctrl = getattr(self, config["search_ctrl_attr"], None)
        choice_ctrl = getattr(self, config["choice_ctrl_attr"], None)
        if not search_ctrl or not choice_ctrl:
            return
        
        # Check if current file is RUN_HISTORY or CURRENT_RUN
        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            choice_ctrl.Set([])
            setattr(self, config["candidate_ids_attr"], [])
            return
        
        query = search_ctrl.GetValue().strip()
        candidate_ids = search_localized_ids(category=config["category"], query=query, limit=200)
        
        # Store candidate IDs
        setattr(self, config["candidate_ids_attr"], candidate_ids)
        
        # Format labels for display
        labels = [format_localized_id_text(item_id, category=config["category"]) for item_id in candidate_ids]
        choice_ctrl.Set(labels)
        
        if candidate_ids:
            choice_ctrl.SetSelection(0)

    def _update_all_run_candidate_choices(self) -> None:
        """Update all candidate choice dropdowns."""
        for item_kind in ("deck", "relic", "potion"):
            self._update_run_candidate_choice(item_kind)

    def _get_selected_run_candidate_id(self, item_kind: str) -> str | None:
        """Get the selected candidate ID from the choice dropdown."""
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return None
        
        choice_ctrl = getattr(self, config["choice_ctrl_attr"], None)
        candidate_ids = getattr(self, config["candidate_ids_attr"], [])
        
        if not choice_ctrl or not candidate_ids:
            return None
        
        selected_index = choice_ctrl.GetSelection()
        if selected_index == wx.NOT_FOUND or selected_index >= len(candidate_ids):
            return None
        
        return candidate_ids[selected_index]

    def _append_run_candidate_to_editor(self, item_kind: str) -> None:
        """Append selected candidate ID to the target text control."""
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return
        
        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if not target_ctrl:
            return
        
        selected_id = self._get_selected_run_candidate_id(item_kind)
        if not selected_id:
            self.SetStatusText(f"当前没有可添加的{config['display_name']}候选项")
            return
        
        # Read existing IDs
        lines = [line.strip() for line in target_ctrl.GetValue().splitlines() if line.strip()]
        
        # Append selected ID
        lines.append(selected_id)
        
        # Write back
        target_ctrl.SetValue("\n".join(lines))
        self.SetStatusText(f"已添加{config['display_name']} ID：{selected_id}")

    def _remove_run_candidate_from_editor(self, item_kind: str) -> None:
        """Remove one instance of selected candidate ID from the target text control."""
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return
        
        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if not target_ctrl:
            return
        
        selected_id = self._get_selected_run_candidate_id(item_kind)
        if not selected_id:
            self.SetStatusText(f"当前没有可删除的{config['display_name']}候选项")
            return
        
        # Read existing IDs
        lines = [line.strip() for line in target_ctrl.GetValue().splitlines() if line.strip()]
        
        if not lines:
            self.SetStatusText(f"当前{config['display_name']}列表为空")
            return
        
        # Build removable IDs set (include both with and without prefix)
        removable_ids = {selected_id}
        if selected_id.startswith(config["prefix"]):
            removable_ids.add(selected_id[len(config["prefix"]):])
        
        # Find last matching ID from the end
        removed_id = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i] in removable_ids:
                removed_id = lines[i]
                del lines[i]
                break
        
        if removed_id is None:
            self.SetStatusText(f"当前{config['display_name']}列表中不存在：{selected_id}")
            return
        
        # Write back
        target_ctrl.SetValue("\n".join(lines))
        self.SetStatusText(f"已删除{config['display_name']} ID：{removed_id}")

    def on_run_candidate_search_changed(self, event: wx.CommandEvent, item_kind: str) -> None:
        """Handle candidate search text change event."""
        self._update_run_candidate_choice(item_kind)
        event.Skip()

    def on_add_run_candidate(self, event: wx.CommandEvent, item_kind: str) -> None:
        """Handle add selected candidate button click."""
        self._append_run_candidate_to_editor(item_kind)

    def on_remove_run_candidate(self, event: wx.CommandEvent, item_kind: str) -> None:
        """Handle remove selected candidate button click."""
        self._remove_run_candidate_from_editor(item_kind)

    def _get_run_item_listbox(self, item_kind: str) -> wx.ListBox | None:
        return getattr(self, f"run_{item_kind}_items_listbox", None)

    def _read_run_item_ids_from_editor(self, item_kind: str) -> list[str]:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return []

        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if target_ctrl is None:
            return []

        return [line.strip() for line in target_ctrl.GetValue().splitlines() if line.strip()]

    def _write_run_item_ids_to_editor(self, item_kind: str, item_ids: list[str]) -> None:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return

        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if target_ctrl is None:
            return

        target_ctrl.SetValue("\n".join(item_ids))

    def _update_run_item_listbox(self, item_kind: str) -> None:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return

        listbox = self._get_run_item_listbox(item_kind)
        if listbox is None:
            return

        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            listbox.Set([])
            return

        current_selection = listbox.GetSelection()
        item_ids = self._read_run_item_ids_from_editor(item_kind)
        labels = [format_localized_id_text(item_id, category=config["category"]) for item_id in item_ids]
        listbox.Set(labels)

        if labels and current_selection != wx.NOT_FOUND:
            listbox.SetSelection(min(current_selection, len(labels) - 1))

    def _update_all_run_item_listboxes(self) -> None:
        for item_kind in ("deck", "relic", "potion"):
            self._update_run_item_listbox(item_kind)

    def _get_selected_run_item_index(self, item_kind: str) -> int | None:
        listbox = self._get_run_item_listbox(item_kind)
        if listbox is None:
            return None

        selected_index = listbox.GetSelection()
        if selected_index == wx.NOT_FOUND:
            return None
        return selected_index

    def _set_selected_run_item_index(self, item_kind: str, index: int) -> None:
        listbox = self._get_run_item_listbox(item_kind)
        if listbox is None:
            return
        if 0 <= index < listbox.GetCount():
            listbox.SetSelection(index)

    def _remove_selected_run_item_from_editor(self, item_kind: str) -> None:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(item_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        item_ids = self._read_run_item_ids_from_editor(item_kind)
        if selected_index < 0 or selected_index >= len(item_ids):
            self.SetStatusText(f"当前{config['display_name']}列表选择无效")
            return

        removed_id = item_ids.pop(selected_index)
        self._write_run_item_ids_to_editor(item_kind, item_ids)
        if item_ids:
            self._set_selected_run_item_index(item_kind, min(selected_index, len(item_ids) - 1))
        self.SetStatusText(f"已删除选中的{config['display_name']}：{removed_id}")

    def _move_selected_run_item_in_editor(self, item_kind: str, direction: int) -> None:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(item_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        item_ids = self._read_run_item_ids_from_editor(item_kind)
        new_index = selected_index + direction
        if new_index < 0 or new_index >= len(item_ids):
            self.SetStatusText(f"选中的{config['display_name']}已无法继续移动")
            return

        item_ids[selected_index], item_ids[new_index] = item_ids[new_index], item_ids[selected_index]
        self._write_run_item_ids_to_editor(item_kind, item_ids)
        self._set_selected_run_item_index(item_kind, new_index)
        move_text = "上移" if direction < 0 else "下移"
        self.SetStatusText(f"已{move_text}选中的{config['display_name']}")

    def _replace_selected_run_item_in_editor(self, item_kind: str) -> None:
        config = self._get_run_candidate_config(item_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(item_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        selected_candidate_id = self._get_selected_run_candidate_id(item_kind)
        if not selected_candidate_id:
            self.SetStatusText(f"当前没有可用于替换的{config['display_name']}候选项")
            return

        item_ids = self._read_run_item_ids_from_editor(item_kind)
        if selected_index < 0 or selected_index >= len(item_ids):
            self.SetStatusText(f"当前{config['display_name']}列表选择无效")
            return

        old_id = item_ids[selected_index]
        item_ids[selected_index] = selected_candidate_id
        self._write_run_item_ids_to_editor(item_kind, item_ids)
        self._set_selected_run_item_index(item_kind, selected_index)
        self.SetStatusText(f"已将选中的{config['display_name']}从 {old_id} 替换为 {selected_candidate_id}")

    def on_remove_selected_run_item(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._remove_selected_run_item_from_editor(item_kind)

    def on_move_run_item_up(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._move_selected_run_item_in_editor(item_kind, -1)

    def on_move_run_item_down(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._move_selected_run_item_in_editor(item_kind, 1)

    def on_replace_selected_run_item(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._replace_selected_run_item_in_editor(item_kind)


class StS2App(wx.App):
    def __init__(self, save_dir: str | Path | None = None, pck_path: str | Path | None = None):
        self.save_dir = save_dir
        self.pck_path = pck_path
        super().__init__(redirect=False)

    def OnInit(self) -> bool:
        self.frame = StS2MainFrame(None, save_dir=self.save_dir, pck_path=self.pck_path)
        self.SetTopWindow(self.frame)
        self.frame.Show()
        wx.CallAfter(self.frame.initialize_after_show)
        return True


def run_sts2_app(save_dir: str | Path | None = None, pck_path: str | Path | None = None) -> int:
    app = StS2App(save_dir=save_dir, pck_path=pck_path)
    app.MainLoop()
    return 0

