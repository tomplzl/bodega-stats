"""Bodega Stats - news : blessures (rapport officiel), transactions (officiel NBA), rotations (box scores).
Usage: python3 -I news.py DBDIR OUTDIR
DBDIR contient (s'ils existent) current.json, feed.json, state.json : les champs des documents
injuries/current, injuries/feed et news/state. Écrit dans OUTDIR les mêmes fichiers mis à jour,
plus changed.txt (liste des documents à réécrire) et un résumé JSON sur stdout."""
import sys, json, os, re, io, time, datetime, urllib.request, unicodedata
NM = lambda s: unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().strip()
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/"}
NOW = datetime.datetime.now(datetime.timezone.utc)
NOWS = NOW.isoformat(timespec="seconds")


def get(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def load(d, n):
    p = os.path.join(d, n)
    return json.load(open(p)) if os.path.exists(p) else {}


# ---------------- injuries ----------------
INJ = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf"
COLS = {"date": 23, "time": 120, "matchup": 200, "team": 264, "player": 425, "status": 586, "reason": 666}


def inj_latest():
    t = datetime.datetime.now(ET)
    t = t.replace(minute=0 if t.minute < 30 else 30, second=0, microsecond=0)
    for _ in range(60):
        url = INJ.format(d=t.strftime("%Y-%m-%d"), t=t.strftime("%I_%M%p"))
        try:
            return url, t, get(url)
        except Exception:
            t -= datetime.timedelta(minutes=30)
    return None, None, None


def inj_parse(pdf_bytes):
    import pdfplumber
    rows, not_sub = [], []
    cur = {"date": None, "time": None, "matchup": None, "team": None}
    col = lambda x: max((k for k, x0 in COLS.items() if x >= x0 - 4), key=lambda k: COLS[k], default=None)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            lines = {}
            for w in page.extract_words():
                if w["top"] < 115 or w["text"].startswith("Page"):
                    continue
                lines.setdefault(round(w["top"]), []).append(w)
            anchors, reasons = [], []
            for top in sorted(lines):
                cells = {}
                for w in sorted(lines[top], key=lambda w: w["x0"]):
                    c = col(w["x0"])
                    cells[c] = (cells.get(c, "") + " " + w["text"]).strip()
                for k in ("date", "time", "matchup"):
                    if k in cells:
                        cur[k] = cells[k]
                if "team" in cells:
                    cur["team"] = cells["team"]
                if cells.get("reason", "").upper().startswith("NOTYETSUBMITTED") and "player" not in cells:
                    not_sub.append({"team": cur["team"], "matchup": cur["matchup"], "date": cur["date"]})
                    continue
                if "player" in cells and "status" in cells:
                    anchors.append(dict(top=top, team=cur["team"], matchup=cur["matchup"], date=cur["date"], time=cur["time"], player=cells["player"], status=cells["status"], reason=[]))
                    if "reason" in cells:
                        reasons.append((top, cells["reason"]))
                elif "reason" in cells:
                    reasons.append((top, cells["reason"]))
            for top, txt in reasons:
                if anchors:
                    min(anchors, key=lambda a: (abs(a["top"] - top), a["top"]))["reason"].append((top, txt))
            for a in anchors:
                a["reason"] = " ".join(t for _, t in sorted(a["reason"]))
                rows.append(a)
    return rows, not_sub


def tidy_reason(r):
    r = r.replace("Injury/Illness-", "").replace("Injury/Illness", "").replace("GLeague-", "G League · ")
    r = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", r)
    r = r.replace("G League · On Assignment", "G League (assignment)").replace("G League · Two- Way", "G League (two-way)").replace("G League · Two-Way", "G League (two-way)")
    r = re.sub(r"\s*;\s*", " · ", r).strip(" -")
    return r[:1].upper() + r[1:] if r else ""


def do_injuries(prev_cur, feed):
    url, t, pdf = inj_latest()
    if not pdf:
        return prev_cur, False, "rapport introuvable"
    if prev_cur.get("report") == t.isoformat():
        return prev_cur, False, "rapport inchangé"
    rows, not_sub = inj_parse(pdf)
    R = [[r["team"], r["matchup"], r["date"], r["time"], r["player"], r["status"], tidy_reason(r["reason"])] for r in rows if r["team"]]
    old = {(x[0], x[4], x[2]): x for x in prev_cur.get("rows", [])}
    if prev_cur:
        for x in R:
            o = old.get((x[0], x[4], x[2]))
            if o is None or o[5] != x[5]:
                feed.append({"kind": "inj", "at": NOWS, "team": x[0], "player": x[4], "from": o[5] if o else None, "to": x[5], "reason": x[6], "matchup": x[1], "date": x[2]})
    return {"at": NOWS, "report": t.isoformat(), "url": url, "rows": R, "notSubmitted": not_sub}, True, f"{len(R)} joueurs"


# ---------------- transactions ----------------
TXFR = {"Trade": "Trade", "Signing": "Signing", "Waive": "Waived", "ContractConverted": "Contract converted", "AwardOnWaivers": "Claimed off waivers"}


def do_transactions(state, feed):
    rows = json.loads(get("https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"))["NBA_Player_Movement"]["rows"]
    seen = set(state.get("txSeen", []))
    first = not seen
    since = (NOW - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    new = 0
    for x in sorted(rows, key=lambda x: x["TRANSACTION_DATE"]):
        key = f'{x["TRANSACTION_DATE"][:10]}|{x["GroupSort"]}|{x.get("PLAYER_ID")}'
        if x["TRANSACTION_DATE"][:10] < since or key in seen:
            continue
        seen.add(key)
        if first and x["TRANSACTION_DATE"][:10] < (NOW - datetime.timedelta(days=4)).strftime("%Y-%m-%d"):
            continue  # premier passage : seulement les 4 derniers jours dans le fil
        feed.append({"kind": "tx", "at": x["TRANSACTION_DATE"][:10] + "T12:00:00+00:00", "type": TXFR.get(x["Transaction_Type"], x["Transaction_Type"]),
                     "team": (x.get("TEAM_SLUG") or "").replace("-", " ").title(), "pid": int(x["PLAYER_ID"]) if x.get("PLAYER_ID") else None, "text": x["TRANSACTION_DESCRIPTION"]})
        new += 1
    state["txSeen"] = sorted(seen)[-400:]
    return new


# ---------------- rotations (box scores Basketball-Reference) ----------------
BR = "https://www.basketball-reference.com"
TEAMS = {"ATL": "Hawks", "BOS": "Celtics", "BRK": "Nets", "CHO": "Hornets", "CHI": "Bulls", "CLE": "Cavaliers", "DET": "Pistons", "IND": "Pacers", "MIA": "Heat", "MIL": "Bucks", "NYK": "Knicks", "ORL": "Magic", "PHI": "76ers", "TOR": "Raptors", "WAS": "Wizards",
         "DAL": "Mavericks", "DEN": "Nuggets", "GSW": "Warriors", "HOU": "Rockets", "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIN": "Timberwolves", "NOP": "Pelicans", "OKC": "Thunder", "PHO": "Suns", "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "UTA": "Jazz"}


def br_box(path):
    html = get(BR + path).decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r'<table[^>]+id="box-([A-Z]{3})-game-basic".*?</table>', html, re.S):
        team, tb = m.group(1), m.group(0)
        body = tb.split("<tbody>", 1)[1]
        starters, rows, starter = [], [], True
        for tr in re.findall(r"<tr[^>]*>.*?</tr>", body, re.S):
            if 'class="thead"' in tr:
                starter = False
                continue
            nm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', tr)
            if not nm:
                continue
            name = NM(nm.group(1))
            mp = re.search(r'data-stat="mp"[^>]*>([\d:]+)<', tr)
            mins = 0.0
            if mp:
                v = mp.group(1)
                mins = int(v.split(":")[0]) + (int(v.split(":")[1]) / 60 if ":" in v else 0)
            dnp = 'data-stat="reason"' in tr
            rows.append((name, round(mins, 1), starter and not dnp, dnp))
            if starter and not dnp:
                starters.append(name)
        out[team] = {"starters": starters, "rows": rows}
    return out


def do_rotations(state, feed, injured_names):
    rot = state.setdefault("rot", {})
    last = state.get("boxLast", (NOW - datetime.timedelta(days=2)).strftime("%Y%m%d"))
    months = {(NOW - datetime.timedelta(days=d)).strftime("%B").lower() for d in (0, 2)}
    season = NOW.year + 1 if NOW.month >= 8 else NOW.year
    links = set()
    for mo in months:
        try:
            page = get(f"{BR}/leagues/NBA_{season}_games-{mo}.html").decode("utf-8", "replace")
            links |= set(re.findall(r'href="(/boxscores/(\d{8})0[A-Z]{3}\.html)"', page))
        except Exception:
            pass
    todo = sorted(l for l in links if l[1] > last)[:16]
    n = 0
    for path, d in todo:
        time.sleep(3.1)
        try:
            box = br_box(path)
        except Exception:
            continue
        for ab, t in box.items():
            name = TEAMS.get(ab, ab)
            st = rot.get(name, {"starters": [], "min": {}})
            mins = st.get("min", {})
            if st["starters"]:
                new_s = [p for p in t["starters"] if p not in st["starters"]]
                out_s = [p for p in st["starters"] if p not in t["starters"]]
                if new_s:
                    feed.append({"kind": "rot", "at": NOWS, "team": name, "date": d, "text": f"{name}: {', '.join(new_s)} started" + (f" (in place of {', '.join(out_s)})" if out_s else "")})
            for p, m, s, dnp in t["rows"]:
                hist = mins.get(p, [])
                avg = sum(hist) / len(hist) if hist else None
                if dnp and avg and avg >= 18 and len(hist) >= 3 and p.lower() not in injured_names:
                    feed.append({"kind": "rot", "at": NOWS, "team": name, "date": d, "text": f"{p} ({name}) did not play, no injury listed (averages {avg:.0f} min)"})
                elif avg is not None and len(hist) >= 3 and not dnp and m >= avg + 10 and m >= 24:
                    feed.append({"kind": "rot", "at": NOWS, "team": name, "date": d, "text": f"{p} ({name}): {m:.0f} min, well above his average ({avg:.0f})"})
                elif avg is not None and len(hist) >= 3 and not dnp and avg >= 24 and m <= avg - 12:
                    feed.append({"kind": "rot", "at": NOWS, "team": name, "date": d, "text": f"{p} ({name}): only {m:.0f} min (averages {avg:.0f})"})
                if not dnp:
                    mins[p] = (hist + [m])[-8:]
            rot[name] = {"starters": t["starters"], "min": mins}
        state["boxLast"] = d
        n += 1
    return n


def main():
    dbdir, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    cur, feedd, state = load(dbdir, "current.json"), load(dbdir, "feed.json"), load(dbdir, "state.json")
    feed = list(feedd.get("items", []))
    n0 = len(feed)
    summary, changed = {}, []
    try:
        cur2, ch, msg = do_injuries(cur, feed)
        summary["blessures"] = msg
        if ch:
            json.dump(cur2, open(f"{out}/current.json", "w"), ensure_ascii=False)
            changed.append("injuries/current")
        cur = cur2
    except Exception as e:
        summary["blessures"] = "erreur : " + str(e)[:120]
    try:
        summary["transactions"] = do_transactions(state, feed)
    except Exception as e:
        summary["transactions"] = "erreur : " + str(e)[:120]
    try:
        inj = {re.sub(r"[^a-z]", "", (r[4].split(",")[-1] + r[4].split(",")[0]).lower()) for r in cur.get("rows", [])}
        injn = set()
        for r in cur.get("rows", []):
            p = r[4].split(",")
            injn.add((p[-1] + " " + p[0]).lower())
        summary["box_scores"] = do_rotations(state, feed, injn)
    except Exception as e:
        summary["box_scores"] = "erreur : " + str(e)[:120]
    feed = sorted(feed, key=lambda x: x.get("at", ""))[-200:]
    if len(feed) != n0 or feed != feedd.get("items", []):
        json.dump({"items": feed, "at": NOWS}, open(f"{out}/feed.json", "w"), ensure_ascii=False)
        changed.append("injuries/feed")
    state["at"] = NOWS
    json.dump(state, open(f"{out}/state.json", "w"), ensure_ascii=False)
    changed.append("news/state")
    open(f"{out}/changed.txt", "w").write("\n".join(changed))
    summary["nouveaux_items"] = len(feed) - n0
    summary["a_ecrire"] = changed
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
