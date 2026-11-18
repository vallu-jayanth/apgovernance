# Kaggle notebook script: judge every proof photo with an open-source vision model on Kaggle's free GPUs.
#
# Setup (Kaggle): Notebook -> Accelerator "GPU T4 x2", Internet "On".
#   Add data -> your dataset containing photos.db (made locally with scripts/photos_db.py fetch).
#   Cell 1:  !pip install -q vllm==0.7.3
#   Cell 2:  paste this file and run. Output: /kaggle/working/results.db (download it, then locally:
#            python3 scripts/photos_db.py import results.db && python3 scripts/photos_db.py export)
#
# Resumable: Kaggle sessions stop after 12 h. Add the previous run's results.db as a second input;
# photos already judged there are skipped and copied forward.
# Untested on Kaggle yet: run the PILOT first (set PILOT = 50) and check the answers by eye.
import base64, glob, json, os, re, sqlite3, time
from vllm import LLM, SamplingParams

MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct'
PILOT = 50          # set to 0 for the full run
BATCH = 64
src = glob.glob('/kaggle/input/**/photos.db', recursive=True)[0]
prev = [p for p in glob.glob('/kaggle/input/**/results.db', recursive=True)]
OUT = '/kaggle/working/results.db'

out = sqlite3.connect(OUT)
out.execute('''CREATE TABLE IF NOT EXISTS checks (file TEXT, work TEXT, model TEXT, matches TEXT, shows TEXT,
  screen INTEGER, blank INTEGER, stamp TEXT, raw TEXT, checked TEXT, PRIMARY KEY (file, work, model))''')
for p in prev:
    out.execute('ATTACH ? AS prev', (p,)); out.execute('INSERT OR IGNORE INTO checks SELECT * FROM prev.checks'); out.commit(); out.execute('DETACH prev')

con = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
done = {(f, w) for f, w in out.execute('SELECT file, work FROM checks')}
# one question per (work, distinct image): identical images reused within a work are judged once
rows = con.execute('''SELECT p.file, p.work, p.work_name, p.stage, i.small, i.sha256 FROM photos p
  JOIN images i ON i.file = p.file WHERE i.small IS NOT NULL GROUP BY p.work, i.sha256''').fetchall()
todo = [r for r in rows if (r[0], r[1]) not in done]
if PILOT: todo = todo[:PILOT]
print(len(rows), 'photo/work pairs,', len(todo), 'to check', flush=True)

PROMPT = """This photo was uploaded by a village panchayat in Andhra Pradesh, India, as proof for a public work.
Work: "{name}". Stage claimed: "{stage}".
Look only at the photo. Reply with JSON only, no other text:
{{"shows": "<what the photo actually shows, max 12 words>",
 "matches": "yes" | "no" | "unclear",   // does it plausibly show this work at this stage?
 "screen": true | false,                // is it a photo of a screen, printout or another photo?
 "blank": true | false,                 // blank, black, fully blurred or unusable?
 "stamp": "<date and place text printed on the photo, or empty>"}}"""

llm = LLM(model=MODEL, tensor_parallel_size=2, dtype='half', max_model_len=4096,
          limit_mm_per_prompt={'image': 1}, gpu_memory_utilization=0.9)
params = SamplingParams(temperature=0, max_tokens=160)

def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    try: j = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError: j = {}
    yn = lambda v: 1 if v is True or str(v).lower() == 'true' else 0
    matches = str(j.get('matches', 'unclear')).lower()
    return (matches if matches in ('yes', 'no', 'unclear') else 'unclear', str(j.get('shows', ''))[:120], yn(j.get('screen')), yn(j.get('blank')), str(j.get('stamp', ''))[:120])

assert parse('x {"shows":"a drain","matches":"no","screen":false,"blank":"true","stamp":""}') == ('no', 'a drain', 0, 1, '')

t0 = time.time()
for b in range(0, len(todo), BATCH):
    chunk = todo[b:b + BATCH]
    convs = [[{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(r[4]).decode()}},
        {'type': 'text', 'text': PROMPT.format(name=r[2], stage=r[3])}]}] for r in chunk]
    res = llm.chat(convs, params, use_tqdm=False)
    now = time.strftime('%Y-%m-%d %H:%M')
    out.executemany('INSERT OR REPLACE INTO checks VALUES (?,?,?,?,?,?,?,?,?,?)',
                    [(r[0], r[1], MODEL, *parse(o.outputs[0].text), o.outputs[0].text, now) for r, o in zip(chunk, res)])
    out.commit()
    n = b + len(chunk); print(f'{n}/{len(todo)}  {n / (time.time() - t0):.1f} photos/s', flush=True)

for row in out.execute("SELECT matches, COUNT(*) FROM checks GROUP BY matches"): print(row)
if PILOT:
    for row in out.execute('SELECT c.work, c.matches, c.shows, c.screen, c.blank FROM checks c LIMIT 50'): print(row)
