"""Working out which disease a published dataset is about, and recording it.

Matching is deliberately conservative. A dataset is linked to a disease only when a
disease *name* appears in its title or description as a whole phrase — not on a shared
word, not on a fuzzy score. "Pain detection from biosignals" names no disease and is
recorded as naming none, which is the honest answer and leaves the dataset perfectly
usable; a wrong link would put a dataset on the wrong disease's dashboard and be much
harder to notice than a missing one.

Two indexes are consulted, in order:

The diseases the platform already holds, built from the `diseases` table at call time, so
a dataset about migraine attaches to the existing `MIGRAINE` entry rather than creating a
second one. This is the "does it already exist?" step.

A vocabulary of diseases these publishers actually carry, below. A match here for a
disease the platform does not hold creates the entry, flagged `curated=False` so it
appears on the dataset dashboard without being offered to clinicians as a vetted
comorbidity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Disease


@dataclass(frozen=True)
class Candidate:
    code: str
    label: str
    category: str
    terms: tuple[str, ...]
    pain_relevant: bool = False


#: Diseases these publishers carry that the clinical comorbidity list does not. The WHO
#: Global Health Observatory, CDC's notifiable-disease tables and the infectious-disease
#: side of Kaggle all speak in these terms, and without them every such dataset would land
#: unattributed.
VOCABULARY: tuple[Candidate, ...] = (
    Candidate("COVID19", "COVID-19", "INFECTIOUS", ("covid-19", "covid19", "sars-cov-2")),
    Candidate(
        "INFLUENZA",
        "Influenza",
        "INFECTIOUS",
        ("influenza", "h1n1", "h3n2", "flu surveillance"),
    ),
    Candidate("TUBERCULOSIS", "Tuberculosis", "INFECTIOUS", ("tuberculosis", "mycobacterium tuberculosis")),
    Candidate("MEASLES", "Measles", "INFECTIOUS", ("measles", "rubeola")),
    Candidate("EBOLA", "Ebola virus disease", "INFECTIOUS", ("ebola", "ebola virus disease")),
    Candidate("MPOX", "Mpox", "INFECTIOUS", ("mpox", "monkeypox")),
    Candidate("LASSA_FEVER", "Lassa fever", "INFECTIOUS", ("lassa", "lassa fever")),
    Candidate("DENGUE", "Dengue fever", "INFECTIOUS", ("dengue",), pain_relevant=True),
    Candidate("CHOLERA", "Cholera", "INFECTIOUS", ("cholera", "vibrio cholerae")),
    Candidate(
        "MENINGOCOCCAL_MENINGITIS",
        "Meningococcal meningitis",
        "INFECTIOUS",
        ("meningococcal", "meningitis"),
        pain_relevant=True,
    ),
    Candidate("MALARIA", "Malaria", "INFECTIOUS", ("malaria", "plasmodium falciparum")),
    Candidate("HIV", "HIV infection", "INFECTIOUS", ("hiv", "human immunodeficiency virus")),
    Candidate("HEPATITIS", "Viral hepatitis", "INFECTIOUS", ("hepatitis",)),
    Candidate(
        "SICKLE_CELL",
        "Sickle cell disease",
        "OTHER",
        ("sickle cell", "sickle-cell"),
        pain_relevant=True,
    ),
    Candidate(
        "ENDOMETRIOSIS",
        "Endometriosis",
        "OTHER",
        ("endometriosis",),
        pain_relevant=True,
    ),
    Candidate(
        "CERVICAL_SPONDYLOSIS",
        "Cervical spine disorder",
        "MUSCULOSKELETAL",
        ("cervical pain", "cervical spondylosis", "neck pain"),
        pain_relevant=True,
    ),
    Candidate(
        "POSTOPERATIVE_PAIN",
        "Post-operative pain",
        "OTHER",
        ("post-operative pain", "postoperative pain", "post surgical pain"),
        pain_relevant=True,
    ),
)

#: Terms that name a disease the platform already holds but under wording a publisher is
#: unlikely to use. Only the extra phrasings go here; the row's own label is always matched.
ALIASES: dict[str, tuple[str, ...]] = {
    "MIGRAINE": ("migraine", "migraines"),
    "OSTEOARTHRITIS": ("osteoarthritis", "knee osteoarthritis"),
    "RHEUMATOID_ARTHRITIS": ("rheumatoid arthritis",),
    "FIBROMYALGIA": ("fibromyalgia",),
    "CHRONIC_BACK_DISORDER": ("low back pain", "lower back pain", "chronic back pain"),
    "NEUROPATHY": ("neuropathic pain", "peripheral neuropathy", "diabetic neuropathy"),
    "CANCER_ACTIVE": ("cancer pain",),
    "DIABETES_T2": ("type 2 diabetes",),
    "DIABETES_T1": ("type 1 diabetes",),
    "IBS": ("irritable bowel syndrome",),
    "IBD": ("inflammatory bowel disease", "crohn's disease", "ulcerative colitis"),
    "NEPHROLITHIASIS": ("kidney stones", "renal colic"),
    "ENDOMETRIOSIS": ("endometriosis",),
}


@dataclass(frozen=True)
class Match:
    code: str | None
    label: str | None
    term: str | None
    basis: str
    created: bool = False

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "matched_term": self.term,
            "basis": self.basis,
            "created": self.created,
        }


UNMATCHED = Match(
    None,
    None,
    None,
    "no disease name appeared in the title or description; the dataset is catalogued "
    "without a disease rather than guessed at",
)


def _phrase(term: str) -> re.Pattern[str]:
    # \b does not fire next to a hyphen, so "covid-19" needs the boundary expressed as
    # "not a letter or digit" on each side instead.
    return re.compile(rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])", re.IGNORECASE)


def _index(db: Session) -> list[tuple[str, str, str]]:
    """(term, code, basis) for every disease the platform already holds, longest first.

    Longest first so "chronic back pain" wins over "back pain" when both would match.
    """
    pairs: list[tuple[str, str, str]] = []
    for row in db.scalars(select(Disease)):
        pairs.append((row.label.casefold(), row.code, "existing disease label"))
        for alias in ALIASES.get(row.code, ()):
            pairs.append((alias.casefold(), row.code, "existing disease alias"))
    return sorted(pairs, key=lambda item: -len(item[0]))


def identify(db: Session, text: str, *, source_ref: str) -> Match:
    """Find the disease a dataset is about, creating the entry when it is new.

    `text` is the publisher's title and description joined; nothing else is consulted,
    because a dataset's own words are the only evidence available at discovery time.
    """
    haystack = " ".join(text.split())
    if not haystack:
        return UNMATCHED

    for term, code, basis in _index(db):
        if _phrase(term).search(haystack):
            row = db.get(Disease, code)
            return Match(code, row.label if row else code, term, basis)

    for candidate in sorted(VOCABULARY, key=lambda c: -max(len(t) for t in c.terms)):
        for term in sorted(candidate.terms, key=len, reverse=True):
            if _phrase(term).search(haystack):
                return _create(db, candidate, term, source_ref)
    return UNMATCHED


def _create(db: Session, candidate: Candidate, term: str, source_ref: str) -> Match:
    existing = db.get(Disease, candidate.code)
    if existing is not None:
        return Match(existing.code, existing.label, term, "existing disease code")
    db.add(
        Disease(
            code=candidate.code,
            label=candidate.label,
            category=candidate.category,
            pain_relevant=candidate.pain_relevant,
            curated=False,
            origin="external_sync",
            source_ref=source_ref[:255],
            discovered_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return Match(
        candidate.code,
        candidate.label,
        term,
        f"created from the recognised disease vocabulary after {term!r} appeared in the "
        "publisher's description",
        created=True,
    )
