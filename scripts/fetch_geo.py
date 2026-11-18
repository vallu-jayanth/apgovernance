"""Download geo-tagged works (activity, cost, stage, lat/long, photo file) for every AP gram panchayat that has any.
Usage: fetch_geo.py <gp.csv from fetch_gp.py> <plan year start, e.g. 2025> <out dir>  -> <out>/<district>.json"""
import csv, json, os, re, sys, html, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
GP_CSV, YEAR, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
cell = lambda c: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip()
def fetch(code):
    url = f"https://egramswaraj.gov.in/geotaggedDetailsforgpdp.do?year={YEAR}&gpcode={code}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
                t = r.read().decode('utf-8', 'replace')
            break
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        return code, None
    i = t.find('Activity Code')
    if i < 0: return code, []
    seg = t[t.rfind('<table', 0, i): t.find('</table>', i)]
    out = []
    for row in re.findall(r'<tr.*?</tr>', seg, flags=re.S)[1:]:
        cs = re.findall(r'<td[^>]*>(.*?)</td>', row, flags=re.S)
        if len(cs) < 8: continue
        photo = cell(cs[6])
        lat = re.search(r'latitude\s*:\s*([-\d.]+)', photo, re.I); lon = re.search(r'Longitude\s*:\s*([-\d.]+)', photo, re.I)
        img = re.search(r'imgId=([^"\s]+)', row)
        out.append({"a": cell(cs[1]), "n": cell(cs[2]), "c": float(cell(cs[3]) or 0), "as": cell(cs[4]), "s": cell(cs[5]),
                    "lat": float(lat.group(1)) if lat else None, "lon": float(lon.group(1)) if lon else None,
                    "f": img.group(1) if img else "", "d": cell(cs[7])[:10]})
    seen, uniq = set(), []
    for w in out:
        k = (w['a'], w['as'], w['s'], w['f'])
        if k not in seen: seen.add(k); uniq.append(w)
    return code, uniq
gps = [r for r in csv.DictReader(open(GP_CSV)) if int(r['geotagged_assets']) > 0]
by_d, failed = {}, []
with ThreadPoolExecutor(4) as ex:
    for n, (code, works) in enumerate(ex.map(fetch, [g['gp_code'] for g in gps])):
        if works is None: failed.append(code); continue
        g = gps[n]; by_d.setdefault(g['district'], {})[code] = works
        if n % 500 == 0: print(n, len(gps), file=sys.stderr, flush=True)
for d, m in by_d.items():
    json.dump(m, open(os.path.join(OUT, re.sub(r'[^A-Za-z]+', '_', d).strip('_').lower() + '.json'), 'w'), separators=(',', ':'))
total = sum(len(w) for m in by_d.values() for w in m.values())
print(f"{len(gps)} GPs, {total} works, {len(failed)} failed", file=sys.stderr)
assert len(failed) < len(gps) * 0.05, f"too many failures: {len(failed)}"
