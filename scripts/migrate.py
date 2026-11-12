"""Bodega Stats - migration ponctuelle vers la structure découpée (voir scripts/store.py).
Usage: python3 scripts/migrate.py [DATA_DIR]
Lit les anciens fichiers players.json, seasons.json, leaders.json et current.json, écrit la nouvelle structure,
vérifie qu'aucune ligne n'a été perdue, puis supprime les trois anciens fichiers. Sans effet si déjà migré."""
import sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import rd, wr, ppath, js_order, career_row, refresh_meta

D = sys.argv[1] if len(sys.argv) > 1 else "data"
OLD = [f"{D}/{n}.json" for n in ("players", "seasons", "leaders")]


def main():
    if not any(os.path.exists(f) for f in OLD):
        print("déjà migré : rien à faire")
        return
    if not all(os.path.exists(f) for f in OLD):
        sys.exit("ECHEC : anciens fichiers incomplets, migration impossible")
    P, S, L, cur = rd(OLD[0]), rd(OLD[1]), rd(OLD[2]), rd(f"{D}/current.json")
    season = cur["meta"]["season"]
    built = P["meta"]["through"]  # les totaux de carrière des fiches incluent la saison en cours jusqu'à cette date
    gdate = {g["id"]: g["d"] for g in cur["games"]}
    part, seen = {}, set()
    for r in cur["rows"]:
        seen.add(r[1])
        if gdate[r[0]] <= built:
            x = part.setdefault(r[1], [0, 0, 0, 0])
            x[0] += 1
            x[1] += r[4]
            x[2] += r[5]
            x[3] += r[6]
    for d in ("players", "seasons"):
        shutil.rmtree(f"{D}/{d}", ignore_errors=True)
    by_season, career, search, n_rows = {}, {}, [], 0
    for p in P["p"]:
        pid = p["i"]
        rows = [r for r in S.get(str(pid), []) if r[0] < season]
        n_rows += len(rows)
        bio = dict(p)
        if pid in part:  # retire la part de la saison en cours : la fiche figée s'arrête à la saison précédente
            g, pts, reb, ast = part[pid]
            g0 = p["g"] - g
            if g0 != sum(r[2] for r in rows):
                sys.exit(f"ECHEC : total de matchs incohérent pour {p['n']}")
            bio["g"], bio["tp"] = g0, p["tp"] - pts
            bio["p"] = round(bio["tp"] / g0, 1) if g0 else 0
            bio["r"] = round(max(p["r"] * p["g"] - reb, 0) / g0, 1) if g0 else 0
            bio["a"] = round(max(p["a"] * p["g"] - ast, 0) / g0, 1) if g0 else 0
        wr(ppath(D, pid), {"p": bio, "s": rows, "l": {k: v for k, v in L.get(str(pid), {}).items() if int(k) < season}})
        search.append([pid, p["n"], p["f"], p["t"], p["tm"], bio["g"]])
        for r in rows:
            by_season.setdefault(r[0], {}).setdefault(pid, []).append(r)
        c = career_row(p, rows)
        if c:
            career[pid] = c
    names = {p["i"]: p["n"] for p in P["p"]}
    for y, m in by_season.items():
        wr(f"{D}/seasons/{y}.json", {"y": y, "r": [[pid, names[pid], r[1]] + r[2:] for pid in js_order(m) for r in m[pid]]})
    wr(f"{D}/career.json", {"through": season - 1, "r": [career[i] for i in js_order(career)]})
    wr(f"{D}/search.json", {"p": search})
    teams = rd(f"{D}/teams.json")
    wr(f"{D}/teams.json", {k: [r for r in v if r[0] < season] for k, v in teams.items()})
    cur["players"] = [{k: p[k] for k in ("i", "n", "f", "t", "tm", "j")} for p in P["p"] if p["t"] >= season - 1 or p["i"] in seen]
    refresh_meta(D, cur)
    wr(f"{D}/current.json", cur)
    # contrôles avant de supprimer les anciens fichiers
    files = [f for f in os.listdir(f"{D}/players") if f.endswith(".json")]
    got = sum(len(rd(f"{D}/seasons/{f}")["r"]) for f in os.listdir(f"{D}/seasons"))
    old_rows = sum(1 for v in S.values() for r in v if r[0] < season)
    missing = seen - {p["i"] for p in cur["players"]}
    if len(files) != len(P["p"]) or got != old_rows or n_rows != old_rows or missing or set(S) - {str(p["i"]) for p in P["p"]}:
        sys.exit(f"ECHEC : contrôle de migration ({len(files)} fiches pour {len(P['p'])} joueurs, {got}/{n_rows}/{old_rows} lignes, {len(missing)} joueurs absents)")
    for f in OLD:
        os.remove(f)
    print(f"migration OK : {len(files)} joueurs, {len(by_season)} saisons figées ({min(by_season)}-{max(by_season)}), {got} lignes, {len(cur['players'])} joueurs récents, saison en cours {season}")


if __name__ == "__main__":
    main()
