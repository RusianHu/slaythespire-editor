from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from .models import (
    PrefsSummary,
    ProgressSummary,
    RunCard,
    RunHistorySummary,
    RunPlayer,
    RunPotion,
    RunRelic,
    SaveFileInfo,
    SaveFileKind,
)
from .localization import build_common_localization_indexes_from_pck, get_effective_pck_cache_key


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


@lru_cache(maxsize=4)
def _get_common_localization_indexes_cached(locale: str, pck_cache_key: str) -> dict[str, dict[str, str]]:
    """
    真正被 lru_cache 修饰的本地化索引获取函数。
    
    Args:
        locale: 语言代码
        pck_cache_key: PCK 缓存键（用于区分不同 PCK 路径）
    
    Returns:
        本地化索引字典
    """
    try:
        return build_common_localization_indexes_from_pck(locale=locale)
    except Exception:
        return {}


def _get_common_localization_indexes(locale: str = "zhs") -> dict[str, dict[str, str]]:
    """
    获取本地化索引的包装函数，自动读取当前有效 PCK 缓存键。
    
    Args:
        locale: 语言代码，默认 "zhs"
    
    Returns:
        本地化索引字典
    """
    pck_cache_key = get_effective_pck_cache_key()
    return _get_common_localization_indexes_cached(locale, pck_cache_key)


def clear_localization_runtime_cache() -> None:
    """
    清除本地化运行时缓存。
    
    供 GUI 在切换 PCK 后调用，确保本地化索引重新加载。
    """
    _get_common_localization_indexes_cached.cache_clear()


def _lookup_localized_name(item_id: str | None, *, category: str, locale: str = "zhs") -> str | None:
    if not isinstance(item_id, str) or not item_id:
        return None
    indexes = _get_common_localization_indexes(locale)
    return indexes.get(category, {}).get(item_id)


def _format_id_with_name(item_id: str | None, *, category: str, locale: str = "zhs") -> str:
    if not isinstance(item_id, str) or not item_id:
        return "<未知ID>"
    localized_name = _lookup_localized_name(item_id, category=category, locale=locale)
    if localized_name:
        return f"{item_id}（{localized_name}）"
    return item_id


def _build_lookup_candidates(item_id: str, *, category: str) -> list[str]:
    """构建本地化查找候选 ID（含前缀容错）。"""
    if not item_id:
        return []
    
    # 定义前缀映射
    prefix_map = {
        "characters": "CHARACTER.",
        "cards": "CARD.",
        "relics": "RELIC.",
        "potions": "POTION.",
        "enchantments": "ENCHANTMENT.",
    }
    
    # 默认候选先放原始 ID
    candidates = [item_id]
    
    # 根据 category 做前缀容错
    prefix = prefix_map.get(category, "")
    if prefix and not item_id.startswith(prefix):
        prefixed_id = f"{prefix}{item_id}"
        # 避免重复添加
        if prefixed_id != item_id:
            candidates.append(prefixed_id)
    
    return candidates


def localized_id_matches_query(
    item_id: str | None,
    *,
    category: str,
    query: str | None,
) -> bool:
    """判断某个 ID 是否匹配搜索词（内部ID/中文名/英文名）。"""
    # item_id 非法或空：返回 False
    if not isinstance(item_id, str) or not item_id:
        return False
    
    # query 为空或仅空白：返回 True
    if not query or not query.strip():
        return True
    
    # 将 query 做 strip().casefold()
    normalized_query = query.strip().casefold()
    
    # 候选 ID 取 _build_lookup_candidates(...)
    candidates = _build_lookup_candidates(item_id, category=category)
    
    # 若 query 命中任一候选 ID（casefold 包含），返回 True
    for candidate in candidates:
        if normalized_query in candidate.casefold():
            return True
    
    # 再尝试命中本地化名称
    for candidate in candidates:
        # zhs：中文名
        zhs_name = _lookup_localized_name(candidate, category=category, locale="zhs")
        if zhs_name and normalized_query in zhs_name.casefold():
            return True
        
        # eng：英文名
        eng_name = _lookup_localized_name(candidate, category=category, locale="eng")
        if eng_name and normalized_query in eng_name.casefold():
            return True
    
    # 否则 False
    return False


def format_localized_id_text(item_id: str | None, *, category: str, locale: str = "zhs") -> str:
    """
    格式化 ID 为"原始ID（中文名）"形式，供 GUI 结构化编辑表单使用。
    
    对不同 category 做前缀容错：
    - characters: 尝试补充 CHARACTER. 前缀
    - cards: 尝试补充 CARD. 前缀
    - relics: 尝试补充 RELIC. 前缀
    - potions: 尝试补充 POTION. 前缀
    
    Args:
        item_id: 物品 ID
        category: 类别（characters / cards / relics / potions）
        locale: 语言代码，默认 "zhs"
    
    Returns:
        格式化后的文本，若 item_id 为空则返回 "无"
    """
    if not isinstance(item_id, str) or not item_id:
        return "无"
    
    # 复用 _build_lookup_candidates 获取候选 ID
    candidates = _build_lookup_candidates(item_id, category=category)
    
    # 遍历候选 ID，优先取第一个可命中的中文名（locale="zhs"）
    for candidate in candidates:
        localized_name = _lookup_localized_name(candidate, category=category, locale=locale)
        if localized_name:
            return f"{item_id}（{localized_name}）"
    
    # 没命中就返回原始 item_id
    return item_id


def build_localized_preview_text(
    ids: list[str],
    *,
    category: str,
    locale: str = "zhs",
    empty_text: str = "无",
    search_query: str | None = None,
) -> str:
    """
    构建本地化预览文本，供 GUI 结构化编辑表单使用。
    
    将 ID 列表格式化为多行文本，每行一个"ID（中文名）"。

    Args:
        ids: ID 列表
        category: 类别（characters / cards / relics / potions）
        locale: 语言代码，默认 "zhs"
        empty_text: 列表为空时返回的文本，默认 "无"
        search_query: 搜索查询词，若提供则过滤匹配项

    Returns:
        多行文本，每行一个格式化后的 ID
    """
    if not ids:
        return empty_text
    
    # 若传入 search_query，则对每个 ID 先用 localized_id_matches_query 过滤
    filtered_ids = ids
    if search_query is not None:
        filtered_ids = [
            item_id for item_id in ids
            if localized_id_matches_query(item_id, category=category, query=search_query)
        ]
    
    # 若过滤后为空，返回 empty_text
    if not filtered_ids:
        return empty_text
    
    lines = []
    for item_id in filtered_ids:
        if isinstance(item_id, str) and item_id:
            formatted = format_localized_id_text(item_id, category=category, locale=locale)
            lines.append(formatted)
    
    if not lines:
        return empty_text
    
    return "\n".join(lines)


def search_localized_ids(
    *,
    category: str,
    query: str | None = None,
    limit: int = 200,
) -> list[str]:
    """
    在已加载的本地化索引中搜索候选内部 ID，供 GUI 下拉菜单使用。

    支持按内部 ID、中文名、英文名匹配。
    """
    zhs_index = _get_common_localization_indexes("zhs").get(category, {})
    eng_index = _get_common_localization_indexes("eng").get(category, {})
    all_ids = sorted(set(zhs_index.keys()) | set(eng_index.keys()))
    if not all_ids:
        return []

    if limit <= 0:
        limit = len(all_ids)

    if not query or not query.strip():
        return all_ids[:limit]

    normalized_query = query.strip().casefold()

    def _match_rank(item_id: str) -> tuple[int, int, str]:
        candidates = _build_lookup_candidates(item_id, category=category)
        id_texts = [candidate.casefold() for candidate in candidates]

        zhs_names: list[str] = []
        eng_names: list[str] = []
        for candidate in candidates:
            zhs_name = _lookup_localized_name(candidate, category=category, locale="zhs")
            if zhs_name:
                zhs_names.append(zhs_name.casefold())

            eng_name = _lookup_localized_name(candidate, category=category, locale="eng")
            if eng_name:
                eng_names.append(eng_name.casefold())

        if any(text == normalized_query for text in id_texts):
            primary = 0
        elif any(text.startswith(normalized_query) for text in id_texts):
            primary = 1
        elif any(normalized_query in text for text in id_texts):
            primary = 2
        elif any(text == normalized_query for text in zhs_names):
            primary = 3
        elif any(text.startswith(normalized_query) for text in zhs_names):
            primary = 4
        elif any(normalized_query in text for text in zhs_names):
            primary = 5
        elif any(text == normalized_query for text in eng_names):
            primary = 6
        elif any(text.startswith(normalized_query) for text in eng_names):
            primary = 7
        elif any(normalized_query in text for text in eng_names):
            primary = 8
        else:
            primary = 9

        return (primary, len(item_id), item_id)

    matched_ids = [
        item_id
        for item_id in all_ids
        if localized_id_matches_query(item_id, category=category, query=query)
    ]
    matched_ids.sort(key=_match_rank)
    return matched_ids[:limit]


def _clone_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clone_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json_value(item) for item in value]
    return deepcopy(value)


def _extract_item_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id", ""))
    item_id = getattr(item, "id", None)
    if item_id is not None:
        return str(item_id)
    return str(item)


def _normalize_enchantment_dict(enchantment: Any) -> dict[str, Any] | None:
    if not isinstance(enchantment, dict):
        return None

    enchantment_id = str(enchantment.get("id", "")).strip()
    if not enchantment_id:
        return None

    normalized: dict[str, Any] = {"id": enchantment_id}
    amount = enchantment.get("amount")
    if isinstance(amount, int):
        normalized["amount"] = amount

    for key, value in enchantment.items():
        if key in {"id", "amount"}:
            continue
        normalized[key] = _clone_json_value(value)

    return normalized


def _normalize_run_item_dict(item: Any, *, item_kind: str, index: int | None = None) -> dict[str, Any]:
    if item_kind not in ("deck", "relics", "potions"):
        raise ValueError(f"item_kind 必须是 'deck', 'relics' 或 'potions'，当前值：{item_kind}")

    if isinstance(item, dict):
        normalized = _clone_json_value(item)
    else:
        normalized = {"id": str(item)}

    normalized["id"] = str(normalized.get("id", ""))

    if item_kind in ("deck", "relics"):
        if not isinstance(normalized.get("floor_added_to_deck"), int):
            normalized["floor_added_to_deck"] = 1

    if item_kind == "potions" and index is not None:
        normalized["slot_index"] = index

    if item_kind == "deck":
        upgrade_level = normalized.get("current_upgrade_level")
        if isinstance(upgrade_level, int) and upgrade_level > 0:
            normalized["current_upgrade_level"] = upgrade_level
        else:
            normalized.pop("current_upgrade_level", None)

        enchantment = _normalize_enchantment_dict(normalized.get("enchantment"))
        if enchantment is not None:
            normalized["enchantment"] = enchantment
        else:
            normalized.pop("enchantment", None)

        props = normalized.get("props")
        if isinstance(props, dict):
            normalized["props"] = _clone_json_value(props)
        else:
            normalized.pop("props", None)

    return normalized


def normalize_run_item_list(items: list[Any], *, item_kind: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        normalized_index = index if item_kind == "potions" else None
        result.append(_normalize_run_item_dict(item, item_kind=item_kind, index=normalized_index))
    return result


def format_run_card_text(item: RunCard | dict[str, Any] | str, *, locale: str = "zhs") -> str:
    if isinstance(item, RunCard):
        card_id = item.id
        current_upgrade_level = item.current_upgrade_level
        enchantment = item.enchantment
    elif isinstance(item, dict):
        normalized = _normalize_run_item_dict(item, item_kind="deck")
        card_id = str(normalized.get("id", ""))
        current_upgrade_level = normalized.get("current_upgrade_level")
        enchantment = normalized.get("enchantment")
    else:
        card_id = str(item)
        current_upgrade_level = None
        enchantment = None

    parts = [format_localized_id_text(card_id, category="cards", locale=locale)]

    if isinstance(current_upgrade_level, int) and current_upgrade_level > 0:
        parts.append(f"[+{current_upgrade_level}]")

    if isinstance(enchantment, dict):
        enchantment_id = str(enchantment.get("id", "")).strip()
        enchantment_text = format_localized_id_text(enchantment_id, category="enchantments", locale=locale) if enchantment_id else "<未知附魔>"
        amount = enchantment.get("amount")
        if isinstance(amount, int) and amount > 1:
            enchantment_text += f" ×{amount}"
        parts.append(f"[附魔: {enchantment_text}]")

    return " ".join(part for part in parts if part)


def _run_card_matches_query(item: RunCard | dict[str, Any] | str, query: str | None) -> bool:
    if not query or not query.strip():
        return True

    normalized_query = query.strip().casefold()

    if isinstance(item, RunCard):
        card_id = item.id
        current_upgrade_level = item.current_upgrade_level
        enchantment = item.enchantment
    elif isinstance(item, dict):
        normalized = _normalize_run_item_dict(item, item_kind="deck")
        card_id = str(normalized.get("id", ""))
        current_upgrade_level = normalized.get("current_upgrade_level")
        enchantment = normalized.get("enchantment")
    else:
        card_id = str(item)
        current_upgrade_level = None
        enchantment = None

    texts: list[str] = []
    for candidate in _build_lookup_candidates(card_id, category="cards"):
        texts.append(candidate)
        zhs_name = _lookup_localized_name(candidate, category="cards", locale="zhs")
        if zhs_name:
            texts.append(zhs_name)
        eng_name = _lookup_localized_name(candidate, category="cards", locale="eng")
        if eng_name:
            texts.append(eng_name)

    if isinstance(current_upgrade_level, int) and current_upgrade_level > 0:
        texts.extend([
            f"+{current_upgrade_level}",
            f"升级{current_upgrade_level}",
            f"升级+{current_upgrade_level}",
        ])

    if isinstance(enchantment, dict):
        enchantment_id = str(enchantment.get("id", "")).strip()
        for candidate in _build_lookup_candidates(enchantment_id, category="enchantments"):
            texts.append(candidate)
            zhs_name = _lookup_localized_name(candidate, category="enchantments", locale="zhs")
            if zhs_name:
                texts.append(zhs_name)
            eng_name = _lookup_localized_name(candidate, category="enchantments", locale="eng")
            if eng_name:
                texts.append(eng_name)
        amount = enchantment.get("amount")
        if isinstance(amount, int):
            texts.append(str(amount))
            texts.append(f"x{amount}")
            texts.append(f"×{amount}")

    return any(normalized_query in text.casefold() for text in texts if isinstance(text, str) and text)


def build_run_cards_preview_text(
    items: list[Any],
    *,
    locale: str = "zhs",
    empty_text: str = "无",
    search_query: str | None = None,
) -> str:
    if not items:
        return empty_text

    filtered_items = items
    if search_query is not None:
        filtered_items = [item for item in items if _run_card_matches_query(item, search_query)]

    if not filtered_items:
        return empty_text

    lines = [format_run_card_text(item, locale=locale) for item in filtered_items]
    lines = [line for line in lines if line]
    if not lines:
        return empty_text
    return "\n".join(lines)


def format_run_item_label(item: Any, *, item_kind: str, locale: str = "zhs") -> str:
    normalized_kind = {
        "deck": "deck",
        "relic": "relics",
        "relics": "relics",
        "potion": "potions",
        "potions": "potions",
    }.get(item_kind, item_kind)

    if normalized_kind == "deck":
        return format_run_card_text(item, locale=locale)

    category_map = {
        "relics": "relics",
        "potions": "potions",
    }
    category = category_map.get(normalized_kind)
    if not category:
        return _extract_item_id(item)
    return format_localized_id_text(_extract_item_id(item), category=category, locale=locale)


def build_run_item_id_lines(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        item_id = _extract_item_id(item).strip()
        if item_id:
            result.append(item_id)
    return result


def build_run_items_preview_text(
    items: list[Any],
    *,
    item_kind: str,
    locale: str = "zhs",
    empty_text: str = "无",
    search_query: str | None = None,
) -> str:
    normalized_kind = {
        "deck": "deck",
        "relic": "relics",
        "relics": "relics",
        "potion": "potions",
        "potions": "potions",
    }.get(item_kind, item_kind)

    if normalized_kind == "deck":
        return build_run_cards_preview_text(items, locale=locale, empty_text=empty_text, search_query=search_query)

    category_map = {
        "relics": "relics",
        "potions": "potions",
    }
    category = category_map.get(normalized_kind)
    if not category:
        return empty_text

    return build_localized_preview_text(
        build_run_item_id_lines(items),
        category=category,
        locale=locale,
        empty_text=empty_text,
        search_query=search_query,
    )


def _preview_ids(items: list[Any], *, category: str | None = None, limit: int = 8) -> str:
    values: list[str] = []
    for item in items[:limit]:
        if category == "cards":
            values.append(format_run_card_text(item))
            continue

        item_id = getattr(item, "id", None)
        if item_id is None:
            item_id = _extract_item_id(item)

        if isinstance(item_id, str) and item_id:
            if category:
                values.append(_format_id_with_name(item_id, category=category))
            else:
                values.append(item_id)
        else:
            values.append("<未知ID>")
    if not values:
        return "无"
    extra = " ..." if len(items) > limit else ""
    return ", ".join(values) + extra


# ============================================================================
# 地图与路线信息辅助函数（仅供结构化视图使用）
# ============================================================================


def _extract_act_id(act: Any) -> str:
    """
    从 act 数据中提取 act ID。
    
    Args:
        act: act 数据，可能是字符串或字典
    
    Returns:
        act ID 字符串
    """
    if isinstance(act, str):
        return act
    if isinstance(act, dict):
        act_id = act.get("id")
        if isinstance(act_id, str):
            return act_id
    return "<未知Act>"


def _count_nested_items(value: Any) -> int:
    """
    递归统计嵌套列表中的标量元素总数。
    
    Args:
        value: 要统计的值
    
    Returns:
        标量元素总数
    """
    if not isinstance(value, list):
        return 0
    
    count = 0
    for item in value:
        if isinstance(item, list):
            count += _count_nested_items(item)
        else:
            count += 1
    return count


def _extract_room_types(points: Any, limit: int = 10) -> list[str]:
    """
    从 map_point_history 中提取房间类型列表。
    
    Args:
        points: 某一幕的 map_point_history 列表
        limit: 最多提取的节点数
    
    Returns:
        房间类型字符串列表
    """
    if not isinstance(points, list):
        return []
    
    room_types = []
    for point in points[:limit]:
        if not isinstance(point, dict):
            room_types.append("<未知节点>")
            continue
        
        # 优先取 map_point_type
        map_point_type = point.get("map_point_type")
        if isinstance(map_point_type, str) and map_point_type:
            room_types.append(map_point_type)
            continue
        
        # 尝试从 rooms[0].room_type 提取
        rooms = point.get("rooms")
        if isinstance(rooms, list) and len(rooms) > 0:
            first_room = rooms[0]
            if isinstance(first_room, dict):
                room_type = first_room.get("room_type")
                if isinstance(room_type, str) and room_type:
                    room_types.append(room_type)
                    continue
        
        room_types.append("<未知节点>")
    
    return room_types


def _format_room_type_preview(points: Any, limit: int = 10) -> str:
    """
    格式化房间类型预览字符串。
    
    Args:
        points: 某一幕的 map_point_history 列表
        limit: 最多显示的节点数
    
    Returns:
        格式化的预览字符串
    """
    room_types = _extract_room_types(points, limit=limit)
    if not room_types:
        return "无"
    
    # 检查实际数量是否超过限制
    actual_count = len(points) if isinstance(points, list) else 0
    extra = " -> ..." if actual_count > limit else ""
    
    return " -> ".join(room_types) + extra


def _format_coord(coord: Any) -> str:
    """
    格式化单个坐标。
    
    Args:
        coord: 坐标数据
    
    Returns:
        格式化的坐标字符串
    """
    if isinstance(coord, dict):
        col = coord.get("col")
        row = coord.get("row")
        if col is not None and row is not None:
            return f"({col},{row})"
    return "<未知坐标>"


def _format_coord_preview(coords: Any, limit: int = 12) -> str:
    """
    格式化坐标预览字符串。
    
    Args:
        coords: visited_map_coords 列表
        limit: 最多显示的坐标数
    
    Returns:
        格式化的预览字符串
    """
    if not isinstance(coords, list):
        return "无"
    
    if not coords:
        return "无"
    
    coord_strs = [_format_coord(coord) for coord in coords[:limit]]
    extra = " -> ..." if len(coords) > limit else ""
    
    return " -> ".join(coord_strs) + extra


def _build_act_preview_lines(data: dict[str, Any]) -> list[str]:
    """
    构建 Act 预览信息行。
    
    Args:
        data: 战局数据
    
    Returns:
        Act 预览信息行列表
    """
    acts = data.get("acts")
    if not isinstance(acts, list) or not acts:
        return []
    
    map_point_history = data.get("map_point_history")
    if not isinstance(map_point_history, list):
        map_point_history = []
    
    lines = ["【Act 预览】"]
    
    # 最多预览前 6 个 act
    preview_limit = 6
    for i, act in enumerate(acts[:preview_limit]):
        act_id = _extract_act_id(act)
        
        # 获取对应的 map_point_history
        points = map_point_history[i] if i < len(map_point_history) else []
        point_count = len(points) if isinstance(points, list) else 0
        
        # 基础行
        line_parts = [f"- 第 {i+1} 幕：{act_id} | 路线节点数：{point_count}"]
        
        # 如果 act 是 dict 且 rooms 是 dict，补充摘要
        if isinstance(act, dict):
            rooms = act.get("rooms")
            if isinstance(rooms, dict):
                # ancient_id
                ancient_id = rooms.get("ancient_id")
                if isinstance(ancient_id, str) and ancient_id:
                    line_parts.append(f" | ancient: {ancient_id}")
                
                # boss_id
                boss_id = rooms.get("boss_id")
                if isinstance(boss_id, str) and boss_id:
                    line_parts.append(f" | boss: {boss_id}")
                
                # elite_encounters_visited
                elite_visited = rooms.get("elite_encounters_visited")
                if isinstance(elite_visited, int):
                    line_parts.append(f" | 已访问精英: {elite_visited}")
                
                # boss_encounters_visited
                boss_visited = rooms.get("boss_encounters_visited")
                if isinstance(boss_visited, int):
                    line_parts.append(f" | 已访问Boss: {boss_visited}")
                
                # event_ids 数量
                event_ids = rooms.get("event_ids")
                if isinstance(event_ids, list):
                    line_parts.append(f" | 事件池: {len(event_ids)}")
                
                # monster_encounter_ids 数量
                monster_ids = rooms.get("monster_encounter_ids")
                if isinstance(monster_ids, list):
                    line_parts.append(f" | 普通战池: {len(monster_ids)}")
                
                # elite_encounter_ids 总数量
                elite_ids = rooms.get("elite_encounter_ids")
                if elite_ids is not None:
                    elite_count = _count_nested_items(elite_ids)
                    if elite_count > 0:
                        line_parts.append(f" | 精英池: {elite_count}")
        
        lines.append("".join(line_parts))
    
    # 如果总数超过 6，补充一行
    if len(acts) > preview_limit:
        lines.append(f"- ... 共 {len(acts)} 幕")
    
    return lines


def _build_map_history_preview_lines(data: dict[str, Any]) -> list[str]:
    """
    构建路线预览信息行。
    
    Args:
        data: 战局数据
    
    Returns:
        路线预览信息行列表
    """
    map_history = data.get("map_point_history")
    if not isinstance(map_history, list) or not map_history:
        return []
    
    lines = ["【路线预览】"]
    
    # 最多预览前 6 幕
    preview_limit = 6
    for i, points in enumerate(map_history[:preview_limit]):
        count = len(points) if isinstance(points, list) else 0
        preview = _format_room_type_preview(points)
        lines.append(f"- 第 {i+1} 幕：{preview} | 节点数：{count}")
    
    # 如果总数超过 6，补充一行
    if len(map_history) > preview_limit:
        lines.append(f"- ... 共 {len(map_history)} 幕路线")
    
    return lines


def _build_visited_coords_lines(data: dict[str, Any]) -> list[str]:
    """
    构建已访问坐标信息行。
    
    Args:
        data: 战局数据
    
    Returns:
        已访问坐标信息行列表
    """
    coords = data.get("visited_map_coords")
    if not isinstance(coords, list) or not coords:
        return []
    
    return [
        "【已访问坐标】",
        f"数量：{len(coords)}",
        f"路径：{_format_coord_preview(coords)}",
    ]


def parse_run_card(item: Any) -> RunCard:
    if isinstance(item, dict):
        props = item.get("props")
        return RunCard(
            id=str(item.get("id", "")),
            floor_added_to_deck=_as_int(item.get("floor_added_to_deck")),
            current_upgrade_level=_as_int(item.get("current_upgrade_level")),
            enchantment=_normalize_enchantment_dict(item.get("enchantment")),
            props=_clone_json_value(props) if isinstance(props, dict) else None,
            raw=item,
        )
    return RunCard(id=str(item), raw={"value": item})


def parse_run_relic(item: Any) -> RunRelic:
    if isinstance(item, dict):
        return RunRelic(
            id=str(item.get("id", "")),
            floor_added_to_deck=_as_int(item.get("floor_added_to_deck")),
            raw=item,
        )
    return RunRelic(id=str(item), raw={"value": item})


def parse_run_potion(item: Any) -> RunPotion:
    if isinstance(item, dict):
        return RunPotion(
            id=str(item.get("id", "")),
            slot_index=_as_int(item.get("slot_index")),
            raw=item,
        )
    return RunPotion(id=str(item), raw={"value": item})


def parse_run_player(item: Any) -> RunPlayer:
    if not isinstance(item, dict):
        return RunPlayer(raw={"value": item})

    deck = [parse_run_card(card) for card in item.get("deck", []) if isinstance(item.get("deck", []), list)]
    relics = [parse_run_relic(relic) for relic in item.get("relics", []) if isinstance(item.get("relics", []), list)]
    potions = [parse_run_potion(potion) for potion in item.get("potions", []) if isinstance(item.get("potions", []), list)]

    # 兼容 character / character_id
    character = _as_str(item.get("character"))
    if not character:
        character = _as_str(item.get("character_id"))
    
    # 兼容 id / net_id
    player_id = _as_str(item.get("id"))
    if not player_id:
        net_id = item.get("net_id")
        if isinstance(net_id, int):
            player_id = str(net_id)
        else:
            player_id = _as_str(net_id)

    return RunPlayer(
        id=player_id,
        character=character,
        deck=deck,
        relics=relics,
        potions=potions,
        max_potion_slot_count=_as_int(item.get("max_potion_slot_count")),
        raw=item,
    )


def parse_run_history_summary(data: Any) -> RunHistorySummary | None:
    if not isinstance(data, dict):
        return None

    players_raw = data.get("players", []) if isinstance(data.get("players", []), list) else []
    players = [parse_run_player(player) for player in players_raw]
    acts = data.get("acts", []) if isinstance(data.get("acts", []), list) else []
    map_history = data.get("map_point_history", []) if isinstance(data.get("map_point_history", []), list) else []

    return RunHistorySummary(
        ascension=_as_int(data.get("ascension")),
        seed=_as_str(data.get("seed")),
        win=data.get("win") if isinstance(data.get("win"), bool) else None,
        game_mode=_as_str(data.get("game_mode")),
        players=players,
        acts_count=len(acts),
        map_acts_count=len(map_history),
        raw=data,
    )


def parse_progress_summary(data: Any) -> ProgressSummary | None:
    if not isinstance(data, dict):
        return None

    discovered_cards = data.get("discovered_cards", []) if isinstance(data.get("discovered_cards", []), list) else []
    discovered_relics = data.get("discovered_relics", []) if isinstance(data.get("discovered_relics", []), list) else []
    discovered_potions = data.get("discovered_potions", []) if isinstance(data.get("discovered_potions", []), list) else []
    character_stats = data.get("character_stats", []) if isinstance(data.get("character_stats", []), list) else []
    unlocked_achievements = data.get("unlocked_achievements", []) if isinstance(data.get("unlocked_achievements", []), list) else []

    return ProgressSummary(
        schema_version=_as_int(data.get("schema_version")),
        unique_id=_as_str(data.get("unique_id")),
        current_score=_as_int(data.get("current_score")),
        floors_climbed=_as_int(data.get("floors_climbed")),
        total_playtime=_as_int(data.get("total_playtime")),
        total_unlocks=_as_int(data.get("total_unlocks")),
        discovered_cards_count=len(discovered_cards),
        discovered_relics_count=len(discovered_relics),
        discovered_potions_count=len(discovered_potions),
        character_stats_count=len(character_stats),
        unlocked_achievements_count=len(unlocked_achievements),
        pending_character_unlock=_as_str(data.get("pending_character_unlock")),
        raw=data,
    )


def parse_prefs_summary(data: Any) -> PrefsSummary | None:
    if not isinstance(data, dict):
        return None
    keys = list(data.keys())
    return PrefsSummary(
        schema_version=_as_int(data.get("schema_version")),
        setting_count=len(keys),
        keys=keys,
        raw=data,
    )


def build_structured_text(info: SaveFileInfo, data: Any) -> str:
    lines: list[str] = []
    lines.append(f"文件：{info.display_name}")
    lines.append(f"路径：{info.path}")
    lines.append(f"类型：{info.kind.value}")
    lines.append("")

    if info.kind is SaveFileKind.PREFS:
        summary = parse_prefs_summary(data)
        if summary is None:
            lines.append("无法解析该偏好设置文件。")
            return "\n".join(lines)

        lines.append("【偏好设置摘要】")
        lines.append(f"Schema 版本：{summary.schema_version}")
        lines.append(f"设置项数量：{summary.setting_count}")
        lines.append(f"键列表：{', '.join(summary.keys) if summary.keys else '无'}")
        return "\n".join(lines)

    if info.kind is SaveFileKind.PROGRESS:
        summary = parse_progress_summary(data)
        if summary is None:
            lines.append("无法解析该档案进度文件。")
            return "\n".join(lines)

        lines.append("【档案进度摘要】")
        lines.append(f"Schema 版本：{summary.schema_version}")
        lines.append(f"唯一 ID：{summary.unique_id}")
        lines.append(f"当前分数：{summary.current_score}")
        lines.append(f"总爬塔层数：{summary.floors_climbed}")
        lines.append(f"总游玩时长：{summary.total_playtime}")
        lines.append(f"总解锁数：{summary.total_unlocks}")
        lines.append(f"待解锁角色：{summary.pending_character_unlock}")
        lines.append(f"已发现卡牌数：{summary.discovered_cards_count}")
        lines.append(f"已发现遗物数：{summary.discovered_relics_count}")
        lines.append(f"已发现药水数：{summary.discovered_potions_count}")
        lines.append(f"角色统计条目数：{summary.character_stats_count}")
        lines.append(f"已解锁成就数：{summary.unlocked_achievements_count}")

        if isinstance(data, dict) and isinstance(data.get("character_stats"), list):
            lines.append("")
            lines.append("【角色统计预览】")
            for item in data.get("character_stats", [])[:8]:
                if not isinstance(item, dict):
                    continue
                # 提取原始角色 ID
                raw_char_id = item.get('id') or item.get('character')
                # 构造显示文本
                if isinstance(raw_char_id, str) and raw_char_id:
                    # 检查是否已经带有 CHARACTER. 前缀
                    if raw_char_id.startswith("CHARACTER."):
                        normalized_char_id = raw_char_id
                    else:
                        normalized_char_id = f"CHARACTER.{raw_char_id}"
                    
                    # 尝试格式化为带中文名的形式
                    display_char = _format_id_with_name(normalized_char_id, category="characters")
                    
                    # 如果没匹配到且前缀是我们补的，退回原始 ID
                    if display_char == normalized_char_id and normalized_char_id != raw_char_id:
                        display_char = raw_char_id
                else:
                    display_char = '<未知角色>'
                lines.append(
                    f"- {display_char} | 最高苦痛: {item.get('max_ascension')} | 偏好苦痛: {item.get('preferred_ascension')}"
                )
        return "\n".join(lines)

    if info.kind is SaveFileKind.RUN_HISTORY or info.kind is SaveFileKind.CURRENT_RUN:
        summary = parse_run_history_summary(data)
        if summary is None:
            if info.kind is SaveFileKind.CURRENT_RUN:
                lines.append("无法解析该当前战局文件。")
            else:
                lines.append("无法解析该历史战局文件。")
            return "\n".join(lines)

        if info.kind is SaveFileKind.CURRENT_RUN:
            lines.append("【当前战局摘要】")
        else:
            lines.append("【历史战局摘要】")
        lines.append(f"Ascension：{summary.ascension}")
        lines.append(f"Seed：{summary.seed}")
        lines.append(f"游戏模式：{summary.game_mode}")
        lines.append(f"是否胜利：{'是' if summary.win else '否' if summary.win is not None else '未知'}")
        lines.append(f"Acts 数量：{summary.acts_count}")
        lines.append(f"地图分段数量：{summary.map_acts_count}")
        lines.append(f"玩家数量：{len(summary.players)}")
        lines.append("")

        for index, player in enumerate(summary.players, start=1):
            lines.append(f"【玩家 {index}】")
            lines.append(f"角色：{_format_id_with_name(player.character, category='characters')}")
            lines.append(f"玩家 ID：{player.id}")
            lines.append(f"卡组数量：{len(player.deck)}")
            lines.append(f"遗物数量：{len(player.relics)}")
            lines.append(
                f"药水数量：{len(player.potions)} / {player.max_potion_slot_count if player.max_potion_slot_count is not None else '?'}"
            )
            lines.append(f"卡组预览：{_preview_ids(player.deck, category='cards')}")
            lines.append(f"遗物预览：{_preview_ids(player.relics, category='relics')}")
            lines.append(f"药水预览：{_preview_ids(player.potions, category='potions')}")
            lines.append("")

        # 添加地图与路线信息展示
        if isinstance(data, dict):
            act_lines = _build_act_preview_lines(data)
            map_history_lines = _build_map_history_preview_lines(data)
            visited_coord_lines = _build_visited_coords_lines(data)
            
            # 如果有任何地图/路线信息，则添加到输出
            if act_lines or map_history_lines or visited_coord_lines:
                # act_lines 已经包含了标题行，直接追加
                if act_lines:
                    lines.extend(act_lines)
                    lines.append("")
                
                # map_history_lines 已经包含了标题行，直接追加
                if map_history_lines:
                    lines.extend(map_history_lines)
                    lines.append("")
                
                # visited_coord_lines 已经包含了标题行，直接追加
                if visited_coord_lines:
                    lines.extend(visited_coord_lines)
                    lines.append("")

        return "\n".join(lines).rstrip()

    lines.append("当前文件类型还没有结构化解析器，已回退到基础文件信息。")
    if isinstance(data, dict):
        lines.append(f"顶层键数量：{len(data)}")
    elif isinstance(data, list):
        lines.append(f"数组长度：{len(data)}")
    else:
        lines.append(f"Python 类型：{type(data).__name__}")
    return "\n".join(lines)


def extract_run_basic_fields(data: Any) -> dict[str, Any]:
    """
    从历史战局数据中提取基础字段，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 历史战局数据（通常是 dict）
    
    Returns:
        包含 ascension, seed, game_mode, win 四个字段的字典
    """
    if not isinstance(data, dict):
        return {
            "ascension": None,
            "seed": None,
            "game_mode": None,
            "win": None,
        }
    
    return {
        "ascension": _as_int(data.get("ascension")),
        "seed": _as_str(data.get("seed")),
        "game_mode": _as_str(data.get("game_mode")),
        "win": data.get("win") if isinstance(data.get("win"), bool) else None,
    }


def apply_run_basic_fields(
    data: Any,
    *,
    ascension: int,
    seed: str,
    game_mode: str,
    win: bool | None,
) -> dict[str, Any]:
    """
    将基础字段应用到历史战局数据，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 原始历史战局数据
        ascension: 苦痛等级
        seed: 种子
        game_mode: 游戏模式
        win: 是否胜利（None 表示删除该字段）
    
    Returns:
        更新后的历史战局数据字典
    
    Raises:
        ValueError: 如果 data 不是 dict
    """
    if not isinstance(data, dict):
        raise ValueError("历史战局数据必须是 JSON 对象")
    
    # 复制一份原 dict，不原地修改
    updated = data.copy()
    
    # 更新基础字段
    # ascension 始终写回
    updated["ascension"] = ascension
    
    # seed 只在原始数据中存在或者值非空时才写回
    if "seed" in data or seed:
        updated["seed"] = seed
    
    # game_mode 只在原始数据中存在或者值非空时才写回
    if "game_mode" in data or game_mode:
        updated["game_mode"] = game_mode
    
    # 处理 win 字段
    if win is True or win is False:
        # 只在原始数据中已有 win 键时才写回（true/false 本身不为 None，所以直接写）
        if "win" in data:
            updated["win"] = win
    elif win is None:
        # 只有当原始数据中本来有 win 键时，才删除
        if "win" in data:
            updated.pop("win", None)
    
    return updated


# ============================================================================
# 玩家结构化编辑辅助函数
# ============================================================================


def _normalize_id_lines(text: str) -> list[str]:
    """
    将多行文本拆成 ID 列表。
    
    Args:
        text: 多行文本
    
    Returns:
        ID 列表，去掉首尾空白，丢弃空行，保持顺序
    """
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            result.append(stripped)
    return result


def _extract_existing_player_items(player: dict[str, Any], key: str) -> list[Any]:
    """
    从玩家对象中读取 deck / relics / potions。
    
    Args:
        player: 玩家数据字典
        key: 要提取的键名（deck / relics / potions）
    
    Returns:
        对应的列表，若不是 list 则返回空列表
    """
    value = player.get(key, [])
    if isinstance(value, list):
        return value
    return []


def _rebuild_run_item_list(
    existing_items: list[Any],
    new_ids: list[str],
    *,
    item_kind: str,
) -> list[dict[str, Any]]:
    """
    按 new_ids 生成新的列表，尽量保留旧条目的元数据。
    """
    if item_kind not in ("deck", "relics", "potions"):
        raise ValueError(f"item_kind 必须是 'deck', 'relics' 或 'potions'，当前值：{item_kind}")

    result: list[dict[str, Any]] = []
    for index, new_id in enumerate(new_ids):
        old_item = existing_items[index] if index < len(existing_items) else None
        if isinstance(old_item, dict):
            new_item = _clone_json_value(old_item)
            old_id = str(new_item.get("id", ""))
        else:
            new_item = {"id": new_id}
            old_id = ""

        new_item["id"] = new_id

        if item_kind == "deck" and old_id and old_id != new_id:
            new_item.pop("current_upgrade_level", None)
            new_item.pop("enchantment", None)
            new_item.pop("props", None)

        normalized_index = index if item_kind == "potions" else None
        result.append(_normalize_run_item_dict(new_item, item_kind=item_kind, index=normalized_index))

    return result


def extract_run_player_fields(data: Any, player_index: int) -> dict[str, Any]:
    """
    从历史战局数据中提取指定玩家的字段，供 GUI 结构化编辑表单使用。
    """
    if not isinstance(data, dict):
        raise ValueError("历史战局数据必须是 JSON 对象")

    players = data.get("players")
    if not isinstance(players, list):
        raise ValueError("历史战局缺少 players 列表")

    if player_index < 0 or player_index >= len(players):
        raise IndexError("玩家索引超出范围")

    player = players[player_index]
    if not isinstance(player, dict):
        raise ValueError("玩家数据必须是 JSON 对象")

    character = _as_str(player.get("character"))
    if not character:
        character = _as_str(player.get("character_id"))
    max_potion_slot_count = _as_int(player.get("max_potion_slot_count"))

    deck = player.get("deck", [])
    relics = player.get("relics", [])
    potions = player.get("potions", [])

    deck_items = normalize_run_item_list(deck if isinstance(deck, list) else [], item_kind="deck")
    relic_items = normalize_run_item_list(relics if isinstance(relics, list) else [], item_kind="relics")
    potion_items = normalize_run_item_list(potions if isinstance(potions, list) else [], item_kind="potions")

    return {
        "character": character,
        "max_potion_slot_count": max_potion_slot_count,
        "deck_items": deck_items,
        "relic_items": relic_items,
        "potion_items": potion_items,
        "deck_ids": build_run_item_id_lines(deck_items),
        "relic_ids": build_run_item_id_lines(relic_items),
        "potion_ids": build_run_item_id_lines(potion_items),
    }


def apply_run_player_fields(
    data: Any,
    *,
    player_index: int,
    character: str,
    max_potion_slot_count: int,
    deck_ids: list[str] | None = None,
    relic_ids: list[str] | None = None,
    potion_ids: list[str] | None = None,
    deck_items: list[Any] | None = None,
    relic_items: list[Any] | None = None,
    potion_items: list[Any] | None = None,
) -> dict[str, Any]:
    """
    将玩家字段应用到历史战局数据，供 GUI 结构化编辑表单使用。
    """
    if not isinstance(data, dict):
        raise ValueError("历史战局数据必须是 JSON 对象")

    players = data.get("players")
    if not isinstance(players, list):
        raise ValueError("历史战局缺少 players 列表")

    if player_index < 0 or player_index >= len(players):
        raise IndexError("玩家索引超出范围")

    player = players[player_index]
    if not isinstance(player, dict):
        raise ValueError("玩家数据必须是 JSON 对象")

    updated = data.copy()
    updated_players = list(players)
    updated_player = player.copy()

    existing_deck = _extract_existing_player_items(player, "deck")
    existing_relics = _extract_existing_player_items(player, "relics")
    existing_potions = _extract_existing_player_items(player, "potions")

    has_character = "character" in player
    has_character_id = "character_id" in player

    if has_character and has_character_id:
        updated_player["character"] = character
        updated_player["character_id"] = character
    elif has_character:
        updated_player["character"] = character
    elif has_character_id:
        updated_player["character_id"] = character
    else:
        updated_player["character"] = character

    updated_player["max_potion_slot_count"] = max_potion_slot_count

    normalized_deck_ids = [item for item in (deck_ids or []) if item]
    normalized_relic_ids = [item for item in (relic_ids or []) if item]
    normalized_potion_ids = [item for item in (potion_ids or []) if item]

    if deck_items is not None:
        if isinstance(player.get("deck"), list) or deck_items:
            updated_player["deck"] = normalize_run_item_list(list(deck_items), item_kind="deck")
    elif isinstance(player.get("deck"), list) or normalized_deck_ids:
        updated_player["deck"] = _rebuild_run_item_list(existing_deck, normalized_deck_ids, item_kind="deck")

    if relic_items is not None:
        if isinstance(player.get("relics"), list) or relic_items:
            updated_player["relics"] = normalize_run_item_list(list(relic_items), item_kind="relics")
    elif isinstance(player.get("relics"), list) or normalized_relic_ids:
        updated_player["relics"] = _rebuild_run_item_list(existing_relics, normalized_relic_ids, item_kind="relics")

    if potion_items is not None:
        if isinstance(player.get("potions"), list) or potion_items:
            updated_player["potions"] = normalize_run_item_list(list(potion_items), item_kind="potions")
    elif isinstance(player.get("potions"), list) or normalized_potion_ids:
        updated_player["potions"] = _rebuild_run_item_list(existing_potions, normalized_potion_ids, item_kind="potions")

    updated_players[player_index] = updated_player
    updated["players"] = updated_players
    return updated


# ============================================================================
# 档案进度结构化编辑辅助函数
# ============================================================================


def extract_progress_basic_fields(data: Any) -> dict[str, Any]:
    """
    从档案进度数据中提取基础字段，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 档案进度数据（通常是 dict）
    
    Returns:
        包含 current_score, floors_climbed, total_playtime, total_unlocks, pending_character_unlock 五个字段的字典
    """
    if not isinstance(data, dict):
        return {
            "current_score": None,
            "floors_climbed": None,
            "total_playtime": None,
            "total_unlocks": None,
            "pending_character_unlock": None,
        }
    
    return {
        "current_score": _as_int(data.get("current_score")),
        "floors_climbed": _as_int(data.get("floors_climbed")),
        "total_playtime": _as_int(data.get("total_playtime")),
        "total_unlocks": _as_int(data.get("total_unlocks")),
        "pending_character_unlock": _as_str(data.get("pending_character_unlock")),
    }


def apply_progress_basic_fields(
    data: Any,
    *,
    current_score: int,
    floors_climbed: int,
    total_playtime: int,
    total_unlocks: int,
    pending_character_unlock: str,
) -> dict[str, Any]:
    """
    将基础字段应用到档案进度数据，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 原始档案进度数据
        current_score: 当前分数
        floors_climbed: 总爬塔层数
        total_playtime: 总游玩时长
        total_unlocks: 总解锁数
        pending_character_unlock: 待解锁角色
    
    Returns:
        更新后的档案进度数据字典
    
    Raises:
        ValueError: 如果 data 不是 dict
    """
    if not isinstance(data, dict):
        raise ValueError("档案进度数据必须是 JSON 对象")
    
    # 复制一份原 dict，不原地修改
    updated = data.copy()
    
    # 更新基础字段
    updated["current_score"] = current_score
    updated["floors_climbed"] = floors_climbed
    updated["total_playtime"] = total_playtime
    updated["total_unlocks"] = total_unlocks
    updated["pending_character_unlock"] = pending_character_unlock
    
    return updated


def extract_prefs_basic_fields(data: Any) -> dict[str, Any]:
    """
    从偏好设置数据中提取基础字段，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 偏好设置数据（通常是 dict）
    
    Returns:
        包含 8 个基础字段的字典
    """
    if not isinstance(data, dict):
        return {
            "fast_mode": None,
            "screenshake": None,
            "long_press": None,
            "mute_in_background": None,
            "show_card_indices": None,
            "show_run_timer": None,
            "text_effects_enabled": None,
            "upload_data": None,
        }
    
    return {
        "fast_mode": _as_str(data.get("fast_mode")),
        "screenshake": _as_int(data.get("screenshake")),
        "long_press": data.get("long_press") if isinstance(data.get("long_press"), bool) else None,
        "mute_in_background": data.get("mute_in_background") if isinstance(data.get("mute_in_background"), bool) else None,
        "show_card_indices": data.get("show_card_indices") if isinstance(data.get("show_card_indices"), bool) else None,
        "show_run_timer": data.get("show_run_timer") if isinstance(data.get("show_run_timer"), bool) else None,
        "text_effects_enabled": data.get("text_effects_enabled") if isinstance(data.get("text_effects_enabled"), bool) else None,
        "upload_data": data.get("upload_data") if isinstance(data.get("upload_data"), bool) else None,
    }


def apply_prefs_basic_fields(
    data: Any,
    *,
    fast_mode: str,
    screenshake: int,
    long_press: bool,
    mute_in_background: bool,
    show_card_indices: bool,
    show_run_timer: bool,
    text_effects_enabled: bool,
    upload_data: bool,
) -> dict[str, Any]:
    """
    将基础字段应用到偏好设置数据，供 GUI 结构化编辑表单使用。
    
    Args:
        data: 原始偏好设置数据
        fast_mode: 快速模式
        screenshake: 屏幕震动
        long_press: 长按
        mute_in_background: 后台静音
        show_card_indices: 显示卡牌索引
        show_run_timer: 显示战局计时器
        text_effects_enabled: 文本效果启用
        upload_data: 上传数据
    
    Returns:
        更新后的偏好设置数据字典
    
    Raises:
        ValueError: 如果 data 不是 dict
    """
    if not isinstance(data, dict):
        raise ValueError("偏好设置数据必须是 JSON 对象")
    
    # 复制一份原 dict，不原地修改
    updated = data.copy()
    
    # 更新基础字段
    updated["fast_mode"] = fast_mode
    updated["screenshake"] = screenshake
    updated["long_press"] = long_press
    updated["mute_in_background"] = mute_in_background
    updated["show_card_indices"] = show_card_indices
    updated["show_run_timer"] = show_run_timer
    updated["text_effects_enabled"] = text_effects_enabled
    updated["upload_data"] = upload_data
    
    return updated

