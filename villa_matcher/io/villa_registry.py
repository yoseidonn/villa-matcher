"""Villa registry I/O — load and save data/villas.json."""

import json
import os
from pathlib import Path

from villa_matcher.models.villa import Villa, VillaRegistry


def load_villa_registry(filepath: str) -> VillaRegistry:
    """Load villa metadata from a JSON file.

    Expected format (new):
    {
      "Villa Name": {
        "capacity": 6,
        "locations": ["Kalkan", "Kördere"],
        "area": "Kördere",
        "bedrooms": 3,
        "bathrooms": 3,
        "attributes": ["pool", "sea_view"]
      },
      ...
    }

    Legacy format (single location string) is also supported and automatically
    converted to the new list format.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Villa registry not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    villas = []
    for name, meta in data.items():
        # Handle both legacy "location" (str) and new "locations" (list)
        locations = meta.get("locations")
        if locations is None:
            # Legacy format: single location string
            legacy_loc = meta.get("location", "")
            locations = [legacy_loc] if legacy_loc else []
        else:
            # Ensure it's a list (defensive)
            if isinstance(locations, str):
                locations = [locations] if locations else []

        villas.append(
            Villa(
                name=name,
                capacity=meta.get("capacity", 0),
                locations=locations,
                area=meta.get("area", ""),
                bedrooms=meta.get("bedrooms", 0),
                bathrooms=meta.get("bathrooms", 0),
                attributes=meta.get("attributes", []),
                resital_url=meta.get("resital_url", ""),
                solmar_url=meta.get("solmar_url", ""),
            )
        )

    return VillaRegistry(villas)


def create_template_registry(
    villa_names: list[str], filepath: str, default_capacity: int = 0
) -> None:
    """Create a template villas.json with empty metadata for the user to fill in.

    Only writes the file if it doesn't already exist.
    """
    if os.path.isfile(filepath):
        return  # Don't overwrite existing data

    data = {}
    for name in sorted(villa_names):
        data[name] = {
            "capacity": default_capacity,
            "locations": [],
            "area": "",
            "bedrooms": 0,
            "bathrooms": 0,
            "attributes": [],
        }

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_villa_registry(registry: VillaRegistry, filepath: str) -> None:
    """Save a VillaRegistry back to JSON."""
    data = {}
    for villa in registry.all_villas:
        data[villa.name] = {
            "capacity": villa.capacity,
            "locations": villa.locations,
            "area": villa.area,
            "bedrooms": villa.bedrooms,
            "bathrooms": villa.bathrooms,
            "attributes": villa.attributes,
            "resital_url": villa.resital_url,
            "solmar_url": villa.solmar_url,
        }

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
