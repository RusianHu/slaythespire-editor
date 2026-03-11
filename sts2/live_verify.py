from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import SaveFileInfo, SaveFileKind
from .save_io import SaveValidationError, StS2SaveIO
from .structured import _rebuild_run_item_list


CURRENT_RUN_LIVE_FILENAME = "current_run.save"
CURRENT_RUN_BACKUP_FILENAME = "current_run.save.backup"


def _format_timestamp(ts: float | int | None) -> str:
    """格式化时间戳为可读字符串。"""
    if ts is None:
        return "无"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _extract_player_list(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SaveValidationError("当前战局数据必须是 JSON 对象")

    players = data.get("players")
    if not isinstance(players, list):
        raise SaveValidationError("当前战局数据缺少 players 列表")

    normalized_players: list[dict[str, Any]] = []
    for index, player in enumerate(players):
        if not isinstance(player, dict):
            raise SaveValidationError(f"players[{index}] 不是 JSON 对象")
        normalized_players.append(player)
    return normalized_players


def _extract_item_ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []

    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item_id = item.get("id")
            result.append(str(item_id) if item_id is not None else "")
        else:
            result.append(str(item))
    return result


def _preview_ids(items: Any, limit: int = 6) -> str:
    ids = [item_id for item_id in _extract_item_ids(items) if item_id]
    if not ids:
        return "无"
    preview = ", ".join(ids[:limit])
    if len(ids) > limit:
        preview += " ..."
    return preview


def _source_label(source: str) -> str:
    mapping = {
        "explicit": "显式指定文件",
        "live": "运行期 current_run.save",
        "backup": "本地 current_run.save.backup",
    }
    return mapping.get(source, source)


def detect_sts2_process_running() -> bool:
    """保守检测 SlayTheSpire2 进程是否正在运行，仅用于 CLI 提示与安全保护。"""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SlayTheSpire2.exe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            check=False,
        )
        return "SlayTheSpire2.exe" in result.stdout
    except Exception:
        return False


def _snapshot_process_state() -> dict[str, Any]:
    """获取游戏进程状态快照。"""
    return {"running": detect_sts2_process_running()}


def _build_process_state_text(state: dict[str, Any]) -> str:
    """构建游戏进程状态文本。"""
    return f"[process] SlayTheSpire2.exe - {'运行中' if state.get('running') else '未运行'}"


def _describe_process_change(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """描述游戏进程状态变化。"""
    prev_running = bool(previous.get('running'))
    curr_running = bool(current.get('running'))
    if prev_running == curr_running:
        return '无变化'
    return '启动' if curr_running else '退出'


def resolve_current_run_target(
    save_io: StS2SaveIO,
    target_path: str | Path | None = None,
    *,
    require_live: bool = False,
) -> tuple[SaveFileInfo, Any, str]:
    """解析当前战局目标文件，优先 live，其次 backup，也支持显式路径。"""
    if target_path:
        info, data = save_io.load_save_file(target_path)
        if info.kind is not SaveFileKind.CURRENT_RUN:
            raise SaveValidationError(f"目标文件不是 current_run.save/current_run.save.backup：{info.path}")
        return info, data, "explicit"

    files = save_io.list_save_files()

    live_info = next(
        (
            info
            for info in files
            if info.kind is SaveFileKind.CURRENT_RUN and info.path.name.lower() == CURRENT_RUN_LIVE_FILENAME
        ),
        None,
    )
    if live_info is not None:
        _, data = save_io.load_save_file(live_info.path)
        return live_info, data, "live"

    # 若未找到 live 且 require_live=True，直接抛出异常
    if require_live:
        raise SaveValidationError("未找到运行期 current_run.save，已阻止 fallback 到 backup")

    backup_info = next(
        (
            info
            for info in files
            if info.kind is SaveFileKind.CURRENT_RUN and info.path.name.lower() == CURRENT_RUN_BACKUP_FILENAME
        ),
        None,
    )
    if backup_info is not None:
        _, data = save_io.load_save_file(backup_info.path)
        return backup_info, data, "backup"

    raise SaveValidationError("未找到 current_run.save 或 current_run.save.backup")


def build_current_run_probe_text(
    info: SaveFileInfo,
    data: Any,
    *,
    source: str,
    game_running: bool | None = None,
) -> str:
    """构建当前战局验证摘要文本。"""
    lines: list[str] = []
    lines.append("【当前战局验证摘要】")
    lines.append(f"来源：{_source_label(source)}")
    lines.append(f"文件：{info.display_name}")
    lines.append(f"路径：{info.path}")
    
    # Add game process status
    if game_running is True:
        lines.append("游戏进程：运行中")
    elif game_running is False:
        lines.append("游戏进程：未运行")
    else:
        lines.append("游戏进程：未知")

    if info.path.exists():
        stat = info.path.stat()
        lines.append(f"文件大小：{stat.st_size} 字节")
        lines.append(f"最后写入时间：{_format_timestamp(stat.st_mtime)}")
        
        # Add warning for live file when game is not running
        if source == "live" and game_running is False:
            lines.append("提示：检测到 live current_run.save 仍然存在，但游戏进程未运行；这可能是退出游戏后残留的 live 文件。")

    if not isinstance(data, dict):
        lines.append(f"数据类型异常：{type(data).__name__}")
        return "\n".join(lines)

    top_keys = list(data.keys())
    lines.append(f"顶层键数量：{len(top_keys)}")
    lines.append(f"顶层键预览：{', '.join(top_keys[:20]) if top_keys else '无'}")
    lines.append(f"schema_version：{data.get('schema_version')}")
    lines.append(f"ascension：{data.get('ascension')}")
    lines.append(f"current_act_index：{data.get('current_act_index')}")
    lines.append(f"run_time：{data.get('run_time')}")
    lines.append(f"save_time：{data.get('save_time')}")
    lines.append(f"win_time：{data.get('win_time')}")

    players = _extract_player_list(data)
    lines.append(f"玩家数量：{len(players)}")
    lines.append("")

    for index, player in enumerate(players, start=1):
        deck = player.get("deck", [])
        relics = player.get("relics", [])
        potions = player.get("potions", [])
        character = player.get("character") or player.get("character_id")
        player_id = player.get("id") or player.get("net_id")

        lines.append(f"【玩家 {index}】")
        lines.append(f"角色：{character}")
        lines.append(f"玩家 ID：{player_id}")
        lines.append(f"金币：{player.get('gold')}")
        lines.append(f"生命：{player.get('current_hp')} / {player.get('max_hp')}")
        lines.append(f"最大能量：{player.get('max_energy')}")
        lines.append(
            f"药水槽：{len(potions) if isinstance(potions, list) else '?'} / {player.get('max_potion_slot_count')}"
        )
        lines.append(f"卡组数量：{len(deck) if isinstance(deck, list) else '?'}")
        lines.append(f"遗物数量：{len(relics) if isinstance(relics, list) else '?'}")
        lines.append(f"药水数量：{len(potions) if isinstance(potions, list) else '?'}")
        lines.append(f"卡组预览：{_preview_ids(deck)}")
        lines.append(f"遗物预览：{_preview_ids(relics)}")
        lines.append(f"药水预览：{_preview_ids(potions)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def apply_current_run_patch(
    data: Any,
    *,
    player_index: int = 0,
    ascension: int | None = None,
    character_id: str | None = None,
    gold: int | None = None,
    current_hp: int | None = None,
    max_hp: int | None = None,
    max_potion_slot_count: int | None = None,
    append_deck_ids: list[str] | None = None,
    append_relic_ids: list[str] | None = None,
    append_potion_ids: list[str] | None = None,
    replace_potion_ids: list[str] | None = None,
) -> dict[str, Any]:
    """对当前战局应用一组最小验证性修改。"""
    players = _extract_player_list(data)

    if player_index < 0 or player_index >= len(players):
        raise SaveValidationError(f"玩家索引超出范围：{player_index}")

    updated = dict(data)
    updated_players = list(players)
    original_player = players[player_index]
    updated_player = dict(original_player)

    if ascension is not None:
        updated["ascension"] = ascension

    if character_id is not None:
        has_character = "character" in original_player
        has_character_id = "character_id" in original_player
        if has_character:
            updated_player["character"] = character_id
        if has_character_id:
            updated_player["character_id"] = character_id
        if not has_character and not has_character_id:
            updated_player["character"] = character_id

    if gold is not None:
        updated_player["gold"] = gold
    if current_hp is not None:
        updated_player["current_hp"] = current_hp
    if max_hp is not None:
        updated_player["max_hp"] = max_hp
    if max_potion_slot_count is not None:
        updated_player["max_potion_slot_count"] = max_potion_slot_count

    existing_deck = original_player.get("deck", []) if isinstance(original_player.get("deck", []), list) else []
    existing_relics = original_player.get("relics", []) if isinstance(original_player.get("relics", []), list) else []
    existing_potions = original_player.get("potions", []) if isinstance(original_player.get("potions", []), list) else []

    append_deck_ids = [item for item in (append_deck_ids or []) if item]
    append_relic_ids = [item for item in (append_relic_ids or []) if item]
    append_potion_ids = [item for item in (append_potion_ids or []) if item]
    replace_potion_ids = [item for item in (replace_potion_ids or []) if item]

    if append_deck_ids:
        new_deck_ids = _extract_item_ids(existing_deck) + append_deck_ids
        updated_player["deck"] = _rebuild_run_item_list(existing_deck, new_deck_ids, item_kind="deck")

    if append_relic_ids:
        new_relic_ids = _extract_item_ids(existing_relics) + append_relic_ids
        updated_player["relics"] = _rebuild_run_item_list(existing_relics, new_relic_ids, item_kind="relics")

    if replace_potion_ids:
        updated_player["potions"] = _rebuild_run_item_list(existing_potions, replace_potion_ids, item_kind="potions")
    elif append_potion_ids:
        new_potion_ids = _extract_item_ids(existing_potions) + append_potion_ids
        updated_player["potions"] = _rebuild_run_item_list(existing_potions, new_potion_ids, item_kind="potions")

    updated_players[player_index] = updated_player
    updated["players"] = updated_players
    return updated


def build_current_run_patch_summary(
    before_data: Any,
    after_data: Any,
    *,
    player_index: int,
) -> str:
    """输出验证补丁前后摘要，便于人工观察改动。"""
    before_players = _extract_player_list(before_data)
    after_players = _extract_player_list(after_data)

    before_player = before_players[player_index]
    after_player = after_players[player_index]

    before_deck = before_player.get("deck", []) if isinstance(before_player.get("deck", []), list) else []
    after_deck = after_player.get("deck", []) if isinstance(after_player.get("deck", []), list) else []
    before_relics = before_player.get("relics", []) if isinstance(before_player.get("relics", []), list) else []
    after_relics = after_player.get("relics", []) if isinstance(after_player.get("relics", []), list) else []
    before_potions = before_player.get("potions", []) if isinstance(before_player.get("potions", []), list) else []
    after_potions = after_player.get("potions", []) if isinstance(after_player.get("potions", []), list) else []

    lines: list[str] = []
    lines.append("【验证补丁前后对比】")
    lines.append(f"玩家索引：{player_index}")
    lines.append(f"ascension：{before_data.get('ascension')} -> {after_data.get('ascension')}")
    lines.append(
        f"角色：{before_player.get('character') or before_player.get('character_id')} -> {after_player.get('character') or after_player.get('character_id')}"
    )
    lines.append(f"金币：{before_player.get('gold')} -> {after_player.get('gold')}")
    lines.append(f"current_hp：{before_player.get('current_hp')} -> {after_player.get('current_hp')}")
    lines.append(f"max_hp：{before_player.get('max_hp')} -> {after_player.get('max_hp')}")
    lines.append(
        f"max_potion_slot_count：{before_player.get('max_potion_slot_count')} -> {after_player.get('max_potion_slot_count')}"
    )
    lines.append(f"卡组数量：{len(before_deck)} -> {len(after_deck)}")
    lines.append(f"遗物数量：{len(before_relics)} -> {len(after_relics)}")
    lines.append(f"药水数量：{len(before_potions)} -> {len(after_potions)}")
    lines.append(f"修改后卡组尾部预览：{_preview_ids(after_deck[-6:])}")
    lines.append(f"修改后遗物尾部预览：{_preview_ids(after_relics[-6:])}")
    lines.append(f"修改后药水预览：{_preview_ids(after_potions)}")
    return "\n".join(lines)


def _snapshot_file_state(path: Path) -> dict[str, Any]:
    """获取文件状态快照。"""
    if not path.exists():
        return {"exists": False, "size": None, "mtime": None}
    stat = path.stat()
    return {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime}


def _collect_current_run_watch_targets(save_io: StS2SaveIO) -> list[tuple[str, Path]]:
    """收集需要监视的 current_run 文件目标。"""
    targets: list[tuple[str, Path]] = []
    
    # 添加 live 路径
    live_path = save_io.ensure_save_dir() / CURRENT_RUN_LIVE_FILENAME
    targets.append(("live", live_path))
    
    # 尝试查找 backup
    files = save_io.list_save_files()
    backup_info = next(
        (
            info
            for info in files
            if info.kind is SaveFileKind.CURRENT_RUN and info.path.name.lower() == CURRENT_RUN_BACKUP_FILENAME
        ),
        None,
    )
    if backup_info is not None:
        targets.append(("backup", backup_info.path))
    else:
        # 即使不存在也添加，以便监视创建
        backup_path = save_io.ensure_save_dir() / CURRENT_RUN_BACKUP_FILENAME
        targets.append(("backup", backup_path))
    
    return targets


def _build_watch_state_text(label: str, path: Path, state: dict[str, Any]) -> str:
    """构建监视状态文本。"""
    if not state["exists"]:
        return f"[{label}] {path} - 不存在"
    return f"[{label}] {path} - 大小: {state['size']} 字节, 修改时间: {_format_timestamp(state['mtime'])}"


def _describe_watch_change(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """描述文件状态变化。"""
    prev_exists = previous["exists"]
    curr_exists = current["exists"]
    
    if not prev_exists and curr_exists:
        return "创建"
    elif prev_exists and not curr_exists:
        return "删除"
    elif not prev_exists and not curr_exists:
        return "无变化"
    else:
        # 都存在，检查是否修改
        if previous["mtime"] != current["mtime"] or previous["size"] != current["size"]:
            return "修改"
        return "无变化"


def cli_current_run_watch(
    save_dir: str | Path | None = None,
    *,
    watch_seconds: float = 60.0,
    interval_seconds: float = 1.0,
) -> int:
    """监视当前战局文件的生命周期变化。"""
    try:
        save_io = StS2SaveIO(save_dir=save_dir) if save_dir else StS2SaveIO()
        targets = _collect_current_run_watch_targets(save_io)
        
        print("【当前战局文件监视已启动】")
        print(f"监视时长：{watch_seconds} 秒")
        print(f"检查间隔：{interval_seconds} 秒")
        print(f"监视目标数量：{len(targets)}")
        print("进程监视：启用")
        for label, path in targets:
            print(f"  - [{label}] {path}")
        print("")
        
        # 初始化状态
        previous_states: dict[str, dict[str, Any]] = {}
        print("【初始状态】")
        previous_process_state = _snapshot_process_state()
        print(_build_process_state_text(previous_process_state))
        for label, path in targets:
            state = _snapshot_file_state(path)
            previous_states[label] = state
            print(_build_watch_state_text(label, path, state))
        print("")
        
        # 开始监视
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed >= watch_seconds:
                break
            
            time.sleep(interval_seconds)
            
            # 检查进程状态变化
            current_process_state = _snapshot_process_state()
            process_change = _describe_process_change(previous_process_state, current_process_state)
            
            if process_change != "无变化":
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{timestamp}] [process] {process_change}")
                print(_build_process_state_text(current_process_state))
                print("")
                previous_process_state = current_process_state
            
            # 检查文件变化
            for label, path in targets:
                current_state = _snapshot_file_state(path)
                change_type = _describe_watch_change(previous_states[label], current_state)
                
                if change_type != "无变化":
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp}] [{label}] {change_type}")
                    print(_build_watch_state_text(label, path, current_state))
                    print("")
                    previous_states[label] = current_state
        
        print("【监视结束】")
        return 0
    
    except Exception as e:
        print(f"监视失败：{e}")
        return 1


def cli_current_run_probe(
    save_dir: str | Path | None = None,
    target_file: str | Path | None = None,
    *,
    require_live: bool = False,
    require_running_game: bool = False,
) -> int:
    """探测当前战局文件。"""
    try:
        save_io = StS2SaveIO(save_dir=save_dir) if save_dir else StS2SaveIO()
        
        game_running = detect_sts2_process_running()
        
        if require_running_game and not game_running:
            print("当前战局探测失败：未检测到 SlayTheSpire2 进程，已阻止把残留 live 文件误判为运行期目标")
            return 1
        
        info, data, source = resolve_current_run_target(save_io, target_path=target_file, require_live=require_live)
        print(build_current_run_probe_text(info, data, source=source, game_running=game_running))
        return 0
    except Exception as e:
        print(f"当前战局探测失败：{e}")
        return 1


def cli_current_run_apply(
    *,
    save_dir: str | Path | None = None,
    target_file: str | Path | None = None,
    player_index: int = 0,
    ascension: int | None = None,
    character_id: str | None = None,
    gold: int | None = None,
    current_hp: int | None = None,
    max_hp: int | None = None,
    max_potion_slot_count: int | None = None,
    append_deck_ids: list[str] | None = None,
    append_relic_ids: list[str] | None = None,
    append_potion_ids: list[str] | None = None,
    replace_potion_ids: list[str] | None = None,
    dry_run: bool = False,
    require_live: bool = False,
    require_running_game: bool = False,
) -> int:
    """应用当前战局补丁。"""
    try:
        save_io = StS2SaveIO(save_dir=save_dir) if save_dir else StS2SaveIO()
        
        game_running = detect_sts2_process_running()
        
        if require_running_game and not game_running:
            print('当前战局补丁应用失败：未检测到 SlayTheSpire2 进程，已阻止对退出后残留的 live 文件执行"运行期写回"操作')
            return 1
        
        info, data, source = resolve_current_run_target(save_io, target_path=target_file, require_live=require_live)

        updated_data = apply_current_run_patch(
            data,
            player_index=player_index,
            ascension=ascension,
            character_id=character_id,
            gold=gold,
            current_hp=current_hp,
            max_hp=max_hp,
            max_potion_slot_count=max_potion_slot_count,
            append_deck_ids=append_deck_ids,
            append_relic_ids=append_relic_ids,
            append_potion_ids=append_potion_ids,
            replace_potion_ids=replace_potion_ids,
        )

        print(build_current_run_patch_summary(data, updated_data, player_index=player_index))
        print("")
        print(build_current_run_probe_text(info, updated_data, source=source, game_running=game_running))

        if dry_run:
            print("")
            print("dry-run 模式：未写回文件。")
            return 0

        if not require_running_game and source == "live" and not game_running:
            print("警告：当前检测到游戏进程未运行，但 live current_run.save 仍然存在；本次写回将作用于退出后残留的 live 文件。")
            print("")

        backup_path = save_io.write_json_file(info.path, updated_data, create_backup=True)
        print("")
        print(f"已写回文件：{info.path}")
        print(f"自动备份：{backup_path}")
        print('提示：根据当前实机验证，修改后的 current_run.save 会在"继续游戏"重新载入当前战局时生效；当前局内不会热更新读取。')
        return 0
    
    except Exception as e:
        print(f"当前战局补丁应用失败：{e}")
        return 1

