# CS2 Stats

**English** · [Español](README.es.md)

A Windows desktop app that collects your Counter-Strike 2 matches (Premier, Competitive and FACEIT), keeps your full history on your PC, compares your numbers with players of your Premier rank and tells you what to practice. It also has a lineups library with in-game clips, and it can message you on Steam with the best moments of every match.

Everything runs on your PC with official Valve tools. It never reads or touches the game's memory, so there is no VAC risk.

![Lineups](docs/screenshots/en/lineups.png)

## Features

* **Automatic match import.** Like Leetify, but local: with your Steam authentication code, the Match History API and a secondary account on the CS2 Game Coordinator, new Premier demos download and get analyzed on their own a few minutes after each match.
* **Full CS2 history** from Steam's official "Personal Game Data" page (sign in once with a QR code).
* **Metrics per match and over time:** rating, ADR, KAST, opening duels, trades, clutches, utility, economy, round by round, by map, by weapon and CT vs T.
* **Comparison with your rank:** each metric against players of your same Premier color taken from your own demos, with where you stand out and where you are below.
* **Tips** written from your own numbers, with how confident each one is.
* **Lineups:** the best known smokes, molotovs and flashes for Mirage, Dust II, Inferno, Ancient, Anubis, Nuke and Cache, each one tested in CS2. Every lineup has a clip recorded in game in three parts (where to stand, where to aim, how it lands), step by step instructions and how many times it was thrown in your matches. Click the clip to watch it full screen.
* **Steam message after every match:** your secondary account sends you a chat message, like a friend, with your best moments (multi-kills, clutches, ADR records).
* **Spanish and English.** Pick the language at the bottom of the sidebar.

| Tips | Matches |
|---|---|
| ![Tips](docs/screenshots/en/tips.png) | ![Matches](docs/screenshots/en/matches.png) |

## Install

1. Download `CS2Stats-windows.zip` from the [latest release](../../releases/latest).
2. Unzip it anywhere and open `CS2Stats.exe`. The `clips` folder next to it has the lineup clips.
3. Follow **Connect Steam** in the app (about 5 minutes, once):
   1. Paste your **authentication code** and **latest match code** (the app opens Valve's page where you get them).
   2. Paste a **Steam Web API key** (domain: `localhost`).
   3. Connect a **secondary Steam account** with a QR code or username and password. It is a free account that only requests demos; your main account is never left signed in.
   4. Optional: sign in once with QR using your main account to import your full history.

For FACEIT, download the demo from the match room and the app imports it from your Downloads folder.

## Safety

* Only official sources: Game State Integration (a text file in the CS2 `cfg` folder), the Match History API, Valve's replay servers and the CS2 Game Coordinator through the secondary account.
* It never opens, reads or modifies the game process or its memory.
* Lineup clips are recorded with CS2 in practice mode (`-insecure`, your own server) and the Windows window capture. To play online again, close CS2 and open it normally.
* Keys and tokens are stored encrypted on your PC with Windows DPAPI. Nothing is sent to other services.

## Data

Everything is stored in `%LOCALAPPDATA%\CS2Stats`: `historial.db` (matches, rounds and weapons), `ajustes.json` and `clips\` (clips you record yourself).

## Development

* Python 3.12 with `PySide6-Essentials`, `demoparser2`, `polars`, `pandas`, `zstandard`, `segno`, `vpk`, `windows-capture`, `opencv-python` and `pyinstaller`.
* Steam helper: Node.js with `steam-user`, `globaloffensive` and `steam-session` (`cd helper && npm install`).
* Run: `python -m cs2stats`. Tests: `python -m unittest discover -s tests`.
* Build: `pyinstaller CS2Stats.spec` creates `dist\CS2Stats\CS2Stats.exe`.
* Texts are written in Spanish and translated with `t()` (`cs2stats/i18n.py`); English translations live in `cs2stats/i18n_en.py`.

| Part | What it does |
|---|---|
| `cs2stats/parser.py` | Reads a demo and builds the metrics round by round for all 10 players |
| `cs2stats/metrics.py` | Calculations over rounds: ADR, KAST, rating, opening duels, utility |
| `cs2stats/benchmarks.py` | Averages by Premier rank and where you stand out |
| `cs2stats/insights.py` | Weak spots, strengths and tips |
| `cs2stats/sync.py`, `steamapi.py`, `helper.py` | Steam sync: match codes, Game Coordinator, downloads, history |
| `cs2stats/resumen.py` | The Steam message with the best moments of the match |
| `cs2stats/nades.py`, `data/latas.json` | Known lineups and how many times you used them |
| `cs2stats/recorder.py` | Records lineup clips in CS2 practice mode |
| `cs2stats/ui/` | The app windows |

## Credits

Lineup positions come from [csnades.gg](https://csnades.gg) (plus the Mirage window smoke from T Spawn, taken from real matches); every lineup was thrown in CS2 and only the ones that land where they should were kept. Map images and icons are read from your local CS2 install. CS2 Stats is not affiliated with Valve.

## License

[MIT](LICENSE)
