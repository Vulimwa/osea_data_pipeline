"""Canonical public dataset registry loaded from config/data_catalog.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DatasetSpec(dict):
    def __getattr__(self, name: str) -> Any:
        if name == "status":
            return self.get("retrieval_status")
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def as_dict(self) -> dict[str, Any]:
        return dict(self)


_CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "data_catalog.json"
with _CATALOG_PATH.open("r", encoding="utf-8") as _catalog_file:
    DATASETS = tuple(DatasetSpec(item) for item in json.load(_catalog_file))

BY_KEY = {item.key: item for item in DATASETS}


def catalog_document() -> list[dict[str, Any]]:
    return [item.as_dict() for item in DATASETS]
