"""Clinical report as a PDF.

Two rules shape what goes in. The estimate and the patient's own score are always printed
next to each other, never merged into one number, and their disagreement is stated when it
is large. And the disclaimer appears on the first page and in the footer of every page,
because a printed report outlives the screen it was reviewed on.

Direct identifiers are included, since a clinical report without a name is not usable in a
patient's file, but nothing beyond name, code and contact details is carried over.
"""

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

from app.api import serializers
from app.database.models import MedicalDocument, PainAssessment
from app.knowledge import confounders as confounder_kb
from app.knowledge import diseases, factors, qualities, symptoms

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#5b6b7f")
ACCENT = colors.HexColor("#0e7490")
RULE = colors.HexColor("#d7e1ea")
SURFACE = colors.HexColor("#f4f8fb")
WARNING = colors.HexColor("#b45309")
ALERT = colors.HexColor("#b91c1c")

BAND_COLOURS = {
    "NONE": colors.HexColor("#0f766e"),
    "MILD": colors.HexColor("#15803d"),
    "MODERATE": colors.HexColor("#b45309"),
    "SEVERE": colors.HexColor("#c2410c"),
    "EXTREME": colors.HexColor("#b91c1c"),
}

DISCLAIMER = (
    "This report was produced by an AI-assisted research and educational prototype. It does "
    "not constitute a medical diagnosis and does not replace professional clinical "
    "judgement. The estimated pain intensity is a model output reviewed by the clinician "
    "named above. The patient's self-reported score is recorded separately and is never "
    "used as an input to the model."
)
DISAGREEMENT_THRESHOLD = 2.0


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
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=9.2, leading=13, textColor=INK
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED
        ),
        "notice": ParagraphStyle(
            "notice", parent=base["Normal"], fontSize=8.2, leading=11.5, textColor=WARNING
        ),
    }


def _cell(value, style: ParagraphStyle) -> Paragraph:
    """Wrap a value so long text wraps inside its column instead of running off the page."""
    return Paragraph(escape(str(value)), style)


def _table(rows: list[list], widths: list[float], style: ParagraphStyle) -> Table:
    wrapped = [[row[0], *(_cell(value, style) for value in row[1:])] for row in rows]
    table = Table(wrapped, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.6),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("TEXTCOLOR", (1, 0), (-1, -1), INK),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    return table


def _scale(estimate: float | None, self_report: float | None, width: float) -> Drawing:
    """The 0-10 scale with the estimate and the patient's score marked separately."""
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

    # Two markers on one track, so the labels sit on separate lines to stay readable when
    # the estimate and the patient's score are close together.
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
    return ", ".join(resolved) if resolved else "None recorded"


def _footer(canvas, document, synthetic: bool) -> None:
    canvas.saveState()
    if synthetic:
        # Above the rule, so it cannot collide with the disclaimer line below it.
        canvas.setFillColor(WARNING)
        canvas.setFont("Helvetica-Bold", 6.6)
        canvas.drawRightString(A4[0] - 18 * mm, 18 * mm, "SYNTHETIC RECORD")

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
    canvas.setFont("Helvetica", 6.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        18 * mm,
        11.5 * mm,
        "AI-assisted prototype. Not a medical diagnosis and not a substitute for clinical judgement.",
    )
    canvas.drawRightString(A4[0] - 18 * mm, 11.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_report(db: Session, assessment: PainAssessment, doctor) -> bytes:
    from io import BytesIO

    style = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=22 * mm,
        title=f"Pain assessment {assessment.patient.code}",
        author="Pain Score",
    )
    width = document.width

    patient = assessment.patient
    identity = serializers.open_identity(patient)
    prediction = assessment.prediction
    measurement = assessment.measurement
    self_report = assessment.self_report
    history = serializers.history(db, patient)

    story: list = [
        Paragraph("Pain assessment report", style["title"]),
        Paragraph(
            f"Patient {patient.code} &nbsp;·&nbsp; assessed "
            f"{assessment.created_at.strftime('%d %B %Y at %H:%M UTC')} &nbsp;·&nbsp; "
            f"status {assessment.status.value.lower()}",
            style["subtitle"],
        ),
    ]

    if patient.is_synthetic:
        story.append(
            Paragraph(
                "SYNTHETIC RECORD. This patient does not exist and the record contains no "
                "clinical data about any person.",
                style["notice"],
            )
        )
        story.append(Spacer(1, 6))

    story.append(Paragraph("Patient", style["section"]))
    story.append(
        _table(
            [
                ["Name", f"{identity.given_name} {identity.family_name}" if identity else "—"],
                ["Internal identifier", patient.code],
                [
                    "Age and sex",
                    f"{assessment.patient_age_years or '—'} years, {patient.sex.value}",
                ],
                ["Ward", patient.ward or "—"],
                ["Telephone", (identity.phone if identity and identity.phone else "—")],
                [
                    "Emergency contact",
                    (
                        f"{identity.emergency_contact_name} {identity.emergency_contact_phone or ''}".strip()
                        if identity and identity.emergency_contact_name
                        else "—"
                    ),
                ],
                ["Smoking status", patient.smoking_status.value.lower()],
            ],
            [42 * mm, width - 42 * mm],
            style["body"],
        )
    )

    story.append(Paragraph("Assessing clinician", style["section"]))
    story.append(
        _table(
            [
                ["Name", doctor.display_name],
                ["Speciality", doctor.speciality or "—"],
                ["Registration", doctor.registration_number or "—"],
                [
                    "Validated",
                    assessment.validated_at.strftime("%d %B %Y at %H:%M UTC")
                    if assessment.validated_at
                    else "Not validated",
                ],
            ],
            [42 * mm, width - 42 * mm],
            style["body"],
        )
    )

    story.append(Paragraph("Pain description", style["section"]))
    duration = (
        f"{assessment.duration_hours:g} hours" if assessment.duration_hours is not None else "—"
    )
    story.append(
        _table(
            [
                ["Site", ", ".join(serializers.location_labels(assessment)) or "None recorded"],
                [
                    "Structures",
                    ", ".join(serializers.structure_labels(assessment))
                    or "None localised on the anatomical model",
                ],
                [
                    "Character",
                    _labels(
                        [row.quality_code for row in assessment.qualities], qualities.BY_CODE
                    ),
                ],
                ["Onset", assessment.onset.value.lower()],
                ["Duration", duration],
                ["Pattern", assessment.pattern.value.lower()],
                ["Course", assessment.course.value.lower()],
                [
                    "Radiation",
                    (assessment.radiation_description or "Reported, not described")
                    if assessment.radiates
                    else "None reported",
                ],
                [
                    "Timing",
                    ", ".join(
                        label
                        for label, flag in (
                            ("night", assessment.night_pain),
                            ("morning", assessment.morning_pain),
                            ("after activity", assessment.pain_after_activity),
                            ("at rest", assessment.pain_at_rest),
                        )
                        if flag
                    )
                    or "No particular timing recorded",
                ],
            ],
            [42 * mm, width - 42 * mm],
            style["body"],
        )
    )

    aggravating = [
        row.factor_code
        for row in assessment.factors
        if factors.BY_CODE.get(row.factor_code, None)
        and factors.BY_CODE[row.factor_code].kind == factors.AGGRAVATING
    ]
    relieving = [
        row.factor_code
        for row in assessment.factors
        if factors.BY_CODE.get(row.factor_code, None)
        and factors.BY_CODE[row.factor_code].kind == factors.RELIEVING
    ]
    story.append(Paragraph("Symptoms, factors and context", style["section"]))
    story.append(
        _table(
            [
                [
                    "Associated symptoms",
                    _labels(
                        [row.symptom_code for row in assessment.symptoms], symptoms.BY_CODE
                    ),
                ],
                ["Worse with", _labels(aggravating, factors.BY_CODE)],
                ["Better with", _labels(relieving, factors.BY_CODE)],
                [
                    "Recorded context",
                    _labels(
                        [row.confounder_code for row in assessment.confounders],
                        confounder_kb.BY_CODE,
                    ),
                ],
                [
                    "Chronic conditions",
                    _labels([row.disease_code for row in patient.conditions], diseases.BY_CODE),
                ],
                [
                    "Current medication",
                    ", ".join(
                        " ".join(filter(None, [row.name, row.dose, row.frequency]))
                        for row in patient.medications
                    )
                    or "None recorded",
                ],
                ["Allergies", patient.allergies or "None recorded"],
                ["Relevant history", patient.medical_history or "None recorded"],
                ["Previous surgery", patient.previous_surgeries or "None recorded"],
            ],
            [42 * mm, width - 42 * mm],
            style["body"],
        )
    )

    story.append(Paragraph("Measured values", style["section"]))
    if measurement is None:
        story.append(
            Paragraph("No measurements were recorded for this assessment.", style["body"])
        )
    else:
        story.append(
            _table(
                [
                    ["Recorded at", measurement.recorded_at.strftime("%d %B %Y at %H:%M UTC")],
                    ["Heart rate", f"{measurement.hr:g} beats/min" if measurement.hr else "—"],
                    [
                        "Respiratory rate",
                        f"{measurement.resp_rate:g} breaths/min"
                        if measurement.resp_rate
                        else "—",
                    ],
                    [
                        "Blood pressure",
                        f"{measurement.sbp:g}/{measurement.dbp:g} mmHg"
                        if measurement.sbp and measurement.dbp
                        else "—",
                    ],
                    [
                        "Oxygen saturation",
                        f"{measurement.spo2:g} %" if measurement.spo2 else "—",
                    ],
                    [
                        "Temperature",
                        f"{measurement.temperature_c:g} °C"
                        if measurement.temperature_c
                        else "—",
                    ],
                    [
                        "Blood glucose",
                        f"{measurement.glucose_mmol:g} mmol/L"
                        if measurement.glucose_mmol
                        else "—",
                    ],
                    [
                        "Weight, height, BMI",
                        f"{measurement.weight_kg:g} kg, {measurement.height_cm:g} cm, "
                        f"BMI {measurement.bmi}"
                        if measurement.bmi
                        else "—",
                    ],
                ],
                [42 * mm, width - 42 * mm],
                style["body"],
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
            _table(
                [
                    [
                        row.kind.value,
                        f"{row.original_filename} — {row.findings or 'no findings entered'}",
                    ]
                    for row in documents
                ],
                [42 * mm, width - 42 * mm],
                style["body"],
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
        rows = [
            [
                "Estimated pain",
                f"{prediction.estimated_pain:.1f} / 10 ({prediction.band.lower()})",
            ],
            [
                "Uncertainty interval",
                (
                    f"{prediction.interval_low:.1f} to {prediction.interval_high:.1f} "
                    "(10th to 90th model quantile)"
                ),
            ],
            [
                "Patient-reported score",
                f"{self_report.nrs:.0f} / 10" if self_report else "Not recorded",
            ],
            [
                "Clinical priority indicator",
                f"{prediction.priority_score:.1f} / 10",
            ],
            ["Data quality", prediction.data_quality.value.lower()],
            ["Model", prediction.model_version or "—"],
            ["Training data", prediction.dataset_version or "—"],
        ]
        story.append(_table(rows, [42 * mm, width - 42 * mm], style["body"]))

        if self_report is not None and prediction.estimated_pain is not None:
            gap = prediction.estimated_pain - self_report.nrs
            if abs(gap) >= DISAGREEMENT_THRESHOLD:
                story.append(Spacer(1, 5))
                story.append(
                    Paragraph(
                        f"The estimate and the patient's own score differ by {abs(gap):.1f} "
                        f"points. Self-report remains a legitimate clinical reference and the "
                        f"platform does not assume the model is the more accurate of the two.",
                        style["notice"],
                    )
                )

        story.append(Paragraph("What the priority indicator is made of", style["section"]))
        story.append(
            _table(
                [
                    [f"+{factor['points']:g}", factor["label"]]
                    for factor in prediction.priority_factors
                ]
                or [["—", "No contributing factors recorded"]],
                [16 * mm, width - 16 * mm],
                style["body"],
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
            _table(
                [
                    [
                        f"{row.contribution:+.2f}",
                        f"{row.label} — {'raises' if row.contribution > 0 else 'lowers'} the estimate",
                    ]
                    for row in sorted(prediction.contributions, key=lambda row: row.rank)
                ]
                or [["—", "No contributions recorded"]],
                [16 * mm, width - 16 * mm],
                style["body"],
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
            _table(
                [
                    [
                        f"{row.score:.2f}",
                        (
                            f"{serializers.category_out(row).label}. Present: "
                            f"{', '.join(row.matched) or 'none'}. Not recorded: "
                            f"{', '.join(row.missing) or 'none'}."
                        ),
                    ]
                    for row in sorted(
                        prediction.categories, key=lambda row: row.score, reverse=True
                    )
                ]
                or [["—", "No category reached the reporting threshold"]],
                [16 * mm, width - 16 * mm],
                style["body"],
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
                _table(
                    [
                        [
                            note["label"],
                            f"{note['explanation']} "
                            + (
                                f"Values recorded outside range: {', '.join(note['vitals_deranged'])}."
                                if note["vitals_deranged"]
                                else "No affected value is outside its reference range."
                            ),
                        ]
                        for note in prediction.confounder_notes
                    ],
                    [38 * mm, width - 38 * mm],
                    style["body"],
                )
            )

        if prediction.alerts:
            story.append(Paragraph("Clinical alerts", style["section"]))
            alert_rows = [
                [
                    row.severity,
                    _cell(
                        f"{row.label}. {row.advice}"
                        + (
                            " Recorded context that can also explain this: "
                            f"{', '.join(row.context_notes)}."
                            if row.context_notes
                            else ""
                        ),
                        style["body"],
                    ),
                ]
                for row in prediction.alerts
            ]
            table = Table(alert_rows, colWidths=[20 * mm, width - 20 * mm], hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
                        ("TEXTCOLOR", (0, 0), (0, -1), ALERT),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
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
                _table(
                    [
                        ["Not recorded", ", ".join(prediction.missing_fields) or "—"],
                        [
                            "Inconsistencies",
                            " ".join(prediction.quality_issues) or "None found",
                        ],
                    ],
                    [38 * mm, width - 38 * mm],
                    style["body"],
                )
            )

    chart = _trend(history.points, width)
    if chart is not None:
        story.append(
            KeepTogether(
                [
                    Paragraph("Pain over time", style["section"]),
                    chart,
                ]
            )
        )
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
                    f"<b>{note.created_at.strftime('%d %b %Y %H:%M')}</b> — {note.body}",
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
                    f"Report generated {datetime.now(timezone.utc).strftime('%d %B %Y at %H:%M UTC')} "
                    f"· reference {uuid.uuid4().hex[:12]}",
                    style["small"],
                ),
            ]
        )
    )

    def draw(canvas, doc):
        _footer(canvas, doc, patient.is_synthetic)

    document.build(story, onFirstPage=draw, onLaterPages=draw)
    return buffer.getvalue()
