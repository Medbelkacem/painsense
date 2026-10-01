"""Whether a dataset may be retrieved, and on whose authority.

Two independent gates have to open before a file is downloaded.

The *access* gate is the publisher's access control. PhysioNet credentialing, a signed
data use agreement, a registration wall: these are decisions the publisher has made about
who may hold the data, and this platform's answer to all of them is the same — record the
procedure a person would follow and fetch nothing. Nothing in this package attempts to
satisfy an access control automatically, including with credentials that happen to be
configured.

The *licence* gate is about what may then be done with the bytes. A licence this module
has not been taught to recognise is `REVIEW_REQUIRED`, not "probably fine": the dataset is
catalogued, the licence text is recorded, and a person decides.

Downloading is not redistributing. Most of what WHO publishes is CC BY-NC-SA, which
permits a research platform to hold and analyse a copy while forbidding redistribution and
commercial use — that is `RESEARCH_ONLY`, and it is retrievable. `PERMISSIVE` is the
narrower set that also permits redistribution. Neither verdict makes this platform a
republisher, which is why every version row carries the licence its bytes arrived under.
"""

from __future__ import annotations

from database.models import (
    DOWNLOADABLE_ACCESS,
    RETRIEVABLE_LICENCES,
    LicenceVerdict,
    SourceAccess,
)

#: Licences that permit holding a copy and redistributing it. Compared after casefolding
#: and whitespace collapse.
#:
#: The same licence is spelled differently by each publisher: Kaggle returns human titles
#: ("Apache 2.0"), Hugging Face and GitHub return SPDX identifiers ("apache-2.0"), and
#: PhysioNet returns the licence's full legal name. All three spellings have to be here or
#: a correctly licensed dataset gets refused for a punctuation difference — which is how
#: an Apache-2.0 dataset was initially turned away.
PERMISSIVE = frozenset(
    {
        # SPDX identifiers, as the Hugging Face Hub and GitHub report them.
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "isc",
        "mpl-2.0",
        "unlicense",
        "pddl",
        "odc-by",
        "cdla-permissive-1.0",
        "cdla-permissive-2.0",
        "cdla-sharing-1.0",
        "cc-by-3.0",
        "cc-by-sa-3.0",
        "cc0: public domain",
        "cc0 1.0",
        "cc0-1.0",
        "cc by 4.0",
        "cc-by-4.0",
        "attribution 4.0 international (cc by 4.0)",
        "creative commons attribution 4.0 international public license",
        "cc by-sa 4.0",
        "cc-by-sa-4.0",
        "creative commons attribution-sharealike 4.0 international public license",
        "odbl-1.0",
        "database: open database, contents: database contents",
        "database: open database, contents: original author",
        "open data commons attribution license v1.0",
        "open data commons open database license v1.0",
        "apache 2.0",
        "mit",
        "u.s. government works",
        "public domain u.s. government",
        "community data license agreement - permissive - version 1.0",
        "community data license agreement - sharing - version 1.0",
    }
)

#: Licences that permit research use of a retrieved copy but not redistribution or
#: commercial use. Matched as substrings because publishers pad these titles, and WHO in
#: particular states its terms as a sentence rather than a licence identifier.
RESEARCH_ONLY_MARKERS = (
    "cc by-nc",
    "cc-by-nc",
    "attribution-noncommercial",
    "attribution-non-commercial",
    "non-commercial",
    "noncommercial",
    "who publishing and copyright policy",
)

#: Licences that gate holding a copy at all behind a signed instrument or an individual
#: grant. The access gate usually catches these first; the marker is here for a publisher
#: that states restrictive terms while leaving the files openly reachable.
RESTRICTED_MARKERS = (
    "credentialed health data license",
    "restricted health data license",
    "data use agreement",
    "request required",
    "all rights reserved",
    "no redistribution",
)

#: What a person has to do to obtain a dataset this platform will not fetch. Keyed by
#: access status, and recorded on the dataset so the interface can show it instead of an
#: empty download button.
PROCEDURES: dict[SourceAccess, tuple[str, ...]] = {
    SourceAccess.REGISTRATION_REQUIRED: (
        "Create an account with the publisher and sign in",
        "Open the dataset page and read the terms attached to it",
        "Accept the terms for this specific dataset",
        "Download the files through the publisher's own interface",
    ),
    SourceAccess.CREDENTIALED: (
        "Create an account with the publisher and sign in",
        (
            "Complete the publisher's credentialing process, which for PhysioNet requires "
            "a CITI human-subjects research training report"
        ),
        "Wait for the credentialing application to be reviewed and approved",
        "Sign the data use agreement attached to this specific project",
        "Download the files once credentialing and the agreement are both in place",
    ),
    SourceAccess.AGREEMENT_REQUIRED: (
        "Read the data use agreement on the dataset page",
        "Have the agreement signed by someone authorised to bind your institution",
        "Submit the signed agreement to the publisher and wait for acceptance",
        "Download the files through the channel the publisher nominates",
    ),
    SourceAccess.DOCUMENT_ONLY: (
        (
            "The publisher releases this material as documents rather than through a data "
            "interface"
        ),
        (
            "Open the publication and transcribe the figures needed, recording the document "
            "version they came from"
        ),
    ),
    SourceAccess.UNKNOWN: (
        "The access policy could not be read automatically",
        "Open the dataset page and follow the access instructions stated there",
    ),
}


def normalise(licence: str | None) -> str:
    return " ".join((licence or "").split()).casefold()


def verdict(licence: str | None) -> LicenceVerdict:
    text = normalise(licence)
    if not text or text in ("unknown", "other", "other (specified in description)"):
        return LicenceVerdict.UNKNOWN
    if text in PERMISSIVE:
        return LicenceVerdict.PERMISSIVE
    # Restriction is checked before research-use, so a non-commercial licence that also
    # requires a signed agreement reads as restricted rather than as retrievable.
    if any(marker in text for marker in RESTRICTED_MARKERS):
        return LicenceVerdict.RESTRICTED
    if any(marker in text for marker in RESEARCH_ONLY_MARKERS):
        return LicenceVerdict.RESEARCH_ONLY
    return LicenceVerdict.REVIEW_REQUIRED


def procedure(access: SourceAccess) -> list[str]:
    return list(PROCEDURES.get(access, PROCEDURES[SourceAccess.UNKNOWN]))


def refusal(access: SourceAccess, licence_verdict: LicenceVerdict) -> str | None:
    """Why this dataset will not be downloaded, or None when both gates are open.

    Order matters: access is reported first because it is the publisher's decision, and
    saying "the licence needs review" about a dataset nobody here is entitled to hold
    would describe the wrong problem.
    """
    if access not in DOWNLOADABLE_ACCESS:
        return (
            f"the publisher restricts access to this dataset ({access.value.lower().replace('_', ' ')}); "
            "its metadata and access procedure are recorded and no files were retrieved"
        )
    if licence_verdict is LicenceVerdict.RESTRICTED:
        return (
            "the licence restricts how a copy may be held or used, so no files were "
            "retrieved automatically"
        )
    if licence_verdict is LicenceVerdict.REVIEW_REQUIRED:
        return (
            "this licence has not been reviewed for automatic acquisition; a person has to "
            "read it and record the decision before files are retrieved"
        )
    if licence_verdict is LicenceVerdict.UNKNOWN:
        return (
            "the publisher states no licence for this dataset, so no files were retrieved "
            "automatically"
        )
    if licence_verdict not in RETRIEVABLE_LICENCES:
        return f"licence verdict {licence_verdict.value.lower()} does not permit automatic retrieval"
    return None


def redistribution_note(licence_verdict: LicenceVerdict) -> str:
    """What this platform may do with a copy once it holds one.

    Recorded per version rather than inferred at display time, so a licence that changes
    after acquisition does not silently rewrite the terms the existing copy arrived under.
    """
    if licence_verdict is LicenceVerdict.PERMISSIVE:
        return "redistribution permitted by the licence; not redistributed by this platform"
    if licence_verdict is LicenceVerdict.RESEARCH_ONLY:
        return "research use only; no redistribution and no commercial use"
    return "not redistributed by this platform"
