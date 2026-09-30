import type { AnatomicalStructure, AnatomyOntology, Laterality, StructureType } from '@/api/types'

/**
 * A handful of ontology entries for the tests.
 *
 * Real codes and real lateralities, so a test that passes here is testing the same rules
 * the server applies: a knee has two sides, a liver has one and it is the right.
 */
export function structure(
  code: string,
  label: string,
  type: StructureType,
  location: string,
  laterality: Laterality,
  extra: Partial<AnatomicalStructure> = {},
): AnatomicalStructure {
  const sides = {
    PAIRED: ['LEFT', 'RIGHT', 'BILATERAL'],
    MIDLINE: ['MIDLINE'],
    LEFT: ['LEFT'],
    RIGHT: ['RIGHT'],
  }[laterality] as AnatomicalStructure['sides']
  return {
    code,
    label,
    latin: '',
    structure_type: type,
    region: 'LOWER_LIMB',
    location_code: location,
    location_left: null,
    location_right: null,
    laterality,
    sides,
    synonyms: [],
    sex: null,
    note: '',
    ...extra,
  }
}

export const KNEE = structure('JOINT_KNEE', 'Knee joint', 'JOINT', 'KNEE', 'PAIRED', {
  latin: 'Articulatio genus',
})
export const SCIATIC = structure('NRV_SCIATIC', 'Sciatic nerve', 'NERVE', 'THIGH', 'PAIRED', {
  latin: 'Nervus ischiadicus',
  synonyms: ['sciatica'],
})
export const LIVER = structure('ORG_LIVER', 'Liver', 'ORGAN', 'ABD_RUQ', 'RIGHT', {
  region: 'ABDOMEN',
  latin: 'Hepar',
})
export const KIDNEY = structure('ORG_KIDNEY', 'Kidney', 'ORGAN', 'ABDOMEN', 'PAIRED', {
  region: 'ABDOMEN',
  location_left: 'ABD_LUQ',
  location_right: 'ABD_RUQ',
})
export const UTERUS = structure('ORG_UTERUS', 'Uterus', 'ORGAN', 'ABD_SUPRAPUBIC', 'MIDLINE', {
  region: 'ABDOMEN',
  sex: 'F',
})
export const LOWER_BACK = structure(
  'REG_LOWER_BACK',
  'Lower back',
  'REGION',
  'BACK_LUMBAR',
  'MIDLINE',
  { region: 'BACK' },
)

export const STRUCTURES = [KNEE, SCIATIC, LIVER, KIDNEY, UTERUS, LOWER_BACK]

export const ONTOLOGY: AnatomyOntology = {
  notice: 'The 3D model localises anatomy; it does not interpret it.',
  regions: [
    { code: 'ABDOMEN', label: 'Abdomen', display_order: 50 },
    { code: 'BACK', label: 'Back', display_order: 40 },
    { code: 'LOWER_LIMB', label: 'Lower limb', display_order: 80 },
  ],
  structure_types: [
    { code: 'REGION', label: 'Body region', description: '', display_order: 10 },
    { code: 'JOINT', label: 'Joints', description: '', display_order: 50 },
    { code: 'ORGAN', label: 'Organs', description: '', display_order: 60 },
    { code: 'NERVE', label: 'Nerves', description: '', display_order: 70 },
  ],
  structures: STRUCTURES,
  tree: [
    {
      region: 'ABDOMEN',
      label: 'Abdomen',
      types: [{ type: 'ORGAN', label: 'Organs', structures: ['ORG_LIVER', 'ORG_KIDNEY', 'ORG_UTERUS'] }],
    },
    {
      region: 'BACK',
      label: 'Back',
      types: [{ type: 'REGION', label: 'Body region', structures: ['REG_LOWER_BACK'] }],
    },
    {
      region: 'LOWER_LIMB',
      label: 'Lower limb',
      types: [
        { type: 'JOINT', label: 'Joints', structures: ['JOINT_KNEE'] },
        { type: 'NERVE', label: 'Nerves', structures: ['NRV_SCIATIC'] },
      ],
    },
  ],
}
