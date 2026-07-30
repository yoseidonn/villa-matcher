"""Caretaker loader — ported from utils/caretakers.py."""

import json


def get_caretakers(file_path: str) -> list[dict]:
    with open(file_path, "r", encoding="UTF-8") as f:
        return json.loads(f.read())
