# Kaggle notebook script: judge every proof photo with an open-source vision model on Kaggle's free GPUs.
#
# Setup (Kaggle): Notebook -> Accelerator "GPU T4 x2", Internet "On".
#   Add data -> your dataset containing photos.db (or kaggle/pilot.db for a first test).
#   Cell 1:  !pip install -q "transformers>=4.49" accelerate   (usually already satisfied on Kaggle)
#   Cell 2:  paste this file and run. Output: /kaggle/working/results.db (download it, then locally:
#            python3 scripts/photos_db.py import results.db && python3 scripts/photos_db.py export)
#
# Resumable: Kaggle sessions stop after 12 h. Add the previous run's results.db as a second input;
# photos already judged there are skipped and copied forward.
# Untested on Kaggle yet: run kaggle/pilot.db first and check the answers by eye.
import glob, io, json, os, re, sqlite3, time
import torch
from PIL import Image
from transformers import AutoProcessor
try:
    from transformers import Qwen2_5_VLForConditionalGeneration as VLM
except ImportError:  # newer transformers releases
    from transformers import AutoModelForImageTextToText as VLM

GPUS = torch.cuda.device_count()
# 7B needs two T4s; on a single GPU fall back to the 3B model
MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct' if GPUS >= 2 else 'Qwen/Qwen2.5-VL-3B-Instruct'
PILOT = 0           # >0 limits the run to that many photos
BATCH = 8
src = (glob.glob('/kaggle/input/**/photos.db', recursive=True) + glob.glob('/kaggle/input/**/pilot.db', recursive=True))[0]
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

PROMPT = """This photo was uploaded by a village panchayat in Andhra Pradesh, India, as proof for a public work: "{name}".
Ignore any stage label; judge only whether the photo relates to this kind of work.
Reply with JSON only, no other text:
{{"shows": "<what the photo actually shows, max 12 words>",
 "matches": "yes" | "no" | "unclear",
 "screen": true | false,
 "blank": true | false,
 "stamp": "<date and place text printed on the photo, or empty>"}}
Rules for "matches":
- "yes": the photo plausibly shows this type of work, its site or its materials (a pipe, trench or tap for a pipeline;
  a road surface for a road; a light or pole for street lights; a drain or channel for drainage; bins, carts or waste for waste management).
- "no": it clearly shows something unrelated to this work (street lights for sanitation kits, pipes for waste management, a blank wall for a road).
- "unclear": you cannot tell.
"screen": true only if the photo is clearly of a screen, a printout or another photo (visible bezel, paper edge, moire, a second stamp).
"blank": true if the photo is blank, black, covered or so blurred nothing can be seen."""

# T4 has no bfloat16: use float16; device_map spreads the 7B model over both GPUs
model = VLM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map='auto').eval()
processor = AutoProcessor.from_pretrained(MODEL, min_pixels=64 * 28 * 28, max_pixels=448 * 448)
processor.tokenizer.padding_side = 'left'  # required for batched generation

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
    texts = [processor.apply_chat_template([{'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': PROMPT.format(name=r[2])}]}],
                                           tokenize=False, add_generation_prompt=True) for r in chunk]
    images = [Image.open(io.BytesIO(r[4])).convert('RGB') for r in chunk]
    inputs = processor(text=texts, images=images, padding=True, return_tensors='pt').to(model.device)
    with torch.no_grad():
        gen = model.generate(**inputs, max_new_tokens=160, do_sample=False)
    res = processor.batch_decode(gen[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)
    now = time.strftime('%Y-%m-%d %H:%M')
    out.executemany('INSERT OR REPLACE INTO checks VALUES (?,?,?,?,?,?,?,?,?,?)',
                    [(r[0], r[1], MODEL, *parse(o), o, now) for r, o in zip(chunk, res)])
    out.commit()
    n = b + len(chunk); print(f'{n}/{len(todo)}  {n / (time.time() - t0):.1f} photos/s', flush=True)

for row in out.execute("SELECT matches, COUNT(*) FROM checks GROUP BY matches"): print(row)
for row in out.execute('SELECT work, matches, screen, blank, shows FROM checks ORDER BY matches LIMIT 200'): print(row)
