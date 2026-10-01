/**
 * Tissue colours for the 3D model. These belong to the anatomy rather than to the
 * product palette, so they are plain values and not theme tokens: bone stays bone-coloured
 * whichever theme the workspace is in.
 */
export const TISSUE: Record<string, string> = {
  REGION: '#d8b9a3',
  MUSCLE: '#b4564c',
  TENDON: '#d9cfb4',
  LIGAMENT: '#c9bf9d',
  BONE: '#e8e4d8',
  JOINT: '#7fa6bd',
  ORGAN: '#8c5a7a',
  NERVE: '#d8a83a',
  VESSEL: '#9b2f2f',
};

/** The structure that was picked. Matches the accent the dark workspace uses for "active". */
export const HIGHLIGHT = '#4f8fe0';
