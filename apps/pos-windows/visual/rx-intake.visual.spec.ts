import { expect, test } from '@playwright/test';

test('manual intake evidence opens as readable text without overflowing', async ({ page }, testInfo) => {
  await page.goto('/?scenario=rx-intake-record');
  await page.getByRole('button', { name: 'Received prescriptions', exact: true }).click();
  await page.getByRole('button', { name: /Demo Patient.*DEMO-RX-RECORD/ }).click();
  await page.getByRole('button', { name: 'INTAKE-DEMO.txt · Intake record', exact: true }).click();
  const preview = page.locator('.pos-rx-preview');
  await preview.scrollIntoViewIfNeeded();
  await expect(preview.locator('pre')).toContainText('Physical original held for pharmacist review');
  await expect(preview.locator('img,iframe')).toHaveCount(0);
  const dialog = page.getByRole('dialog');
  expect(await dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(2);
  expect(await preview.locator('pre').evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('manual-intake-record.png') });
});

test('RX intake remains usable, scrollable and keyboard accessible', async ({ page }, testInfo) => {
  await page.goto('/?scenario=rx-intake');
  const trigger = page.getByRole('button', { name: 'Receive prescription', exact: true });
  await expect(trigger).toBeEnabled(); await trigger.click();
  const dialog = page.getByRole('dialog', { name: 'Receive prescription' });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Patient', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('rx-intake-form.png') });
  await expect(page.getByRole('option', { name: /DHA/ })).toHaveJSProperty('disabled', true);
  await page.getByLabel('Original RX reference').fill('DEMO-RX-001');
  await page.getByRole('combobox', { name: 'Patient', exact: true }).selectOption('fixture-patient');
  await page.getByRole('combobox', { name: 'Prescriber', exact: true }).selectOption('fixture-prescriber');
  await page.getByLabel('Prescription date').fill('2026-10-18');
  await page.getByLabel('Prescription type').selectOption('ACUTE');
  await page.getByLabel('Prescribed medicine / pack').selectOption('fixture-sku');
  await page.getByLabel('Authorised quantity').fill('2');
  await page.getByLabel('Directions as prescribed').fill('Original source directions for pharmacist review.');
  await expect(page.getByRole('button', { name: 'Receive for review', exact: true })).toBeDisabled();
  await page.getByLabel('The genuine original is available for pharmacist review.').check();
  await page.getByRole('status').filter({ hasText: 'Malware scanning is deferred.' }).scrollIntoViewIfNeeded();
  await expect(page.getByRole('status').filter({ hasText: 'Malware scanning is deferred.' })).toBeVisible();
  await expect(page.getByLabel('Upload scan / photo / PDF')).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Receive for review', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Receive for review', exact: true }).scrollIntoViewIfNeeded();
  expect(await dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('rx-intake-evidence.png') });
  await page.keyboard.press('Escape'); await expect(dialog).toBeHidden(); await expect(trigger).toBeFocused();
});
