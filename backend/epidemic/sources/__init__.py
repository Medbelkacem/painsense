"""The sources this pipeline knows about, one adapter per published resource.

Ordering matters only for the report: sources are probed and fetched in the order they
appear, so the cheap ones come first and a run interrupted halfway has still written the
small series.
"""

from __future__ import annotations

from backend.epidemic.sources.base import Fetched, Probe, Refused, Source
from backend.epidemic.sources.cdc import (
    CDC_COVID_CASE_SURVEILLANCE,
    CDC_NNDSS_WEEKLY,
)
from backend.epidemic.sources.manual import NCDC_LASSA_SITREPS
from backend.epidemic.sources.opendengue import OPENDENGUE_NATIONAL
from backend.epidemic.sources.owid import OWID_MPOX
from backend.epidemic.sources.who import (
    WHO_COVID_DAILY,
    WHO_FLUNET,
    WHO_GHO_CHOLERA,
    WHO_GHO_MEASLES,
    WHO_GHO_MENINGITIS,
    WHO_TB_BURDEN,
    WHO_TB_OUTCOMES,
)
from backend.epidemic.sources.who_ebola import WHO_EBOLA_SITREPS

SOURCES: tuple[Source, ...] = (
    WHO_GHO_CHOLERA,
    WHO_GHO_MEASLES,
    WHO_GHO_MENINGITIS,
    WHO_TB_BURDEN,
    WHO_TB_OUTCOMES,
    WHO_COVID_DAILY,
    WHO_FLUNET,
    OWID_MPOX,
    OPENDENGUE_NATIONAL,
    CDC_NNDSS_WEEKLY,
    CDC_COVID_CASE_SURVEILLANCE,
    WHO_EBOLA_SITREPS,
    NCDC_LASSA_SITREPS,
)

BY_ID = {source.dataset_id: source for source in SOURCES}


def get(dataset_id: str) -> Source:
    try:
        return BY_ID[dataset_id]
    except KeyError:
        raise KeyError(f"no source adapter for dataset {dataset_id!r}") from None


def for_disease(code: str) -> tuple[Source, ...]:
    return tuple(source for source in SOURCES if code in source.diseases)


__all__ = ["BY_ID", "SOURCES", "Fetched", "Probe", "Refused", "Source", "for_disease", "get"]
