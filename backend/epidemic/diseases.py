"""The ten diseases this module covers.

Nothing here is derived from data. It is reference information used to label what the
pipeline collects, to decide which sources are worth probing for a given disease, and to
give the interface something to say about a disease for which no data was obtained.

`incubation_days` is the range quoted by the WHO fact sheet for the disease and is used
only to sanity-check an exposure interval the user types in; it is not a model input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CLINICAL = "clinical"
EPIDEMIOLOGICAL = "epidemiological"
LABORATORY = "laboratory"
SURVEILLANCE = "surveillance"
IMAGING = "imaging"

DATASET_TYPES = (CLINICAL, EPIDEMIOLOGICAL, LABORATORY, SURVEILLANCE, IMAGING)


@dataclass(frozen=True)
class Disease:
    code: str
    name: str
    short_name: str
    pathogen: str
    icd10: str
    transmission: str
    incubation_days: tuple[int, int]
    notifiable_us: bool
    # What the published sources actually carry for this disease, as established by
    # probing them. A disease with only aggregate counts gets a dashboard and no model;
    # see app.epidemic.training for where that decision is enforced.
    expected_data: tuple[str, ...] = field(default=(SURVEILLANCE,))
    summary: str = ""


DISEASES: tuple[Disease, ...] = (
    Disease(
        code="covid19",
        name="COVID-19",
        short_name="COVID-19",
        pathogen="SARS-CoV-2",
        icd10="U07.1",
        transmission="Respiratory droplets and aerosols",
        incubation_days=(2, 14),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, EPIDEMIOLOGICAL, CLINICAL),
        summary=(
            "The only one of the ten for which a public, patient-level, labelled dataset "
            "was obtained: the CDC case surveillance public use file."
        ),
    ),
    Disease(
        code="influenza_h1n1",
        name="Influenza A (H1N1)pdm09",
        short_name="Influenza A(H1N1)",
        pathogen="Influenza A virus subtype H1N1pdm09",
        icd10="J09-J10",
        transmission="Respiratory droplets",
        incubation_days=(1, 4),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, LABORATORY),
        summary=(
            "Laboratory-confirmed subtype counts from the WHO global influenza "
            "surveillance network, reported by sentinel laboratories per ISO week."
        ),
    ),
    Disease(
        code="tuberculosis",
        name="Tuberculosis",
        short_name="Tuberculosis",
        pathogen="Mycobacterium tuberculosis",
        icd10="A15-A19",
        transmission="Airborne, prolonged close contact",
        incubation_days=(14, 84),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, EPIDEMIOLOGICAL),
        summary=(
            "WHO publishes modelled national incidence and mortality alongside reported "
            "notifications and treatment outcomes. The two are kept apart: an estimate is "
            "not a count."
        ),
    ),
    Disease(
        code="measles",
        name="Measles",
        short_name="Measles",
        pathogen="Measles morbillivirus",
        icd10="B05",
        transmission="Airborne, extremely contagious",
        incubation_days=(7, 21),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, EPIDEMIOLOGICAL),
        summary=(
            "Reported cases per country-year, with first- and second-dose vaccine "
            "coverage for the same country-year so the two can be read together."
        ),
    ),
    Disease(
        code="ebola",
        name="Ebola virus disease",
        short_name="Ebola",
        pathogen="Orthoebolavirus (Zaire, Sudan and related species)",
        icd10="A98.4",
        transmission="Direct contact with blood or body fluids",
        incubation_days=(2, 21),
        notifiable_us=True,
        expected_data=(SURVEILLANCE,),
        summary=(
            "Outbreak case and death counts transcribed from WHO situation reports for "
            "the 2014-2016 West African epidemic, plus US notifiable-disease counts."
        ),
    ),
    Disease(
        code="mpox",
        name="Mpox",
        short_name="Mpox",
        pathogen="Monkeypox virus",
        icd10="B04",
        transmission="Close physical contact, including sexual contact",
        incubation_days=(3, 17),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, EPIDEMIOLOGICAL),
        summary=(
            "Daily confirmed cases and deaths per country for the multi-country outbreak "
            "from May 2022, compiled from the WHO situation dashboard."
        ),
    ),
    Disease(
        code="lassa",
        name="Lassa fever",
        short_name="Lassa fever",
        pathogen="Lassa mammarenavirus",
        icd10="A96.2",
        transmission="Contact with Mastomys rodent excreta; person-to-person in care settings",
        incubation_days=(6, 21),
        notifiable_us=True,
        expected_data=(SURVEILLANCE,),
        summary=(
            "The detailed series lives in Nigeria CDC weekly situation reports, which are "
            "published as documents rather than through a data interface. Only the US "
            "notifiable-disease counts were obtained automatically."
        ),
    ),
    Disease(
        code="dengue",
        name="Dengue fever",
        short_name="Dengue",
        pathogen="Dengue virus serotypes 1-4",
        icd10="A90-A91",
        transmission="Aedes mosquito bite",
        incubation_days=(4, 10),
        notifiable_us=True,
        expected_data=(SURVEILLANCE, EPIDEMIOLOGICAL),
        summary=(
            "OpenDengue assembles national case counts from ministry-of-health bulletins "
            "and publishes them as a versioned release with its own provenance per record."
        ),
    ),
    Disease(
        code="cholera",
        name="Cholera",
        short_name="Cholera",
        pathogen="Vibrio cholerae O1 and O139",
        icd10="A00",
        transmission="Contaminated water and food",
        incubation_days=(1, 5),
        notifiable_us=True,
        expected_data=(SURVEILLANCE,),
        summary=(
            "Annual reported cases, reported deaths and case fatality rate per country, "
            "from the WHO Global Health Observatory."
        ),
    ),
    Disease(
        code="meningococcal_meningitis",
        name="Meningococcal meningitis",
        short_name="Meningitis",
        pathogen="Neisseria meningitidis",
        icd10="A39",
        transmission="Respiratory droplets, prolonged close contact",
        incubation_days=(2, 10),
        notifiable_us=True,
        expected_data=(SURVEILLANCE,),
        summary=(
            "WHO reports suspected cases and deaths for the African meningitis belt; the "
            "US surveillance tables add laboratory-confirmed counts by serogroup."
        ),
    ),
)

BY_CODE = {disease.code: disease for disease in DISEASES}


def get(code: str) -> Disease:
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(f"unknown disease {code!r}") from None


def codes() -> tuple[str, ...]:
    return tuple(disease.code for disease in DISEASES)
