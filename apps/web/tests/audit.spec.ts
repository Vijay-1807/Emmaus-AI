import { test, expect, type Page } from "@playwright/test";

const BASE = "http://localhost:3000";

function routes() {
  return [
    { path: "/", title: /What should we investigate|Emmaus/i },
    { path: "/documents", title: /Documents/i },
    { path: "/datasets", title: /Datasets/i },
    { path: "/investigations", title: /History|Investigation/i },
    { path: "/settings", title: /Settings/i },
    { path: "/login", title: /Emmaus|Sign in/i },
  ] as const;
}

async function assertNavbar(page: Page) {
  if (page.url().includes("/login")) {
      await expect(page.getByText(/Emmaus AI|Sign in/i).first()).toBeVisible();
    return;
  }
  await expect(page.locator("nav").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /New/ })).toBeVisible();
  for (const label of ["Home", "Documents", "Datasets", "History", "Settings"]) {
    await expect(page.locator("nav").getByText(label).first()).toBeAttached();
  }
}

async function noJSError(page: Page, cb: () => Promise<void>) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  await cb();
  expect(errors, `page errors: ${errors.join("\n")}`).toEqual([]);
}

test.describe("Routes load + navbar present", () => {
  for (const r of routes()) {
    test(`GET ${r.path} renders without crash`, async ({ page }) => {
      await page.goto(`${BASE}${r.path}`, { waitUntil: "domcontentloaded" });
      await expect(page).toHaveTitle(/Emmaus/i);
      await expect(page.getByText(r.title).first()).toBeVisible({ timeout: 10000 });
      await assertNavbar(page);
    });
  }
});

test.describe("Responsiveness", () => {
  const viewports = [
    { name: "mobile 390", w: 390, h: 844 },
    { name: "tablet 768", w: 768, h: 1024 },
    { name: "laptop 1280", w: 1280, h: 800 },
    { name: "desktop 1920", w: 1920, h: 1080 },
  ];

  for (const vp of viewports) {
    test(`layout does not overflow at ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      for (const r of routes().slice(0, 4)) {
        await page.goto(`${BASE}${r.path}`, { waitUntil: "domcontentloaded" });
        // No horizontal scrollbar — content width <= viewport
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, `${r.path} overflows at ${vp.name}`).toBeLessThanOrEqual(4);
      }
    });
  }

  test("mobile hamburger opens/closes and staggered items appear", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const toggle = page.locator("nav button").last();
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.locator(".staggered-menu-panel").first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator(".staggered-menu-panel").getByText("Documents").first()).toBeVisible({ timeout: 5000 });
  });

  test("Documents table stays readable on mobile (no clipped columns)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/documents`, { waitUntil: "domcontentloaded" });
    const hasTable = await page.locator("table").first().isVisible().catch(() => false);
    const hasEmpty = await page.getByText(/No documents yet|Upload PDFs/i).first().isVisible().catch(() => false);
    expect(hasTable || hasEmpty).toBeTruthy();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(8);
  });

  test("Settings tabs fit on mobile (no wrapping disaster)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/settings`, { waitUntil: "domcontentloaded" });
    for (const tab of ["Overview", "Models", "Evaluation", "Observability"]) {
      await expect(page.getByRole("button", { name: tab })).toBeVisible();
    }
  });

  test("footer stays compact on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const footer = page.locator("footer").first();
    await expect(footer).toBeVisible();
    const box = await footer.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeLessThan(520);
  });
});

test.describe("Core interactions", () => {
  test("Home Upload button opens file picker", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByRole("button", { name: /Upload/ }).first().click(),
    ]);
    expect(fileChooser).toBeTruthy();
    await fileChooser.setFiles([]);
  });

  test("Documents Upload button opens file picker", async ({ page }) => {
    await page.goto(`${BASE}/documents`, { waitUntil: "domcontentloaded" });
    // Documents Upload is a <label> wrapping a hidden <input type=file> — click the label's for, then expect input
    const fileInput = page.locator('input[type="file"]').first();
    await expect(fileInput).toBeAttached();
    // Trigger via label click; Playwright filechooser fires from the input
    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.locator("label").filter({ hasText: "Upload" }).first().click(),
    ]);
    expect(fileChooser).toBeTruthy();
    await fileChooser.setFiles([]);
  });

  test("Camera button opens CameraCapture modal", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /Camera/ }).first().click();
    await expect(page.getByText(/Camera Capture|Rear camera|Front camera/i).first()).toBeVisible({ timeout: 5000 });
  });

  test("Voice button opens VoiceRecordModal", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /^Voice$/ }).first().click();
    await expect(page.getByText(/Voice|Microphone|Transcri/i).first()).toBeVisible({ timeout: 8000 });
  });

  test("Settings tabs switch content", async ({ page }) => {
    // Deep-link via ?tab= — SettingsContent reads searchParams once on mount
    await page.goto(`${BASE}/settings?tab=evaluation`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/benchmarks|Seeded cases/i).first()).toBeVisible({ timeout: 8000 });
    await page.goto(`${BASE}/settings?tab=models`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Primary Reasoning|Active Models/i).first()).toBeVisible({ timeout: 8000 });
    await page.goto(`${BASE}/settings?tab=observability`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Observability|Investigations|Avg latency|No traces|No workspace selected/i).first()).toBeVisible({ timeout: 12000 });
  });

  test("Documents thumbnails + lightbox (if images exist)", async ({ page }) => {
    await page.goto(`${BASE}/documents`, { waitUntil: "domcontentloaded" });
    const hasImage = await page.locator('img[alt]').first().isVisible().catch(() => false);
    if (!hasImage) test.skip(true, "No image docs to preview");
    await page.locator('img[alt]').first().click();
    await expect(page.locator('[role="dialog"], .fixed.inset-0').first()).toBeVisible({ timeout: 5000 });
  });

  test("@ mention picker appears on Home", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const textarea = page.getByPlaceholder(/Ask anything|type @/i).first();
    await textarea.click();
    // Exercise the handler directly — fill via fill() may not trigger selection logic
    await textarea.pressSequentially("@", { delay: 40 });
    // Debounced library fetch + render
    await expect(
      page.locator("text=Nothing here yet").or(page.locator("text=No match"))
    ).toBeVisible({ timeout: 7000 });
  });

  test("Image Gen toggles prompt-to-output panel on Home", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /Image Gen/i }).click();
    await expect(page.getByPlaceholder(/Describe an image/i)).toBeVisible({ timeout: 7000 });
    await expect(page.getByRole("button", { name: /^Generate$/i })).toBeVisible();
    // Simplified UI: no steps dropdown, no char counter
    await expect(page.locator("text=/2048/")).toHaveCount(0);
  });

  test("Hero + composer stay centered (desktop and mobile)", async ({ page }) => {
    for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(vp);
      await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
      const off = await page.evaluate(() => {
        const vc = window.innerWidth / 2;
        const cx = (el: Element | null) => {
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return Math.abs(r.left + r.width / 2 - vc);
        };
        const ta = document.querySelector("main textarea");
        return {
          h1: cx(document.querySelector("main h1")),
          composer: cx(ta?.closest("div[class*='max-w-2xl']") ?? ta),
        };
      });
      expect(off.h1 ?? 99).toBeLessThanOrEqual(2);
      expect(off.composer ?? 99).toBeLessThanOrEqual(2);
    }
  });

  test("Image Gen panel opens on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: /Image Gen/i }).click();
    await expect(page.getByPlaceholder(/Describe an image/i)).toBeVisible({ timeout: 7000 });
  });

  test("Connection status pill present on desktop and mobile", async ({ page }) => {
    for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(vp);
      await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
      await expect(page.locator('a[title*="Backend connection"]').first()).toBeVisible({ timeout: 7000 });
    }
  });

  test("Footer links reachable", async ({ page }) => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("footer").getByText("THE MISSION").first()).toBeVisible();
    await expect(page.locator("footer").getByText("CONCIERGE").first()).toBeVisible();
  });
});

test.describe("No console errors on key pages", () => {
  for (const path of ["/", "/documents", "/datasets", "/settings"]) {
    test(`no pageerror on ${path}`, async ({ page }) => {
      await noJSError(page, async () => {
        await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(1200);
      });
    });
  }
});
