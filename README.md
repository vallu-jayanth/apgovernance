# AP Public Finance Watch

A public website that explains Andhra Pradesh's public money in plain words:

- **State money**: budget vs actual and the auditors' findings (CAG / Accountant General), explained simply.
- **Your panchayat**: 15th Finance Commission grants for all 13,327 gram panchayats, and every geo-tagged work with its photos, GPS location and photo-proof flags.
- **Check vouchers**: citizens load their panchayat's monthly Cash Book (Excel from eGramSwaraj) and see every payment, with unusual ones flagged and matched to photo proof. The file never leaves their device.

It is a static site: `docs/` is everything that gets published. No server or database is needed.

## Folder layout

| Path | What it is |
|---|---|
| `docs/` | The website. `index.html` plus `data/` (state figures, panchayat grants) and `geo/` (photo-proof data per district). |
| `src/template.html` | The page design and app code. Edit this, then rebuild. |
| `src/core.js` | Cash book parser and all flagging rules (vouchers and photos). |
| `src/test_core.js` | Self-check: `cd src && node test_core.js "$PWD/sample_cashbook_rows.json"` |
| `scripts/fetch_gp.py` | Downloads grants for every panchayat from eGramSwaraj. |
| `scripts/fetch_geo.py` | Downloads geo-tagged works (photos, GPS, stage) for every panchayat. |
| `scripts/build_site.py` | Builds `docs/index.html` from `src/`. |
| `scripts/refresh.sh` | Runs both downloads, then rebuilds. About 20 minutes. |
| `docs/data/state.json` | State-level figures and plain-language findings. Update by hand when a new CAG report or Accounts at a Glance is published. |
| `.github/workflows/refresh.yml` | Runs `refresh.sh` every Monday on GitHub and publishes the new data. |

Python 3 (standard library only) is all the scripts need.

## Preview on your computer

```
python3 scripts/build_site.py
python3 -m http.server 8000 --directory docs
```

Then open http://localhost:8000.

## Make it public

### Option 1: GitHub Pages (free, updates itself every week) — recommended

1. Create a free account at github.com and a new **public** repository, e.g. `apgovernance`.
2. Upload this folder to it. Easiest: install GitHub Desktop, choose *Add existing repository* → this folder → *Publish repository*.
   Or from Terminal, inside this folder:
   ```
   git init && git add . && git commit -m "First version"
   git branch -M main
   git remote add origin https://github.com/<your-username>/apgovernance.git
   git push -u origin main
   ```
3. On GitHub: repository **Settings → Pages → Build and deployment → Deploy from a branch**, branch `main`, folder `/docs`, Save.
4. After a minute the site is live at `https://<your-username>.github.io/apgovernance/`.
5. **Settings → Actions → General → Workflow permissions → Read and write**, so the weekly refresh can save new data. Run it once by hand from the **Actions** tab → *Weekly data refresh* → *Run workflow*.

If the Action fails at the download step, eGramSwaraj may be blocking servers outside India. Then run `sh scripts/refresh.sh` on your own computer each week and push (`git add docs && git commit -m "Data refresh" && git push`).

**Your own domain** (e.g. `apgovernance.in`): buy it from any registrar, then in **Settings → Pages → Custom domain** enter it and follow the DNS instructions GitHub shows.

### Option 2: Netlify Drop (one minute, no account needed to start)

Go to https://app.netlify.com/drop and drag the `docs` folder onto the page. You get a public link at once. It does not update itself: drag the folder again after each refresh.

### Option 3: Cloudflare Pages

Connect the GitHub repository from Option 1 at https://pages.cloudflare.com, set the output directory to `docs`, no build command. Faster in India and free.

## Checking the photos (free, open-source vision model on Kaggle)

All photo data lives in one local SQLite file, `data/photos.db` (not committed; about 2 GB when full).
It stores every proof photo's details, a small 448px copy of each image (about 20 KB instead of 220 KB),
its fingerprint (sha256), and the model's verdicts, with indexes for fast lookups.

1. `python3 scripts/photos_db.py index` — list every photo from `docs/geo/`.
2. `python3 scripts/photos_db.py fetch` — download and shrink all photos (about 3 hours; safe to stop and rerun).
   Add `--district visakhapatanam` or `--gp 211758` to do part of it.
3. `python3 scripts/photos_db.py export` — finds identical pictures reused for different works (no AI needed)
   and writes `docs/checks/<district>.json`, which the site shows on each work.
4. Vision check on Kaggle's free GPUs:
   - Upload `data/photos.db` as a private Kaggle dataset.
   - New notebook, Accelerator **GPU T4 x2**, Internet **On**, add the dataset.
   - Import `kaggle/vlm_check.ipynb` (File → Import Notebook); it uses Hugging Face transformers, already on Kaggle.
   - Run with `PILOT = 50` first and check the answers; then `PILOT = 0` for everything.
     A session stops after 12 hours: add the last `results.db` as an input and run again to continue.
   - Download `results.db`, then `python3 scripts/photos_db.py import results.db && python3 scripts/photos_db.py export`, commit and push.
5. `python3 scripts/photos_db.py stats` shows progress.

The model (Qwen2.5-VL-7B) says what each photo shows, whether it matches the work and stage, whether it is
a photo of a screen or paper, whether it is blank, and reads the date/place stamp. Its answers can be wrong:
the site labels them as model reviews, and a person should open the photo before raising it publicly.

## Updating the state figures

When the CAG publishes a newer State Finances Audit Report or the Accountant General publishes a newer *Accounts at a Glance*, edit `docs/data/state.json` (numbers are in ₹ crore; keep every explanation in plain words and cite the source), then commit.

## Ground rules for the site

- Only official records are used, and every figure links to its source.
- No individual is named. Flags are reasons to ask questions, not findings of wrongdoing.
