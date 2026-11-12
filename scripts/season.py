"""Bodega Stats - mise à jour de la saison en cours à partir des feuilles de match (API publique ESPN).
Usage: python3 scripts/season.py [DATA_DIR]   (par défaut: data)
Met à jour current.json, leaders.json, seasons.json et players.json pour les matchs joués depuis meta.through."""
import sys, os, re, json, time, datetime, urllib.request, urllib.error, unicodedata, hashlib

D = sys.argv[1] if len(sys.argv) > 1 else "data"
BR = "https://www.basketball-reference.com"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = {"User-Agent": "Mozilla/5.0"}
TEAMS = {"ATL": "Hawks", "BOS": "Celtics", "BRK": "Nets", "CHO": "Hornets", "CHI": "Bulls", "CLE": "Cavaliers", "DET": "Pistons", "IND": "Pacers", "MIA": "Heat", "MIL": "Bucks", "NYK": "Knicks", "ORL": "Magic", "PHI": "76ers", "TOR": "Raptors", "WAS": "Wizards",
         "DAL": "Mavericks", "DEN": "Nuggets", "GSW": "Warriors", "HOU": "Rockets", "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIN": "Timberwolves", "NOP": "Pelicans", "OKC": "Thunder", "PHO": "Suns", "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "UTA": "Jazz"}
CODES = sorted(TEAMS)
MAX_GAMES = 45


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def key(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def num(tr, stat):
    m = re.search(r'data-stat="%s"[^>]*>([^<]*)<' % stat, tr)
    v = (m.group(1).strip() if m else "") or "0"
    try:
        return int(v.replace("+", ""))
    except ValueError:
        return 0


def parse_box(path):
    html = get(BR + path)
    out = {}
    for m in re.finditer(r'<table[^>]+id="box-([A-Z]{3})-game-basic".*?</table>', html, re.S):
        code, tb = m.group(1), m.group(0)
        body = tb.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        foot = tb.split("<tfoot>", 1)[1] if "<tfoot>" in tb else ""
        rows, starter = [], True
        for tr in re.findall(r"<tr[^>]*>.*?</tr>", body, re.S):
            if 'class="thead"' in tr:
                starter = False
                continue
            nm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', tr)
            if not nm or 'data-stat="reason"' in tr:
                continue
            mp = re.search(r'data-stat="mp"[^>]*>([\d:]+)<', tr)
            if not mp:
                continue
            v = mp.group(1)
            mins = int(v.split(":")[0]) + (int(v.split(":")[1]) / 60 if ":" in v else 0)
            rows.append(dict(name=unicodedata.normalize("NFKD", nm.group(1)).encode("ascii", "ignore").decode().strip(), min=round(mins, 1), pts=num(tr, "pts"), reb=num(tr, "trb"), ast=num(tr, "ast"), tov=num(tr, "tov"), pm=num(tr, "plus_minus"), st=1 if starter else 0, ext=[num(tr, k) for k in ("stl", "blk", "fg", "fga", "fg3", "fg3a", "ft", "fta")]))
        out[code] = {"rows": rows, "score": num(foot, "pts")}
    return out


def main():
    cur = json.load(open(f"{D}/current.json"))
    P = json.load(open(f"{D}/players.json"))
    season = cur["meta"]["season"]
    through = cur["meta"]["through"].replace("-", "")
    today_et = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)).strftime("%Y%m%d")
    start = (datetime.datetime.strptime(through, "%Y%m%d") + datetime.timedelta(days=1))
    dates = []
    d = start
    while d.strftime("%Y%m%d") < today_et and len(dates) < 20:
        dates.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    if not dates:
        print(json.dumps({"nouveaux_matchs": 0}))
        return
    idx = {}
    for p in P["p"]:
        k = key(p["n"])
        if k not in idx or p["t"] > idx[k]["t"]:
            idx[k] = p
    known = {g["id"] for g in cur["games"]}
    added, failed = 0, []
    src_error = None
    def find(name, team):
        w = name.split()
        p = idx.get(key(name)) or idx.get(key(" ".join(reversed(w))))
        if p:
            return p
        last_k, first = key(w[-1] if not re.match(r"(?i)^(jr\.?|sr\.?|ii|iii|iv)$", w[-1]) else w[-2]), w[0][:1].lower()
        c = [x for x in P["p"] if x.get("tm") == team and x["t"] >= season - 1 and key(x["n"].split()[-1] if not re.match(r"(?i)^(jr\.?|sr\.?|ii|iii|iv)$", x["n"].split()[-1]) else x["n"].split()[-2]) == last_k and x["n"][:1].lower() == first]
        return c[0] if len(c) == 1 else None
    def team_of(c):
        n = c["team"]["displayName"]
        return next((t for t in TEAMS.values() if n.endswith(t)), None)
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
            st = ev["status"]["type"]
            if st.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue
            if not st.get("completed"):
                complete = False
                continue
            comp = ev["competitions"][0]["competitors"]
            home = next(c for c in comp if c["homeAway"] == "home")
            away = next(c for c in comp if c["homeAway"] == "away")
            hn, an = team_of(home), team_of(away)
            if not hn or not an:
                continue  # match hors NBA (All-Star, etc.)
            hcode = next(k for k, v in TEAMS.items() if v == hn)
            gid = int(f"9{date}{CODES.index(hcode):02d}")
            if gid in known:
                continue
            try:
                sm = json.loads(get(f"{ESPN}/summary?event={ev['id']}"))
            except Exception as e:
                print("summary", ev["id"], e)
                complete = False
                continue
            rows = []
            for tb in sm["boxscore"]["players"]:
                tn = next((t for t in TEAMS.values() if tb["team"]["displayName"].endswith(t)), None)
                stt = tb["statistics"][0]
                lab = stt["labels"]
                for a in stt["athletes"]:
                    if a.get("didNotPlay") or not a.get("stats"):
                        continue
                    v = dict(zip(lab, a["stats"]))
                    def i(x):
                        try:
                            return int(str(x).replace("+", ""))
                        except ValueError:
                            return 0
                    def mk(x):
                        m, t = (str(x) + "-0").split("-")[:2]
                        return i(m), i(t)
                    fg, tp, ft = mk(v.get("FG", "0-0")), mk(v.get("3PT", "0-0")), mk(v.get("FT", "0-0"))
                    if i(v.get("MIN", 0)) <= 0:
                        continue
                    name = unicodedata.normalize("NFKD", a["athlete"]["displayName"]).encode("ascii", "ignore").decode().strip()
                    rows.append((tn, name, [i(v.get("MIN")), i(v.get("PTS")), i(v.get("REB")), i(v.get("AST")), i(v.get("TO")), i(v.get("+/-")), 1 if a.get("starter") else 0, i(v.get("STL")), i(v.get("BLK")), fg[0], fg[1], tp[0], tp[1], ft[0], ft[1]]))
            iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            cur["games"].append({"id": gid, "d": iso, "h": hn, "a": an, "hs": i(home["score"]), "as": i(away["score"])})
            for tn, name, x in rows:
                p = find(name, tn)
                if not p:
                    p = {"i": -int(hashlib.md5(key(name).encode()).hexdigest()[:7], 16), "n": name, "f": season, "t": season, "g": 0, "p": 0, "r": 0, "a": 0, "tp": 0, "tm": tn, "pos": None, "h": None, "b": None, "j": None, "dy": None, "dn": None, "c": None, "po": 0}
                    P["p"].append(p)
                    idx[key(name)] = p
                p["t"] = max(p["t"], season)
                p["tm"] = tn
                cur["rows"].append([gid, p["i"], tn] + x)
            known.add(gid)
            added += 1
            time.sleep(0.5)
        if not complete:
            break
        last = date
    cur["meta"]["through"] = f"{last[:4]}-{last[4:6]}-{last[6:]}"
    cur["meta"]["built"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")
    # leaders + saison en cours
    L = json.load(open(f"{D}/leaders.json"))
    S = json.load(open(f"{D}/seasons.json"))
    games = {}
    for r in cur["rows"]:
        games.setdefault(r[0], []).append(r)
    cnt, agg = {}, {}
    for rs in games.values():
        mx = [max(x[i] for x in rs) for i in (4, 5, 6, 7, 8)] + [max(-x[8] for x in rs)]
        for x in rs:
            c = cnt.setdefault(x[1], [0, 0, 0, 0, 0, 0, 0])
            c[0] += 1
            for j, v in enumerate((x[4], x[5], x[6], x[7], x[8], -x[8])):
                if v == mx[j]:
                    c[j + 1] += 1
            a = agg.setdefault((x[1], x[2]), [0, 0, 0, 0, 0, 0, 0])
            a[0] += 1
            for j, i in enumerate((3, 4, 5, 6, 7, 8)):
                a[j + 1] += x[i]
    for pid, c in cnt.items():
        L.setdefault(str(pid), {})[str(season)] = c
    for (pid, team), a in agg.items():
        lst = S.setdefault(str(pid), [])
        row = next((r for r in lst if r[0] == season and r[1] == team), None)
        vals = [round(a[i] / a[0], 1) for i in range(1, 7)]
        if row is None:
            lst.append([season, team, a[0], vals[0], vals[1], vals[2], vals[3], None, None, vals[4], vals[5], None, None, None])
        else:
            row[2], row[3], row[4], row[5], row[6], row[9], row[10] = a[0], vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]
    for n, o in (("current.json", cur), ("players.json", P), ("leaders.json", L), ("seasons.json", S)):
        json.dump(o, open(f"{D}/{n}", "w"), separators=(",", ":"), ensure_ascii=False)
    print(json.dumps({"nouveaux_matchs": added, "jusqu_au": cur["meta"]["through"]}))
    if src_error and added == 0:
        print("ECHEC : source ESPN injoignable ou format changé -> " + src_error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
