import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import serializers
from database.models import MedicalDocument, PainAssessment, User
from knowledge import confounders as confounder_kb
from knowledge import consistency, diseases, factors, qualities, symptoms

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#5b6b7f")
ACCENT = colors.HexColor("#0e7490")
RULE = colors.HexColor("#d7e1ea")
SURFACE = colors.HexColor("#f4f8fb")
WARNING = colors.HexColor("#b45309")
ALERT = colors.HexColor("#b91c1c")
ALERT_WASH = colors.HexColor("#fdf2f2")

BAND_COLOURS = {
    "NONE": colors.HexColor("#0f766e"),
    "MILD": colors.HexColor("#15803d"),
    "MODERATE": colors.HexColor("#b45309"),
    "SEVERE": colors.HexColor("#c2410c"),
    "EXTREME": colors.HexColor("#b91c1c"),
}

FOOTER = "AI-assisted prototype. Not a medical diagnosis and not a substitute for clinical judgement."
DISCLAIMER = (
    "This report was produced by an AI-assisted research and educational prototype. It does "
    "not constitute a medical diagnosis and does not replace professional clinical "
    "judgement. The estimated pain intensity is a model output reviewed by the clinician "
    "named above. The patient's self-reported score is recorded separately and is never "
    "used as an input to the model."
)
DISAGREEMENT_THRESHOLD = 2.0
NONE_RECORDED = "None recorded"

MARGIN = 18 * mm
LABEL_WIDTH = 44 * mm


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=17,
            textColor=INK,
            spaceAfter=2,
            alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontSize=9.5, textColor=MUTED, spaceAfter=10
        ),
        "section": ParagraphStyle(
            "section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            textColor=ACCENT,
            spaceBefore=12,
            spaceAfter=5,
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.6,
            leading=12,
            textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9.2, leading=13, textColor=INK
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED
        ),
        "notice": ParagraphStyle(
            "notice", parent=base["Normal"], fontSize=8.2, leading=11.5, textColor=WARNING
        ),
        "alert": ParagraphStyle(
            "alert",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            textColor=ALERT,
        ),
    }


class _NumberedCanvas(pdfcanvas.Canvas):
    """Draws the footer once the page count is known, and after the body of each page, so
    the running text of the report comes before "Page 1 of 3" rather than after it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total: int) -> None:
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.4)
        self.line(MARGIN, 16 * mm, A4[0] - MARGIN, 16 * mm)
        self.setFont("Helvetica", 6.8)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 11.5 * mm, FOOTER)
        self.drawRightString(A4[0] - MARGIN, 11.5 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def _text(value) -> str:
    value = "" if value is None else str(value).strip()
    return value or NONE_RECORDED


def _pairs(rows: list[tuple], style: dict, width: float) -> Table:
    """A label column and a value column, each cell its own paragraph so a long value wraps
    under itself and never runs into the label beside it."""
    cells = [
        [Paragraph(escape(str(label)), style["label"]), Paragraph(escape(_text(value)), style["body"])]
        for label, value in rows
    ]
    table = Table(cells, colWidths=[LABEL_WIDTH, width - LABEL_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
                ("LINEAFTER", (0, 0), (0, -1), 0.4, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 8),
                ("LEFTPADDING", (1, 0), (1, -1), 10),
            ]
        )
    )
    return table


def _scale(estimate: float | None, self_report: float | None, width: float) -> Drawing:
    height = 44
    drawing = Drawing(width, height)
    track_width = width - 20
    for step in range(10):
        left = 10 + track_width * step / 10
        band = (
            "NONE",
            "MILD",
            "MILD",
            "MILD",
            "MODERATE",
            "MODERATE",
            "MODERATE",
            "SEVERE",
            "SEVERE",
            "SEVERE",
        )[step]
        drawing.add(
            Rect(
                left,
                14,
                track_width / 10,
                9,
                fillColor=BAND_COLOURS[band],
                strokeColor=colors.white,
                strokeWidth=0.6,
                fillOpacity=0.28,
            )
        )
    for step in range(11):
        x = 10 + track_width * step / 10
        drawing.add(String(x - 2, 4, str(step), fontSize=6.5, fillColor=MUTED))

    def marker(value: float, colour, label: str, label_y: float) -> None:
        x = 10 + track_width * min(max(value, 0), 10) / 10
        drawing.add(Line(x, 12, x, 25, strokeColor=colour, strokeWidth=1.8))
        drawing.add(
            String(
                min(x + 3, width - 70),
                label_y,
                label,
                fontSize=7,
                fillColor=colour,
                fontName="Helvetica-Bold",
            )
        )

    if estimate is not None:
        marker(estimate, ACCENT, f"estimate {estimate:.1f}", 35)
    if self_report is not None:
        marker(self_report, INK, f"self-report {self_report:.0f}", 26)
    return drawing


def _trend(points: list, width: float) -> Drawing | None:
    usable = [point for point in points if point.estimated_pain is not None]
    if len(usable) < 2:
        return None

    height = 110
    drawing = Drawing(width, height)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 32, 24, width - 50, height - 42
    estimates = [(index, point.estimated_pain) for index, point in enumerate(usable)]
    reported = [
        (index, point.self_report)
        for index, point in enumerate(usable)
        if point.self_report is not None
    ]
    plot.data = [estimates, reported] if len(reported) >= 2 else [estimates]

    plot.lines[0].strokeColor = ACCENT
    plot.lines[0].strokeWidth = 1.6
    if len(plot.data) > 1:
        plot.lines[1].strokeColor = MUTED
        plot.lines[1].strokeWidth = 1.1
        plot.lines[1].strokeDashArray = (2, 2)

    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax, plot.yValueAxis.valueStep = 0, 10, 2
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, len(usable) - 1
    plot.xValueAxis.valueStep = max(1, (len(usable) - 1) // 5 or 1)
    plot.xValueAxis.labelTextFormat = lambda value: (
        usable[int(value)].created_at.strftime("%d %b") if int(value) < len(usable) else ""
    )
    plot.xValueAxis.labels.fontSize = 6.5
    plot.yValueAxis.labels.fontSize = 6.5
    drawing.add(plot)
    drawing.add(
        String(
            32,
            height - 9,
            "Estimated pain",
            fontSize=6.8,
            fillColor=ACCENT,
            fontName="Helvetica-Bold",
        )
    )
    if len(plot.data) > 1:
        drawing.add(String(110, height - 9, "Patient-reported", fontSize=6.8, fillColor=MUTED))
    return drawing


def _labels(codes, catalogue) -> str:
    resolved = [catalogue[code].label if code in catalogue else code for code in sorted(codes)]
    return ", ".join(resolved)


def _with_note(coded: str, note: str | None) -> str:
    parts = [part for part in (coded, (note or "").strip()) if part]
    return "; ".join(parts)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%d %B %Y at %H:%M UTC")


def build_report(db: Session, assessment: PainAssessment, doctor) -> bytes:
    from io import BytesIO

    style = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=16 * mm,
        bottomMargin=24 * mm,
        title=f"Pain assessment {assessment.patient.code}",
        author="PainSense",
    )
    width = document.width

    patient = assessment.patient
    identity = serializers.open_identity(patient)
    prediction = assessment.prediction
    measurement = assessment.measurement
    self_report = assessment.self_report
    history = serializers.history(db, patient)
    findings = serializers.assessment_findings(assessment)
    validator = db.get(User, assessment.validated_by) if assessment.validated_by else None

    story: list = [
        Paragraph("Pain assessment report", style["title"]),
        Paragraph(
            f"Patient {patient.code} &nbsp;·&nbsp; assessed {_stamp(assessment.created_at)} "
            f"&nbsp;·&nbsp; status {assessment.status.value.lower()}",
            style["subtitle"],
        ),
    ]

    urgent = [f for f in findings if f.level == consistency.URGENT]
    if urgent:
        banner = Table(
            [[Paragraph("Requires urgent clinical review", style["alert"])]]
            + [[Paragraph(escape(f.message), style["body"])] for f in urgent],
            colWidths=[width],
            hAlign="LEFT",
        )
        banner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), ALERT_WASH),
                    ("BOX", (0, 0), (-1, -1), 0.8, ALERT),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story += [banner, Spacer(1, 6)]

    emergency = ""
    if identity and identity.emergency_contact_name:
        emergency = " ".join(
            filter(None, [identity.emergency_contact_name, identity.emergency_contact_phone])
        )
    age = assessment.patient_age_years
    story.append(Paragraph("Patient", style["section"]))
    story.append(
        _pairs(
            [
                ("Name", f"{identity.given_name} {identity.family_name}" if identity else ""),
                ("Internal identifier", patient.code),
                (
                    "Age and sex",
                    f"{age} {'year' if age == 1 else 'years'}, {patient.sex.value}"
                    if age is not None
                    else patient.sex.value,
                ),
                ("Ward", patient.ward),
                ("Telephone", identity.phone if identity else None),
                ("Emergency contact", emergency),
                ("Smoking status", patient.smoking_status.value.capitalize()),
            ],
            style,
            width,
        )
    )

    if assessment.validated_at:
        validated = f"Validated on {_stamp(assessment.validated_at)}"
        if validator is not None:
            validated = f"Validated by {validator.display_name} on {_stamp(assessment.validated_at)}"
    else:
        validated = "Not validated"
    story.append(Paragraph("Assessing clinician", style["section"]))
    story.append(
        _pairs(
            [
                ("Name", doctor.display_name),
                ("Speciality", doctor.speciality),
                ("Registration number", doctor.registration_number),
                ("Validated", validated),
            ],
            style,
            width,
        )
    )

    timing = ", ".join(
        label
        for label, flag in (
            ("morning", assessment.morning_pain),
            ("afternoon", assessment.afternoon_pain),
            ("evening", assessment.evening_pain),
            ("night", assessment.night_pain),
            ("after activity", assessment.pain_after_activity),
            ("at rest", assessment.pain_at_rest),
        )
        if flag
    )
    story.append(Paragraph("Pain description", style["section"]))
    story.append(
        _pairs(
            [
                ("Site", ", ".join(serializers.location_labels(assessment))),
                (
                    "Structures",
                    ", ".join(serializers.structure_labels(assessment))
                    or "None localised on the anatomical model",
                ),
                (
                    "Character",
                    _labels([row.quality_code for row in assessment.qualities], qualities.BY_CODE),
                ),
                ("Onset", assessment.onset.value.capitalize()),
                (
                    "Duration",
                    serializers.duration_label(assessment.duration_value, assessment.duration_unit),
                ),
                ("Pattern", assessment.pattern.value.capitalize()),
                ("Course", assessment.course.value.capitalize()),
                (
                    "Radiation",
                    (assessment.radiation_description or "Reported, not described")
                    if assessment.radiates
                    else "None reported",
                ),
                ("Timing", timing or "No particular timing recorded"),
            ],
            style,
            width,
        )
    )

    aggravating = [
        row.factor_code
        for row in assessment.factors
        if factors.BY_CODE.get(row.factor_code)
        and factors.BY_CODE[row.factor_code].kind == factors.AGGRAVATING
    ]
    relieving = [
        row.factor_code
        for row in assessment.factors
        if factors.BY_CODE.get(row.factor_code)
        and factors.BY_CODE[row.factor_code].kind == factors.RELIEVING
    ]
    story.append(Paragraph("Symptoms, factors and context", style["section"]))
    story.append(
        _pairs(
            [
                (
                    "Associated symptoms",
                    _with_note(
                        _labels([row.symptom_code for row in assessment.symptoms], symptoms.BY_CODE),
                        assessment.symptoms_note,
                    ),
                ),
                (
                    "Worse with",
                    _with_note(_labels(aggravating, factors.BY_CODE), assessment.aggravating_note),
                ),
                (
                    "Better with",
                    _with_note(_labels(relieving, factors.BY_CODE), assessment.relieving_note),
                ),
                (
                    "Recorded context",
                    _labels(
                        [row.confounder_code for row in assessment.confounders],
                        confounder_kb.BY_CODE,
                    ),
                ),
                (
                    "Chronic conditions",
                    _labels([row.disease_code for row in patient.conditions], diseases.BY_CODE),
                ),
                (
                    "Current medication",
                    ", ".join(
                        " ".join(filter(None, [row.name, row.dose, row.frequency]))
                        for row in patient.medications
                    ),
                ),
                ("Allergies", patient.allergies),
                ("Relevant history", patient.medical_history),
                ("Previous surgery", patient.previous_surgeries),
            ],
            style,
            width,
        )
    )

    warnings = [f for f in findings if f.level != consistency.URGENT]
    if warnings:
        story.append(Paragraph("Consistency checks", style["section"]))
        for finding in warnings:
            story.append(Paragraph(escape(finding.message), style["notice"]))
            story.append(Spacer(1, 2))

    story.append(Paragraph("Self-reported intensity", style["section"]))
    story.append(
        _pairs(
            [
                (
                    "Patient-reported score",
                    f"{self_report.nrs:g} / 10 on the {self_report.scale_code} scale"
                    if self_report
                    else "Not recorded",
                ),
                ("Note", self_report.note if self_report else None),
            ],
            style,
            width,
        )
    )
    story.append(
        Paragraph(
            "The patient's own score is recorded for comparison only. It is never an input "
            "to the model.",
            style["small"],
        )
    )

    story.append(Paragraph("Measured values", style["section"]))
    if measurement is None:
        story.append(
            Paragraph("No measurements were recorded for this assessment.", style["body"])
        )
    else:

        def reading(value, unit: str) -> str:
            return f"{value:g} {unit}" if value is not None else ""

        story.append(
            _pairs(
                [
                    ("Recorded at", _stamp(measurement.recorded_at)),
                    ("Heart rate", reading(measurement.hr, "beats/min")),
                    ("Respiratory rate", reading(measurement.resp_rate, "breaths/min")),
                    (
                        "Blood pressure",
                        f"{measurement.sbp:g}/{measurement.dbp:g} mmHg"
                        if measurement.sbp and measurement.dbp
                        else "",
                    ),
                    ("Oxygen saturation", reading(measurement.spo2, "%")),
                    ("Temperature", reading(measurement.temperature_c, "°C")),
                    ("Blood glucose", reading(measurement.glucose_mmol, "mmol/L")),
                    (
                        "Weight, height, BMI",
                        f"{measurement.weight_kg:g} kg, {measurement.height_cm:g} cm, "
                        f"BMI {measurement.bmi}"
                        if measurement.bmi
                        else "",
                    ),
                ],
                style,
                width,
            )
        )

    documents = list(
        db.scalars(
            select(MedicalDocument)
            .where(MedicalDocument.assessment_id == assessment.id)
            .order_by(MedicalDocument.uploaded_at)
        )
    )
    story.append(Paragraph("Investigations on file", style["section"]))
    if not documents:
        story.append(Paragraph("No documents attached to this assessment.", style["body"]))
    else:
        story.append(
            _pairs(
                [
                    (
                        row.kind.value.replace("_", " ").capitalize(),
                        f"{row.original_filename}: {row.findings or 'no findings entered'}",
                    )
                    for row in documents
                ],
                style,
                width,
            )
        )

    story.append(Paragraph("Estimated pain intensity", style["section"]))

    if prediction is None:
        story.append(
            Paragraph("No estimate has been produced for this assessment.", style["body"])
        )
    elif prediction.refused:
        story.append(
            Paragraph(prediction.refusal_reason or "Estimate withheld.", style["notice"])
        )
    else:
        story.append(
            _scale(
                prediction.estimated_pain,
                self_report.nrs if self_report else None,
                width,
            )
        )
        story.append(Spacer(1, 6))
        story.append(
            _pairs(
                [
                    (
                        "Estimated pain",
                        f"{prediction.estimated_pain:.1f} / 10 ({prediction.band.lower()})",
                    ),
                    (
                        "Uncertainty interval",
                        (
                            f"{prediction.interval_low:.1f} to {prediction.interval_high:.1f} "
                            "(10th to 90th model quantile)"
                        ),
                    ),
                    (
                        "Patient-reported score",
                        f"{self_report.nrs:.0f} / 10" if self_report else "Not recorded",
                    ),
                    ("Clinical priority indicator", f"{prediction.priority_score:.1f} / 10"),
                    ("Data quality", prediction.data_quality.value.capitalize()),
                    ("Model", prediction.model_version),
                    ("Training data", prediction.dataset_version),
                ],
                style,
                width,
            )
        )

        if self_report is not None and prediction.estimated_pain is not None:
            gap = prediction.estimated_pain - self_report.nrs
            if abs(gap) >= DISAGREEMENT_THRESHOLD:
                story.append(Spacer(1, 5))
                story.append(
                    Paragraph(
                        f"The estimate and the patient's own score differ by {abs(gap):.1f} "
                        "points. Self-report remains a legitimate clinical reference and the "
                        "platform does not assume the model is the more accurate of the two.",
                        style["notice"],
                    )
                )

        story.append(Paragraph("What the priority indicator is made of", style["section"]))
        story.append(
            _pairs(
                [(f"+{factor['points']:g}", factor["label"]) for factor in prediction.priority_factors]
                or [("", "No contributing factors recorded")],
                style,
                width,
            )
        )
        story.append(
            Paragraph(
                "The priority indicator is an arithmetic of the findings above. It is not a "
                "probability of death, of an emergency, or of any diagnosis.",
                style["small"],
            )
        )

        story.append(Paragraph("Model contributions", style["section"]))
        story.append(
            _pairs(
                [
                    (
                        f"{row.contribution:+.2f}",
                        f"{row.label}: {'raises' if row.contribution > 0 else 'lowers'} the estimate",
                    )
                    for row in sorted(prediction.contributions, key=lambda row: row.rank)
                ]
                or [("", "No contributions recorded")],
                style,
                width,
            )
        )
        story.append(
            Paragraph(
                "These values are contributions to this model output. They are not evidence "
                "that a factor caused the pain.",
                style["small"],
            )
        )

        story.append(Paragraph("Potentially compatible categories", style["section"]))
        story.append(
            _pairs(
                [
                    (
                        f"{row.score:.2f}",
                        (
                            f"{serializers.category_out(row).label}. Present: "
                            f"{', '.join(row.matched) or 'none'}. Not recorded: "
                            f"{', '.join(row.missing) or 'none'}."
                        ),
                    )
                    for row in sorted(prediction.categories, key=lambda row: row.score, reverse=True)
                ]
                or [("", "No category reached the reporting threshold")],
                style,
                width,
            )
        )
        story.append(
            Paragraph(
                "Categories are patterns the recorded information is compatible with. None of "
                "them is a diagnosis.",
                style["small"],
            )
        )

        if prediction.confounder_notes:
            story.append(Paragraph("Context affecting the measured values", style["section"]))
            story.append(
                _pairs(
                    [
                        (
                            note["label"],
                            f"{note['explanation']} "
                            + (
                                f"Values recorded outside range: {', '.join(note['vitals_deranged'])}."
                                if note["vitals_deranged"]
                                else "No affected value is outside its reference range."
                            ),
                        )
                        for note in prediction.confounder_notes
                    ],
                    style,
                    width,
                )
            )

        if prediction.alerts:
            story.append(Paragraph("Clinical alerts", style["section"]))
            alert_rows = [
                [
                    Paragraph(row.severity, style["alert"]),
                    Paragraph(
                        escape(
                            f"{row.label}. {row.advice}"
                            + (
                                " Recorded context that can also explain this: "
                                f"{', '.join(row.context_notes)}."
                                if row.context_notes
                                else ""
                            )
                        ),
                        style["body"],
                    ),
                ]
                for row in prediction.alerts
            ]
            table = Table(alert_rows, colWidths=[22 * mm, width - 22 * mm], hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(table)
            story.append(
                Paragraph(
                    "An alert reports a feature of the recorded information that usually "
                    "warrants prompt review. It is not a diagnosis.",
                    style["small"],
                )
            )

        if prediction.missing_fields or prediction.quality_issues:
            story.append(Paragraph("Data quality", style["section"]))
            story.append(
                _pairs(
                    [
                        ("Not recorded", ", ".join(prediction.missing_fields)),
                        ("Inconsistencies", " ".join(prediction.quality_issues) or "None found"),
                    ],
                    style,
                    width,
                )
            )

    chart = _trend(history.points, width)
    if chart is not None:
        story.append(KeepTogether([Paragraph("Pain over time", style["section"]), chart]))
        story.append(
            Paragraph(
                f"{len(history.points)} assessments on file. Trend {history.trend.lower()}"
                + (
                    f", {history.change_from_previous:+.1f} since the previous assessment."
                    if history.change_from_previous is not None
                    else "."
                ),
                style["small"],
            )
        )

    if assessment.notes:
        story.append(Paragraph("Clinical notes", style["section"]))
        for note in sorted(assessment.notes, key=lambda row: row.created_at):
            story.append(
                Paragraph(
                    f"<b>{note.created_at.strftime('%d %b %Y %H:%M')}</b> {escape(note.body)}",
                    style["body"],
                )
            )
            story.append(Spacer(1, 3))

    story.append(Spacer(1, 10))
    story.append(
        KeepTogether(
            [
                Paragraph("Disclaimer", style["section"]),
                Paragraph(DISCLAIMER, style["small"]),
                Spacer(1, 4),
                Paragraph(
                    f"Report generated {_stamp(datetime.now(timezone.utc))} "
                    f"· reference {uuid.uuid4().hex[:12]}",
                    style["small"],
                ),
            ]
        )
    )

    document.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
