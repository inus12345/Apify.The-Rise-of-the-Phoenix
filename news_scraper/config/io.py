"""Helpers for loading and saving JSON-backed scraper configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_json_model(path: str | Path, model_type: type[T]) -> T:
    """Load a JSON file into a pydantic model."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return model_type.model_validate(data)


def save_json_model(path: str | Path, model: BaseModel) -> None:
    """Persist a pydantic model as nicely formatted JSON."""

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def save_json_data(path: str | Path, data: object) -> None:
    """Persist raw JSON-serializable data."""

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
