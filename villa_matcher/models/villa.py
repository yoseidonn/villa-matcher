"""Villa metadata model and registry."""

from dataclasses import dataclass, field


@dataclass
class Villa:
    """A villa property with capacity and location metadata."""

    name: str
    capacity: int = 0  # max persons
    locations: list[str] = field(default_factory=list)
    # e.g. ["Kalkan", "Kördere", "İslamlar"]
    area: str = ""  # neighbourhood
    bedrooms: int = 0
    bathrooms: int = 0
    attributes: list[str] = field(default_factory=list)
    # e.g. ["pool", "sea_view", "conservative", "honeymoon", "jacuzzi"]
    resital_url: str = ""  # Resital Villa listing URL
    solmar_url: str = ""   # Solmar Villas listing URL

    @property
    def display_name(self) -> str:
        return self.name

    def has_location(self, location: str) -> bool:
        """Check if this villa is in the given location (case-insensitive)."""
        loc_lower = location.lower()
        return any(loc.lower() == loc_lower for loc in self.locations)

    def has_any_location(self, locations: list[str]) -> bool:
        """Check if this villa is in any of the given locations."""
        if not locations:
            return True  # No filter means all locations match
        villa_locs = {loc.lower() for loc in self.locations}
        return any(loc.lower() in villa_locs for loc in locations)


class VillaRegistry:
    """In-memory registry of all villas with metadata lookups."""

    def __init__(self, villas: list[Villa]):
        self._villas: dict[str, Villa] = {}
        for v in villas:
            self._villas[v.name] = v

    def get(self, name: str) -> Villa | None:
        return self._villas.get(name)

    def find_by_capacity(self, min_persons: int) -> list[Villa]:
        """Return all villas with capacity >= min_persons, sorted by name."""
        result = [v for v in self._villas.values() if v.capacity >= min_persons]
        result.sort(key=lambda v: v.name.lower())
        return result

    def find_by_location(self, location: str) -> list[Villa]:
        """Return all villas in a given location."""
        result = [v for v in self._villas.values() if v.has_location(location)]
        result.sort(key=lambda v: v.name.lower())
        return result

    def find_by_any_location(self, locations: list[str]) -> list[Villa]:
        """Return all villas in any of the given locations."""
        if not locations:
            return self.all_villas
        result = [v for v in self._villas.values() if v.has_any_location(locations)]
        result.sort(key=lambda v: v.name.lower())
        return result

    @property
    def all_villas(self) -> list[Villa]:
        return sorted(self._villas.values(), key=lambda v: v.name.lower())

    @property
    def names(self) -> list[str]:
        return sorted(self._villas.keys(), key=str.lower)

    @property
    def locations(self) -> list[str]:
        locs: set[str] = set()
        for v in self._villas.values():
            for loc in v.locations:
                if loc:
                    locs.add(loc)
        return sorted(locs)

    def __len__(self) -> int:
        return len(self._villas)

    def __contains__(self, name: str) -> bool:
        return name in self._villas

    def __iter__(self):
        return iter(self.all_villas)
