from __future__ import annotations

import json
import os
import subprocess
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
    build_run_item_id_lines,
    build_run_items_preview_text,
    format_run_item_label,
    normalize_run_item_list,
    _rebuild_run_item_list,
)
from .localization import set_runtime_pck_path_override
from .path_manager import (
    STS2_STEAM_APP_ID,
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
from .live_verify import detect_sts2_process_running

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
        self.run_deck_items: list[dict[str, Any]] = []
        self.run_relic_items: list[dict[str, Any]] = []
        self.run_potion_items: list[dict[str, Any]] = []
        self.run_deck_enchantment_candidate_ids: list[str] = []
        self._suppress_run_item_text_sync = False
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

        restart_game_item = file_menu.Append(wx.ID_ANY, "一键重启游戏(&G)")
        self.Bind(wx.EVT_MENU, self.on_restart_game, restart_game_item)

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
        self.restart_game_button = wx.Button(panel, wx.ID_ANY, "重启游戏")
        self.choose_save_dir_button = wx.Button(panel, wx.ID_ANY, "选择存档目录")
        self.auto_detect_button = wx.Button(panel, wx.ID_ANY, "自动探测路径")
        self.choose_pck_button = wx.Button(panel, wx.ID_ANY, "选择 PCK")
        self.directory_label = wx.StaticText(panel, wx.ID_ANY, "存档目录：未解析")
        self.pck_label = wx.StaticText(panel, wx.ID_ANY, "PCK 文件：未解析")

        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_files)
        self.reload_button.Bind(wx.EVT_BUTTON, self.on_reload_current_file)
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save_current_file)
        self.restart_game_button.Bind(wx.EVT_BUTTON, self.on_restart_game)
        self.choose_save_dir_button.Bind(wx.EVT_BUTTON, self.on_choose_save_dir)
        self.auto_detect_button.Bind(wx.EVT_BUTTON, self.on_auto_detect_all_paths)
        self.choose_pck_button.Bind(wx.EVT_BUTTON, self.on_choose_pck_file)

        toolbar.Add(self.refresh_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.reload_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.save_button, 0, wx.RIGHT, 8)
        toolbar.Add(self.restart_game_button, 0, wx.RIGHT, 16)
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
        self.file_list.SetMinSize(wx.Size(260, -1))
        self.file_list.Bind(wx.EVT_LISTBOX, self.on_select_file)
        left_panel.Add(self.file_list, 1, wx.EXPAND)
        left_panel.Add(
            wx.StaticText(
                panel,
                wx.ID_ANY,
                "建议：优先选择 current_run.save / history/*.run，\n然后直接使用右侧“结构化编辑”的顶部物品区。",
            ),
            0,
            wx.TOP,
            8,
        )
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

        self.notebook = wx.Notebook(panel, wx.ID_ANY)
        self.structured_edit_tab_index = 0
        self.structured_view_tab_index = 1
        self.json_editor_tab_index = 2

        self.structured_edit_panel = wx.ScrolledWindow(
            self.notebook,
            wx.ID_ANY,
            style=wx.TAB_TRAVERSAL | wx.VSCROLL,
        )
        structured_edit_panel = self.structured_edit_panel
        structured_edit_panel.SetScrollRate(10, 10)
        structured_edit_sizer = wx.BoxSizer(wx.VERTICAL)

        intro_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "上手即用")
        intro_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "推荐顺序：先在顶部的卡牌 / 遗物 / 药水区直接操作；确认无误后点击底部“同步到 JSON（未保存）”；最后再点击窗口顶部“保存”。",
            ),
            0,
            wx.ALL,
            8,
        )
        intro_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "候选下拉与中文名预览只用于搜索和显示，真正写回存档的始终是内部 ID。",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )
        structured_edit_sizer.Add(intro_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        quick_items_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "卡牌 / 遗物 / 药水（推荐优先使用）")
        quick_items_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "上方搜索候选，下方查看当前列表。常用操作都放在这里，通常不需要先手动改原始 ID 文本。",
            ),
            0,
            wx.ALL,
            8,
        )

        self.run_player_choice = wx.Choice(structured_edit_panel, wx.ID_ANY)
        self.run_player_choice.Bind(wx.EVT_CHOICE, self.on_select_run_player)
        self.run_character_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.run_character_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_READONLY,
        )
        self.run_character_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        self.run_max_potion_slots_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=20,
            initial=0,
        )

        player_header_grid = wx.FlexGridSizer(0, 4, 8, 12)
        player_header_grid.AddGrowableCol(1, 1)
        player_header_grid.AddGrowableCol(3, 1)
        player_header_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "当前玩家："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_header_grid.Add(self.run_player_choice, 1, wx.EXPAND)
        player_header_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "角色 ID："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_header_grid.Add(self.run_character_ctrl, 1, wx.EXPAND)
        player_header_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "角色中文名："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_header_grid.Add(self.run_character_preview_ctrl, 1, wx.EXPAND)
        player_header_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "药水槽上限："), 0, wx.ALIGN_CENTER_VERTICAL)
        player_header_grid.Add(self.run_max_potion_slots_ctrl, 1, wx.EXPAND)
        quick_items_box.Add(player_header_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        def _populate_quick_item_editor(parent: wx.Window, root_sizer: wx.BoxSizer, *, item_kind: str) -> None:
            search_row = wx.BoxSizer(wx.HORIZONTAL)
            search_row.Add(
                wx.StaticText(parent, wx.ID_ANY, "搜索："),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                6,
            )
            search_ctrl = wx.TextCtrl(parent, wx.ID_ANY, "")
            search_ctrl.Bind(
                wx.EVT_TEXT,
                lambda event, current_kind=item_kind: self.on_run_candidate_search_changed(event, current_kind),
            )
            search_row.Add(search_ctrl, 1, wx.RIGHT, 8)

            search_row.Add(
                wx.StaticText(parent, wx.ID_ANY, "候选："),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                6,
            )
            choice_ctrl = wx.Choice(parent, wx.ID_ANY)
            search_row.Add(choice_ctrl, 1)
            root_sizer.Add(search_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            primary_actions = wx.BoxSizer(wx.HORIZONTAL)
            add_button = wx.Button(parent, wx.ID_ANY, "添加到末尾")
            add_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_add_run_candidate(event, current_kind),
            )
            primary_actions.Add(add_button, 0, wx.RIGHT, 6)

            remove_button = wx.Button(parent, wx.ID_ANY, "删除一个同 ID")
            remove_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_remove_run_candidate(event, current_kind),
            )
            primary_actions.Add(remove_button, 0, wx.RIGHT, 6)

            clear_all_button = wx.Button(parent, wx.ID_ANY, "清空列表")
            clear_all_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_clear_all_run_items(event, current_kind),
            )
            primary_actions.Add(clear_all_button, 0)
            root_sizer.Add(primary_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            listbox = wx.ListBox(parent, wx.ID_ANY, style=wx.LB_SINGLE)
            listbox.SetMinSize(wx.Size(-1, 260 if item_kind == "deck" else 240))
            listbox.Bind(
                wx.EVT_LISTBOX,
                lambda event, current_kind=item_kind: self.on_select_run_item(event, current_kind),
            )
            root_sizer.Add(listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            secondary_actions = wx.BoxSizer(wx.HORIZONTAL)
            remove_selected_button = wx.Button(parent, wx.ID_ANY, "删除选中")
            remove_selected_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_remove_selected_run_item(event, current_kind),
            )
            secondary_actions.Add(remove_selected_button, 0, wx.RIGHT, 6)

            move_up_button = wx.Button(parent, wx.ID_ANY, "上移")
            move_up_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_move_run_item_up(event, current_kind),
            )
            secondary_actions.Add(move_up_button, 0, wx.RIGHT, 6)

            move_down_button = wx.Button(parent, wx.ID_ANY, "下移")
            move_down_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_move_run_item_down(event, current_kind),
            )
            secondary_actions.Add(move_down_button, 0, wx.RIGHT, 6)

            replace_button = wx.Button(parent, wx.ID_ANY, "替换为候选")
            replace_button.Bind(
                wx.EVT_BUTTON,
                lambda event, current_kind=item_kind: self.on_replace_selected_run_item(event, current_kind),
            )
            secondary_actions.Add(replace_button, 0)
            root_sizer.Add(secondary_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            setattr(self, f"run_{item_kind}_candidate_search_ctrl", search_ctrl)
            setattr(self, f"run_{item_kind}_candidate_choice", choice_ctrl)
            setattr(self, f"run_{item_kind}_candidate_add_button", add_button)
            setattr(self, f"run_{item_kind}_candidate_remove_button", remove_button)
            setattr(self, f"run_{item_kind}_candidate_ids", [])
            setattr(self, f"run_{item_kind}_items_listbox", listbox)
            setattr(self, f"run_{item_kind}_remove_selected_button", remove_selected_button)
            setattr(self, f"run_{item_kind}_move_up_button", move_up_button)
            setattr(self, f"run_{item_kind}_move_down_button", move_down_button)
            setattr(self, f"run_{item_kind}_replace_button", replace_button)
            setattr(self, f"run_{item_kind}_clear_all_button", clear_all_button)

        def _build_quick_item_page(title_text: str, item_kind: str) -> wx.Panel:
            page = wx.Panel(self.run_items_notebook, wx.ID_ANY)
            page_sizer = wx.BoxSizer(wx.VERTICAL)

            page_sizer.Add(
                wx.StaticText(page, wx.ID_ANY, f"{title_text}操作区：先搜候选，再对当前列表执行添加、替换、排序或清空。"),
                0,
                wx.ALL,
                6,
            )

            if item_kind == "deck":
                self.run_deck_editor_notebook = wx.Notebook(page, wx.ID_ANY)
                self.run_deck_editor_notebook.SetMinSize(wx.Size(-1, 420))
                self.run_deck_editor_notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)

                deck_list_page = wx.Panel(self.run_deck_editor_notebook, wx.ID_ANY)
                deck_list_sizer = wx.BoxSizer(wx.VERTICAL)
                deck_list_sizer.Add(
                    wx.StaticText(deck_list_page, wx.ID_ANY, "这里专门管理当前卡组内容、顺序与替换。"),
                    0,
                    wx.LEFT | wx.RIGHT | wx.BOTTOM,
                    6,
                )
                _populate_quick_item_editor(deck_list_page, deck_list_sizer, item_kind="deck")
                deck_list_page.SetSizer(deck_list_sizer)
                self.run_deck_editor_notebook.AddPage(deck_list_page, "当前卡组")

                deck_meta_page = wx.Panel(self.run_deck_editor_notebook, wx.ID_ANY)
                deck_meta_sizer = wx.BoxSizer(wx.VERTICAL)
                deck_meta_box = wx.StaticBoxSizer(wx.VERTICAL, deck_meta_page, "选中卡牌附加属性")
                deck_meta_box.Add(
                    wx.StaticText(
                        deck_meta_page,
                        wx.ID_ANY,
                        "选中“当前卡组”中的某张卡后，可在这里直接修改升级等级与附魔。更换卡牌 ID 时会自动清理不再适用的卡牌专属元数据。",
                    ),
                    0,
                    wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
                    6,
                )

                deck_meta_grid = wx.FlexGridSizer(0, 4, 8, 8)
                deck_meta_grid.AddGrowableCol(1, 1)
                deck_meta_grid.AddGrowableCol(3, 1)

                deck_meta_grid.Add(wx.StaticText(deck_meta_page, wx.ID_ANY, "升级等级："), 0, wx.ALIGN_CENTER_VERTICAL)
                self.run_deck_upgrade_level_ctrl = wx.SpinCtrl(
                    deck_meta_page,
                    wx.ID_ANY,
                    min=0,
                    max=99,
                    initial=0,
                )
                deck_meta_grid.Add(self.run_deck_upgrade_level_ctrl, 0, wx.EXPAND)

                deck_meta_grid.Add(wx.StaticText(deck_meta_page, wx.ID_ANY, "附魔搜索："), 0, wx.ALIGN_CENTER_VERTICAL)
                self.run_deck_enchantment_search_ctrl = wx.TextCtrl(deck_meta_page, wx.ID_ANY, "")
                deck_meta_grid.Add(self.run_deck_enchantment_search_ctrl, 1, wx.EXPAND)

                deck_meta_grid.Add(wx.StaticText(deck_meta_page, wx.ID_ANY, "附魔候选："), 0, wx.ALIGN_CENTER_VERTICAL)
                self.run_deck_enchantment_choice = wx.Choice(deck_meta_page, wx.ID_ANY)
                deck_meta_grid.Add(self.run_deck_enchantment_choice, 1, wx.EXPAND)

                deck_meta_grid.Add(wx.StaticText(deck_meta_page, wx.ID_ANY, "附魔层数："), 0, wx.ALIGN_CENTER_VERTICAL)
                self.run_deck_enchantment_amount_ctrl = wx.SpinCtrl(
                    deck_meta_page,
                    wx.ID_ANY,
                    min=1,
                    max=99,
                    initial=1,
                )
                deck_meta_grid.Add(self.run_deck_enchantment_amount_ctrl, 0, wx.EXPAND)
                deck_meta_box.Add(deck_meta_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

                deck_meta_actions = wx.BoxSizer(wx.HORIZONTAL)
                self.run_deck_apply_upgrade_button = wx.Button(deck_meta_page, wx.ID_ANY, "应用升级")
                self.run_deck_clear_upgrade_button = wx.Button(deck_meta_page, wx.ID_ANY, "清除升级")
                self.run_deck_apply_enchantment_button = wx.Button(deck_meta_page, wx.ID_ANY, "应用附魔")
                self.run_deck_clear_enchantment_button = wx.Button(deck_meta_page, wx.ID_ANY, "清除附魔")
                deck_meta_actions.Add(self.run_deck_apply_upgrade_button, 0, wx.RIGHT, 8)
                deck_meta_actions.Add(self.run_deck_clear_upgrade_button, 0, wx.RIGHT, 8)
                deck_meta_actions.Add(self.run_deck_apply_enchantment_button, 0, wx.RIGHT, 8)
                deck_meta_actions.Add(self.run_deck_clear_enchantment_button, 0)
                deck_meta_box.Add(deck_meta_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

                self.run_deck_selected_meta_preview_ctrl = wx.TextCtrl(
                    deck_meta_page,
                    wx.ID_ANY,
                    "",
                    style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.TE_RICH2,
                )
                self.run_deck_selected_meta_preview_ctrl.SetFont(mono_font)
                self.run_deck_selected_meta_preview_ctrl.SetMinSize(wx.Size(-1, 120))
                deck_meta_box.Add(self.run_deck_selected_meta_preview_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

                deck_meta_sizer.Add(deck_meta_box, 1, wx.EXPAND | wx.ALL, 6)
                deck_meta_page.SetSizer(deck_meta_sizer)
                self.run_deck_editor_notebook.AddPage(deck_meta_page, "升级 / 附魔")

                page_sizer.Add(self.run_deck_editor_notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
            else:
                _populate_quick_item_editor(page, page_sizer, item_kind=item_kind)

            page.SetSizer(page_sizer)
            return page

        self.run_items_notebook = wx.Notebook(structured_edit_panel, wx.ID_ANY)
        self.run_items_notebook.SetMinSize(wx.Size(-1, 500))
        self.run_items_notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)
        self.run_items_notebook.AddPage(_build_quick_item_page("卡组", "deck"), "卡组(0)")
        self.run_items_notebook.AddPage(_build_quick_item_page("遗物", "relic"), "遗物(0)")
        self.run_items_notebook.AddPage(_build_quick_item_page("药水", "potion"), "药水(0)")
        quick_items_box.Add(self.run_items_notebook, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        localized_preview_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "中文名总览（仅展示）")
        localized_preview_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "用于快速确认当前卡组、遗物、药水是否正确；不会写回存档。",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM,
            6,
        )

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
        localized_preview_box.Add(preview_filter_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.run_localized_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2 | wx.TE_READONLY,
        )
        self.run_localized_preview_ctrl.SetFont(mono_font)
        self.run_localized_preview_ctrl.SetMinSize(wx.Size(-1, 180))
        localized_preview_box.Add(self.run_localized_preview_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        quick_items_box.Add(localized_preview_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        structured_edit_sizer.Add(quick_items_box, 0, wx.EXPAND | wx.ALL, 10)

        run_basics_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "战局基础字段")
        run_basics_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "这些字段也会参与结构化同步，但一般没有顶部物品区那么高频。",
            ),
            0,
            wx.ALL,
            8,
        )

        self.run_ascension_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=99,
            initial=0,
        )
        self.run_seed_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.run_game_mode_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.run_win_choice = wx.Choice(
            structured_edit_panel,
            wx.ID_ANY,
            choices=["未设置", "是", "否"],
        )
        self.run_win_choice.SetSelection(0)

        run_basics_grid = wx.FlexGridSizer(0, 4, 8, 12)
        run_basics_grid.AddGrowableCol(1, 1)
        run_basics_grid.AddGrowableCol(3, 1)
        run_basics_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "飞升等级："), 0, wx.ALIGN_CENTER_VERTICAL)
        run_basics_grid.Add(self.run_ascension_ctrl, 1, wx.EXPAND)
        run_basics_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "胜利："), 0, wx.ALIGN_CENTER_VERTICAL)
        run_basics_grid.Add(self.run_win_choice, 1, wx.EXPAND)
        run_basics_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "种子："), 0, wx.ALIGN_CENTER_VERTICAL)
        run_basics_grid.Add(self.run_seed_ctrl, 1, wx.EXPAND)
        run_basics_grid.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "游戏模式："), 0, wx.ALIGN_CENTER_VERTICAL)
        run_basics_grid.Add(self.run_game_mode_ctrl, 1, wx.EXPAND)
        run_basics_box.Add(run_basics_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        structured_edit_sizer.Add(run_basics_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        advanced_ids_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "高级：原始 ID 文本投影")
        advanced_ids_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "这里保留给高级用户做批量文本粘贴或精细调整。上面的可视化列表操作会自动同步到这里。",
            ),
            0,
            wx.ALL,
            8,
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
        self.run_deck_ids_ctrl.SetMinSize(wx.Size(-1, 96))
        self.run_relic_ids_ctrl.SetMinSize(wx.Size(-1, 96))
        self.run_potion_ids_ctrl.SetMinSize(wx.Size(-1, 96))
        self.run_deck_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        self.run_relic_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)
        self.run_potion_ids_ctrl.Bind(wx.EVT_TEXT, self.on_run_localized_preview_changed)

        raw_id_columns = wx.BoxSizer(wx.HORIZONTAL)
        for idx, (label_text, ctrl) in enumerate((
            ("卡组 ID（每行一个）", self.run_deck_ids_ctrl),
            ("遗物 ID（每行一个）", self.run_relic_ids_ctrl),
            ("药水 ID（每行一个）", self.run_potion_ids_ctrl),
        )):
            column = wx.BoxSizer(wx.VERTICAL)
            column.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, label_text), 0, wx.BOTTOM, 4)
            column.Add(ctrl, 1, wx.EXPAND)
            flags = wx.EXPAND
            border = 0
            if idx < 2:
                flags |= wx.RIGHT
                border = 8
            raw_id_columns.Add(column, 1, flags, border)
        advanced_ids_box.Add(raw_id_columns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        structured_edit_sizer.Add(advanced_ids_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        progress_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "档案进度编辑")
        progress_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "用于编辑 progress.save；未加载该类型文件时会自动禁用。",
            ),
            0,
            wx.ALL,
            8,
        )

        progress_form_sizer = wx.FlexGridSizer(0, 4, 8, 12)
        progress_form_sizer.AddGrowableCol(1, 1)
        progress_form_sizer.AddGrowableCol(3, 1)

        self.progress_current_score_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0,
        )
        self.progress_floors_climbed_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0,
        )
        self.progress_total_playtime_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999999,
            initial=0,
        )
        self.progress_total_unlocks_ctrl = wx.SpinCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            min=0,
            max=999999,
            initial=0,
        )
        self.progress_pending_character_unlock_ctrl = wx.TextCtrl(structured_edit_panel, wx.ID_ANY, "")
        self.progress_pending_character_unlock_ctrl.Bind(wx.EVT_TEXT, self.on_progress_localized_preview_changed)
        self.progress_pending_character_unlock_preview_ctrl = wx.TextCtrl(
            structured_edit_panel,
            wx.ID_ANY,
            "",
            style=wx.TE_READONLY,
        )

        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "当前分数："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_current_score_ctrl, 1, wx.EXPAND)
        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "总爬塔层数："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_floors_climbed_ctrl, 1, wx.EXPAND)
        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "总游玩时长："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_total_playtime_ctrl, 1, wx.EXPAND)
        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "总解锁数："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_total_unlocks_ctrl, 1, wx.EXPAND)
        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "待解锁角色："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_pending_character_unlock_ctrl, 1, wx.EXPAND)
        progress_form_sizer.Add(wx.StaticText(structured_edit_panel, wx.ID_ANY, "待解锁角色中文名："), 0, wx.ALIGN_CENTER_VERTICAL)
        progress_form_sizer.Add(self.progress_pending_character_unlock_preview_ctrl, 1, wx.EXPAND)
        progress_box.Add(progress_form_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        structured_edit_sizer.Add(progress_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        prefs_box = wx.StaticBoxSizer(wx.VERTICAL, structured_edit_panel, "偏好设置编辑")
        prefs_box.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "用于编辑 prefs.save；未加载该类型文件时会自动禁用。",
            ),
            0,
            wx.ALL,
            8,
        )

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

        prefs_form_sizer = wx.FlexGridSizer(0, 4, 8, 12)
        prefs_form_sizer.AddGrowableCol(1, 1)
        prefs_form_sizer.AddGrowableCol(3, 1)

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
        prefs_box.Add(prefs_form_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        structured_edit_sizer.Add(prefs_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        bottom_actions = wx.BoxSizer(wx.HORIZONTAL)
        bottom_actions.Add(
            wx.StaticText(
                structured_edit_panel,
                wx.ID_ANY,
                "说明：这里的“同步”只是把结构化编辑结果写入右侧 JSON 编辑器，真正落盘仍需点击窗口顶部“保存”。",
            ),
            1,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            12,
        )
        self.apply_structured_button = wx.Button(
            structured_edit_panel,
            wx.ID_ANY,
            "同步到 JSON（未保存）",
        )
        self.apply_structured_button.Bind(wx.EVT_BUTTON, self.on_apply_structured_edits)
        bottom_actions.Add(self.apply_structured_button, 0)
        structured_edit_sizer.Add(bottom_actions, 0, wx.EXPAND | wx.ALL, 10)

        self.run_deck_enchantment_search_ctrl.Bind(wx.EVT_TEXT, self.on_run_deck_enchantment_search_changed)
        self.run_deck_apply_upgrade_button.Bind(wx.EVT_BUTTON, self.on_apply_selected_deck_upgrade)
        self.run_deck_clear_upgrade_button.Bind(wx.EVT_BUTTON, self.on_clear_selected_deck_upgrade)
        self.run_deck_apply_enchantment_button.Bind(wx.EVT_BUTTON, self.on_apply_selected_deck_enchantment)
        self.run_deck_clear_enchantment_button.Bind(wx.EVT_BUTTON, self.on_clear_selected_deck_enchantment)

        structured_edit_panel.SetSizer(structured_edit_sizer)
        structured_edit_panel.FitInside()
        structured_edit_panel.Layout()
        self.notebook.AddPage(structured_edit_panel, "结构化编辑")

        self.structured_view = wx.TextCtrl(
            self.notebook,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2 | wx.TE_READONLY,
        )
        self.structured_view.SetFont(mono_font)
        self.notebook.AddPage(self.structured_view, "结构化视图")

        self.editor = wx.TextCtrl(
            self.notebook,
            wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.HSCROLL | wx.TE_RICH2,
        )
        self.editor.SetFont(mono_font)
        self.notebook.AddPage(self.editor, "JSON 编辑")
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_notebook_page_changed)

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
        for attr_name in (
            "run_player_choice",
            "run_character_ctrl",
            "run_max_potion_slots_ctrl",
            "run_deck_ids_ctrl",
            "run_relic_ids_ctrl",
            "run_potion_ids_ctrl",
            "run_localized_search_ctrl",
            "run_localized_filter_choice",
            "run_items_notebook",
            "run_deck_editor_notebook",
            "run_deck_upgrade_level_ctrl",
            "run_deck_enchantment_search_ctrl",
            "run_deck_enchantment_choice",
            "run_deck_enchantment_amount_ctrl",
            "run_deck_apply_upgrade_button",
            "run_deck_clear_upgrade_button",
            "run_deck_apply_enchantment_button",
            "run_deck_clear_enchantment_button",
            "run_deck_selected_meta_preview_ctrl",
        ):
            ctrl = getattr(self, attr_name, None)
            if ctrl is not None:
                ctrl.Enable(enabled)

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
                f"run_{item_kind}_clear_all_button",
            ):
                ctrl = getattr(self, attr_name, None)
                if ctrl is not None:
                    ctrl.Enable(enabled)
        
        self._update_selected_deck_meta_controls()


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
        self.run_deck_items = []
        self.run_relic_items = []
        self.run_potion_items = []
        self.run_deck_enchantment_candidate_ids = []

        if hasattr(self, 'run_player_choice'):
            self.run_player_choice.Set([])
        if hasattr(self, 'run_character_ctrl'):
            self.run_character_ctrl.SetValue("")
        if hasattr(self, 'run_max_potion_slots_ctrl'):
            self.run_max_potion_slots_ctrl.SetValue(0)
        if hasattr(self, 'run_deck_ids_ctrl'):
            self.run_deck_ids_ctrl.ChangeValue("")
        if hasattr(self, 'run_relic_ids_ctrl'):
            self.run_relic_ids_ctrl.ChangeValue("")
        if hasattr(self, 'run_potion_ids_ctrl'):
            self.run_potion_ids_ctrl.ChangeValue("")
        if hasattr(self, 'run_character_preview_ctrl'):
            self.run_character_preview_ctrl.SetValue("")
        if hasattr(self, 'run_localized_preview_ctrl'):
            self.run_localized_preview_ctrl.SetValue("")
        if hasattr(self, 'run_localized_search_ctrl'):
            self.run_localized_search_ctrl.SetValue("")
        if hasattr(self, 'run_localized_filter_choice'):
            self.run_localized_filter_choice.SetSelection(0)
        if hasattr(self, 'run_deck_upgrade_level_ctrl'):
            self.run_deck_upgrade_level_ctrl.SetValue(0)
        if hasattr(self, 'run_deck_enchantment_search_ctrl'):
            self.run_deck_enchantment_search_ctrl.ChangeValue("")
        if hasattr(self, 'run_deck_enchantment_choice'):
            self.run_deck_enchantment_choice.Set([])
        if hasattr(self, 'run_deck_enchantment_amount_ctrl'):
            self.run_deck_enchantment_amount_ctrl.SetValue(1)
        if hasattr(self, 'run_deck_selected_meta_preview_ctrl'):
            self.run_deck_selected_meta_preview_ctrl.SetValue("")
        if hasattr(self, 'run_deck_apply_upgrade_button'):
            self.run_deck_apply_upgrade_button.Enable(False)
        if hasattr(self, 'run_deck_clear_upgrade_button'):
            self.run_deck_clear_upgrade_button.Enable(False)
        if hasattr(self, 'run_deck_apply_enchantment_button'):
            self.run_deck_apply_enchantment_button.Enable(False)
        if hasattr(self, 'run_deck_clear_enchantment_button'):
            self.run_deck_clear_enchantment_button.Enable(False)

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

    @staticmethod
    def _normalize_run_item_kind(item_kind: str) -> str:
        mapping = {
            "deck": "deck",
            "relic": "relic",
            "relics": "relic",
            "potion": "potion",
            "potions": "potion",
        }
        return mapping.get(item_kind, item_kind)

    @staticmethod
    def _read_spin_ctrl_int(ctrl: Any, default: int = 0) -> int:
        """Read the current integer value from a SpinCtrl, including uncommitted text."""
        if ctrl is None:
            return default

        get_text_value = getattr(ctrl, "GetTextValue", None)
        if callable(get_text_value):
            try:
                text_value = str(get_text_value()).strip()
            except Exception:
                text_value = ""
            if text_value:
                try:
                    return int(text_value)
                except ValueError:
                    pass

        get_value = getattr(ctrl, "GetValue", None)
        if callable(get_value):
            try:
                value = get_value()
            except Exception:
                value = default
            if isinstance(value, int):
                return value
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                pass

        return default

    @staticmethod
    def _structured_item_kind(item_kind: str) -> str:
        mapping = {
            "deck": "deck",
            "relic": "relics",
            "potion": "potions",
        }
        normalized_kind = StS2MainFrame._normalize_run_item_kind(item_kind)
        return mapping.get(normalized_kind, normalized_kind)

    def _get_run_items_attr_name(self, item_kind: str) -> str | None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        mapping = {
            "deck": "run_deck_items",
            "relic": "run_relic_items",
            "potion": "run_potion_items",
        }
        return mapping.get(normalized_kind)

    def _get_run_items(self, item_kind: str) -> list[dict[str, Any]]:
        attr_name = self._get_run_items_attr_name(item_kind)
        if not attr_name:
            return []
        value = getattr(self, attr_name, [])
        return value if isinstance(value, list) else []

    def _set_run_items(self, item_kind: str, items: list[Any]) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        structured_kind = self._structured_item_kind(normalized_kind)
        attr_name = self._get_run_items_attr_name(normalized_kind)
        if not attr_name:
            return
        normalized_items = normalize_run_item_list(list(items), item_kind=structured_kind)
        setattr(self, attr_name, normalized_items)
        self._sync_run_item_text_ctrl_from_items(normalized_kind)

    def _sync_run_item_text_ctrl_from_items(self, item_kind: str) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return
        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if target_ctrl is None:
            return
        item_lines = build_run_item_id_lines(self._get_run_items(normalized_kind))
        self._suppress_run_item_text_sync = True
        try:
            target_ctrl.ChangeValue("\n".join(item_lines))
        finally:
            self._suppress_run_item_text_sync = False

    def _sync_run_items_from_editor_text(self, item_kind: str) -> None:
        if self._suppress_run_item_text_sync:
            return

        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return
        target_ctrl = getattr(self, config["target_ctrl_attr"], None)
        if target_ctrl is None:
            return

        new_ids = [line.strip() for line in target_ctrl.GetValue().splitlines() if line.strip()]
        current_items = self._get_run_items(normalized_kind)
        structured_kind = self._structured_item_kind(normalized_kind)
        normalized_items = normalize_run_item_list(list(current_items), item_kind=structured_kind)

        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in normalized_items:
            item_id = str(item.get("id", ""))
            buckets.setdefault(item_id, []).append(item)

        rebuilt: list[Any] = []
        for item_id in new_ids:
            candidates = buckets.get(item_id, [])
            if candidates:
                rebuilt.append(candidates.pop(0))
            else:
                rebuilt.append({"id": item_id})

        setattr(self, self._get_run_items_attr_name(normalized_kind), normalize_run_item_list(rebuilt, item_kind=structured_kind))

    def _sync_all_run_items_from_editor_text(self) -> None:
        for item_kind in ("deck", "relic", "potion"):
            self._sync_run_items_from_editor_text(item_kind)

    def _update_run_deck_enchantment_choice(self) -> None:
        if not hasattr(self, "run_deck_enchantment_choice"):
            return
        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            self.run_deck_enchantment_choice.Set([])
            self.run_deck_enchantment_candidate_ids = []
            return

        query = self.run_deck_enchantment_search_ctrl.GetValue().strip() if hasattr(self, "run_deck_enchantment_search_ctrl") else ""
        candidate_ids = search_localized_ids(category="enchantments", query=query, limit=200)
        self.run_deck_enchantment_candidate_ids = candidate_ids
        labels = [format_localized_id_text(item_id, category="enchantments") for item_id in candidate_ids]
        self.run_deck_enchantment_choice.Set(labels)
        if candidate_ids:
            self.run_deck_enchantment_choice.SetSelection(0)


    def _get_selected_run_deck_enchantment_id(self) -> str | None:
        choice_ctrl = getattr(self, "run_deck_enchantment_choice", None)
        candidate_ids = getattr(self, "run_deck_enchantment_candidate_ids", [])
        if choice_ctrl is None or not candidate_ids:
            return None
        selected_index = choice_ctrl.GetSelection()
        if selected_index == wx.NOT_FOUND or selected_index >= len(candidate_ids):
            return None
        return candidate_ids[selected_index]


    def _update_selected_deck_meta_controls(self) -> None:
        if not hasattr(self, "run_deck_selected_meta_preview_ctrl"):
            return

        selected_index = self._get_selected_run_item_index("deck")
        items = self._get_run_items("deck")
        if selected_index is None or selected_index < 0 or selected_index >= len(items):
            if hasattr(self, "run_deck_upgrade_level_ctrl"):
                self.run_deck_upgrade_level_ctrl.SetValue(0)
            if hasattr(self, "run_deck_enchantment_amount_ctrl"):
                self.run_deck_enchantment_amount_ctrl.SetValue(1)
            if hasattr(self, "run_deck_selected_meta_preview_ctrl"):
                self.run_deck_selected_meta_preview_ctrl.SetValue("")
            if hasattr(self, "run_deck_upgrade_level_ctrl"):
                self.run_deck_upgrade_level_ctrl.Enable(False)
            if hasattr(self, "run_deck_enchantment_search_ctrl"):
                self.run_deck_enchantment_search_ctrl.Enable(False)
            if hasattr(self, "run_deck_enchantment_choice"):
                self.run_deck_enchantment_choice.Enable(False)
            if hasattr(self, "run_deck_enchantment_amount_ctrl"):
                self.run_deck_enchantment_amount_ctrl.Enable(False)
            if hasattr(self, "run_deck_apply_upgrade_button"):
                self.run_deck_apply_upgrade_button.Enable(False)
            if hasattr(self, "run_deck_clear_upgrade_button"):
                self.run_deck_clear_upgrade_button.Enable(False)
            if hasattr(self, "run_deck_apply_enchantment_button"):
                self.run_deck_apply_enchantment_button.Enable(False)
            if hasattr(self, "run_deck_clear_enchantment_button"):
                self.run_deck_clear_enchantment_button.Enable(False)
            self._update_run_deck_enchantment_choice()
            return

        item = items[selected_index]
        upgrade_level = item.get("current_upgrade_level") if isinstance(item.get("current_upgrade_level"), int) else 0
        if hasattr(self, "run_deck_upgrade_level_ctrl"):
            self.run_deck_upgrade_level_ctrl.SetValue(max(0, upgrade_level))

        enchantment = item.get("enchantment") if isinstance(item.get("enchantment"), dict) else None
        enchantment_id = str(enchantment.get("id", "")).strip() if enchantment else ""
        enchantment_amount = enchantment.get("amount") if enchantment and isinstance(enchantment.get("amount"), int) else 1
        if hasattr(self, "run_deck_enchantment_amount_ctrl"):
            self.run_deck_enchantment_amount_ctrl.SetValue(max(1, enchantment_amount))

        if hasattr(self, "run_deck_upgrade_level_ctrl"):
            self.run_deck_upgrade_level_ctrl.Enable(True)
        if hasattr(self, "run_deck_enchantment_search_ctrl"):
            self.run_deck_enchantment_search_ctrl.Enable(True)
        if hasattr(self, "run_deck_enchantment_choice"):
            self.run_deck_enchantment_choice.Enable(True)
        if hasattr(self, "run_deck_enchantment_amount_ctrl"):
            self.run_deck_enchantment_amount_ctrl.Enable(True)
        if hasattr(self, "run_deck_apply_upgrade_button"):
            self.run_deck_apply_upgrade_button.Enable(True)
        if hasattr(self, "run_deck_clear_upgrade_button"):
            self.run_deck_clear_upgrade_button.Enable(True)
        if hasattr(self, "run_deck_apply_enchantment_button"):
            self.run_deck_apply_enchantment_button.Enable(True)
        if hasattr(self, "run_deck_clear_enchantment_button"):
            self.run_deck_clear_enchantment_button.Enable(True)

        self._update_run_deck_enchantment_choice()
        if enchantment_id and hasattr(self, "run_deck_enchantment_choice"):
            candidate_ids = getattr(self, "run_deck_enchantment_candidate_ids", [])
            if enchantment_id in candidate_ids:
                self.run_deck_enchantment_choice.SetSelection(candidate_ids.index(enchantment_id))

        lines = [
            f"卡牌：{format_run_item_label(item, item_kind='deck')}",
            f"升级等级：{upgrade_level if upgrade_level > 0 else '无'}",
        ]
        if enchantment_id:
            enchantment_text = format_localized_id_text(enchantment_id, category="enchantments")
            if enchantment_amount > 1:
                enchantment_text += f" ×{enchantment_amount}"
            lines.append(f"附魔：{enchantment_text}")
        else:
            lines.append("附魔：无")
        self.run_deck_selected_meta_preview_ctrl.SetValue("\n".join(lines))


    def on_select_run_item(self, event: wx.CommandEvent, item_kind: str) -> None:
        if self._normalize_run_item_kind(item_kind) == "deck":
            self._update_selected_deck_meta_controls()
        event.Skip()

    def on_run_deck_enchantment_search_changed(self, event: wx.CommandEvent) -> None:
        self._update_run_deck_enchantment_choice()
        event.Skip()

    def _update_run_localized_preview(self) -> None:
        """Update run localized preview controls."""
        if not hasattr(self, 'run_character_preview_ctrl') or not hasattr(self, 'run_localized_preview_ctrl'):
            return

        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            self.run_character_preview_ctrl.SetValue("")
            self.run_localized_preview_ctrl.SetValue("")
            self._update_all_run_item_listboxes()
            self._update_selected_deck_meta_controls()
            return

        self._sync_all_run_items_from_editor_text()

        character = self.run_character_ctrl.GetValue().strip() if hasattr(self, 'run_character_ctrl') else ""
        character_preview = format_localized_id_text(character, category="characters")
        self.run_character_preview_ctrl.SetValue(character_preview)

        deck_items = self._get_run_items("deck")
        relic_items = self._get_run_items("relic")
        potion_items = self._get_run_items("potion")

        search_query = self.run_localized_search_ctrl.GetValue().strip() if hasattr(self, 'run_localized_search_ctrl') else ""
        selected_filter = "全部"
        if hasattr(self, 'run_localized_filter_choice'):
            selected_filter = self.run_localized_filter_choice.GetStringSelection() or "全部"

        empty_text = "无匹配项" if search_query else "无"
        sections: list[str] = []

        if selected_filter in ("全部", "卡组"):
            deck_preview = build_run_items_preview_text(
                deck_items,
                item_kind="deck",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【卡组】\n{deck_preview}")

        if selected_filter in ("全部", "遗物"):
            relic_preview = build_run_items_preview_text(
                relic_items,
                item_kind="relics",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【遗物】\n{relic_preview}")

        if selected_filter in ("全部", "药水"):
            potion_preview = build_run_items_preview_text(
                potion_items,
                item_kind="potions",
                search_query=search_query,
                empty_text=empty_text,
            )
            sections.append(f"【药水】\n{potion_preview}")

        preview_text = "\n\n".join(sections) if sections else empty_text
        self.run_localized_preview_ctrl.SetValue(preview_text)
        self._update_all_run_item_listboxes()
        self._update_selected_deck_meta_controls()

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
        self._sync_all_run_items_from_editor_text()
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
        if not (self.current_info and
                self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN) and
                hasattr(self, 'run_player_choice')):
            self._clear_run_player_editor()
            return

        self._update_all_run_candidate_choices()

        selected_index = self.run_player_choice.GetSelection()
        if selected_index == wx.NOT_FOUND:
            if hasattr(self, 'run_character_ctrl'):
                self.run_character_ctrl.SetValue("")
            if hasattr(self, 'run_max_potion_slots_ctrl'):
                self.run_max_potion_slots_ctrl.SetValue(0)
            self.run_deck_items = []
            self.run_relic_items = []
            self.run_potion_items = []
            if hasattr(self, 'run_deck_ids_ctrl'):
                self.run_deck_ids_ctrl.ChangeValue("")
            if hasattr(self, 'run_relic_ids_ctrl'):
                self.run_relic_ids_ctrl.ChangeValue("")
            if hasattr(self, 'run_potion_ids_ctrl'):
                self.run_potion_ids_ctrl.ChangeValue("")
            self._update_run_localized_preview()
            return

        try:
            fields = extract_run_player_fields(self.current_data, selected_index)

            if hasattr(self, 'run_character_ctrl'):
                self.run_character_ctrl.SetValue(fields.get("character") or "")
            if hasattr(self, 'run_max_potion_slots_ctrl'):
                max_potion_slots = fields.get("max_potion_slot_count", 0)
                if not isinstance(max_potion_slots, int):
                    max_potion_slots = 0
                self.run_max_potion_slots_ctrl.SetValue(max_potion_slots)

            self.run_deck_items = normalize_run_item_list(fields.get("deck_items", []), item_kind="deck")
            self.run_relic_items = normalize_run_item_list(fields.get("relic_items", []), item_kind="relics")
            self.run_potion_items = normalize_run_item_list(fields.get("potion_items", []), item_kind="potions")

            if hasattr(self, 'run_deck_ids_ctrl'):
                self.run_deck_ids_ctrl.ChangeValue("\n".join(build_run_item_id_lines(self.run_deck_items)))
            if hasattr(self, 'run_relic_ids_ctrl'):
                self.run_relic_ids_ctrl.ChangeValue("\n".join(build_run_item_id_lines(self.run_relic_items)))
            if hasattr(self, 'run_potion_ids_ctrl'):
                self.run_potion_ids_ctrl.ChangeValue("\n".join(build_run_item_id_lines(self.run_potion_items)))

            self._update_run_localized_preview()

        except Exception as exc:
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
            self.run_deck_items = []
            self.run_relic_items = []
            self.run_potion_items = []
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
            self._update_all_run_items_notebook_page_labels()
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

    def _current_file_supports_structured_edit(self) -> bool:
        return (
            self.current_info is not None
            and self.current_info.kind in (
                SaveFileKind.RUN_HISTORY,
                SaveFileKind.CURRENT_RUN,
                SaveFileKind.PROGRESS,
                SaveFileKind.PREFS,
            )
        )

    def _build_data_from_structured_editor(self) -> tuple[Any, int]:
        """根据当前结构化编辑区控件生成 JSON 投影，但不直接写回文件。"""
        info = self.current_info
        if info is None or not self._current_file_supports_structured_edit():
            raise SaveValidationError("当前文件不支持结构化编辑")

        if info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN):
            ascension = self._read_spin_ctrl_int(self.run_ascension_ctrl, 0)
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
                self._sync_all_run_items_from_editor_text()
                character = self.run_character_ctrl.GetValue().strip()
                max_potion_slot_count = self._read_spin_ctrl_int(self.run_max_potion_slots_ctrl, 0)

                updated_data = apply_run_player_fields(
                    updated_data,
                    player_index=selected_player,
                    character=character,
                    max_potion_slot_count=max_potion_slot_count,
                    deck_items=self.run_deck_items,
                    relic_items=self.run_relic_items,
                    potion_items=self.run_potion_items,
                )

            return updated_data, selected_player

        if info.kind is SaveFileKind.PROGRESS:
            current_score = self._read_spin_ctrl_int(self.progress_current_score_ctrl, 0)
            floors_climbed = self._read_spin_ctrl_int(self.progress_floors_climbed_ctrl, 0)
            total_playtime = self._read_spin_ctrl_int(self.progress_total_playtime_ctrl, 0)
            total_unlocks = self._read_spin_ctrl_int(self.progress_total_unlocks_ctrl, 0)
            pending_character_unlock = self.progress_pending_character_unlock_ctrl.GetValue().strip()

            updated_data = apply_progress_basic_fields(
                self.current_data,
                current_score=current_score,
                floors_climbed=floors_climbed,
                total_playtime=total_playtime,
                total_unlocks=total_unlocks,
                pending_character_unlock=pending_character_unlock,
            )
            return updated_data, wx.NOT_FOUND

        fast_mode = self.prefs_fast_mode_ctrl.GetValue().strip()
        screenshake = self._read_spin_ctrl_int(self.prefs_screenshake_ctrl, 0)
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
        return updated_data, wx.NOT_FOUND

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
        current_info = self.current_info
        if current_info is None:
            self.SetStatusText("当前没有可保存的文件")
            return

        structured_data: Any | None = None
        structured_data_available = False
        if self._current_file_supports_structured_edit():
            try:
                structured_data, _ = self._build_data_from_structured_editor()
                structured_data_available = True
            except Exception:
                structured_data = None
                structured_data_available = False

        editor_data: Any | None = None
        editor_error: SaveValidationError | None = None
        try:
            editor_data = self.parse_editor_json()
        except SaveValidationError as exc:
            editor_error = exc

        used_structured_sync = False

        if editor_error is not None:
            if not structured_data_available:
                wx.MessageBox(str(editor_error), "保存失败", wx.OK | wx.ICON_ERROR)
                self.SetStatusText(f"保存失败：{editor_error}")
                return

            dialog = wx.MessageDialog(
                self,
                f"{editor_error}\n\n当前“JSON 编辑”页不是合法 JSON，无法按 JSON 内容直接保存。\n\n是否改为按“结构化编辑”页当前内容同步到 JSON 并保存？\n如果你刚刚修改的是结构化编辑区，这通常就是你想要的操作。",
                "保存前确认",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            )
            try:
                result = dialog.ShowModal()
            finally:
                dialog.Destroy()

            if result != wx.ID_YES:
                self.SetStatusText("已取消保存")
                return

            data_to_save = structured_data
            used_structured_sync = True
        else:
            data_to_save = editor_data
            if structured_data_available and structured_data != editor_data:
                dialog = wx.MessageDialog(
                    self,
                    "检测到“结构化编辑”页与“JSON 编辑”页内容不一致。\n\n如果直接保存，写入文件的将是“JSON 编辑”页当前内容，结构化编辑区刚刚改的内容不会自动生效。\n\n选择“是”：先将结构化修改同步到 JSON，再保存。\n选择“否”：仅保存当前 JSON 编辑区内容。\n选择“取消”：放弃本次保存。",
                    "保存前确认",
                    wx.YES_NO | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_QUESTION,
                )
                try:
                    result = dialog.ShowModal()
                finally:
                    dialog.Destroy()

                if result == wx.ID_YES:
                    data_to_save = structured_data
                    used_structured_sync = True
                elif result == wx.ID_NO:
                    data_to_save = editor_data
                else:
                    self.SetStatusText("已取消保存")
                    return

        try:
            backup_path = self.save_io.write_json_file(current_info.path, data_to_save, create_backup=True)
        except SaveIOError as exc:
            wx.MessageBox(str(exc), "保存失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"保存失败：{exc}")
            return

        self._update_current_views(current_info, data_to_save)

        backup_hint = f"，备份：{backup_path.name}" if backup_path else ""
        self.SetStatusText(f"已保存：{current_info.path.name}{backup_hint}；请重启游戏后再读取修改后的存档")
        self._prompt_restart_after_save(
            current_path=current_info.path,
            backup_path=backup_path,
            used_structured_sync=used_structured_sync,
        )

    def on_apply_structured_edits(self, event: wx.CommandEvent | None) -> None:
        """Apply structured edits to current JSON data."""
        current_info = self.current_info
        if current_info is None:
            self.SetStatusText("当前文件不支持结构化编辑")
            return

        if not self._current_file_supports_structured_edit():
            self.SetStatusText("当前文件不支持结构化编辑")
            return

        try:
            updated_data, selected_player = self._build_data_from_structured_editor()
            self._update_current_views(current_info, updated_data)

            if current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN):
                if selected_player != wx.NOT_FOUND and hasattr(self, "run_player_choice"):
                    if selected_player < self.run_player_choice.GetCount():
                        self.run_player_choice.SetSelection(selected_player)
                        self._load_selected_run_player_fields()

            self.notebook.SetSelection(getattr(self, "json_editor_tab_index", 2))
            self.SetStatusText("已将结构化修改同步到当前 JSON（尚未保存到文件）")

        except Exception as exc:
            wx.MessageBox(str(exc), "结构化修改失败", wx.OK | wx.ICON_ERROR)
            self.SetStatusText(f"结构化修改失败：{exc}")
            return

    @staticmethod
    def _build_sts2_steam_uri() -> str:
        return f"steam://rungameid/{STS2_STEAM_APP_ID}"

    def _restart_game_via_steam(self) -> tuple[bool, str]:
        was_running = detect_sts2_process_running()

        if was_running:
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", "SlayTheSpire2.exe"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=15,
                    check=False,
                )
            except Exception as exc:
                return False, f"关闭《杀戮尖塔 2》进程失败：{exc}"

            if result.returncode != 0 and detect_sts2_process_running():
                detail = (result.stdout or result.stderr or "").strip()
                if not detail:
                    detail = f"taskkill 返回码 {result.returncode}"
                return False, f"关闭《杀戮尖塔 2》进程失败：{detail}"

        try:
            os.startfile(self._build_sts2_steam_uri())
        except Exception as exc:
            return False, f"通过 Steam 启动《杀戮尖塔 2》失败：{exc}"

        if was_running:
            return True, "已关闭游戏进程，并已通过 Steam 发起重启请求。"
        return True, "当前未检测到游戏进程，已通过 Steam 发起启动请求。"

    def _perform_restart_game_action(self) -> bool:
        ok, message = self._restart_game_via_steam()
        if ok:
            wx.MessageBox(message, "已发起操作", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(message, "重启失败", wx.OK | wx.ICON_ERROR)
        self.SetStatusText(message)
        return ok

    def _prompt_restart_after_save(
        self,
        *,
        current_path: Path,
        backup_path: Path | None,
        used_structured_sync: bool,
    ) -> None:
        success_text = "保存成功。"
        if used_structured_sync:
            success_text = "已先将结构化修改同步到 JSON，再保存成功。"

        backup_text = str(backup_path) if backup_path else "无"
        game_running = detect_sts2_process_running()
        if game_running:
            restart_text = (
                "注意：修改后的存档通常不会被当前游戏进程热更新读取。\n"
                "请重启游戏后再继续，否则你可能会看到“什么都没变”。\n\n"
                "是否现在一键重启《杀戮尖塔 2》？"
            )
        else:
            restart_text = (
                "注意：修改后的存档需要在重新启动游戏后才会被读取。\n"
                "如果不重新启动游戏，你之后可能会误以为修改没有生效。\n\n"
                "是否现在通过 Steam 启动《杀戮尖塔 2》？"
            )

        dialog = wx.MessageDialog(
            self,
            f"{success_text}\n\n文件：{current_path}\n备份：{backup_text}\n\n{restart_text}",
            "保存成功",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_INFORMATION,
        )
        try:
            result = dialog.ShowModal()
        finally:
            dialog.Destroy()

        if result == wx.ID_YES:
            self._perform_restart_game_action()
        else:
            self.SetStatusText(f"已保存：{current_path.name}；请重启游戏后再读取修改后的存档")

    def on_restart_game(self, event: wx.CommandEvent | None) -> None:
        game_running = detect_sts2_process_running()
        if game_running:
            message = (
                "将强制关闭正在运行的《杀戮尖塔 2》，并通过 Steam 重新启动。\n\n"
                "请确认游戏内需要保留的内容已经正常保存，否则可能丢失当前进程中的未保存状态。\n\n"
                "是否继续？"
            )
            title = "一键重启游戏"
            style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        else:
            message = "当前未检测到《杀戮尖塔 2》进程。\n\n是否现在通过 Steam 启动游戏？"
            title = "启动游戏"
            style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION

        dialog = wx.MessageDialog(self, message, title, style)
        try:
            result = dialog.ShowModal()
        finally:
            dialog.Destroy()

        if result != wx.ID_YES:
            self.SetStatusText("已取消启动/重启游戏")
            return

        self._perform_restart_game_action()

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
        """Append selected candidate item to the structured item state."""
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        selected_id = self._get_selected_run_candidate_id(normalized_kind)
        if not selected_id:
            self.SetStatusText(f"当前没有可添加的{config['display_name']}候选项")
            return

        items = list(self._get_run_items(normalized_kind))
        items.append({"id": selected_id})
        self._set_run_items(normalized_kind, items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index(normalized_kind, len(items) - 1)
        self.SetStatusText(f"已添加{config['display_name']} ID：{selected_id}")

    def _remove_run_candidate_from_editor(self, item_kind: str) -> None:
        """Remove one instance of selected candidate item from the structured item state."""
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        selected_id = self._get_selected_run_candidate_id(normalized_kind)
        if not selected_id:
            self.SetStatusText(f"当前没有可删除的{config['display_name']}候选项")
            return

        items = list(self._get_run_items(normalized_kind))
        if not items:
            self.SetStatusText(f"当前{config['display_name']}列表为空")
            return

        removable_ids = {selected_id}
        if selected_id.startswith(config["prefix"]):
            removable_ids.add(selected_id[len(config["prefix"]):])

        removed_id = None
        removed_index = None
        for i in range(len(items) - 1, -1, -1):
            item = items[i]
            item_id = str(item.get("id", "")) if isinstance(item, dict) else str(item)
            if item_id in removable_ids:
                removed_id = item_id
                removed_index = i
                del items[i]
                break

        if removed_id is None:
            self.SetStatusText(f"当前{config['display_name']}列表中不存在：{selected_id}")
            return

        self._set_run_items(normalized_kind, items)
        self._update_run_localized_preview()
        if items and removed_index is not None:
            self._set_selected_run_item_index(normalized_kind, min(removed_index, len(items) - 1))
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

    def _update_run_items_notebook_page_label(self, item_kind: str) -> None:
        notebook = getattr(self, "run_items_notebook", None)
        if notebook is None:
            return

        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        page_index_map = {
            "deck": 0,
            "relic": 1,
            "potion": 2,
        }
        page_index = page_index_map.get(normalized_kind)
        if page_index is None or page_index >= notebook.GetPageCount():
            return

        count = 0
        if self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN):
            count = len(self._get_run_items(normalized_kind))
        notebook.SetPageText(page_index, f"{config['display_name']}({count})")

    def _update_all_run_items_notebook_page_labels(self) -> None:
        for item_kind in ("deck", "relic", "potion"):
            self._update_run_items_notebook_page_label(item_kind)

    def _read_run_item_ids_from_editor(self, item_kind: str) -> list[str]:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        self._sync_run_items_from_editor_text(normalized_kind)
        return build_run_item_id_lines(self._get_run_items(normalized_kind))


    def _write_run_item_ids_to_editor(self, item_kind: str, item_ids: list[str]) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        structured_kind = self._structured_item_kind(normalized_kind)
        rebuilt_items = _rebuild_run_item_list(
            self._get_run_items(normalized_kind),
            item_ids,
            item_kind=structured_kind,
        )
        self._set_run_items(normalized_kind, rebuilt_items)


    def _update_run_item_listbox(self, item_kind: str) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        listbox = self._get_run_item_listbox(normalized_kind)

        if not (self.current_info and self.current_info.kind in (SaveFileKind.RUN_HISTORY, SaveFileKind.CURRENT_RUN)):
            if listbox is not None:
                listbox.Set([])
            self._update_run_items_notebook_page_label(normalized_kind)
            return

        items = self._get_run_items(normalized_kind)
        labels = [format_run_item_label(item, item_kind=normalized_kind) for item in items]

        if listbox is not None:
            current_selection = listbox.GetSelection()
            listbox.Set(labels)

            if labels and current_selection != wx.NOT_FOUND:
                listbox.SetSelection(min(current_selection, len(labels) - 1))

        self._update_run_items_notebook_page_label(normalized_kind)

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
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(normalized_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        items = list(self._get_run_items(normalized_kind))
        if selected_index < 0 or selected_index >= len(items):
            self.SetStatusText(f"当前{config['display_name']}列表选择无效")
            return

        removed_item = items.pop(selected_index)
        removed_id = str(removed_item.get("id", "")) if isinstance(removed_item, dict) else str(removed_item)
        self._set_run_items(normalized_kind, items)
        self._update_run_localized_preview()
        if items:
            self._set_selected_run_item_index(normalized_kind, min(selected_index, len(items) - 1))
        self.SetStatusText(f"已删除选中的{config['display_name']}：{removed_id}")

    def _move_selected_run_item_in_editor(self, item_kind: str, direction: int) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(normalized_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        items = list(self._get_run_items(normalized_kind))
        new_index = selected_index + direction
        if new_index < 0 or new_index >= len(items):
            self.SetStatusText(f"选中的{config['display_name']}已无法继续移动")
            return

        items[selected_index], items[new_index] = items[new_index], items[selected_index]
        self._set_run_items(normalized_kind, items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index(normalized_kind, new_index)
        move_text = "上移" if direction < 0 else "下移"
        self.SetStatusText(f"已{move_text}选中的{config['display_name']}")

    def _replace_selected_run_item_in_editor(self, item_kind: str) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        selected_index = self._get_selected_run_item_index(normalized_kind)
        if selected_index is None:
            self.SetStatusText(f"请先在{config['display_name']}当前列表中选择一项")
            return

        selected_candidate_id = self._get_selected_run_candidate_id(normalized_kind)
        if not selected_candidate_id:
            self.SetStatusText(f"当前没有可用于替换的{config['display_name']}候选项")
            return

        items = list(self._get_run_items(normalized_kind))
        if selected_index < 0 or selected_index >= len(items):
            self.SetStatusText(f"当前{config['display_name']}列表选择无效")
            return

        original_item = items[selected_index]
        if isinstance(original_item, dict):
            updated_item = dict(original_item)
            old_id = str(updated_item.get("id", ""))
        else:
            updated_item = {"id": str(original_item)}
            old_id = str(original_item)

        updated_item["id"] = selected_candidate_id
        if normalized_kind == "deck" and old_id != selected_candidate_id:
            updated_item.pop("current_upgrade_level", None)
            updated_item.pop("enchantment", None)
            updated_item.pop("props", None)

        items[selected_index] = updated_item
        self._set_run_items(normalized_kind, items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index(normalized_kind, selected_index)
        self.SetStatusText(f"已将选中的{config['display_name']}从 {old_id} 替换为 {selected_candidate_id}")

    def on_remove_selected_run_item(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._remove_selected_run_item_from_editor(item_kind)

    def on_move_run_item_up(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._move_selected_run_item_in_editor(item_kind, -1)

    def on_move_run_item_down(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._move_selected_run_item_in_editor(item_kind, 1)

    def on_replace_selected_run_item(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._replace_selected_run_item_in_editor(item_kind)

    def _clear_all_run_items_in_editor(self, item_kind: str) -> None:
        normalized_kind = self._normalize_run_item_kind(item_kind)
        config = self._get_run_candidate_config(normalized_kind)
        if not config:
            return

        items = list(self._get_run_items(normalized_kind))
        if not items:
            self.SetStatusText(f"当前{config['display_name']}列表已为空")
            return

        dialog = wx.MessageDialog(
            self,
            f"确定要清空当前玩家的全部{config['display_name']}吗？\n\n此操作只会修改当前结构化编辑区，仍需你后续同步并保存。",
            f"清空{config['display_name']}列表",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        try:
            result = dialog.ShowModal()
        finally:
            dialog.Destroy()

        if result != wx.ID_YES:
            self.SetStatusText(f"已取消清空{config['display_name']}列表")
            return

        self._set_run_items(normalized_kind, [])
        self._update_run_localized_preview()
        self.SetStatusText(f"已清空当前玩家的全部{config['display_name']}")

    def on_clear_all_run_items(self, event: wx.CommandEvent, item_kind: str) -> None:
        self._clear_all_run_items_in_editor(item_kind)

    def on_apply_selected_deck_upgrade(self, event: wx.CommandEvent | None) -> None:
        selected_index = self._get_selected_run_item_index("deck")
        if selected_index is None:
            self.SetStatusText("请先在卡组当前列表中选择一张卡")
            return

        items = list(self._get_run_items("deck"))
        if selected_index < 0 or selected_index >= len(items):
            self.SetStatusText("当前卡组选择无效")
            return

        item = dict(items[selected_index]) if isinstance(items[selected_index], dict) else {"id": str(items[selected_index])}
        upgrade_level = self.run_deck_upgrade_level_ctrl.GetValue() if hasattr(self, "run_deck_upgrade_level_ctrl") else 0
        if isinstance(upgrade_level, int) and upgrade_level > 0:
            item["current_upgrade_level"] = upgrade_level
        else:
            item.pop("current_upgrade_level", None)

        items[selected_index] = item
        self._set_run_items("deck", items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index("deck", selected_index)
        self._update_selected_deck_meta_controls()
        if isinstance(upgrade_level, int) and upgrade_level > 0:
            self.SetStatusText(f"已将选中卡牌升级等级设置为 +{upgrade_level}")
        else:
            self.SetStatusText("已清除选中卡牌的升级等级")

    def on_clear_selected_deck_upgrade(self, event: wx.CommandEvent | None) -> None:
        if hasattr(self, "run_deck_upgrade_level_ctrl"):
            self.run_deck_upgrade_level_ctrl.SetValue(0)
        self.on_apply_selected_deck_upgrade(event)

    def on_apply_selected_deck_enchantment(self, event: wx.CommandEvent | None) -> None:
        selected_index = self._get_selected_run_item_index("deck")
        if selected_index is None:
            self.SetStatusText("请先在卡组当前列表中选择一张卡")
            return

        selected_enchantment_id = self._get_selected_run_deck_enchantment_id()
        if not selected_enchantment_id:
            self.SetStatusText("当前没有可应用的附魔候选项")
            return

        items = list(self._get_run_items("deck"))
        if selected_index < 0 or selected_index >= len(items):
            self.SetStatusText("当前卡组选择无效")
            return

        item = dict(items[selected_index]) if isinstance(items[selected_index], dict) else {"id": str(items[selected_index])}
        enchantment_amount = self.run_deck_enchantment_amount_ctrl.GetValue() if hasattr(self, "run_deck_enchantment_amount_ctrl") else 1
        if not isinstance(enchantment_amount, int) or enchantment_amount <= 0:
            enchantment_amount = 1
        item["enchantment"] = {"id": selected_enchantment_id, "amount": enchantment_amount}

        items[selected_index] = item
        self._set_run_items("deck", items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index("deck", selected_index)
        self._update_selected_deck_meta_controls()
        self.SetStatusText(f"已为选中卡牌应用附魔：{selected_enchantment_id}")

    def on_clear_selected_deck_enchantment(self, event: wx.CommandEvent | None) -> None:
        selected_index = self._get_selected_run_item_index("deck")
        if selected_index is None:
            self.SetStatusText("请先在卡组当前列表中选择一张卡")
            return

        items = list(self._get_run_items("deck"))
        if selected_index < 0 or selected_index >= len(items):
            self.SetStatusText("当前卡组选择无效")
            return

        item = dict(items[selected_index]) if isinstance(items[selected_index], dict) else {"id": str(items[selected_index])}
        item.pop("enchantment", None)
        items[selected_index] = item
        self._set_run_items("deck", items)
        self._update_run_localized_preview()
        self._set_selected_run_item_index("deck", selected_index)
        self._update_selected_deck_meta_controls()
        self.SetStatusText("已清除选中卡牌的附魔")


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

