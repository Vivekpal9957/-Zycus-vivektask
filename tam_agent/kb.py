"""KB loader: splits each markdown file into sections (the retrieval unit)."""
import re, pathlib
KB = pathlib.Path(__file__).resolve().parent.parent / "knowledge-base"

def load_kb():
    """Each section (split on '---') becomes an article: id = '<file>#<n>', title = file title + first heading."""
    out = []
    for f in sorted(KB.glob("*/*.md")):
        text = f.read_text(encoding="utf-8")
        doc = (re.match(r"#\s*(.+)", text) or [None, f.stem])[1].strip()
        for n, sec in enumerate(s.strip() for s in text.split("\n---\n")):
            if not re.search(r"[a-z]{4}", sec): continue
            h = re.search(r"^#{2,4}\s*(.+)$", sec, re.M)
            out.append(dict(id=f"{f.stem}#{n}", title=f"{doc} - {h[1].strip() if h else 'overview'}", category=f.parent.name, source=str(f.relative_to(KB.parent)),
                            body=sec, deprecated=bool(re.search(r"deprecated|end[- ]of[- ]life|\bEOL\b", sec, re.I))))
    return out
