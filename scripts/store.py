"""Bodega Stats - organisation des fichiers de données (partagé par season.py et migrate.py).

Principe : l'historique est FIGÉ, seule la saison en cours bouge.
  data/current.json           saison en cours : meta, teams, games, rows (feuilles de match), players (joueurs récents)
  data/players/<id>.json      un fichier par joueur : {"p": fiche, "s": lignes par saison terminée, "l": couronnes par saison terminée}
  data/seasons/<année>.json   une saison terminée : {"y": année, "r": [[id, nom, équipe, MJ, 15 stats], ...]}
  data/career.json            totaux de carrière sur les saisons terminées : {"through": année, "r": [[id, nom, début, fin, équipe, MJ, 15 totaux], ...]}
  data/search.json            index de recherche de tous les joueurs : {"p": [[id, nom, début, fin, équipe, MJ], ...]}
  data/teams.json             bilans par franchise, saisons terminées
season.py n'écrit que current.json au quotidien. Les fichiers figés ne changent qu'une fois par an (freeze_season)
ou lors d'un import d'historique (Kaggle), qui doit produire exactement ces formats.

Ligne de saison (18 colonnes) : [saison, équipe, MJ, min, pts, reb, ast, stl, blk, tov, +/-, FG%, 3P%, FT%, FGA, 3PA, FTA, 3PM]
Ligne de match dans current.json : [match, joueur, équipe, min, pts, reb, ast, tov, +/-, titulaire, stl, blk, fgm, fga, 3pm, 3pa, ftm, fta]
"""
import json, os

TOT = ("min", "pts", "reb", "ast", "stl", "blk", "tov", "pm", "tpm", "fga", "tpa", "fta", "fgm", "tpmA", "ftm")
BIO = {"g": 0, "p": 0, "r": 0, "a": 0, "tp": 0, "pos": None, "h": None, "b": None, "j": None, "dy": None, "dn": None, "c": None, "po": 0}


def rd(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def wr(path, obj):
    """Écriture atomique ; refuse d'écrire un contenu vide."""
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    if not obj or len(s) < 3:
        raise SystemExit("ECHEC : refus d'écrire un fichier vide -> " + path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(s)
    os.replace(tmp, path)


def ppath(D, pid):
    return f"{D}/players/{pid}.json"


def js_order(ids):
    """Ordre de parcours d'un objet JavaScript : entiers positifs croissants, puis le reste dans l'ordre d'arrivée."""
    ids = list(ids)
    return sorted(i for i in ids if i >= 0) + [i for i in ids if i < 0]


def add_row_totals(t, r):
    """Ajoute une ligne de saison aux totaux de carrière (mêmes calculs que l'ancien site)."""
    r = list(r) + [None] * (18 - len(r))
    g = r[2]

    def add(k, v):
        if v is not None:
            t[k] = t.get(k, 0) + v * g
    for k, i in (("min", 3), ("pts", 4), ("reb", 5), ("ast", 6), ("stl", 7), ("blk", 8), ("tov", 9), ("pm", 10), ("tpm", 17)):
        add(k, r[i])
    for att, pct, made, col in (("fga", 11, "fgm", 14), ("tpa", 12, "tpmA", 15), ("fta", 13, "ftm", 16)):
        if r[col] is not None:
            add(att, r[col])
            if r[pct] is not None:
                t[made] = t.get(made, 0) + r[pct] / 100 * r[col] * g
    return g


def pack_totals(t):
    """Totaux -> liste. Les nombres sont gardés tels quels (pas d'arrondi) pour que le site affiche exactement
    les mêmes chiffres qu'avec l'ancien calcul. tpmA ne sert que si les 3PM ne sont pas suivis."""
    out = []
    for k in TOT:
        v = t.get(k)
        if k == "tpmA" and t.get("tpm") is not None:
            v = None
        if isinstance(v, float) and v == int(v):
            v = int(v)
        out.append(v)
    return out


def career_row(p, rows):
    """Ligne de career.json pour un joueur, ou None s'il n'a aucun match."""
    t, gp = {}, 0
    for r in rows:
        gp += add_row_totals(t, r)
    if not rows or not gp:
        return None
    return [p["i"], p["n"], p["f"], p["t"], rows[-1][1], gp] + pack_totals(t)


def season_lines(cur):
    """Saison en cours -> lignes de saison par (joueur, équipe), dans l'ordre de première apparition.
    Renvoie [(id, ligne 18 colonnes, {pts, reb, ast exacts})]."""
    season, agg = cur["meta"]["season"], {}
    for r in cur["rows"]:
        a = agg.setdefault((r[1], r[2]), [0] * 15)
        a[0] += 1
        for j, i in enumerate((3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17)):
            a[j + 1] += r[i]
    out = []
    for (pid, team), a in agg.items():
        g, mn, pts, reb, ast, tov, pm, stl, blk, fgm, fga, tpm, tpa, ftm, fta = a
        av = lambda v: round(v / g, 1)
        pc = lambda m, n: round(100 * m / n, 1) if n else None
        out.append((pid, [season, team, g, av(mn), av(pts), av(reb), av(ast), av(stl), av(blk), av(tov), av(pm), pc(fgm, fga), pc(tpm, tpa), pc(ftm, fta), av(fga), av(tpa), av(fta), av(tpm)], {"pts": pts, "reb": reb, "ast": ast}))
    return out


def season_leaders(cur):
    """Couronnes de la saison : {id: [MJ, pts, reb, ast, tov, meilleur +/-, pire +/-]} (égalités comptées)."""
    games, cnt = {}, {}
    for r in cur["rows"]:
        games.setdefault(r[0], []).append(r)
    for rs in games.values():
        mx = [max(x[i] for x in rs) for i in (4, 5, 6, 7, 8)] + [max(-x[8] for x in rs)]
        for x in rs:
            c = cnt.setdefault(x[1], [0, 0, 0, 0, 0, 0, 0])
            c[0] += 1
            for j, v in enumerate((x[4], x[5], x[6], x[7], x[8], -x[8])):
                if v == mx[j]:
                    c[j + 1] += 1
    return cnt


def refresh_meta(D, cur):
    """Compteurs affichés sur l'accueil et liste des saisons terminées disponibles."""
    ids = {e[0] for e in rd(f"{D}/search.json")["p"]} | {p["i"] for p in cur["players"]}
    ts = {r[0] for v in rd(f"{D}/teams.json").values() for r in v} | {cur["meta"]["season"]}
    hist = sorted(int(f[:-5]) for f in os.listdir(f"{D}/seasons") if f.endswith(".json") and f[:-5].isdigit())
    if not hist:
        raise SystemExit("ECHEC : aucune saison figée dans data/seasons")
    cur["meta"]["counts"] = {"players": len(ids), "seasons": len(ts)}
    cur["meta"]["hist"] = hist


def freeze_season(D, cur, new_season, through):
    """Fige la saison terminée dans l'historique, puis remet current.json à zéro pour new_season.
    Rien n'est enregistré sur GitHub si une étape échoue (le workflow ne commite qu'en cas de succès)."""
    season = cur["meta"]["season"]
    sfile = f"{D}/seasons/{season}.json"
    if os.path.exists(sfile):
        raise SystemExit(f"ECHEC : la saison {season} est déjà figée ({sfile})")
    roster = {p["i"]: p for p in cur["players"]}
    lines, lead = season_lines(cur), season_leaders(cur)
    if lines:
        search = rd(f"{D}/search.json")
        sidx = {e[0]: e for e in search["p"]}
        career = rd(f"{D}/career.json")
        cidx = {r[0]: r for r in career["r"]}
        by = {}
        for pid, row, ex in lines:
            by.setdefault(pid, []).append((row, ex))
        for pid, lst in by.items():
            ro = roster.get(pid) or {"i": pid, "n": "?", "f": season, "t": season, "tm": lst[-1][0][1], "j": None}
            path = ppath(D, pid)
            doc = rd(path) if os.path.exists(path) else {"p": dict(BIO, i=pid, n=ro["n"], f=ro["f"], t=ro["t"], tm=ro["tm"]), "s": [], "l": {}}
            p = doc["p"]
            gp = sum(r[2] for r, _ in lst)
            pts, reb, ast = (sum(e[k] for _, e in lst) for k in ("pts", "reb", "ast"))
            g0 = p.get("g") or 0
            p["tp"] = (p.get("tp") or 0) + pts
            p["g"] = g0 + gp
            p["p"] = round(p["tp"] / p["g"], 1)
            p["r"] = round(((p.get("r") or 0) * g0 + reb) / p["g"], 1)
            p["a"] = round(((p.get("a") or 0) * g0 + ast) / p["g"], 1)
            p["n"], p["tm"], p["t"] = ro["n"], lst[-1][0][1], max(p.get("t") or season, season)
            p["f"] = p.get("f") or season
            if ro.get("j") and not p.get("j"):
                p["j"] = ro["j"]
            doc["s"] = [r for r in doc["s"] if r[0] != season] + [r for r, _ in lst]
            if pid in lead:
                doc["l"][str(season)] = lead[pid]
            wr(path, doc)
            ro["t"], ro["tm"] = p["t"], p["tm"]
            e = [pid, p["n"], p["f"], p["t"], p["tm"], p["g"]]
            if pid in sidx:
                sidx[pid][:] = e
            else:
                search["p"].append(e)
                sidx[pid] = e
            c = cidx.get(pid)
            if c is None:
                c = [pid, p["n"], p["f"], p["t"], p["tm"], 0] + [None] * len(TOT)
                career["r"].append(c)
                cidx[pid] = c
            t = {k: v for k, v in zip(TOT, c[6:]) if v is not None}
            for r, _ in lst:
                c[5] += add_row_totals(t, r)
            c[1:5] = [p["n"], p["f"], p["t"], p["tm"]]
            if t.get("tpm") is None and t.get("tpmA") is None:
                t.pop("tpmA", None)
            c[6:] = pack_totals(t)
        order = {pid: n for n, pid in enumerate(js_order(by))}
        career["r"].sort(key=lambda r: (r[0] < 0, r[0] if r[0] >= 0 else 0))
        career["through"] = season
        wr(f"{D}/career.json", career)
        wr(f"{D}/search.json", search)
        # bilans des équipes
        teams, rec = rd(f"{D}/teams.json"), {}
        for g in cur["games"]:
            for me, opp, f, a in ((g["h"], g["a"], g["hs"], g["as"]), (g["a"], g["h"], g["as"], g["hs"])):
                x = rec.setdefault(me, [0, 0, 0, 0])
                x[0 if f > a else 1] += 1
                x[2] += f
                x[3] += a
        for name, (w, l, pf, pa) in rec.items():
            info = cur["teams"].get(name)
            if not info:
                continue
            lst = teams.setdefault(str(info["id"]), [])
            lst[:] = [r for r in lst if r[0] != season] + [[season, w, l, info.get("city", ""), name, round(pf / (w + l), 1), round(pa / (w + l), 1)]]
        wr(f"{D}/teams.json", teams)
        rows = sorted(((pid, r) for pid, r, _ in lines), key=lambda x: order[x[0]])
        wr(sfile, {"y": season, "r": [[pid, roster[pid]["n"] if pid in roster else "?", r[1]] + r[2:] for pid, r in rows]})
    cur["games"], cur["rows"] = [], []
    cur["players"] = [p for p in cur["players"] if p["t"] >= new_season - 1]
    cur["meta"]["season"], cur["meta"]["through"] = new_season, through
    refresh_meta(D, cur)
    return len(lines)
