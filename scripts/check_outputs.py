import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tam_agent import data, schema
ok = 0; ids = data.load_review_ids()
for t in ids:
    p = pathlib.Path("outputs") / f"{t}.json"
    e = schema.validate(json.loads(p.read_text())) if p.exists() else ["missing file"]
    print(("OK   " if not e else "FAIL ") + t, *e); ok += not e
print(f"{ok}/{len(ids)} valid"); sys.exit(0 if ok == len(ids) else 1)
