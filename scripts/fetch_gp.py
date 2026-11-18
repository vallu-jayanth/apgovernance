"""Download 15th FC grant spending + geo-tagged asset counts for every AP gram panchayat from eGramSwaraj."""
import json, csv, sys, time, urllib.request
B = "https://egramswaraj.gov.in"
YEAR = sys.argv[1]; OUT = sys.argv[2]
def get(path):
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(B + path, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
                return json.load(r)
        except Exception as e:
            err = e; time.sleep(3)
    raise err
# geo-tagged assets per GP code
geo = {}
for z in get(f"/geoTaggingZpReport.do?stateId=28&year={YEAR}"):
    for b in get(f"/geoTaggingBpReport.do?stateId=28&code={z['code']}&year={YEAR}"):
        if b['count']:
            for g in get(f"/geoTaggingGpReport.do?stateId=28&code={b['code']}&year={YEAR}"):
                geo[g['code']] = g['count']
        time.sleep(0.2)
    print("geo", z['name'], file=sys.stderr)
q = f"finYear={YEAR}&schemeCode=3287&stateCode=28"
rows = []
for d in get(f"/recExpZpVpNew.do?{q}"):
    for v in get(f"/recExpVpNew.do?{q}&districtCode={d['lBCode']}"):
        avail = v['totOb'] + v['totReceiptDirect'] + v['totReceiptAuto']
        assert abs(avail - v['totPaymentAmount'] - (v['untiedUb'] + v['tiedUb'])) < 5, v
        rows.append({"gp_code": v['bpCode'], "district": d['localBodyNameEnglish'].strip(), "mandal": v['zpName'].strip(), "panchayat": v['bpName'].strip(),
            "opening_balance": round(v['totOb']), "receipts": round(v['totReceiptDirect'] + v['totReceiptAuto']),
            "expenditure": round(v['totPaymentAmount']), "closing_balance": round(v['untiedUb'] + v['tiedUb']),
            "geotagged_assets": geo.get(v['bpCode'], 0)})
    time.sleep(1)
assert len(rows) > 10000, len(rows)  # guard against a half-empty download replacing good data
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows), "rows;", sum(1 for r in rows if r['geotagged_assets']), "with geo-tags;", len(geo), "geo GPs", file=sys.stderr)
