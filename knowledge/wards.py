WARDS = (
    "Emergency",
    "Surgery",
    "Medicine",
    "Intensive care",
    "Oncology",
    "Rheumatology",
    "Paediatrics",
    "Other",
)

PAEDIATRIC_WARD = "Paediatrics"
#: Wards that admit adults only. Emergency, intensive care and "Other" take anyone.
ADULT_WARDS = frozenset({"Surgery", "Medicine", "Oncology", "Rheumatology"})
PAEDIATRIC_AGE_LIMIT = 16
