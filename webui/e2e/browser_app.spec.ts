import fs from 'node:fs';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

type BrowserScenario = 'success' | 'failure' | 'quota' | 'paused' | 'regenerate';

function createAudioFixture(testInfo: TestInfo, name = 'lezione_test.wav'): string {
  const fixturePath = testInfo.outputPath(name);
  const wavHeader = Buffer.from(
    '524946462400000057415645666d7420100000000100010044ac000088580100020010006461746100000000',
    'hex',
  );
  fs.writeFileSync(fixturePath, wavHeader);
  return fixturePath;
}

async function selectScenario(page: Page, scenario: BrowserScenario): Promise<void> {
  const result = await page.evaluate(async selected => {
    return window.pywebview?.api?.set_browser_scenario?.(selected);
  }, scenario);
  expect(result?.ok).toBe(true);
}

async function uploadFromDropzone(page: Page, fixturePath: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: /Trascina i file qui o clicca per sfogliare/i }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(fixturePath);
  await expect(page.locator('.queue-card', { hasText: 'lezione_test.wav' })).toBeVisible();
}

async function startScenario(page: Page): Promise<void> {
  const startButton = page.getByRole('button', { name: /Avvia sbobinatura/i });
  await expect(startButton).toBeEnabled();
  await startButton.click();
}

test.describe('jot Browser Host E2E', () => {
  test('happy path covers upload, phases, console, archive, and editor', async ({ page }, testInfo) => {
    const fixturePath = createAudioFixture(testInfo);
    await page.goto('/');
    await expect(page.locator('body')).toBeVisible();
    await selectScenario(page, 'success');
    await uploadFromDropzone(page, fixturePath);
    await page.screenshot({ path: testInfo.outputPath('queued.png') });

    await startScenario(page);
    await expect(page.getByText('Sbobine completate')).toBeVisible({ timeout: 15_000 });
    const completedCard = page.locator('.queue-card.is-completed', { hasText: 'lezione_test.wav' });
    await expect(completedCard).toBeVisible();

    await page.getByRole('button', { name: 'Mostra console' }).click();
    const expandConsole = page.getByRole('button', { name: 'Espandi' });
    if (await expandConsole.isVisible()) await expandConsole.click();
    const consolePanel = page.locator('.console-shell');
    await expect(consolePanel.getByText(/Trascrizione chunk 1\/2\.\.\./)).toHaveCount(1);
    await expect(consolePanel.getByText(/Revisione macro-blocchi\.\.\./)).toHaveCount(1);
    await expect(consolePanel.getByText(/Completato!/)).toHaveCount(1);
    await page.screenshot({ path: testInfo.outputPath('completed-console.png') });

    await completedCard.click();
    await expect(page.locator('.ProseMirror, [contenteditable="true"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Ciclo Cardiaco/i })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Apri file HTML' })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('editor.png') });

    await page.getByRole('button', { name: /Torna indietro/i }).click();
    await page.getByRole('button', { name: 'Pulisci tutto' }).click();
    await page.getByRole('button', { name: 'Conferma pulizia' }).click();
    await expect(completedCard).toHaveCount(0);
    await page.getByRole('button', { name: 'Archivio' }).click();
    await expect(page.getByText('Archivio Sbobine')).toBeVisible();
    await expect(page.getByText(/lezione test/i).first()).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('archive.png') });
  });

  for (const scenario of ['failure', 'paused', 'quota', 'regenerate'] as const) {
    test(`shows the expected UI for ${scenario}`, async ({ page }, testInfo) => {
      const fixturePath = createAudioFixture(testInfo);
      await page.goto('/');
      await selectScenario(page, scenario);
      await uploadFromDropzone(page, fixturePath);
      await startScenario(page);

      const expected = {
        failure: /Errore simulato|file audio danneggiato/i,
        paused: /Elaborazione in pausa|Capacità Google Gemini temporaneamente esaurita/i,
        quota: /Chiavi.*esaurite|limite API|nuova chiave/i,
        regenerate: /già completato|rigenerare|versione pronta/i,
      }[scenario];
      await expect(page.getByText(expected).first()).toBeVisible({ timeout: 10_000 });
      await page.screenshot({ path: testInfo.outputPath(`${scenario}.png`) });
    });
  }

  test('exports, imports, and streams simulated session audio', async ({ page }, testInfo) => {
    const fixturePath = createAudioFixture(testInfo);
    await page.goto('/');
    await selectScenario(page, 'success');
    await uploadFromDropzone(page, fixturePath);
    await startScenario(page);
    await expect(page.getByText('Sbobine completate')).toBeVisible({ timeout: 15_000 });

    const session = await page.evaluate(async () => {
      const response = await window.pywebview?.api?.get_completed_sessions?.(10);
      return response?.sessions?.[0];
    });
    expect(session?.session_dir).toBeTruthy();

    const media = await page.evaluate(async sessionDir => {
      const resolved = await window.pywebview?.api?.stream_media_file?.('', sessionDir);
      if (!resolved?.ok || !resolved.url) return resolved;
      const response = await fetch(resolved.url, { credentials: 'include' });
      return { ...resolved, status: response.status, size: (await response.arrayBuffer()).byteLength };
    }, session!.session_dir);
    expect(media?.ok).toBe(true);
    expect(media?.has_audio).toBe(true);
    expect(media?.status).toBe(200);
    expect(media?.size).toBeGreaterThan(0);

    const downloadPromise = page.waitForEvent('download');
    const exportPromise = page.evaluate(async sessionDir => {
      return window.pywebview?.api?.export_sbobina_package?.(sessionDir, 'full');
    }, session!.session_dir);
    const download = await downloadPromise;
    const packagePath = testInfo.outputPath('roundtrip.sbobina');
    await download.saveAs(packagePath);
    expect((await exportPromise)?.ok).toBe(true);
    expect(fs.statSync(packagePath).size).toBeGreaterThan(0);

    const importPromise = page.evaluate(async () => {
      return window.pywebview?.api?.import_sbobina_package?.();
    });
    const chooser = await page.waitForEvent('filechooser');
    await chooser.setFiles(packagePath);
    const imported = await importPromise;
    expect(imported?.ok || imported?.conflict).toBeTruthy();
  });

  test('browser capabilities hide desktop-only settings controls', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Impostazioni/i }).click();
    await expect(page.getByRole('heading', { name: 'Impostazioni' })).toBeVisible();
    await expect(page.getByText('Notifiche desktop')).toHaveCount(0);
    await expect(page.getByText('Versione applicazione')).toHaveCount(0);

    await page.getByRole('button', { name: 'Archiviazione' }).click();
    await expect(page.getByRole('button', { name: 'Cambia cartella' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Diagnostica' }).click();
    await expect(page.getByRole('button', { name: 'Apri cartella log' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Verifica ambiente' }).click();
    await expect(page.getByText(/API simulata/i)).toBeVisible();
  });
});
