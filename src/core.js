// Parses an eGramSwaraj Cash Book export (rows as arrays) and flags unusual vouchers.
// Layout: receipts in columns 0-6, payments in 7-13; each voucher row is followed by
// "Classification: ..." and "Particulars: ..." rows on the same side.
const DATE = /^\d{2}\/\d{2}\/\d{4}$/;
const decode = (s) => String(s ?? '').replace(/#(\d\d)/g, (_, n) => String.fromCharCode(+n)).replace(/\s+/g, ' ').trim();
const num = (v) => (typeof v === 'number' ? v : parseFloat(String(v).replace(/,/g, '')) || 0);

function parseCashBook(rows) {
  const title = decode((rows[0] || [])[0]);
  const vouchers = [], totals = [];
  const last = {R: null, P: null};
  let block = {R: 0, P: 0};
  for (const r of rows) {
    for (const [side, o] of [['R', 0], ['P', 7]]) {
      const c0 = decode(r[o]);
      if (DATE.test(c0) && decode(r[o + 1])) {
        const cash = num(r[o + 3]), pd = num(r[o + 4]), bank = num(r[o + 5]), post = num(r[o + 6]);
        const v = {side, date: c0, voucher: decode(r[o + 1]), cheque: decode(r[o + 2]), cash, pd, bank, post,
          amount: cash + pd + bank + post, classification: '', head: '', particulars: ''};
        vouchers.push(v); last[side] = v; block[side] += v.amount;
      } else if (/^Classification:/i.test(c0) && last[side]) {
        const t = c0.replace(/^Classification:\s*/i, '');
        last[side].classification = t;
        const m = String(r[o]).split('\n')[1];
        last[side].head = m ? decode(m) : '';
      } else if (/^Particulars:/i.test(c0) && last[side]) {
        last[side].particulars = c0.replace(/^Particulars:\s*/i, '');
      } else if (c0 === 'Total' && side === 'P') {
        // Total row: payments total sits in columns 10-13 for this block
        const t = num(r[10]) + num(r[11]) + num(r[12]) + num(r[13]);
        totals.push({stated: t, parsed: block.P});
        block = {R: 0, P: 0};
      }
    }
  }
  return {title, vouchers, totals};
}

const LIMITS = [100000, 200000, 300000, 500000, 1000000, 2000000, 5000000];
const estimateOf = (text) => {
  const m = text.match(/Est\.?\s*(?:Rs\.?|₹)?\s*([\d.]+)(?:\s*\/\s*([\d.]+))?\s*lakh/i);
  if (!m) return null;
  return Math.max(+m[1] || 0, +(m[2] || 0)) * 100000;
};
const workKey = (text) => text.toLowerCase()
  .replace(/^\s*\d+(st|nd|rd|th)\s+(and final\s+)?(part\s+)?(payment|bill)\s+(for|towards)\s+(the\s+)?(work\s+)?/i, '')
  .replace(/^work\s+/i, '').replace(/est\.?.*$/i, '').replace(/[^a-z0-9]+/g, ' ').trim();

// Returns vouchers with .flags = [{level:'high'|'medium'|'info', rule, text}]
function flagVouchers(vouchers) {
  const pay = vouchers.filter((v) => v.side === 'P');
  const byAmount = new Map(), byWorkAmount = new Map(), byVoucher = new Map();
  for (const v of pay) {
    byAmount.set(v.amount, (byAmount.get(v.amount) || 0) + 1);
    const wk = workKey(v.particulars) + '|' + v.amount;
    byWorkAmount.set(wk, (byWorkAmount.get(wk) || 0) + 1);
    byVoucher.set(v.voucher, (byVoucher.get(v.voucher) || 0) + 1);
  }
  for (const v of vouchers) {
    const f = [];
    const add = (level, rule, text) => f.push({level, rule, text});
    if (v.side === 'P') {
      const est = estimateOf(v.particulars);
      if (est && v.amount > est * 1.0001) add('high', 'Over estimate', `Paid ₹${v.amount.toLocaleString('en-IN')} in one voucher, more than the work's stated estimate of ₹${est.toLocaleString('en-IN')}.`);
      if (byWorkAmount.get(workKey(v.particulars) + '|' + v.amount) > 1 && workKey(v.particulars)) add('high', 'Possible duplicate', 'Another voucher this month pays the same amount for the same work.');
      if (byVoucher.get(v.voucher) > 1) add('high', 'Repeated voucher number', 'This voucher number appears more than once.');
      if (v.cash > 0) add('high', 'Cash payment', 'Paid in cash. Panchayat grant payments are meant to go through bank/PFMS.');
      if (!v.particulars || v.particulars.length < 15) add('medium', 'No clear description', 'The cash book does not say what this payment was for.');
      const under = LIMITS.find((L) => v.amount < L && v.amount >= L * 0.97);
      if (under) add('medium', 'Just under a limit', `Within 3% below ₹${under.toLocaleString('en-IN')}. Splitting bills to stay under approval or tender limits is a known red flag.`);
      if (byAmount.get(v.amount) >= 3 && v.amount >= 10000) add('medium', 'Same amount repeated', `${byAmount.get(v.amount)} payments this month are for exactly ₹${v.amount.toLocaleString('en-IN')}.`);
      if (v.amount >= 50000 && v.amount % 10000 === 0) add('info', 'Round amount', 'A large, perfectly round amount. Real bills for works are rarely round; worth checking the measurement book.');
      const [d, m, y] = v.date.split('/').map(Number);
      if (new Date(Date.UTC(y, m - 1, d)).getUTCDay() === 0) add('medium', 'Paid on a Sunday', 'Payment dated on a Sunday.');
      if (m === 3 && d >= 25) add('info', 'Year-end rush', 'Paid in the last week of the financial year, when unspent money is often rushed out.');
    }
    v.flags = f;
  }
  return vouchers;
}


// ---- Geo-tagged works (photo proof) ----
const AP_BOX = {lat: [12.5, 19.3], lon: [76.6, 84.9]};
const km = (a, b) => { const R = 6371, r = Math.PI / 180, dl = (b.lat - a.lat) * r, dn = (b.lon - a.lon) * r;
  const h = Math.sin(dl / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };
const median = (xs) => { const s = xs.slice().sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };

// works: [{a,n,c,s,lat,lon,f,d}] photo rows for one panchayat. Drops duplicate listings, adds .flags to each row.
function flagWorks(rows) {
  const seen = new Set();
  const works = rows.filter((w) => { const k = w.a + '|' + (w.as || '') + '|' + (w.f || '').split('/').pop() + '|' + w.s; if (seen.has(k)) return false; seen.add(k); return true; });
  // one point per work, so a work with many photos does not pull the centre
  const perWork = new Map();
  works.filter((w) => w.lat && w.lon).forEach((w) => perWork.set(w.a, [...(perWork.get(w.a) || []), w]));
  const pts = [...perWork.values()].map((ps) => ({lat: median(ps.map((p) => p.lat)), lon: median(ps.map((p) => p.lon))}));
  const centre = pts.length >= 3 ? {lat: median(pts.map((w) => w.lat)), lon: median(pts.map((w) => w.lon))} : null;
  // stage order: a completion photo uploaded before an earlier-stage photo of the same work
  const STAGE = (s) => (/complet/i.test(s) ? 3 : /roof/i.test(s) ? 2 : /plinth/i.test(s) ? 1 : 0);
  const firstDone = new Map(), lastEarly = new Map();
  const asset = (w) => w.a + '|' + (w.as || '');  // stages are compared within one asset of a work
  for (const w of works) { if (!w.d) continue; const st = STAGE(w.s), k = asset(w);
    if (st === 3 && (!firstDone.has(k) || w.d < firstDone.get(k))) firstDone.set(k, w.d);
    if (st === 1 || st === 2) { const cur = lastEarly.get(k); if (!cur || w.d > cur.d) lastEarly.set(k, {d: w.d, s: w.s}); } }
  const byFile = new Map(), bySpot = new Map();
  for (const w of works) {
    if (w.f) { const k = w.f.split('/').pop(); byFile.set(k, (byFile.get(k) || new Set()).add(w.a)); }
    if (w.lat && w.lon) { const k = w.lat.toFixed(5) + ',' + w.lon.toFixed(5); bySpot.set(k, (bySpot.get(k) || new Set()).add(w.a)); }
  }
  for (const w of works) {
    const f = []; const add = (level, rule, text) => f.push({level, rule, text});
    if (!w.lat || !w.lon) add('high', 'No location', 'This photo has no GPS location.');
    else if (w.lat < AP_BOX.lat[0] || w.lat > AP_BOX.lat[1] || w.lon < AP_BOX.lon[0] || w.lon > AP_BOX.lon[1]) add('high', 'Outside Andhra Pradesh', 'The photo was tagged at a location outside the state.');
    else if (centre) { const d = km(centre, w); if (d > 15) add('medium', 'Far from the village', `A photo${w.s ? ' (' + w.s.toLowerCase() + ', ' + (w.d || 'no date') + ')' : ''} was tagged ${d.toFixed(1)} km from this panchayat's other works.`); }
    const k = w.f ? w.f.split('/').pop() : '';
    if (k && byFile.get(k).size > 1) add('high', 'Same photo, different works', 'The same photo file is used as proof for more than one work.');
    const spot = w.lat && w.lon ? bySpot.get(w.lat.toFixed(5) + ',' + w.lon.toFixed(5)) : null;
    if (STAGE(w.s) === 3 && w.d && lastEarly.has(asset(w)) && (Date.parse(lastEarly.get(asset(w)).d) - Date.parse(w.d)) / 864e5 >= 30) add('high', 'Stages out of order', `A "completed" photo${w.as ? ' of ' + w.as : ''} was uploaded on ${w.d}, before its "${lastEarly.get(asset(w)).s.toLowerCase()}" photo of ${lastEarly.get(asset(w)).d}. A work should not be finished before its foundation is laid.`);
    if (spot && spot.size >= 3) add('medium', 'Many works, one spot', `Photos for ${spot.size} different works were taken at exactly the same GPS point. Check that each work was photographed at its own site.`);
    w.flags = f;
  }
  return works;
}

const STOP = new Set('the of to in at and for from near work works providing provision construction constructing const gp village mandal est rs lakh lakhs lakhs payment part bill final 1st 2nd 3rd 4th nd rd th st with on by a an mb no page house road'.split(' '));
const tokens = (s) => new Set(String(s).toLowerCase().replace(/est.*$/, '').split(/[^a-z0-9]+/).filter((x) => x.length > 2 && !STOP.has(x)));
// Best geo-tagged work for a voucher description; returns {work, score} or null.
function matchWork(particulars, works) {
  const a = tokens(particulars); if (!a.size) return null;
  let best = null;
  for (const w of works) {
    const b = tokens(w.n); if (!b.size) continue;
    let inter = 0; a.forEach((x) => { if (b.has(x)) inter++; });
    const score = inter / Math.min(a.size, b.size);
    if (inter >= 2 && score >= 0.5 && (!best || score > best.score)) best = {work: w, score};
  }
  return best;
}

// Adds photo-proof flags to payment vouchers using the panchayat's geo-tagged works.
function linkVouchersToWorks(vouchers, works) {
  const paidPerWork = new Map();
  for (const v of vouchers) {
    if (v.side !== 'P') continue;
    const isWork = /work|construct|providing|repair|laying|drain|road|pipe|bore|shed/i.test(v.particulars);
    const m = matchWork(v.particulars, works);
    v.match = m ? m.work : null;
    if (m) {
      paidPerWork.set(m.work.a, (paidPerWork.get(m.work.a) || 0) + v.amount);
      works.filter((x) => x.a === m.work.a).flatMap((x) => x.flags).filter((x, i, arr) => x.level === 'high' && arr.findIndex((y) => y.rule === x.rule) === i).forEach((x) => v.flags.push({level: 'high', rule: 'Photo proof problem', text: `${x.rule}: ${x.text}`}));
    } else if (isWork) {
      v.flags.push({level: 'medium', rule: 'No photo proof found', text: 'No geo-tagged photo on eGramSwaraj matches this work for this panchayat.'});
    }
  }
  for (const v of vouchers) if (v.match && v.match.c && paidPerWork.get(v.match.a) > v.match.c * 1.0001)
    v.flags.push({level: 'high', rule: 'Paid above approved cost', text: `Payments this month for this work total ₹${paidPerWork.get(v.match.a).toLocaleString('en-IN')}, above its approved cost of ₹${v.match.c.toLocaleString('en-IN')}.`});
  return vouchers;
}

if (typeof module !== 'undefined') module.exports = {parseCashBook, flagVouchers, estimateOf, workKey, decode, flagWorks, matchWork, linkVouchersToWorks, km};
