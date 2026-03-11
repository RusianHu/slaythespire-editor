from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SaveFileKind(str, Enum):
    PREFS = "prefs"
    PROGRESS = "progress"
    RUN_HISTORY = "run_history"
    CURRENT_RUN = "current_run"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SaveFileInfo:
    path: Path
    kind: SaveFileKind
    profile_dir: Path
    display_name: str

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(slots=True)
class RunCard:
    id: str
    floor_added_to_deck: int | None = None
    current_upgrade_level: int | None = None
    enchantment: dict[str, Any] | None = None
    props: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class RunRelic:
    id: str
    floor_added_to_deck: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class RunPotion:
    id: str
    slot_index: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class RunPlayer:
    id: str | None = None
    character: str | None = None
    deck: list[RunCard] = field(default_factory=list)
    relics: list[RunRelic] = field(default_factory=list)
    potions: list[RunPotion] = field(default_factory=list)
    max_potion_slot_count: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class RunHistorySummary:
    ascension: int | None = None
    seed: str | None = None
    win: bool | None = None
    game_mode: str | None = None
    players: list[RunPlayer] = field(default_factory=list)
    acts_count: int = 0
    map_acts_count: int = 0
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class ProgressSummary:
    schema_version: int | None = None
    unique_id: str | None = None
    current_score: int | None = None
    floors_climbed: int | None = None
    total_playtime: int | None = None
    total_unlocks: int | None = None
    discovered_cards_count: int = 0
    discovered_relics_count: int = 0
    discovered_potions_count: int = 0
    character_stats_count: int = 0
    unlocked_achievements_count: int = 0
    pending_character_unlock: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class PrefsSummary:
    schema_version: int | None = None
    setting_count: int = 0
    keys: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None

