# Lowball — Hypixel SkyBlock Lowballing Assistant

A desktop companion app and Minecraft mod for **Hypixel SkyBlock** lowballing. Lowball values items in real time, generates profitable offers, tracks every trade in a ledger, and shows you how you're doing — so you can quote a price while the customer is still standing on your island.

## Overview

Lowball is a two-component system:

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Desktop App** | Python · PySide6 (Qt) | Valuation engine, offer model, ledger, statistics dashboard |
| **Minecraft Mod** | Kotlin · Fabric | Captures trade screen items and chat outcomes, forwards them to the app |

The mod runs inside Minecraft and sends item data to the desktop app over a **loopback WebSocket** (`ws://127.0.0.1:8765`). The mod is read-only — it sends zero packets to the server, binds no macros, and automates no gameplay actions.

---

## Features

### Desktop App

- **Item Valuation** — Prices items using comparable auction sales from the Coflnet API, with modifier-aware matching (enchantments, reforges, stars, gems, attributes, pet level/skin)
- **Offer Model** — Generates buy offers factoring in target margin, estimated sell time, auction tax, confidence level, and modifier value adjustments
- **Rule Engine** — User-configurable YAML rules that override or adjust valuations for specific item categories, rarities, or tags
- **Trade Ledger** — SQLite-backed log of every trade with full item detail, profit/loss tracking, and historical projections
- **Session Tracking** — Groups trades into sessions with running totals and hourly return calculations
- **Statistics Dashboard** — Charts and summaries of trading performance over time
- **Bazaar Integration** — Real-time Bazaar price lookups for materials and commodities
- **Hot-Set Prefetching** — Warms the price cache on startup for commonly traded items so the first trade of a session isn't cold
- **Demo Mode** — Seed synthetic data to explore the interface without needing the mod or network

### Minecraft Mod

- **Item Selection** — Click slots in any container screen to select items for pricing; selection persists across screens
- **Send to App** — Transmits the selected item set (with full NBT data) to the desktop app
- **Trade Outcome Capture** — Watches chat for Hypixel's `Trade completed with …` announcement and forwards the settled items and coin amounts
- **Multi-Version** — Built with Stonecutter for Minecraft 26.1.2 and 26.2

---

## Architecture

```
┌──────────────────────────────┐       WebSocket        ┌──────────────────────┐
│        Minecraft Mod         │ ────────────────────►   │     Desktop App      │
│   (Fabric · Kotlin)          │   ws://127.0.0.1:8765   │  (Python · PySide6)  │
│                              │                         │                      │
│  • Item selection & NBT      │                         │  • Valuation engine   │
│  • Trade chat parsing        │                         │  • Offer model        │
│  • Zero server packets       │                         │  • Trade ledger       │
└──────────────────────────────┘                         │  • Statistics         │
                                                         │  • Rule engine        │
         ┌──────────────┐                                │  • Bazaar prices      │
         │  Coflnet API  │◄──────── HTTP ──────────────  │                      │
         └──────────────┘                                └──────────────────────┘
         ┌──────────────┐                                         │
         │ Hypixel API   │◄──────── HTTP ──────────────────────────┘
         │ (Bazaar)      │
         └──────────────┘
```

---

## Installation

### Pre-Built Executable (Windows)

> `Not available yet! Use the source code <3`

1. Download the latest release from the [Releases](https://github.com/Meeth-W/Skyblock-Lowballing-Assistant/releases) page
2. Extract the `Lowball/` folder
3. Run `Lowball.exe`
4. Install the Fabric mod `.jar` into your Minecraft `mods/` folder

### Running from Source

**Requirements**: Python 3.12+, Java 25 (for the mod)

```bash
# Clone the repository
git clone https://github.com/Meeth-W/Skyblock-Lowballing-Assistant.git
cd Skyblock-Lowballing-Assistant

# Set up the Python app
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -e app
pip install -e "app[dev]"     # for development (pytest, ruff)

# Run the app
python -m lowball
python -m lowball --demo      # demo mode with synthetic data
python -m lowball --listen    # diagnostic: print mod messages only
python -m lowball --help      # all options
```

### Building the Mod

```bash
cd mod
./gradlew build               # both configured Minecraft versions
./gradlew :26.1.2:build       # just one version
```

Output jars are placed in:
```
mod/versions/26.1.2/build/libs/lowball-26.1.2-0.1.0+26.1.2.jar
mod/versions/26.2/build/libs/lowball-26.2-0.1.0+26.2.jar
```

---

## Usage

1. **Start the desktop app** — it begins listening on `ws://127.0.0.1:8765`
2. **Launch Minecraft** with the Lowball Fabric mod installed
3. **Open a trade or chest** — use the mod's on-screen buttons to select items
4. **Click Send** — the selected items appear in the desktop app with valuations and a recommended offer
5. **Complete the trade** — the mod captures the trade outcome from chat and logs it to the ledger

### Command-Line Options

| Flag | Description |
|------|-------------|
| `--data-dir PATH` | Where the database and settings live (default: `~/.lowball`) |
| `--port PORT` | Uplink WebSocket port (default: `8765`) |
| `--no-prefetch` | Skip the hot-set cache warm-up on startup |
| `--demo` | Seed synthetic data and open the app |
| `--listen` | Diagnostic mode: print mod messages, no GUI |
| `-v, --verbose` | Debug-level logging |

---

## Configuration

Settings are stored in `~/.lowball/settings.yaml` and are created with defaults on first run. Key options:

```yaml
uplink_port: 8765
min_comparables: 5
target_margin: 0.05
target_hourly_return: 2000000
exploration_every: 15
derpy: false
prefetch_tags:
  - HYPERION
  - TERMINATOR
  # ... commonly traded item tags
```

Custom valuation rules can be defined in `~/.lowball/rules.yaml`. The app ships with sensible defaults covering common lowballing scenarios.

---

## Project Structure

```
├── app/                    # Python desktop application
│   ├── lowball/            # Main package
│   │   ├── api/            # Coflnet & Bazaar API clients
│   │   ├── ledger/         # SQLite trade ledger
│   │   ├── parsing/        # NBT & item data parsing
│   │   ├── pricing/        # Valuation, offer model, modifiers
│   │   ├── rules/          # User-configurable rule engine
│   │   ├── session/        # Trade session state machine
│   │   ├── stats/          # Statistics queries
│   │   ├── ui/             # PySide6 interface
│   │   ├── uplink/         # WebSocket server for mod communication
│   │   ├── config.py       # Application settings
│   │   ├── controller.py   # Main application controller
│   │   └── __main__.py     # Entry point
│   ├── tests/              # Test suite (pytest)
│   └── pyproject.toml      # Build configuration
├── mod/                    # Fabric Minecraft mod (Kotlin)
│   ├── src/                # Mod source code
│   ├── build.gradle.kts    # Gradle build script
│   └── versions/           # Stonecutter multi-version targets
├── LICENSE                 # MIT License
└── README.md               # This file
```

---

## Development

```bash
# Run tests
cd app
pytest

# Lint
ruff check .
ruff format --check .
```

### Dependencies

| Package | Purpose |
|---------|---------|
| PySide6 | Qt GUI framework |
| pyqtgraph | Real-time charts |
| httpx | Async HTTP client |
| websockets | WebSocket server for mod uplink |
| nbtlib | Minecraft NBT data parsing |
| ruamel.yaml | YAML config with comment preservation |
| numpy | Numerical operations for pricing |

---

## Compliance Note

The Minecraft mod is designed to comply with Hypixel's rules:

- **Zero server packets** — the mod sends nothing to the game server
- **No macros** — no keybind triggers any in-game action
- **Read-only capture** — item selection swallows clicks (preventing in-game action), never generates them
- **Client-side rendering only** — button overlays and slot highlights are purely visual

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
