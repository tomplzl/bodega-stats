# Bodega Stats

NBA stats from 1946 to today, built around which player would have won each pick slot ("box"), by player and team, with a news feed (injuries, transactions, rotations).

- Site : `index.html` + `data/` (GitHub Pages, branche `main`, dossier racine).
- `scripts/news.py` : rapport officiel des blessures, mouvements de joueurs NBA, changements de rotation. Lancé toutes les heures par `.github/workflows/news.yml`.
- `scripts/season.py` : updates the current season from box scores (ESPN public API). Runs every morning via `.github/workflows/season.yml`.

Pour relancer une mise à jour à la main : onglet **Actions** → choisir le workflow → **Run workflow**.
