"""Anatomical ontology for the 3D localisation module.

Three levels, in this order: a region holds structure types, and a structure type holds
structures. A structure is the thing a clinician points at on the model; its `code` is the
stable identifier that gets stored, and the label is only what the interface prints. A code
an assessment already references must never change meaning, exactly as in
app.knowledge.locations.

Two axes are deliberately kept apart:

- `location` is where the pain is recorded, as a code from the existing pain-location
  taxonomy. Every structure projects onto one, so a structure selected on the model feeds
  the question engine, the rule engine, the cause knowledge base and the model features
  through machinery that already exists and needs no knowledge of anatomy.
- `region` is not stored on the structure at all. It is read back from the projected
  location, so there is one answer to which region a structure belongs to rather than two
  that can drift apart.

`REGION` is a structure type like the others and holds the body-surface zones. Those are
what a clinician selects when the exact structure is not known or not represented: the
record then says "lower back" rather than guessing at a facet joint.

`latin` carries the Terminologia Anatomica term where there is a settled one. It is left
empty for the surface zones and for the few clinical groupings that have no single Latin
name, rather than inventing one. `external_ref` is the slot for a deployment that maps
these codes onto FMA, UBERON or SNOMED CT; nothing is shipped in it, because a wrong
identifier in a clinical record is worse than an absent one.
"""

from dataclasses import dataclass

from app.knowledge import locations

# --- structure types, the middle level of the ontology ------------------------------

REGION = "REGION"
BONE = "BONE"
JOINT = "JOINT"
MUSCLE = "MUSCLE"
TENDON = "TENDON"
ORGAN = "ORGAN"
NERVE = "NERVE"
VESSEL = "VESSEL"


@dataclass(frozen=True)
class StructureType:
    code: str
    label: str
    description: str
    order: int


STRUCTURE_TYPES = (
    StructureType(
        REGION,
        "Body region",
        "Surface zones, for when the exact structure is not known or not represented.",
        10,
    ),
    StructureType(MUSCLE, "Muscles", "Skeletal muscles and muscle groups.", 20),
    StructureType(
        TENDON, "Tendons and ligaments", "Tendons, ligaments, fasciae and menisci.", 30
    ),
    StructureType(BONE, "Bones", "Bones and cartilage.", 40),
    StructureType(JOINT, "Joints", "Synovial joints, symphyses and intervertebral discs.", 50),
    StructureType(ORGAN, "Organs", "Viscera and other organs.", 60),
    StructureType(NERVE, "Nerves", "Nerves, nerve roots and plexuses.", 70),
    StructureType(VESSEL, "Vessels", "Arteries and veins.", 80),
)

TYPE_BY_CODE = {entry.code: entry for entry in STRUCTURE_TYPES}
# Everything except the surface zones: selecting one of these means the anatomy was
# identified rather than approximated.
EXACT_TYPES = frozenset(TYPE_BY_CODE) - {REGION}

# --- laterality --------------------------------------------------------------------

PAIRED = "PAIRED"
MIDLINE = "MIDLINE"
LEFT = "LEFT"
RIGHT = "RIGHT"

LATERALITIES = (PAIRED, MIDLINE, LEFT, RIGHT)

# The sides an assessment may record for a structure, given its laterality.
SIDES_FOR_LATERALITY = {
    PAIRED: ("LEFT", "RIGHT", "BILATERAL"),
    MIDLINE: ("MIDLINE",),
    LEFT: ("LEFT",),
    RIGHT: ("RIGHT",),
}


@dataclass(frozen=True)
class Structure:
    code: str
    label: str
    type: str
    location: str
    laterality: str = MIDLINE
    latin: str = ""
    # The pain-location taxonomy names the two sides of the chest and the abdominal
    # quadrants separately. Where it does, a paired structure says which code each side
    # projects onto; everywhere else both sides share `location` and are told apart by the
    # side recorded on the assessment.
    location_left: str = ""
    location_right: str = ""
    # Alternative wording a clinician may search for. Not shown, only matched.
    synonyms: tuple[str, ...] = ()
    # Restricts the structure to patients of that sex. None means it is offered to everyone.
    sex: str | None = None
    note: str = ""

    @property
    def region(self) -> str:
        return locations.BY_CODE[self.location].region

    def location_for(self, side: str) -> str:
        """The pain-location code this structure projects onto for a recorded side."""
        if side == "LEFT" and self.location_left:
            return self.location_left
        if side == "RIGHT" and self.location_right:
            return self.location_right
        return self.location

    def accepts(self, side: str) -> bool:
        return side in SIDES_FOR_LATERALITY[self.laterality]

    def default_side(self) -> str:
        return SIDES_FOR_LATERALITY[self.laterality][0]


# Where the pain-location taxonomy names the sides separately, a paired structure borrows
# the pair rather than repeating it at every entry.
_CHEST = {"location_left": "CHEST_LEFT", "location_right": "CHEST_RIGHT"}
_ABD_UPPER = {"location_left": "ABD_LUQ", "location_right": "ABD_RUQ"}
_ABD_LOWER = {"location_left": "ABD_LLQ", "location_right": "ABD_RLQ"}


# --- surface zones -----------------------------------------------------------------
# The body as a clinician points at it. One per pain-location code that can be the whole
# answer, so a record is never forced to name a structure the examination did not identify.

SURFACE_ZONES = (
    Structure("REG_HEAD", "Head", REGION, "HEAD"),
    Structure("REG_FOREHEAD", "Forehead", REGION, "FOREHEAD", synonyms=("frontal",)),
    Structure("REG_TEMPLE", "Temple", REGION, "TEMPLE", PAIRED, synonyms=("temporal",)),
    Structure("REG_OCCIPUT", "Back of the head", REGION, "OCCIPUT", synonyms=("occipital",)),
    Structure("REG_FACE", "Face", REGION, "FACE"),
    Structure("REG_ORBIT", "Around the eye", REGION, "EYE", PAIRED, synonyms=("periorbital",)),
    Structure("REG_EAR", "Ear", REGION, "EAR", PAIRED),
    Structure("REG_JAW", "Jaw", REGION, "JAW", PAIRED),
    Structure("REG_NECK_FRONT", "Front of the neck", REGION, "NECK"),
    Structure("REG_NECK_BACK", "Back of the neck", REGION, "BACK_CERVICAL"),
    Structure("REG_CHEST_CENTRAL", "Central chest", REGION, "CHEST_CENTRAL"),
    Structure("REG_CHEST_WALL", "Chest wall", REGION, "CHEST", PAIRED, **_CHEST),
    Structure("REG_CHEST_DIFFUSE", "Chest, diffusely", REGION, "CHEST_DIFFUSE"),
    Structure("REG_BREAST", "Breast", REGION, "BREAST", PAIRED),
    Structure("REG_UPPER_BACK", "Upper back", REGION, "BACK_THORACIC"),
    Structure("REG_LOWER_BACK", "Lower back", REGION, "BACK_LUMBAR", synonyms=("loin",)),
    Structure("REG_SACRAL", "Sacral area", REGION, "BACK_SACRAL"),
    Structure("REG_EPIGASTRIUM", "Epigastrium", REGION, "ABD_EPIGASTRIC"),
    Structure("REG_ABD_RUQ", "Right upper quadrant", REGION, "ABD_RUQ", RIGHT),
    Structure("REG_ABD_LUQ", "Left upper quadrant", REGION, "ABD_LUQ", LEFT),
    Structure("REG_UMBILICAL", "Around the navel", REGION, "ABD_PERIUMBILICAL"),
    Structure("REG_ABD_RLQ", "Right lower quadrant", REGION, "ABD_RLQ", RIGHT),
    Structure("REG_ABD_LLQ", "Left lower quadrant", REGION, "ABD_LLQ", LEFT),
    Structure("REG_ABD_DIFFUSE", "Abdomen, diffusely", REGION, "ABD_DIFFUSE"),
    Structure("REG_SUPRAPUBIC", "Suprapubic area", REGION, "ABD_SUPRAPUBIC"),
    Structure("REG_PELVIS", "Pelvis", REGION, "PELVIS"),
    Structure("REG_GENITAL", "Genital region", REGION, "GENITAL"),
    Structure("REG_BUTTOCK", "Buttock", REGION, "HIP", PAIRED, synonyms=("gluteal",)),
    Structure("REG_SHOULDER", "Shoulder", REGION, "SHOULDER", PAIRED),
    Structure("REG_UPPER_ARM", "Upper arm", REGION, "ARM", PAIRED),
    Structure("REG_ELBOW", "Elbow", REGION, "ELBOW", PAIRED),
    Structure("REG_FOREARM", "Forearm", REGION, "FOREARM", PAIRED),
    Structure("REG_WRIST", "Wrist", REGION, "WRIST", PAIRED),
    Structure("REG_HAND", "Hand", REGION, "HAND", PAIRED),
    Structure("REG_FINGERS", "Fingers", REGION, "FINGER", PAIRED),
    Structure("REG_HIP", "Hip", REGION, "HIP", PAIRED),
    Structure("REG_THIGH", "Thigh", REGION, "THIGH", PAIRED),
    Structure("REG_KNEE", "Knee", REGION, "KNEE", PAIRED),
    Structure("REG_LEG", "Lower leg", REGION, "LEG", PAIRED, synonyms=("calf", "shin")),
    Structure("REG_ANKLE", "Ankle", REGION, "ANKLE", PAIRED),
    Structure("REG_FOOT", "Foot", REGION, "FOOT", PAIRED, synonyms=("heel", "sole")),
    Structure("REG_TOES", "Toes", REGION, "TOE", PAIRED),
    Structure(
        "REG_GENERALIZED",
        "Generalised, no single site",
        REGION,
        "GENERALIZED",
        synonyms=("all over", "widespread"),
        note="For pain the examination cannot localise to one part of the body.",
    ),
    Structure(
        "REG_UNSPECIFIED",
        "Other or unspecified site",
        REGION,
        "UNSPECIFIED",
        note="For a site the model does not represent. Describe it in the clinical note.",
    ),
)


# --- bones -------------------------------------------------------------------------

BONES = (
    Structure("BONE_CRANIUM", "Skull", BONE, "HEAD", MIDLINE, "Cranium"),
    Structure("BONE_MANDIBLE", "Mandible", BONE, "JAW", MIDLINE, "Mandibula"),
    Structure("BONE_MAXILLA", "Maxilla", BONE, "FACE", PAIRED, "Maxilla"),
    Structure(
        "BONE_CERVICAL_SPINE",
        "Cervical vertebrae",
        BONE,
        "BACK_CERVICAL",
        MIDLINE,
        "Vertebrae cervicales",
        synonyms=("neck spine",),
    ),
    Structure(
        "BONE_THORACIC_SPINE",
        "Thoracic vertebrae",
        BONE,
        "BACK_THORACIC",
        MIDLINE,
        "Vertebrae thoracicae",
    ),
    Structure(
        "BONE_LUMBAR_SPINE",
        "Lumbar vertebrae",
        BONE,
        "BACK_LUMBAR",
        MIDLINE,
        "Vertebrae lumbales",
    ),
    Structure("BONE_SACRUM", "Sacrum", BONE, "BACK_SACRAL", MIDLINE, "Os sacrum"),
    Structure("BONE_COCCYX", "Coccyx", BONE, "BACK_SACRAL", MIDLINE, "Os coccygis"),
    Structure("BONE_STERNUM", "Sternum", BONE, "CHEST_CENTRAL", MIDLINE, "Sternum"),
    Structure("BONE_RIB", "Ribs", BONE, "CHEST", PAIRED, "Costae", **_CHEST),
    Structure(
        "BONE_COSTAL_CARTILAGE",
        "Costal cartilage",
        BONE,
        "CHEST_CENTRAL",
        PAIRED,
        "Cartilagines costales",
    ),
    Structure("BONE_CLAVICLE", "Clavicle", BONE, "SHOULDER", PAIRED, "Clavicula"),
    Structure(
        "BONE_SCAPULA",
        "Scapula",
        BONE,
        "SHOULDER",
        PAIRED,
        "Scapula",
        synonyms=("shoulder blade",),
    ),
    Structure(
        "BONE_HIP_BONE", "Hip bone", BONE, "PELVIS", PAIRED, "Os coxae", synonyms=("ilium",)
    ),
    Structure("BONE_HUMERUS", "Humerus", BONE, "ARM", PAIRED, "Humerus"),
    Structure("BONE_RADIUS", "Radius", BONE, "FOREARM", PAIRED, "Radius"),
    Structure("BONE_ULNA", "Ulna", BONE, "FOREARM", PAIRED, "Ulna"),
    Structure("BONE_CARPUS", "Carpal bones", BONE, "WRIST", PAIRED, "Ossa carpi"),
    Structure("BONE_METACARPUS", "Metacarpal bones", BONE, "HAND", PAIRED, "Ossa metacarpi"),
    Structure("BONE_HAND_PHALANGES", "Finger bones", BONE, "FINGER", PAIRED, "Phalanges manus"),
    Structure("BONE_FEMUR", "Femur", BONE, "THIGH", PAIRED, "Os femoris"),
    Structure(
        "BONE_PATELLA", "Patella", BONE, "KNEE", PAIRED, "Patella", synonyms=("kneecap",)
    ),
    Structure("BONE_TIBIA", "Tibia", BONE, "LEG", PAIRED, "Tibia", synonyms=("shin bone",)),
    Structure("BONE_FIBULA", "Fibula", BONE, "LEG", PAIRED, "Fibula"),
    Structure("BONE_TARSUS", "Tarsal bones", BONE, "FOOT", PAIRED, "Ossa tarsi"),
    Structure(
        "BONE_CALCANEUS",
        "Calcaneus",
        BONE,
        "FOOT",
        PAIRED,
        "Calcaneus",
        synonyms=("heel bone",),
    ),
    Structure("BONE_METATARSUS", "Metatarsal bones", BONE, "FOOT", PAIRED, "Ossa metatarsi"),
    Structure("BONE_FOOT_PHALANGES", "Toe bones", BONE, "TOE", PAIRED, "Phalanges pedis"),
)


# --- joints ------------------------------------------------------------------------

JOINTS = (
    Structure(
        "JOINT_TMJ",
        "Temporomandibular joint",
        JOINT,
        "JAW",
        PAIRED,
        "Articulatio temporomandibularis",
        synonyms=("TMJ",),
    ),
    Structure(
        "JOINT_CERVICAL_FACET",
        "Cervical facet joints",
        JOINT,
        "BACK_CERVICAL",
        PAIRED,
        "Articulationes zygapophysiales",
    ),
    Structure(
        "JOINT_CERVICAL_DISC",
        "Cervical intervertebral disc",
        JOINT,
        "BACK_CERVICAL",
        MIDLINE,
        "Discus intervertebralis",
    ),
    Structure(
        "JOINT_THORACIC_FACET",
        "Thoracic facet joints",
        JOINT,
        "BACK_THORACIC",
        PAIRED,
        "Articulationes zygapophysiales",
    ),
    Structure(
        "JOINT_LUMBAR_FACET",
        "Lumbar facet joints",
        JOINT,
        "BACK_LUMBAR",
        PAIRED,
        "Articulationes zygapophysiales",
    ),
    Structure(
        "JOINT_LUMBAR_DISC",
        "Lumbar intervertebral disc",
        JOINT,
        "BACK_LUMBAR",
        MIDLINE,
        "Discus intervertebralis",
    ),
    Structure(
        "JOINT_SACROILIAC",
        "Sacroiliac joint",
        JOINT,
        "BACK_SACRAL",
        PAIRED,
        "Articulatio sacroiliaca",
    ),
    Structure(
        "JOINT_COSTOSTERNAL",
        "Costosternal joints",
        JOINT,
        "CHEST_CENTRAL",
        PAIRED,
        "Articulationes sternocostales",
    ),
    Structure(
        "JOINT_PUBIC_SYMPHYSIS",
        "Pubic symphysis",
        JOINT,
        "ABD_SUPRAPUBIC",
        MIDLINE,
        "Symphysis pubica",
    ),
    Structure(
        "JOINT_SHOULDER", "Shoulder joint", JOINT, "SHOULDER", PAIRED, "Articulatio humeri"
    ),
    Structure(
        "JOINT_ACROMIOCLAVICULAR",
        "Acromioclavicular joint",
        JOINT,
        "SHOULDER",
        PAIRED,
        "Articulatio acromioclavicularis",
    ),
    Structure("JOINT_ELBOW", "Elbow joint", JOINT, "ELBOW", PAIRED, "Articulatio cubiti"),
    Structure(
        "JOINT_WRIST", "Wrist joint", JOINT, "WRIST", PAIRED, "Articulatio radiocarpalis"
    ),
    Structure(
        "JOINT_HAND_SMALL",
        "Finger joints",
        JOINT,
        "FINGER",
        PAIRED,
        "Articulationes digitorum manus",
    ),
    Structure("JOINT_HIP", "Hip joint", JOINT, "HIP", PAIRED, "Articulatio coxae"),
    Structure("JOINT_KNEE", "Knee joint", JOINT, "KNEE", PAIRED, "Articulatio genus"),
    Structure("JOINT_ANKLE", "Ankle joint", JOINT, "ANKLE", PAIRED, "Articulatio talocruralis"),
    Structure(
        "JOINT_FOOT_SMALL",
        "Toe joints",
        JOINT,
        "TOE",
        PAIRED,
        "Articulationes digitorum pedis",
    ),
)


# --- muscles -----------------------------------------------------------------------

MUSCLES = (
    Structure("MUS_TEMPORALIS", "Temporalis", MUSCLE, "TEMPLE", PAIRED, "Musculus temporalis"),
    Structure("MUS_MASSETER", "Masseter", MUSCLE, "JAW", PAIRED, "Musculus masseter"),
    Structure(
        "MUS_STERNOCLEIDOMASTOID",
        "Sternocleidomastoid",
        MUSCLE,
        "NECK",
        PAIRED,
        "Musculus sternocleidomastoideus",
    ),
    Structure("MUS_SCALENE", "Scalene muscles", MUSCLE, "NECK", PAIRED, "Musculi scaleni"),
    Structure(
        "MUS_LEVATOR_SCAPULAE",
        "Levator scapulae",
        MUSCLE,
        "BACK_CERVICAL",
        PAIRED,
        "Musculus levator scapulae",
    ),
    Structure(
        "MUS_TRAPEZIUS",
        "Trapezius",
        MUSCLE,
        "BACK_THORACIC",
        PAIRED,
        "Musculus trapezius",
        synonyms=("upper back", "shoulder girdle"),
    ),
    Structure(
        "MUS_ERECTOR_SPINAE_THORACIC",
        "Thoracic paraspinal muscles",
        MUSCLE,
        "BACK_THORACIC",
        PAIRED,
        "Musculi erectores spinae",
    ),
    Structure(
        "MUS_ERECTOR_SPINAE_LUMBAR",
        "Lumbar paraspinal muscles",
        MUSCLE,
        "BACK_LUMBAR",
        PAIRED,
        "Musculi erectores spinae",
        synonyms=("low back muscles",),
    ),
    Structure(
        "MUS_QUADRATUS_LUMBORUM",
        "Quadratus lumborum",
        MUSCLE,
        "BACK_LUMBAR",
        PAIRED,
        "Musculus quadratus lumborum",
    ),
    Structure(
        "MUS_LATISSIMUS_DORSI",
        "Latissimus dorsi",
        MUSCLE,
        "BACK_THORACIC",
        PAIRED,
        "Musculus latissimus dorsi",
    ),
    Structure(
        "MUS_PECTORALIS_MAJOR",
        "Pectoralis major",
        MUSCLE,
        "CHEST",
        PAIRED,
        "Musculus pectoralis major",
        **_CHEST,
    ),
    Structure(
        "MUS_INTERCOSTAL",
        "Intercostal muscles",
        MUSCLE,
        "CHEST",
        PAIRED,
        "Musculi intercostales",
        **_CHEST,
    ),
    Structure(
        "MUS_SERRATUS_ANTERIOR",
        "Serratus anterior",
        MUSCLE,
        "CHEST",
        PAIRED,
        "Musculus serratus anterior",
        **_CHEST,
    ),
    Structure("MUS_DIAPHRAGM", "Diaphragm", MUSCLE, "CHEST_DIFFUSE", MIDLINE, "Diaphragma"),
    Structure(
        "MUS_RECTUS_ABDOMINIS",
        "Rectus abdominis",
        MUSCLE,
        "ABD_PERIUMBILICAL",
        PAIRED,
        "Musculus rectus abdominis",
    ),
    Structure(
        "MUS_ABDOMINAL_OBLIQUE",
        "Abdominal oblique muscles",
        MUSCLE,
        "ABD_DIFFUSE",
        PAIRED,
        "Musculi obliqui abdominis",
    ),
    Structure("MUS_DELTOID", "Deltoid", MUSCLE, "SHOULDER", PAIRED, "Musculus deltoideus"),
    Structure(
        "MUS_SUPRASPINATUS",
        "Supraspinatus",
        MUSCLE,
        "SHOULDER",
        PAIRED,
        "Musculus supraspinatus",
    ),
    Structure(
        "MUS_BICEPS_BRACHII", "Biceps brachii", MUSCLE, "ARM", PAIRED, "Musculus biceps brachii"
    ),
    Structure(
        "MUS_TRICEPS_BRACHII",
        "Triceps brachii",
        MUSCLE,
        "ARM",
        PAIRED,
        "Musculus triceps brachii",
    ),
    Structure(
        "MUS_FOREARM_FLEXORS",
        "Forearm flexor muscles",
        MUSCLE,
        "FOREARM",
        PAIRED,
        "Musculi flexores antebrachii",
    ),
    Structure(
        "MUS_FOREARM_EXTENSORS",
        "Forearm extensor muscles",
        MUSCLE,
        "FOREARM",
        PAIRED,
        "Musculi extensores antebrachii",
    ),
    Structure(
        "MUS_GLUTEUS_MAXIMUS",
        "Gluteus maximus",
        MUSCLE,
        "HIP",
        PAIRED,
        "Musculus gluteus maximus",
    ),
    Structure(
        "MUS_GLUTEUS_MEDIUS", "Gluteus medius", MUSCLE, "HIP", PAIRED, "Musculus gluteus medius"
    ),
    Structure("MUS_PIRIFORMIS", "Piriformis", MUSCLE, "HIP", PAIRED, "Musculus piriformis"),
    Structure("MUS_ILIOPSOAS", "Iliopsoas", MUSCLE, "HIP", PAIRED, "Musculus iliopsoas"),
    Structure(
        "MUS_QUADRICEPS",
        "Quadriceps femoris",
        MUSCLE,
        "THIGH",
        PAIRED,
        "Musculus quadriceps femoris",
    ),
    Structure(
        "MUS_HAMSTRINGS",
        "Hamstring muscles",
        MUSCLE,
        "THIGH",
        PAIRED,
        synonyms=("biceps femoris", "semitendinosus", "semimembranosus"),
        note="The posterior thigh group, which has no single Latin name.",
    ),
    Structure(
        "MUS_THIGH_ADDUCTORS",
        "Adductor muscles of the thigh",
        MUSCLE,
        "THIGH",
        PAIRED,
        "Musculi adductores",
        synonyms=("groin",),
    ),
    Structure(
        "MUS_GASTROCNEMIUS",
        "Gastrocnemius",
        MUSCLE,
        "LEG",
        PAIRED,
        "Musculus gastrocnemius",
        synonyms=("calf",),
    ),
    Structure("MUS_SOLEUS", "Soleus", MUSCLE, "LEG", PAIRED, "Musculus soleus"),
    Structure(
        "MUS_TIBIALIS_ANTERIOR",
        "Tibialis anterior",
        MUSCLE,
        "LEG",
        PAIRED,
        "Musculus tibialis anterior",
    ),
)


# --- tendons, ligaments and fasciae ------------------------------------------------

TENDONS = (
    Structure(
        "TEN_ROTATOR_CUFF",
        "Rotator cuff tendons",
        TENDON,
        "SHOULDER",
        PAIRED,
        note="The supraspinatus, infraspinatus, subscapularis and teres minor tendons.",
    ),
    Structure(
        "TEN_LONG_HEAD_BICEPS",
        "Long head of biceps tendon",
        TENDON,
        "SHOULDER",
        PAIRED,
        "Tendo capitis longi musculi bicipitis brachii",
    ),
    Structure(
        "TEN_COMMON_EXTENSOR_ORIGIN",
        "Common extensor origin at the elbow",
        TENDON,
        "ELBOW",
        PAIRED,
        synonyms=("tennis elbow", "lateral epicondyle"),
    ),
    Structure(
        "TEN_COMMON_FLEXOR_ORIGIN",
        "Common flexor origin at the elbow",
        TENDON,
        "ELBOW",
        PAIRED,
        synonyms=("golfer's elbow", "medial epicondyle"),
    ),
    Structure(
        "TEN_WRIST_EXTENSOR",
        "Wrist extensor tendons",
        TENDON,
        "WRIST",
        PAIRED,
        "Tendines musculorum extensorum",
    ),
    Structure(
        "TEN_ILIOTIBIAL_TRACT",
        "Iliotibial tract",
        TENDON,
        "THIGH",
        PAIRED,
        "Tractus iliotibialis",
    ),
    Structure(
        "TEN_PATELLAR", "Patellar ligament", TENDON, "KNEE", PAIRED, "Ligamentum patellae"
    ),
    Structure(
        "TEN_ACL",
        "Anterior cruciate ligament",
        TENDON,
        "KNEE",
        PAIRED,
        "Ligamentum cruciatum anterius",
    ),
    Structure("TEN_KNEE_MENISCUS", "Meniscus of the knee", TENDON, "KNEE", PAIRED, "Meniscus"),
    Structure("TEN_ACHILLES", "Calcaneal tendon", TENDON, "ANKLE", PAIRED, "Tendo calcaneus"),
    Structure(
        "TEN_ANKLE_LATERAL_LIGAMENT",
        "Lateral ankle ligaments",
        TENDON,
        "ANKLE",
        PAIRED,
        note="The anterior talofibular, calcaneofibular and posterior talofibular ligaments.",
    ),
    Structure(
        "TEN_PLANTAR_FASCIA",
        "Plantar fascia",
        TENDON,
        "FOOT",
        PAIRED,
        "Aponeurosis plantaris",
    ),
)


# --- organs ------------------------------------------------------------------------

ORGANS = (
    Structure("ORG_BRAIN", "Brain", ORGAN, "HEAD", MIDLINE, "Encephalon"),
    Structure("ORG_MENINGES", "Meninges", ORGAN, "HEAD", MIDLINE, "Meninges"),
    Structure("ORG_EYE", "Eye", ORGAN, "EYE", PAIRED, "Bulbus oculi"),
    Structure(
        "ORG_PARANASAL_SINUS",
        "Paranasal sinuses",
        ORGAN,
        "FACE",
        PAIRED,
        "Sinus paranasales",
    ),
    Structure("ORG_TEETH", "Teeth", ORGAN, "TEETH", PAIRED, "Dentes"),
    Structure("ORG_THYROID", "Thyroid gland", ORGAN, "NECK", MIDLINE, "Glandula thyroidea"),
    Structure("ORG_PHARYNX", "Pharynx", ORGAN, "NECK", MIDLINE, "Pharynx"),
    Structure("ORG_HEART", "Heart", ORGAN, "CHEST_CENTRAL", MIDLINE, "Cor"),
    Structure("ORG_PERICARDIUM", "Pericardium", ORGAN, "CHEST_CENTRAL", MIDLINE, "Pericardium"),
    Structure("ORG_LUNG", "Lung", ORGAN, "CHEST", PAIRED, "Pulmo", **_CHEST),
    Structure("ORG_PLEURA", "Pleura", ORGAN, "CHEST", PAIRED, "Pleura", **_CHEST),
    Structure(
        "ORG_OESOPHAGUS",
        "Oesophagus",
        ORGAN,
        "CHEST_CENTRAL",
        MIDLINE,
        "Oesophagus",
        synonyms=("esophagus", "reflux"),
    ),
    Structure("ORG_STOMACH", "Stomach", ORGAN, "ABD_EPIGASTRIC", MIDLINE, "Gaster"),
    Structure("ORG_DUODENUM", "Duodenum", ORGAN, "ABD_EPIGASTRIC", MIDLINE, "Duodenum"),
    Structure("ORG_LIVER", "Liver", ORGAN, "ABD_RUQ", RIGHT, "Hepar"),
    Structure("ORG_GALLBLADDER", "Gallbladder", ORGAN, "ABD_RUQ", RIGHT, "Vesica biliaris"),
    Structure("ORG_BILE_DUCT", "Bile duct", ORGAN, "ABD_RUQ", RIGHT, "Ductus choledochus"),
    Structure("ORG_PANCREAS", "Pancreas", ORGAN, "ABD_EPIGASTRIC", MIDLINE, "Pancreas"),
    Structure("ORG_SPLEEN", "Spleen", ORGAN, "ABD_LUQ", LEFT, "Splen"),
    Structure(
        "ORG_SMALL_INTESTINE",
        "Small intestine",
        ORGAN,
        "ABD_PERIUMBILICAL",
        MIDLINE,
        "Intestinum tenue",
    ),
    Structure("ORG_APPENDIX", "Appendix", ORGAN, "ABD_RLQ", RIGHT, "Appendix vermiformis"),
    Structure("ORG_CAECUM", "Caecum", ORGAN, "ABD_RLQ", RIGHT, "Caecum"),
    Structure(
        "ORG_COLON", "Colon", ORGAN, "ABD_DIFFUSE", MIDLINE, "Colon", synonyms=("bowel",)
    ),
    Structure("ORG_SIGMOID_COLON", "Sigmoid colon", ORGAN, "ABD_LLQ", LEFT, "Colon sigmoideum"),
    Structure("ORG_RECTUM", "Rectum", ORGAN, "PELVIS", MIDLINE, "Rectum"),
    Structure("ORG_PERITONEUM", "Peritoneum", ORGAN, "ABD_DIFFUSE", MIDLINE, "Peritoneum"),
    Structure(
        "ORG_KIDNEY",
        "Kidney",
        ORGAN,
        "ABDOMEN",
        PAIRED,
        "Ren",
        synonyms=("renal",),
        **_ABD_UPPER,
    ),
    Structure("ORG_URETER", "Ureter", ORGAN, "ABDOMEN", PAIRED, "Ureter", **_ABD_LOWER),
    Structure("ORG_BLADDER", "Bladder", ORGAN, "ABD_SUPRAPUBIC", MIDLINE, "Vesica urinaria"),
    Structure("ORG_UTERUS", "Uterus", ORGAN, "ABD_SUPRAPUBIC", MIDLINE, "Uterus", sex="F"),
    Structure("ORG_OVARY", "Ovary", ORGAN, "ABDOMEN", PAIRED, "Ovarium", sex="F", **_ABD_LOWER),
    Structure("ORG_PROSTATE", "Prostate", ORGAN, "PELVIS", MIDLINE, "Prostata", sex="M"),
    Structure("ORG_TESTIS", "Testis", ORGAN, "GENITAL", PAIRED, "Testis", sex="M"),
)


# --- nerves ------------------------------------------------------------------------

NERVES = (
    Structure("NRV_TRIGEMINAL", "Trigeminal nerve", NERVE, "FACE", PAIRED, "Nervus trigeminus"),
    Structure(
        "NRV_OCCIPITAL",
        "Greater occipital nerve",
        NERVE,
        "OCCIPUT",
        PAIRED,
        "Nervus occipitalis major",
    ),
    Structure(
        "NRV_CERVICAL_ROOT",
        "Cervical nerve root",
        NERVE,
        "BACK_CERVICAL",
        PAIRED,
        "Radix nervi spinalis",
    ),
    Structure(
        "NRV_BRACHIAL_PLEXUS", "Brachial plexus", NERVE, "SHOULDER", PAIRED, "Plexus brachialis"
    ),
    Structure(
        "NRV_MEDIAN",
        "Median nerve",
        NERVE,
        "HAND",
        PAIRED,
        "Nervus medianus",
        synonyms=("carpal tunnel",),
    ),
    Structure("NRV_ULNAR", "Ulnar nerve", NERVE, "ELBOW", PAIRED, "Nervus ulnaris"),
    Structure("NRV_RADIAL", "Radial nerve", NERVE, "FOREARM", PAIRED, "Nervus radialis"),
    Structure(
        "NRV_DIGITAL_HAND",
        "Digital nerves of the hand",
        NERVE,
        "FINGER",
        PAIRED,
        "Nervi digitales",
    ),
    Structure(
        "NRV_INTERCOSTAL",
        "Intercostal nerve",
        NERVE,
        "CHEST",
        PAIRED,
        "Nervus intercostalis",
        **_CHEST,
    ),
    Structure(
        "NRV_SPINAL_CORD", "Spinal cord", NERVE, "BACK_THORACIC", MIDLINE, "Medulla spinalis"
    ),
    Structure(
        "NRV_LUMBAR_ROOT",
        "Lumbar nerve root",
        NERVE,
        "BACK_LUMBAR",
        PAIRED,
        "Radix nervi spinalis",
        synonyms=("radicular", "sciatica"),
    ),
    Structure(
        "NRV_CAUDA_EQUINA", "Cauda equina", NERVE, "BACK_SACRAL", MIDLINE, "Cauda equina"
    ),
    Structure(
        "NRV_SCIATIC",
        "Sciatic nerve",
        NERVE,
        "THIGH",
        PAIRED,
        "Nervus ischiadicus",
        synonyms=("sciatica",),
    ),
    Structure("NRV_FEMORAL", "Femoral nerve", NERVE, "THIGH", PAIRED, "Nervus femoralis"),
    Structure(
        "NRV_COMMON_FIBULAR",
        "Common fibular nerve",
        NERVE,
        "LEG",
        PAIRED,
        "Nervus fibularis communis",
        synonyms=("common peroneal",),
    ),
    Structure("NRV_TIBIAL", "Tibial nerve", NERVE, "LEG", PAIRED, "Nervus tibialis"),
    Structure("NRV_PLANTAR", "Plantar nerves", NERVE, "FOOT", PAIRED, "Nervi plantares"),
    Structure("NRV_PUDENDAL", "Pudendal nerve", NERVE, "GENITAL", PAIRED, "Nervus pudendus"),
)


# --- vessels -----------------------------------------------------------------------

VESSELS = (
    Structure(
        "VES_TEMPORAL_ARTERY",
        "Superficial temporal artery",
        VESSEL,
        "TEMPLE",
        PAIRED,
        "Arteria temporalis superficialis",
    ),
    Structure(
        "VES_THORACIC_AORTA",
        "Thoracic aorta",
        VESSEL,
        "CHEST_CENTRAL",
        MIDLINE,
        "Aorta thoracica",
    ),
    Structure(
        "VES_CORONARY",
        "Coronary arteries",
        VESSEL,
        "CHEST_CENTRAL",
        MIDLINE,
        "Arteriae coronariae",
    ),
    Structure(
        "VES_PULMONARY_ARTERY",
        "Pulmonary artery",
        VESSEL,
        "CHEST_CENTRAL",
        MIDLINE,
        "Arteria pulmonalis",
    ),
    Structure(
        "VES_ABDOMINAL_AORTA",
        "Abdominal aorta",
        VESSEL,
        "ABD_PERIUMBILICAL",
        MIDLINE,
        "Aorta abdominalis",
    ),
    Structure(
        "VES_LEG_ARTERY",
        "Arteries of the leg",
        VESSEL,
        "LEG",
        PAIRED,
        "Arteriae membri inferioris",
        synonyms=("claudication",),
    ),
    Structure(
        "VES_LEG_DEEP_VEIN",
        "Deep veins of the leg",
        VESSEL,
        "LEG",
        PAIRED,
        "Venae profundae membri inferioris",
        synonyms=("deep vein thrombosis",),
    ),
)


# --- the ontology ------------------------------------------------------------------

# The region level is the one already defined for pain locations. Reusing it is what lets a
# structure selected on the model reach the rest of the platform: the region a feature or a
# rule asks about is the region the projected location belongs to.
REGIONS = locations.REGIONS

STRUCTURES = SURFACE_ZONES + MUSCLES + TENDONS + BONES + JOINTS + ORGANS + NERVES + VESSELS

BY_CODE = {structure.code: structure for structure in STRUCTURES}


def types_of(codes) -> set[str]:
    """The structure types present in a set of structure codes."""
    return {BY_CODE[code].type for code in codes if code in BY_CODE}


def of_type(type_code: str) -> tuple[Structure, ...]:
    return tuple(structure for structure in STRUCTURES if structure.type == type_code)


def in_region(region: str) -> tuple[Structure, ...]:
    return tuple(structure for structure in STRUCTURES if structure.region == region)


def projected_locations(code: str, side: str) -> tuple[tuple[str, str], ...]:
    """The pain locations and sides a selected structure records.

    Usually one. A structure recorded on both sides whose two halves have separate location
    codes yields both, so "both kidneys" reaches the taxonomy as the two flanks rather than
    as the abdomen in general.

    Empty when the code is not in the ontology. The caller drops the site rather than
    inventing a location for it; an unresolvable stored code is a migration problem.
    """
    structure = BY_CODE.get(code)
    if structure is None:
        return ()
    if side == "BILATERAL" and (structure.location_left or structure.location_right):
        return (
            (structure.location_for("LEFT"), "LEFT"),
            (structure.location_for("RIGHT"), "RIGHT"),
        )
    return ((structure.location_for(side), side),)


def combine_sides(first: str, second: str) -> str:
    """One side for a location two sites both point at."""
    if first == second:
        return first
    vague = {"MIDLINE", "NOT_APPLICABLE"}
    if first in vague:
        return second
    if second in vague:
        return first
    return "BILATERAL"


def _location_laterality() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for zone in of_type(REGION):
        mapping[zone.location] = zone.laterality
        if zone.location_left:
            mapping[zone.location_left] = LEFT
        if zone.location_right:
            mapping[zone.location_right] = RIGHT
    return mapping


# The laterality a pain location carries on its own, read off the surface zones: a knee has
# a side, a lumbar spine does not, and the chest has one because the taxonomy names its two
# halves separately. Derived rather than written out again, so it cannot drift.
LOCATION_LATERALITY = _location_laterality()


def tree() -> list[dict]:
    """Regions, each holding the structure types present in it, each holding its structures.

    Built here rather than in the API layer so the nesting the interface renders and the
    nesting the taxonomy describes are the same object.
    """
    grouped: list[dict] = []
    for region_code, region_label in REGIONS:
        members = in_region(region_code)
        if not members:
            continue
        groups = []
        for entry in STRUCTURE_TYPES:
            of_this_type = [s for s in members if s.type == entry.code]
            if of_this_type:
                groups.append(
                    {
                        "type": entry.code,
                        "label": entry.label,
                        "structures": [s.code for s in of_this_type],
                    }
                )
        grouped.append({"region": region_code, "label": region_label, "types": groups})
    return grouped
