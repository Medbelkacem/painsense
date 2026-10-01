from dataclasses import dataclass


@dataclass(frozen=True)
class Quality:
    code: str
    label: str
    neuropathic_hint: bool = False


QUALITIES = (
    Quality("SHARP", "Sharp"),
    Quality("STABBING", "Stabbing"),
    Quality("BURNING", "Burning", neuropathic_hint=True),
    Quality("ACHING", "Aching"),
    Quality("THROBBING", "Throbbing"),
    Quality("CRAMPING", "Cramping"),
    Quality("PRESSURE", "Pressure"),
    Quality("TIGHTNESS", "Tightness"),
    Quality("ELECTRIC", "Electric-shock-like", neuropathic_hint=True),
    Quality("SHOOTING", "Shooting", neuropathic_hint=True),
    Quality("DULL", "Dull"),
    Quality("TINGLING", "Tingling", neuropathic_hint=True),
    Quality("NUMBNESS", "Associated with numbness", neuropathic_hint=True),
    Quality("HEAVY", "Heavy"),
    Quality("PULSATING", "Pulsating"),
    Quality("OTHER_QUALITY", "Other"),
)

BY_CODE = {quality.code: quality for quality in QUALITIES}
NEUROPATHIC_HINTS = frozenset(q.code for q in QUALITIES if q.neuropathic_hint)
