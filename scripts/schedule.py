# Bodega Stats - calendrier NBA (Basketball-Reference). Usage: python3 schedule.py <in.json> <out.json>
# Lit le calendrier actuel (in), recharge les mois a venir, ecrit out (meme format) et imprime un resume JSON.
import sys, json, re, html, time, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
M={'Atlanta Hawks':'Hawks','Boston Celtics':'Celtics','Brooklyn Nets':'Nets','Charlotte Hornets':'Hornets','Chicago Bulls':'Bulls','Cleveland Cavaliers':'Cavaliers','Detroit Pistons':'Pistons','Indiana Pacers':'Pacers','Miami Heat':'Heat','Milwaukee Bucks':'Bucks','New York Knicks':'Knicks','Orlando Magic':'Magic','Philadelphia 76ers':'76ers','Toronto Raptors':'Raptors','Washington Wizards':'Wizards','Dallas Mavericks':'Mavericks','Denver Nuggets':'Nuggets','Golden State Warriors':'Warriors','Houston Rockets':'Rockets','Los Angeles Clippers':'Clippers','LA Clippers':'Clippers','Los Angeles Lakers':'Lakers','Memphis Grizzlies':'Grizzlies','Minnesota Timberwolves':'Timberwolves','New Orleans Pelicans':'Pelicans','Oklahoma City Thunder':'Thunder','Phoenix Suns':'Suns','Portland Trail Blazers':'Trail Blazers','Sacramento Kings':'Kings','San Antonio Spurs':'Spurs','Utah Jazz':'Jazz'}
NAMES=['october','november','december','january','february','march','april','may','june']
ET=ZoneInfo('America/New_York')
src,dst=sys.argv[1],sys.argv[2]
try: old=json.load(open(src)).get('games',[])
except Exception: old=[]
today=dt.datetime.now(ET).date()
season=today.year+1 if today.month>=8 else today.year
def months():
    y,m=today.year,today.month
    out=[]
    while True:
        out.append((y,m))
        if (m==6): break
        m+=1
        if m==13: y,m=y+1,1
        if len(out)>9: break
    return [x for x in out if x[1] in (10,11,12,1,2,3,4,5,6)]
def parse(s):
    res=[]
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>',s,re.S):
        d=re.search(r'data-stat="date_game"[^>]*csk="(\d{8})',tr)
        v=re.search(r'data-stat="visitor_team_name"[^>]*>(?:<a[^>]*>)?([^<]+)',tr)
        h=re.search(r'data-stat="home_team_name"[^>]*>(?:<a[^>]*>)?([^<]+)',tr)
        t=re.search(r'data-stat="game_start_time"[^>]*>([^<]*)',tr)
        if not(d and v and h): continue
        a,hh=html.unescape(v.group(1)).strip(),html.unescape(h.group(1)).strip()
        if a not in M or hh not in M: continue
        ds=d.group(1); y,mo,da=int(ds[:4]),int(ds[4:6]),int(ds[6:8])
        tt=(t.group(1) if t else '').strip(); u=''
        mm=re.match(r'(\d{1,2}):(\d{2})([ap])',tt)
        if mm:
            hr=int(mm.group(1))%12+(12 if mm.group(3)=='p' else 0)
            u=dt.datetime(y,mo,da,hr,int(mm.group(2)),tzinfo=ET).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        res.append(['%04d-%02d-%02d'%(y,mo,da),M[a],M[hh],u])
    return res
ok,fail,new=[],[],{}
for i,(y,m) in enumerate(months()):
    url='https://www.basketball-reference.com/leagues/NBA_%d_games-%s.html'%(season,NAMES[[10,11,12,1,2,3,4,5,6].index(m)])
    try:
        if i: time.sleep(4)
        with urllib.request.urlopen(url,timeout=30) as r: s=r.read().decode('utf8','ignore')
        g=parse(s); new[(y,m)]=g; ok.append('%d-%02d:%d'%(y,m,len(g)))
    except Exception as e:
        if getattr(e,'code',None)==404: new[(y,m)]=[]; ok.append('%d-%02d:0'%(y,m))
        else: fail.append('%d-%02d:%s'%(y,m,str(e)[:60]))
games=[]
for g in old:
    k=(int(g[0][:4]),int(g[0][5:7]))
    if k not in new: games.append(g)
for v in new.values(): games+=v
cut=(today-dt.timedelta(days=1)).isoformat()
games=sorted({(g[0],g[1],g[2]):g for g in games if g[0]>=cut}.values())
changed=[[g[0],g[1],g[2]] for g in games]!=[[g[0],g[1],g[2]] for g in old if g[0]>=cut] or any(a!=b for a,b in zip(games,[g for g in old if g[0]>=cut]))
if not ok:
    print(json.dumps({'mois_ok':ok,'mois_erreur':fail,'echec_total':True})); sys.exit(1)
json.dump({'games':games,'source':'basketball-reference.com','updatedAt':dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},open(dst,'w'),separators=(',',':'))
print(json.dumps({'mois_ok':ok,'mois_erreur':fail,'matchs':len(games),'change':bool(changed),'echec_total':not ok}))
