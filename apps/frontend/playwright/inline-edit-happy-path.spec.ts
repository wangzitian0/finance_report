import { test, expect, Page } from '@playwright/test';

test.skip(
  !process.env.RUN_E2E_HAPPY_PATH,
  'Requires authenticated session and seeded statement; gated by RUN_E2E_HAPPY_PATH=1'
);

test('inline-edit happy path (AC16.11.33)', async ({ page }: { page: Page }) => {

  await page.goto('/upload');

  // Navigate to a review page
  const firstReviewLink = page.locator('a[href*="/review"]').first();
  await expect(firstReviewLink).toBeVisible();
  await firstReviewLink.click();

  // Wait for review page
  await expect(page).toHaveURL(/\/statements\/.*\/review/);

  // Find a transaction row and click to edit
  const firstTxnRow = page.locator('table tbody tr').first();
  await firstTxnRow.click();

  // Edit description
  const descInput = firstTxnRow.locator('input[type="text"]');
  await expect(descInput).toBeVisible();
  await descInput.fill('Updated Description via Playwright');
  await descInput.press('Enter');

  // Verify approve-edits button appears because this flow validates and approves.
  const saveButton = page.getByRole('button', { name: /Approve Edits/ });
  await expect(saveButton).toBeVisible();

  // Click approve edits and confirm the approval/posting side effect.
  await saveButton.click();
  const dialog = page.getByRole('dialog', { name: 'Approve Edited Statement' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Approve Edits' }).click();

  // Assert approval success.
  await expect(page.getByText(/Statement approved/)).toBeVisible();
});
