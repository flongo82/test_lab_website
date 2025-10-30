# scripts/scopus_to_bib.py
import os
import re
from datetime import date
from pathlib import Path

# 🔸 Inizializza pybliometrics PRIMA di importare i moduli Scopus
import pybliometrics
pybliometrics.init()  # usa ~/.config/pybliometrics.cfg per default

try:
    from pybliometrics.scopus import AuthorRetrieval, ScopusSearch, AbstractRetrieval
except Exception as e:
    raise SystemExit("pybliometrics non disponibile o non inizializzato correttamente.") from e

OUT_PATH = Path("publications.bib")

def get_env_list(name: str):
    v = os.getenv(name, "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

def slugify(text):
    text = re.sub(r"[^\w\s-]", "", (text or "")).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text

def make_citekey(rec):
    first_author = ""
    if rec.get("authors"):
        a0 = rec["authors"][0]
        last = a0.split()[-1]
        first_author = slugify(last)
    year = rec.get("year") or ""
    title_slug = slugify(rec.get("title") or "")[:30]
    base = f"{first_author}{year}{title_slug}".strip("-")
    if rec.get("doi"):
        suffix = slugify(rec["doi"])[:12]
        return f"{base}_{suffix}"
    if rec.get("eid"):
        return f"{base}_{slugify(rec['eid'])[:12]}"
    return base or f"ref{date.today().strftime('%Y%m%d')}"

def to_bibtex(rec):
    entry_type = rec.get("entry_type", "article")
    citekey = rec.get("citekey") or make_citekey(rec)
    fields = []
    def add(k, v):
        if v:
            v = v.replace("{", "\\{").replace("}", "\\}")
            fields.append(f"  {k} = {{{v}}}")
    add("title", rec.get("title"))
    add("author", " and ".join(rec.get("authors", [])))
    add("year", rec.get("year"))
    if entry_type == "article":
        add("journal", rec.get("venue"))
    else:
        add("booktitle", rec.get("venu
