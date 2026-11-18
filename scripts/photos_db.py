"""Photo-proof database (SQLite, one file: data/photos.db). Standard library only.

  python3 scripts/photos_db.py index                 # load every geo-tagged photo from docs/geo/*.json
  python3 scripts/photos_db.py fetch [--district X | --gp CODE] [--limit N]
                                                     # download photos, store a small copy + sha256 (resumable)
  python3 scripts/photos_db.py import results.db     # merge model results produced on Kaggle
  python3 scripts/photos_db.py export                # write docs/checks/<district>.json for the website
  python3 scripts/photos_db.py stats

Images are kept only as small (448px) JPEGs inside the DB (macOS `sips` does the resize), so the
originals never need to be stored; eGramSwaraj keeps hosting them.
"""
import glob, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'photos.db')
PHOTO_URL = 'https://egramswaraj.gov.in/getMactionPhoto.do?imgId='
SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (      -- one row per photo listed as proof for a work
  gp_code TEXT, district TEXT, work TEXT, work_name TEXT, cost REAL, asset TEXT, stage TEXT,
  uploaded TEXT, lat REAL, lon REAL, file TEXT,
  PRIMARY KEY (gp_code, work, asset, stage, file));
CREATE TABLE IF NOT EXISTS images (      -- one row per distinct photo file
  file TEXT PRIMARY KEY, sha256 TEXT, bytes INTEGER, small BLOB, fetched TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS checks (      -- one row per (photo, work) judged by a vision model
  file TEXT, work TEXT, model TEXT, matches TEXT, shows TEXT, screen INTEGER, blank INTEGER,
  stamp TEXT, raw TEXT, checked TEXT, PRIMARY KEY (file, work, model));
CREATE INDEX IF NOT EXISTS photos_gp ON photos(gp_code);
CREATE INDEX IF NOT EXISTS photos_file ON photos(file);
CREATE INDEX IF NOT EXISTS images_sha ON images(sha256);
CREATE INDEX IF NOT EXISTS checks_matches ON checks(matches);
"""

def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c

def index():
    c = db(); n = 0
    for path in glob.glob(os.path.join(ROOT, 'docs', 'geo', '*.json')):
        district = os.path.basename(path)[:-5]
        for gp, works in json.load(open(path)).items():
            rows = [(gp, district, w['a'], w['n'], w['c'], w.get('as', ''), w['s'], w['d'], w['lat'], w['lon'], w['f']) for w in works if w['f']]
            c.executemany('INSERT OR IGNORE INTO photos VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows); n += len(rows)
    c.commit()
    print(n, 'photo rows indexed;', c.execute('SELECT COUNT(DISTINCT file) FROM photos').fetchone()[0], 'distinct files')

def _download(file):
    try:
        with urllib.request.urlopen(urllib.request.Request(PHOTO_URL + file, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60) as r:
            data = r.read()
        if len(data) < 500: return file, None, 'too small: %d bytes' % len(data)
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as t: t.write(data)
        out = t.name + '.s.jpg'
        # shortcut: sips is macOS-only; on Linux replace with Pillow's thumbnail()
        subprocess.run(['sips', '-Z', '448', '-s', 'format', 'jpeg', '-s', 'formatOptions', '50', t.name, '--out', out], capture_output=True, check=True)
        small = open(out, 'rb').read(); os.unlink(t.name); os.unlink(out)
        return file, (hashlib.sha256(data).hexdigest(), len(data), small), None
    except Exception as e:
        return file, None, str(e)[:200]

def fetch(district=None, limit=None, gp=None):
    c = db()
    q = 'SELECT DISTINCT p.file FROM photos p LEFT JOIN images i ON i.file = p.file WHERE i.sha256 IS NULL'  # includes earlier failures
    args = []
    if district: q += ' AND p.district = ?'; args.append(district)
    if gp: q += ' AND p.gp_code = ?'; args.append(gp)
    todo = [r[0] for r in c.execute(q + (' LIMIT %d' % limit if limit else ''), args)]
    print(len(todo), 'photos to fetch', flush=True)
    now = time.strftime('%Y-%m-%d %H:%M')
    with ThreadPoolExecutor(4) as ex:  # 4 at a time keeps load on the government server modest
        for n, (file, got, err) in enumerate(ex.map(_download, todo), 1):
            c.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?)',
                      (file, got[0] if got else None, got[1] if got else None, got[2] if got else None, now, err))
            if n % 200 == 0: c.commit(); print(n, flush=True)
    c.commit(); stats()

def import_results(path):
    c = db(); c.execute('ATTACH ? AS r', (path,))
    n = c.execute('INSERT OR REPLACE INTO checks SELECT * FROM r.checks').rowcount
    c.commit(); print(n, 'results imported')

def export():
    """Per district: {gp_code: {work: [flags]}} for the site. Same-image reuse needs no model."""
    c = db(); out = {}
    # identical image (same sha256) used as proof for more than one work in the same panchayat
    for gp, district, work, n in c.execute('''
        SELECT p.gp_code, p.district, p.work, COUNT(DISTINCT p2.work) FROM photos p
        JOIN images i ON i.file = p.file JOIN images i2 ON i2.sha256 = i.sha256
        JOIN photos p2 ON p2.file = i2.file AND p2.gp_code = p.gp_code AND p2.work != p.work
        WHERE i.sha256 IS NOT NULL GROUP BY p.gp_code, p.work'''):
        out.setdefault(district, {}).setdefault(gp, {}).setdefault(work, []).append(
            {'level': 'high', 'rule': 'Same picture, different works', 'text': f'An identical photo is also uploaded as proof for {n} other work{"s" if n > 1 else ""} in this panchayat.'})
    for gp, district, work, matches, shows, screen, blank, model in c.execute('''
        SELECT p.gp_code, p.district, p.work, k.matches, k.shows, k.screen, k.blank, k.model
        FROM checks k JOIN photos p ON p.file = k.file AND p.work = k.work'''):
        f = out.setdefault(district, {}).setdefault(gp, {}).setdefault(work, []); model = model.split(' |')[0].split('/')[-1]
        if blank: f.append({'level': 'high', 'rule': 'Blank or unusable photo', 'text': f'The proof photo is blank or unreadable ({model}).'})
        elif matches == 'no': f.append({'level': 'high', 'rule': "Photo doesn't show this work", 'text': f'The photo shows {shows} ({model}). Ask to see the work itself.'})
        if screen: f.append({'level': 'medium', 'rule': 'Photo of a screen or printout', 'text': f'The proof looks like a photo taken of a screen or paper, not of the site ({model}).'})
    os.makedirs(os.path.join(ROOT, 'docs', 'checks'), exist_ok=True)
    for district, m in out.items():
        for gp in m:  # drop repeated flags from multiple photos of one work
            for w in m[gp]: m[gp][w] = list({(x['rule'], x['text']): x for x in m[gp][w]}.values())
        json.dump(m, open(os.path.join(ROOT, 'docs', 'checks', district + '.json'), 'w'), separators=(',', ':'))
    print('exported', sum(len(w) for m in out.values() for w in m.values()), 'flagged works')

def stats():
    c = db()
    for label, q in [('photo rows', 'SELECT COUNT(*) FROM photos'), ('distinct files', 'SELECT COUNT(DISTINCT file) FROM photos'),
                     ('fetched', 'SELECT COUNT(*) FROM images WHERE sha256 IS NOT NULL'), ('fetch errors', 'SELECT COUNT(*) FROM images WHERE error IS NOT NULL'),
                     ('model checks', 'SELECT COUNT(*) FROM checks'), ('db MB', "SELECT page_count*page_size/1048576 FROM pragma_page_count(), pragma_page_size()")]:
        print(f'{label:15} {c.execute(q).fetchone()[0]}')

if __name__ == '__main__':
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else 'stats'), sys.argv[2:]
    opt = lambda k: rest[rest.index(k) + 1] if k in rest else None
    if cmd == 'index': index()
    elif cmd == 'fetch': fetch(opt('--district'), int(opt('--limit')) if opt('--limit') else None, opt('--gp'))
    elif cmd == 'import': import_results(rest[0])
    elif cmd == 'export': export()
    else: stats()
