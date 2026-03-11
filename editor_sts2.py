#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from sts2 import StS2SaveIO
from sts2.localization import (
    build_localization_probe_text,
    probe_localization_from_pck,
    build_common_localization_indexes_from_pck,
    build_localization_index_preview_text,
)
from sts2.path_manager import (
    build_external_path_status_text,
    resolve_sts2_pck_path,
)
from sts2.live_verify import (
    cli_current_run_probe,
    cli_current_run_apply,
    cli_current_run_watch,
)


def cli_preview(save_dir: str | Path | None = None) -> int:
    """CLI 预览模式：列出并预览 2 代存档文件"""
    save_io = StS2SaveIO(save_dir=save_dir) if save_dir else StS2SaveIO()
    print(f"使用 2 代存档目录：{save_io.ensure_save_dir()}")

    files = save_io.list_save_files()
    if not files:
        print("未找到已支持的 2 代存档文件。")
        return 1

    print("发现以下 2 代存档文件：")
    for index, info in enumerate(files, start=1):
        print(f"[{index}] {info.display_name} | {info.kind.value} | {info.path}")

    first_file = files[0]
    print(f"\n尝试读取首个文件：{first_file.path}")
    _, data = save_io.load_save_file(first_file.path)

    if isinstance(data, dict):
        preview = {
            "top_level_keys": list(data.keys())[:20],
            "key_count": len(data),
        }
    elif isinstance(data, list):
        preview = {
            "item_count": len(data),
            "first_item_type": type(data[0]).__name__ if data else None,
        }
    else:
        preview = {
            "python_type": type(data).__name__,
        }

    print("读取预览：")
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    return 0


def cli_localization_preview(pck_path: str | Path | None = None) -> int:
    """CLI PCK 本地化预览模式：探测并显示本地化路径"""
    try:
        # 解析 PCK 路径（支持自动探测与配置回退）
        resolved = resolve_sts2_pck_path(pck_path)
        print(build_external_path_status_text(label="PCK 文件", resolved=resolved, optional=False))
        
        # 调用探测函数（使用原始 pck_path，让底层自行处理）
        probe_result = probe_localization_from_pck(pck_path)
        
        # 构建并打印结果文本
        result_text = build_localization_probe_text(probe_result)
        print(result_text)
        
        # 构建并打印 zhs 本地化索引样本（使用原始 pck_path）
        indexes = build_common_localization_indexes_from_pck(pck_path, locale="zhs")
        if indexes:
            index_preview_text = build_localization_index_preview_text(indexes)
            print(index_preview_text)
        else:
            print("未生成任何 zhs 本地化索引样本。")
        
        return 0
    except Exception as e:
        print(f"本地化预览失败：{e}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="Slay the Spire 2 编辑器 - 支持 GUI 启动、存档 CLI 预览与 PCK 本地化预览"
    )
    parser.add_argument(
        "--cli-preview",
        action="store_true",
        help="仅执行 CLI 预览，不启动 GUI",
    )
    parser.add_argument(
        "--cli-localization-preview",
        action="store_true",
        help="执行 PCK 本地化路径探测预览，不启动 GUI",
    )
    parser.add_argument(
        "--cli-current-run-probe",
        action="store_true",
        help="执行当前战局文件探测预览，不启动 GUI",
    )
    parser.add_argument(
        "--cli-current-run-apply",
        action="store_true",
        help="对当前战局文件应用验证补丁，不启动 GUI",
    )
    parser.add_argument(
        "--cli-current-run-watch",
        action="store_true",
        help="监视当前战局 live/backup 文件变化，不启动 GUI",
    )
    parser.add_argument(
        "--pck-path",
        type=str,
        default=None,
        help="指定 Slay the Spire 2 的 PCK 文件路径（可选）",
    )
    parser.add_argument(
        "--save-dir",
        type=str,
        default=None,
        help="指定 2 代存档目录（可选）",
    )
    parser.add_argument(
        "--target-file",
        type=str,
        default=None,
        help="显式指定 current_run.save 或 current_run.save.backup 文件路径",
    )
    parser.add_argument(
        "--player-index",
        type=int,
        default=0,
        help="玩家索引",
    )
    parser.add_argument(
        "--ascension",
        type=int,
        default=None,
        help="心跳等级",
    )
    parser.add_argument(
        "--character-id",
        type=str,
        default=None,
        help="角色 ID",
    )
    parser.add_argument(
        "--gold",
        type=int,
        default=None,
        help="金币数量",
    )
    parser.add_argument(
        "--current-hp",
        type=int,
        default=None,
        help="当前生命值",
    )
    parser.add_argument(
        "--max-hp",
        type=int,
        default=None,
        help="最大生命值",
    )
    parser.add_argument(
        "--max-potion-slot-count",
        type=int,
        default=None,
        help="最大药水槽位数",
    )
    parser.add_argument(
        "--append-deck-id",
        action="append",
        default=None,
        help="追加卡牌 ID（可重复传入）",
    )
    parser.add_argument(
        "--append-relic-id",
        action="append",
        default=None,
        help="追加遗物 ID（可重复传入）",
    )
    parser.add_argument(
        "--append-potion-id",
        action="append",
        default=None,
        help="追加药水 ID（可重复传入）",
    )
    parser.add_argument(
        "--replace-potion-id",
        action="append",
        default=None,
        help="替换药水 ID（可重复传入）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览修改，不实际写回文件",
    )
    parser.add_argument(
        "--watch-seconds",
        type=float,
        default=60.0,
        help="监视持续秒数",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=1.0,
        help="轮询间隔秒数",
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="要求目标必须是运行期 current_run.save，禁止自动 fallback 到 backup",
    )
    parser.add_argument(
        "--require-running-game",
        action="store_true",
        help="要求 SlayTheSpire2 进程正在运行，防止把退出后残留的 live 文件误判为运行期目标",
    )
    return parser


def main() -> int:
    """主入口：根据参数决定启动 GUI 还是 CLI 预览"""
    parser = build_parser()
    args = parser.parse_args()

    if args.cli_localization_preview:
        # CLI PCK 本地化预览模式
        return cli_localization_preview(pck_path=args.pck_path)
    elif args.cli_current_run_probe:
        # CLI current_run 探测模式
        return cli_current_run_probe(
            save_dir=args.save_dir,
            target_file=args.target_file,
            require_live=args.require_live,
            require_running_game=args.require_running_game,
        )
    elif args.cli_current_run_apply:
        # CLI current_run 应用模式
        return cli_current_run_apply(
            save_dir=args.save_dir,
            target_file=args.target_file,
            player_index=args.player_index,
            ascension=args.ascension,
            character_id=args.character_id,
            gold=args.gold,
            current_hp=args.current_hp,
            max_hp=args.max_hp,
            max_potion_slot_count=args.max_potion_slot_count,
            append_deck_ids=args.append_deck_id,
            append_relic_ids=args.append_relic_id,
            append_potion_ids=args.append_potion_id,
            replace_potion_ids=args.replace_potion_id,
            dry_run=args.dry_run,
            require_live=args.require_live,
            require_running_game=args.require_running_game,
        )
    elif args.cli_current_run_watch:
        # CLI current_run 监视模式
        return cli_current_run_watch(
            save_dir=args.save_dir,
            watch_seconds=args.watch_seconds,
            interval_seconds=args.interval_seconds,
        )
    elif args.cli_preview:
        # CLI 预览模式
        return cli_preview(save_dir=args.save_dir)
    else:
        # 默认启动 GUI
        from sts2.app import run_sts2_app
        return run_sts2_app(save_dir=args.save_dir, pck_path=args.pck_path)


if __name__ == "__main__":
    raise SystemExit(main())

