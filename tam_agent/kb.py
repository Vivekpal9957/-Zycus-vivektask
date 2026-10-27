"""KB loader only."""
import json, pathlib
def load_kb(): return json.loads((pathlib.Path(__file__).resolve().parent.parent/"data"/"kb.json").read_text())
