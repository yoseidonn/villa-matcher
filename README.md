# Villa Matcher

Terminal-based villa availability engine for Resital Villa.

Uses **multi-snapshot occupancy detection** to reliably determine which villas
are occupied — solving the problem of distinguishing "guest is currently staying"
from "reservation was deleted" by analyzing ALL report snapshots over time.

## Quick Start

```bash
# Install
cd ~/Software/villa-matcher
pip install -e .

# Initialize villa registry (auto-discovers villa names from existing data)
villa-matcher init

# Build occupancy timelines from report snapshots
villa-matcher rebuild

# Find available villas for a 7-day stay
villa-matcher find --from 2026-07-25 --to 2026-08-01 --persons 4

# Find with multi-villa sequences (3 days here, 4 days there)
villa-matcher find --from 2026-08-01 --to 2026-08-08 --persons 6 --allow-sequences

# Interactive calendar browser
villa-matcher calendar --interactive

# Static calendar for one villa
villa-matcher calendar --villa "Samira One" --month 7 --year 2026

# Occupancy overview for a month
villa-matcher overview --month 8 --year 2026

# Analyze snapshot data and show classification details
villa-matcher analyze --show-ambiguous

# Timeline for a specific villa
villa-matcher status "Tigra"
```

## Setup

### 1. Villa metadata

Edit `data/villas.json` and fill in each villa's capacity, location, area, and attributes:

```json
{
  "Samira One": {
    "capacity": 6,
    "location": "Kalkan",
    "area": "Kördere",
    "bedrooms": 3,
    "bathrooms": 3,
    "attributes": ["pool", "sea_view", "jacuzzi"]
  }
}
```

### 2. Snapshots

Create a symlink to your existing report snapshots:

```bash
ln -s ~/Masaüstü/Resital\ Villa\ Scripts/inputs/all_reservations data/all_reservations
```

Or the tool will automatically fall back to the legacy path.

## How It Works

### The Data Problem

Resort Report Excel snapshots only show **future** check-ins. Once a check-in date
passes, the reservation disappears from the report — even though the guest is
still in the villa!

### The Solution

By analyzing ALL consecutive snapshots (e.g., 30+ weekly reports), the occupancy
engine classifies every reservation using 6 rules:

| Rule | Classification | Meaning |
|---|---|---|
| Still in latest snapshot | `confirmed` | Active/future booking |
| Checkout before snapshot drop | `confirmed` | Stay naturally completed |
| Check-in passed, checkout future | `likely_active` | Guest still in villa |
| Disappeared before check-in | `deleted` | Genuinely cancelled |
| New in latest snapshot | `confirmed` | Fresh booking |
| Single appearance, old snapshot | `ambiguous` | Needs manual review |

### Algorithms

- **Single villa matcher**: Checks each villa's timeline for blocking overlaps
- **Sequence finder**: Partitions date range, finds villa combinations using
  constraint-satisfaction + scoring (fewer moves, same region preferred)

## Data Files

| File | Purpose |
|---|---|
| `data/villas.json` | Villa metadata (capacity, location, attributes) — **you fill this** |
| `data/all_reservations/` | Symlink to Resort Report .xlsx snapshots |

## Future

Phase 2 will add a web UI (FastAPI + React) wrapping the same engine,
with interactive calendar widgets inspired by resitalvilla.com.
