import { test, expect, Page } from '@playwright/test';

test.skip(
  !process.env.RUN_E2E_HAPPY_PATH,
  'Requires authenticated session and seeded statement; gated by RUN_E2E_HAPPY_PATH=1'
);

test('inline-edit happy path (AC16.11.33)', async ({ page }: { page: Page }) => {
  
  await page.goto('/statements');
  
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
  
  // Verify Save button appears
  const saveButton = page.getByRole('button', { name: /Save Edits/ });
  await expect(saveButton).toBeVisible();
  
  // Click save
  await saveButton.click();
  
  // Assert success toast or persistence
  await expect(page.getByText('Edits saved successfully')).toBeVisible();
});
