import { expect, test } from "@playwright/test";

// The four public routes a judge opens first, with no credentials and no login.
for (const path of ["/", "/pitch", "/app", "/app/judge"]) {
  test(`${path} answers 200 and renders`, async ({ page }) => {
    const res = await page.goto(path);
    expect(res?.status()).toBe(200);
    await expect(page.locator("body")).not.toBeEmpty();
    await expect(page).toHaveTitle(/.+/);
  });
}
