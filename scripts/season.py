"""Bodega Stats - mise à jour de la saison en cours à partir des feuilles de match (API publique ESPN).
Usage: python3 scripts/season.py [DATA_DIR] [JOURS_A_REVERIFIER]   (par défaut: data 2)
N'écrit que current.json (plus une fiche vide pour un joueur jamais vu) : l'historique est figé, voir scripts/store.py.
Seuls les matchs de saison régulière comptent (ni présaison, ni play-in, ni playoffs, ni All-Star, ni finale de la NBA Cup).
Les matchs des derniers jours sont relus à chaque passage : ESPN corrige parfois un score ou complète le +/- après coup.
Une feuille de match récente est considérée incomplète si tous les +/- valent 0 ou si les points des joueurs ne
font pas le score : elle est alors reprise au passage suivant (et acceptée telle quelle au bout de 2 jours).
Au premier match de saison régulière d'une nouvelle saison, la saison terminée est figée dans l'historique (store.freeze_season)."""
import sys, os, re, json, time, datetime, urllib.request, urllib.error, unicodedata, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

D = sys.argv[1] if len(sys.argv) > 1 else "data"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = {"User-Agent": "Mozilla/5.0"}
TEAMS = {"ATL": "Hawks", "BOS": "Celtics", "BRK": "Nets", "CHO": "Hornets", "CHI": "Bulls", "CLE": "Cavaliers", "DET": "Pistons", "IND": "Pacers", "MIA": "Heat", "MIL": "Bucks", "NYK": "Knicks", "ORL": "Magic", "PHI": "76ers", "TOR": "Raptors", "WAS": "Wizards",
         "DAL": "Mavericks", "DEN": "Nuggets", "GSW": "Warriors", "HOU": "Rockets", "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIN": "Timberwolves", "NOP": "Pelicans", "OKC": "Thunder", "PHO": "Suns", "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "UTA": "Jazz"}
CODES = sorted(TEAMS)
RECHECK = int(sys.argv[2]) if len(sys.argv) > 2 else 2
SKIP_TYPES = ("ALLSTAR", "CC")  # All-Star Game, finale de la NBA Cup (ne compte pas en saison régulière)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def key(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def num(x):
    try:
        return int(str(x).replace("+", ""))
    except ValueError:
        return 0


def team_of(c):
    n = c["team"]["displayName"]
    return next((t for t in TEAMS.values() if n.endswith(t)), None)


def regular(ev):
    """True si le match compte en saison régulière. Lève KeyError si ESPN ne donne plus le type de saison."""
    se = ev.get("season") or {}
    if se.get("type") is None or se.get("year") is None:
        raise KeyError("type de saison absent (format ESPN changé ?)")
    if se["type"] != 2 or (ev["competitions"][0].get("type") or {}).get("abbreviation") in SKIP_TYPES:
        return False  # présaison, play-in, playoffs, All-Star, finale de la NBA Cup
    return ev["status"]["type"].get("name") not in ("STATUS_POSTPONED", "STATUS_CANCELED")


def read_game(ev, date):
    """Feuille de match ESPN -> (match, [(équipe, nom, 15 stats)]) ; None si les deux équipes ne sont pas des équipes NBA."""
    comp = ev["competitions"][0]["competitors"]
    home = next(c for c in comp if c["homeAway"] == "home")
    away = next(c for c in comp if c["homeAway"] == "away")
    hn, an = team_of(home), team_of(away)
    if not hn or not an:
        return None
    hcode = next(k for k, v in TEAMS.items() if v == hn)
    gid = int(f"9{date}{CODES.index(hcode):02d}")
    game = {"id": gid, "d": f"{date[:4]}-{date[4:6]}-{date[6:]}", "h": hn, "a": an, "hs": num(home["score"]), "as": num(away["score"])}

    def rows():
        sm = json.loads(get(f"{ESPN}/summary?event={ev['id']}"))
        out = []
        for tb in sm["boxscore"]["players"]:
            tn = next((t for t in TEAMS.values() if tb["team"]["displayName"].endswith(t)), None)
            stt = tb["statistics"][0]
            lab = stt["labels"]
            for a in stt["athletes"]:
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                v = dict(zip(lab, a["stats"]))
                mk = lambda x: tuple(num(y) for y in (str(x) + "-0").split("-")[:2])
                fg, tp, ft = mk(v.get("FG", "0-0")), mk(v.get("3PT", "0-0")), mk(v.get("FT", "0-0"))
                if num(v.get("MIN", 0)) <= 0:
                    continue
                name = unicodedata.normalize("NFKD", a["athlete"]["displayName"]).encode("ascii", "ignore").decode().strip()
                out.append((tn, name, [num(v.get("MIN")), num(v.get("PTS")), num(v.get("REB")), num(v.get("AST")), num(v.get("TO")), num(v.get("+/-")), 1 if a.get("starter") else 0, num(v.get("STL")), num(v.get("BLK")), fg[0], fg[1], tp[0], tp[1], ft[0], ft[1]]))
        return out
    return game, rows


def main():
    cur = store.rd(f"{D}/current.json")
    if "players" not in cur or not os.path.isdir(f"{D}/players"):
        sys.exit("ECHEC : données pas encore migrées (lancer scripts/migrate.py)")
    season = cur["meta"]["season"]
    through = cur["meta"]["through"].replace("-", "")
    day = lambda s: datetime.datetime.strptime(s, "%Y%m%d")
    today_et = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)).strftime("%Y%m%d")
    dates, d = [], day(through) + datetime.timedelta(days=1)
    while d.strftime("%Y%m%d") < today_et and len(dates) < 20:
        dates.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    stored = {g["d"].replace("-", "") for g in cur["games"]}
    redo = [x for x in ((day(through) - datetime.timedelta(days=n)).strftime("%Y%m%d") for n in range(RECHECK - 1, -1, -1)) if x in stored]
    if not dates and not redo:
        print(json.dumps({"nouveaux_matchs": 0}))
        return
    roster = {p["i"]: p for p in cur["players"]}
    # index des noms : tous les joueurs connus (search.json), les joueurs récents de current.json faisant foi
    everyone = dict(roster)
    for e in store.rd(f"{D}/search.json")["p"]:
        everyone.setdefault(e[0], {"i": e[0], "n": e[1], "f": e[2], "t": e[3], "tm": e[4], "j": None})
    idx = {}
    for p in everyone.values():
        k = key(p["n"])
        if k not in idx or p["t"] > idx[k]["t"]:
            idx[k] = p
    known = {g["id"] for g in cur["games"]}
    added, fixed, frozen, src_error = 0, 0, None, None
    last_name = lambda n: key(n.split()[-1] if not re.match(r"(?i)^(jr\.?|sr\.?|ii|iii|iv)$", n.split()[-1]) or len(n.split()) < 2 else n.split()[-2])

    def enroll(p):
        """Fait entrer dans current.json un ancien joueur qui rejoue (numéro de maillot repris de sa fiche)."""
        if p["i"] not in roster:
            try:
                p["j"] = store.rd(store.ppath(D, p["i"]))["p"].get("j")
            except Exception:
                pass
            roster[p["i"]] = p
            cur["players"].append(p)
        return p

    def player(name, team):
        """Retrouve le joueur par son nom, ou le crée (identifiant négatif) s'il n'a jamais été vu."""
        w = name.split()
        p = idx.get(key(name)) or idx.get(key(" ".join(reversed(w))))
        if p:
            return enroll(p)
        c = [x for x in cur["players"] if x.get("tm") == team and x["t"] >= season - 1 and last_name(x["n"]) == last_name(name) and x["n"][:1].lower() == w[0][:1].lower()]
        if len(c) == 1:
            return c[0]
        p = {"i": -int(hashlib.md5(key(name).encode()).hexdigest()[:7], 16), "n": name, "f": season, "t": season, "tm": team, "j": None}
        if p["i"] in everyone:  # identifiant déjà attribué : on reprend le joueur existant
            p = enroll(everyone[p["i"]])
        else:
            cur["players"].append(p)
            roster[p["i"]] = everyone[p["i"]] = p
            if not os.path.exists(store.ppath(D, p["i"])):
                store.wr(store.ppath(D, p["i"]), {"p": dict(store.BIO, **p), "s": [], "l": {}})
        idx[key(name)] = p
        return p

    fresh = lambda date: (day(today_et) - day(date)).days <= 2

    def suspect(game, rs):
        """Feuille de match pas encore fiable : vide, +/- pas encore remplis, ou points des joueurs différents du score."""
        if not rs or all(x[5] == 0 for _, _, x in rs):
            return True
        return any(sum(x[1] for tn, _, x in rs if tn == game[t]) != game[s] for t, s in (("h", "hs"), ("a", "as")))

    # 1) relecture des derniers jours déjà enregistrés (corrections ESPN) ; une panne ici n'est pas bloquante
    for date in redo:
        try:
            for ev in json.loads(get(f"{ESPN}/scoreboard?dates={date}")).get("events", []):
                if not regular(ev) or not ev["status"]["type"].get("completed") or ev["season"]["year"] - 1 != season:
                    continue
                g = read_game(ev, date)
                if not g or g[0]["id"] not in known:
                    continue
                game, rs = g[0], g[1]()
                if suspect(game, rs):
                    continue
                new = [[game["id"], player(name, tn)["i"], tn] + x for tn, name, x in rs]
                old = [r for r in cur["rows"] if r[0] == game["id"]]
                og = next(x for x in cur["games"] if x["id"] == game["id"])
                sig = lambda rows: sorted(r[:3] + r[4:] for r in rows)  # hors minutes (arrondies différemment selon la source)
                if sig(new) != sig(old) or og != game:
                    out, done = [], False
                    for r in cur["rows"]:  # remplacement sur place : l'ordre des lignes donne l'équipe actuelle d'un joueur
                        if r[0] != game["id"]:
                            out.append(r)
                        elif not done:
                            out.extend(new)
                            done = True
                    cur["rows"] = out
                    og.update(game)
                    fixed += 1
                time.sleep(0.5)
        except Exception as e:
            print("relecture", date, e)

    # 2) nouveaux matchs
    last = through
    for date in dates:
        try:
            sb = json.loads(get(f"{ESPN}/scoreboard?dates={date}"))
        except Exception as e:
            print("scoreboard", date, e)
            src_error = f"scoreboard {date}: {e}"
            break
        complete = True
        for ev in sb.get("events", []):
            try:
                if not regular(ev):
                    continue
            except KeyError as e:
                src_error, complete = f"scoreboard {date}: {e}", False
                break
            if not ev["status"]["type"].get("completed"):
                complete = False
                continue
            g = read_game(ev, date)
            if not g:
                continue  # match hors NBA
            game, syear = g[0], ev["season"]["year"] - 1
            if syear < season:
                continue
            if syear > season:  # premier match d'une nouvelle saison : on fige la précédente
                day_before = (day(date) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                n = store.freeze_season(D, cur, syear, day_before)
                frozen, season = season, syear
                known = set()
                roster.clear()
                roster.update({p["i"]: p for p in cur["players"]})
                print(f"saison {frozen} figée ({n} lignes), nouvelle saison {season}")
            if game["id"] in known:
                continue
            try:
                rs = g[1]()
            except Exception as e:
                print("summary", ev["id"], e)
                complete = False
                continue
            if not rs or (suspect(game, rs) and fresh(date)):
                print("feuille de match incomplète, reprise au prochain passage :", game["d"], game["a"], "@", game["h"])
                complete = False
                continue
            cur["games"].append(game)
            for tn, name, x in rs:
                p = player(name, tn)
                p["t"] = max(p["t"], season)
                p["tm"] = tn
                cur["rows"].append([game["id"], p["i"], tn] + x)
            known.add(game["id"])
            added += 1
            time.sleep(0.5)
        if not complete:
            break
        last = date
    if not (added or fixed or frozen is not None or last != through):
        print(json.dumps({"nouveaux_matchs": 0, "matchs_corriges": 0}))
        if src_error:
            sys.exit("ECHEC : source ESPN injoignable ou format changé -> " + src_error)
        return
    cur["meta"]["through"] = f"{last[:4]}-{last[4:6]}-{last[6:]}"
    cur["meta"]["built"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")
    store.refresh_meta(D, cur)
    store.wr(f"{D}/current.json", cur)
    print(json.dumps({"nouveaux_matchs": added, "matchs_corriges": fixed, "jusqu_au": cur["meta"]["through"], "saison": season, "saison_figee": frozen}))
    if src_error and added == 0:
        print("ECHEC : source ESPN injoignable ou format changé -> " + src_error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
