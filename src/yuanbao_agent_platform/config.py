from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"


def load_config(name: str) -> Dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def scheduler_policy() -> Dict[str, Any]:
    return load_config("scheduler_policy.json")


def integration_config() -> Dict[str, Any]:
    return load_config("integration.json")


def metrics_config() -> Dict[str, Any]:
    return load_config("metrics.json")
