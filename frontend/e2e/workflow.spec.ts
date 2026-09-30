import { expect, test, type Page } from '@playwright/test'

const DOCTOR = { email: 's.benali@chu-batna.dz', password: 'Consultation-Batna-2026' }

/**
 * Each test signs in and makes its own patient, so none of them depends on another having
 * run. Sharing one saved session would not work anyway: refresh tokens are single use, so
 * a second context replaying the same cookie is correctly refused.
 */
async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(DOCTOR.email)
  await page.getByLabel('Password').fill(DOCTOR.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

function uniqueFamilyName(prefix: string) {
  return `${prefix}-${Date.now().toString().slice(-7)}`
}

async function createPatient(page: Page, familyName: string, conditions: string[] = []) {
  await page.goto('/patients/new')
  await page.getByLabel('Given name').fill('Hocine')
  await page.getByLabel('Family name').fill(familyName)
  await page.getByLabel('Date of birth').fill('1966-02-17')
  await page.getByLabel('Sex').selectOption('M')
  await page.getByLabel('Ward or unit').fill('Emergency')
  for (const condition of conditions) {
    await page.getByRole('button', { name: condition, exact: true }).click()
  }
  await page.getByRole('button', { name: 'Create patient' }).click()
  await expect(page.getByRole('heading', { name: `Hocine ${familyName}` })).toBeVisible()
}

test('a clinician records a chest-pain assessment and takes the report away', async ({ page }) => {
  await signIn(page)
  await expect(page.getByText(/does not constitute a medical diagnosis/).first()).toBeVisible()
  await createPatient(page, uniqueFamilyName('Lounis'), [
    'Coronary artery disease',
    'Hypertension',
  ])

  await test.step('localise the pain on the anatomical model', async () => {
    await page.getByRole('link', { name: 'New assessment' }).click()
    await expect(page.getByRole('heading', { name: 'New assessment' })).toBeVisible()
    await expect(page.getByText('What this model is for')).toBeVisible()
    await expect(page.getByText(/does not interpret it/)).toBeVisible()

    // The heart is reached through the structure list, which is the path that does not
    // depend on hitting a mesh with the pointer.
    await page.getByLabel('Search the anatomy').fill('heart')
    await page.getByRole('button', { name: 'Heart', exact: true }).click()

    const panel = page.getByRole('article', { name: 'Heart' })
    await expect(panel).toBeVisible()
    await expect(panel.getByText('Main site')).toBeVisible()
    await expect(panel.getByText('Cor ·')).toBeVisible()
    await expect(panel.getByText('ORG_HEART')).toBeVisible()
    // Its own intensity, which is stored with the site and is not a model input.
    await panel.getByRole('button', { name: '7 at Heart' }).click()
    await expect(panel.getByText('severe')).toBeVisible()

    // Selecting a structure also records a site in the pain-location taxonomy.
    await expect(page.getByText('Central chest', { exact: true }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step('describe the pain', async () => {
    await page.getByRole('button', { name: 'Pressure', exact: true }).click()
    await page.getByRole('button', { name: 'Tightness', exact: true }).click()
    await page.getByRole('radio', { name: 'Sudden' }).click()
    await page.getByLabel('How long has it been going on?').fill('3')
    await page.getByRole('radio', { name: 'Worsening' }).click()
    await page.getByRole('checkbox', { name: 'The pain radiates' }).check()
    await page.getByRole('button', { name: 'Exertion', exact: true }).click()
    await page.getByRole('button', { name: 'Rest', exact: true }).click()
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step('record symptoms and context', async () => {
    await page.getByRole('button', { name: 'Sweating', exact: true }).click()
    await page.getByRole('button', { name: 'Shortness of breath', exact: true }).click()
    await page.getByRole('button', { name: 'Nausea', exact: true }).click()
    await page.getByRole('button', { name: 'Anxiety', exact: true }).click()
    await expect(page.getByText(/Raises heart rate, respiratory rate/)).toBeVisible()
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step('the questionnaire narrows to the case', async () => {
    await expect(page.getByText(/questions apply to this picture/)).toBeVisible()
    // Chest-specific questions appear; a spinal one does not.
    await expect(page.getByText('Does the pain come on or worsen with exertion?')).toBeVisible()
    await expect(page.getByText('Where does the chest pain radiate?')).toBeVisible()
    await expect(page.getByText('Straight leg raise.')).toHaveCount(0)

    await page.getByLabel('Does the pain come on or worsen with exertion?').check()
    // Answering that question opens the follow-up.
    await expect(page.getByText('Does it settle within minutes of stopping?')).toBeVisible()
    await page.getByLabel('How much does the pain limit usual activity?').selectOption('SEVERE')
    await page.getByLabel('ECG.').selectOption('ABNORMAL')
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step('enter the measured values', async () => {
    await page.getByLabel('Heart rate (beats/min)').fill('112')
    await page.getByLabel('Respiratory rate (breaths/min)').fill('22')
    await page.getByLabel('Systolic blood pressure (mmHg)').fill('156')
    await page.getByLabel('Diastolic blood pressure (mmHg)').fill('92')
    await page.getByLabel('Oxygen saturation (%)').fill('94')
    await page.getByLabel('Temperature (°C)').fill('37.1')
    await expect(page.getByText(/Outside the usual range/).first()).toBeVisible()
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step('pass the document step', async () => {
    await expect(page.getByText('No documents attached')).toBeVisible()
    await page.getByRole('button', { name: 'Continue' }).click()
  })

  await test.step("record the patient's own score", async () => {
    await expect(page.getByText('Recorded separately from the estimate')).toBeVisible()
    await page.getByRole('button', { name: '4', exact: true }).click()
    await page.getByRole('button', { name: 'Run the estimate' }).click()
  })

  await test.step('review the result', async () => {
    await expect(page).toHaveURL(/\/assessments\//)
    await expect(page.getByText('Estimated pain', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Patient-reported', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('Clinical priority', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Model contributions' })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Potentially compatible categories' }),
    ).toBeVisible()
    await expect(page.getByText('These are contributions to this model output')).toBeVisible()
    await expect(page.getByText('Ischaemic cardiac pattern')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'What was recorded' })).toBeVisible()
    await expect(page.getByText('Localised structures')).toBeVisible()
    await expect(page.getByText('7/10')).toBeVisible()
  })

  await test.step('validate and take the report', async () => {
    await page.getByRole('button', { name: 'Validate' }).click()
    await expect(page.getByText('validated', { exact: true })).toBeVisible()

    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Report' }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/^pain-assessment-PS-\d{4}-\d{6}\.pdf$/)
  })
})

test('a record too thin for the model is refused rather than guessed at', async ({ page }) => {
  await signIn(page)
  await createPatient(page, uniqueFamilyName('Chaib'))

  await page.getByRole('link', { name: 'New assessment' }).click()
  // The flat diagram still records a region on its own, for a site the model cannot name.
  await page.getByRole('checkbox', { name: 'Left knee' }).click()
  await expect(page.getByText('Selected regions')).toBeVisible()
  for (let step = 0; step < 6; step += 1) {
    await page.getByRole('button', { name: 'Continue' }).click()
  }
  await page.getByRole('button', { name: 'Run the estimate' }).click()

  await expect(page.getByRole('heading', { name: 'Insufficient data' })).toBeVisible()
  await expect(page.getByText(/not sufficient for a reliable estimate/)).toBeVisible()
  await expect(page.getByText('Not recorded', { exact: true })).toBeVisible()
})

test('a patient can be found by family name even though names are sealed', async ({ page }) => {
  const familyName = uniqueFamilyName('Bensaid')
  await signIn(page)
  await createPatient(page, familyName)

  await page.goto('/patients')
  await page.getByPlaceholder('Patient code, name or ward').fill(familyName)
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page.getByRole('link', { name: `Hocine ${familyName}` })).toBeVisible()
})

test('the platform pages report what was measured', async ({ page }) => {
  await signIn(page)

  await page.goto('/integrity')
  await page.getByRole('button', { name: 'Verify now' }).click()
  await expect(page.getByText('Both chains verify')).toBeVisible()

  await page.goto('/security')
  await expect(page.getByText('AES-256-GCM').first()).toBeVisible()
  await expect(page.getByText('X25519 with ML-KEM-768').first()).toBeVisible()
  await expect(page.getByText('Ed25519 with ML-DSA-65').first()).toBeVisible()
  await expect(page.getByText(/Terminated by the reverse proxy/)).toBeVisible()

  await page.goto('/ai-model')
  await expect(page.getByText('MAE', { exact: true })).toBeVisible()
  await expect(page.getByText(/Trained on synthetic data only/).first()).toBeVisible()
  await expect(page.getByText(/never an inference feature/)).toBeVisible()
})
