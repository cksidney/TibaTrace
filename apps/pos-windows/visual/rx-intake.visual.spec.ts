import { expect, test } from '@playwright/test';

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
  await expect(page.getByRole('button', { name: 'Receive for review', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Receive for review', exact: true }).scrollIntoViewIfNeeded();
  expect(await dialog.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('rx-intake-evidence.png') });
  await page.keyboard.press('Escape'); await expect(dialog).toBeHidden(); await expect(trigger).toBeFocused();
});
