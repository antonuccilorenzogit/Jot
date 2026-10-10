import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('webui Content-Security-Policy', () => {
  it('allows pywebview dynamic bridge evaluation on macOS WebKit', () => {
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    expect(html).toContain('http-equiv="Content-Security-Policy"');

    // Extract CSP content
    const match = /<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"/i.exec(html);
    expect(match).not.toBeNull();
    const csp = match![1];

    // pywebview generates JS bridge functions dynamically via new Function(...) in api.js
    // WebKit (macOS) strictly enforces document CSP on evaluateJavaScript; missing 'unsafe-eval'
    // throws an uncaught EvalError that breaks window.pywebview.api.* on boot.
    expect(csp).toMatch(/script-src[^;]*'unsafe-eval'/);
    expect(csp).toMatch(/script-src[^;]*'unsafe-inline'/);
  });
});
