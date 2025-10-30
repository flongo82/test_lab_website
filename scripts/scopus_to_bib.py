import os
import re
from datetime import date
from pathlib import Path

# Installazione runtime (no-op se già presente)
# (Su GitHub Actions installeremo via pip nel workflow)
try:
    from pybliometrics.scopus import AuthorRetrieval, ScopusSearch, AbstractRetrieval
except Exception as e:
    raise SystemExit("pybliometrics non disponibile. Assicurati che il workflow faccia pip install pybliometrics.") from e

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
    # es: cognome-primoautore_anno_slugtitolo
    first_author = ""
    if rec.get("authors"):
        a0 = rec["authors"][0]
        last = a0.split()[-1]
        first_author = slugify(last)
    year = rec.get("year") or ""
    title_slug = slugify(rec.get("title") or "")[:30]
    base = f"{first_author}{year}{title_slug}".strip("-")
    # se abbiamo DOI/EID rendiamolo unico
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
            # Escapa braces basilari
            v = v.replace("{", "\\{").replace("}", "\\}")
            fields.append(f"  {k} = {{{v}}}")

    add("title", rec.get("title"))
    add("author", " and ".join(rec.get("authors", [])))
    add("year", rec.get("year"))
    if entry_type == "article":
        add("journal", rec.get("venue"))
    else:
        add("booktitle", rec.get("venue"))
    add("volume", rec.get("volume"))
    add("number", rec.get("number"))
    add("pages", rec.get("pages"))
    add("doi", rec.get("doi"))
    add("url", rec.get("url"))

    return "@{}{{{},\n{}\n}}\n".format(entry_type, citekey, ",\n".join(fields))

def record_from_abstract(ab):
    # Determina tipo (article vs inproceedings) in modo semplice
    entry_type = "article"
    if getattr(ab, "aggregationType", None):
        agg = str(ab.aggregationType).lower()
        if "conference" in agg or "proceedings" in agg:
            entry_type = "inproceedings"

    # Autori
    authors = []
    for a in getattr(ab, "authors", []) or []:
        gn = getattr(a, "given_name", "") or ""
        sn = getattr(a, "surname", "") or ""
        fullname = " ".join([gn, sn]).strip()
        if fullname:
            authors.append(fullname)

    # Venue / pagine
    venue = getattr(ab, "publicationName", None)
    pages = None
    try:
        # a volte pageRange è 'S123-S130'
        pages = getattr(ab, "pageRange", None) or getattr(ab, "pageRange", None)
    except Exception:
        pages = None

    rec = {
        "entry_type": entry_type,
        "title": getattr(ab, "title", None),
        "year": (getattr(ab, "coverDate", None) or "")[:4] or None,
        "doi": getattr(ab, "doi", None),
        "venue": venue,
        "volume": getattr(ab, "volume", None),
        "number": getattr(ab, "issueIdentifier", None),
        "pages": pages,
        "authors": authors,
        "eid": getattr(ab, "eid", None),
        "url": f"https://www.scopus.com/record/display.uri?eid={getattr(ab, 'eid', '')}&origin=resultslist",
    }
    rec["citekey"] = make_citekey(rec)
    return rec

def map_orcid_to_auid(orcid):
    # ScopusSearch ORCID
    q = f"ORCID({orcid})"
    s = ScopusSearch(q, refresh=True)
    auids = set()
    for eid in s.get_eids() or []:
        try:
            ab = AbstractRetrieval(eid, view="STANDARD")
            for a in (ab.authors or []):
                if getattr(a, "orcid", None) == orcid:
                    if getattr(a, "auid", None):
                        auids.add(a.auid)
        except Exception:
            continue
    return sorted(auids)

def collect_eids_for_author(auid):
    q = f"AU-ID({auid})"
    s = ScopusSearch(q, refresh=True)  # usa paginazione interna
    return s.get_eids() or []

def main():
    author_ids = get_env_list("SCOPUS_AUTHOR_IDS")
    orcids = get_env_list("SCOPUS_ORCIDS")

    if not author_ids and orcids:
        # prova a mappare ORCID -> AUID
        mapped = set()
        for oc in orcids:
            mapped.update(map_orcid_to_auid(oc))
        author_ids = sorted(mapped)

    if not author_ids:
        raise SystemExit(
            "Nessun autore specificato. Imposta una repo variable SCOPUS_AUTHOR_IDS (es: 5719...,7001...) "
            "oppure SCOPUS_ORCIDS (es: 0000-0002-1825-0097)."
        )

    # Dedup
    seen_eids = set()
    recs = []

    for auid in author_ids:
        eids = collect_eids_for_author(auid)
        for eid in eids:
            if eid in seen_eids:
                continue
            seen_eids.add(eid)
            try:
                ab = AbstractRetrieval(eid, view="STANDARD")
                rec = record_from_abstract(ab)
                recs.append(rec)
            except Exception as e:
                # salta la voce problematica, ma continua
                print(f"[WARN] Impossibile leggere EID {eid}: {e}")

    # Dedup per DOI (se presente)
    seen_doi = set()
    uniq = []
    for r in recs:
        doi = (r.get("doi") or "").lower()
        if doi and doi in seen_doi:
            continue
        if doi:
            seen_doi.add(doi)
        uniq.append(r)

    # Ordina: anno desc, titolo
    def sort_key(r):
        try:
            y = int(r.get("year") or 0)
        except Exception:
            y = 0
        return (-y, (r.get("title") or "").lower())

    uniq.sort(key=sort_key)

    # Scrivi BibTeX
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"% Generated from Scopus on {date.today().isoformat()}\n\n")
        for r in uniq:
            f.write(to_bibtex(r))
            f.write("\n")

    print(f"✅ Scritto {OUT_PATH} con {len(uniq)} record.")

if __name__ == "__main__":
    main()
