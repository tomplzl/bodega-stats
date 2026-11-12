# Bodega Stats

NBA stats from 1946 to today, built around which player would have won each pick slot ("box"), by player and team, with a news feed (injuries, transactions, rotations).

- Site : `index.html` + `data/` (GitHub Pages, branche `main`, dossier racine).
- `scripts/news.py` : rapport officiel des blessures, mouvements de joueurs NBA, changements de rotation. Lancé toutes les heures par `.github/workflows/news.yml`.
- `scripts/season.py` : updates the current season from box scores (ESPN public API). Runs twice a day via `.github/workflows/season.yml`. It only writes `data/current.json`.
- Data layout (details in `scripts/store.py`): the live season is in `data/current.json`; history is frozen and loaded on demand: `data/players/<id>.json` (one file per player), `data/seasons/<year>.json`, `data/career.json`, `data/search.json`, `data/teams.json`. When a new season starts, `season.py` freezes the finished one into these files by itself. A history import (Kaggle) must write these same formats.
- `scripts/migrate.py` : one-off conversion from the old single files (`players.json`, `seasons.json`, `leaders.json`), kept for reference.

Pour relancer une mise à jour à la main : onglet **Actions** → choisir le workflow → **Run workflow**.
