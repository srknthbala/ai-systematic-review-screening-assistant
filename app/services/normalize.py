"""Unicode -> ASCII-safe normalization.

Converts Greek letters to their spelled-out names, en/em dashes to '-', smart
quotes to ASCII quotes, common scientific symbols to ASCII, then strips accents
via NFKD decomposition. Used on titles/abstracts so the screening model and the
deduper see clean, comparable text.
"""
import re
import unicodedata

GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "π": "pi", "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Α": "Alpha", "Β": "Beta", "Γ": "Gamma", "Δ": "Delta", "Ε": "Epsilon",
    "Ζ": "Zeta", "Η": "Eta", "Θ": "Theta", "Ι": "Iota", "Κ": "Kappa",
    "Λ": "Lambda", "Μ": "Mu", "Ν": "Nu", "Ξ": "Xi", "Ο": "Omicron",
    "Π": "Pi", "Ρ": "Rho", "Σ": "Sigma", "Τ": "Tau", "Υ": "Upsilon",
    "Φ": "Phi", "Χ": "Chi", "Ψ": "Psi", "Ω": "Omega",
}
DASHES = {c: "-" for c in "‐‑‒–—―−"}
QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "«": '"', "»": '"', "′": "'", "″": '"',
}
MISC = {
    " ": " ", " ": " ", " ": " ", " ": " ", "﻿": "",
    "…": "...", "×": "x", "→": "->", "≤": "<=",
    "≥": ">=", "±": "+/-", "°": " deg ", "™": "(TM)",
    "®": "(R)", "©": "(C)",
}
_REPLACEMENTS = {**GREEK, **DASHES, **QUOTES, **MISC}
_WS = re.compile(r"\s+")


def normalize_text(s: str | None) -> str:
    """Return an ASCII-safe, whitespace-collapsed version of *s*."""
    if not s:
        return ""
    for k, v in _REPLACEMENTS.items():
        if k in s:
            s = s.replace(k, v)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.encode("ascii", "ignore").decode("ascii")
    return _WS.sub(" ", s).strip()


_NONALNUM = re.compile(r"[^a-z0-9]+")


def title_key(s: str | None) -> str:
    """Aggressive key for fuzzy title comparison: ascii, lowercase, alnum-only."""
    return _NONALNUM.sub("", normalize_text(s).lower())


def author_key(author: str | None) -> str:
    """First-author surname key. Handles 'Smith, John' and 'John Smith'."""
    if not author:
        return ""
    a = normalize_text(author).strip()
    if "," in a:
        surname = a.split(",")[0]
    else:
        parts = a.split()
        surname = parts[-1] if parts else ""
    return _NONALNUM.sub("", surname.lower())


def year_of(s: str | None) -> str:
    """Extract a 4-digit year (1900-2099) from a string, else ''."""
    if not s:
        return ""
    m = re.search(r"(19|20)\d{2}", s)
    return m.group(0) if m else ""


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    d = normalize_text(doi).lower().strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.strip().rstrip(".")


def extract_doi(text: str | None) -> str:
    """Pull the first DOI-looking token out of arbitrary text."""
    if not text:
        return ""
    m = re.search(r"10\.\d{4,9}/[^\s\"'<>\]]+", text)
    return m.group(0).rstrip(".,;)") if m else ""


def extract_pmid(text: str | None) -> str:
    if not text:
        return ""
    m = re.search(r"pmid[:\s]*([0-9]{5,9})", text, re.I)
    if m:
        return m.group(1)
    return ""
