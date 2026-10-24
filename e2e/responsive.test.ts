import { expect, test } from "@playwright/test";

// 375 px is the width the product is built for (two phones across a counter): no horizontal scroll.
test.use({ viewport: { width: 375, height: 812 } });

for (const path of ["/", "/pitch", "/app", "/app/judge"]) {
  test(`${path} has no horizontal scroll at 375 px`, async ({ page }) => {
    await page.goto(path, { waitUntil: "load" });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
