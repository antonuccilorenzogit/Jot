import { describe, expect, it, vi } from 'vitest';
import { readAndOptimizeImageAsDataUrl, optimizeDataUrlImage, convertWebpImagesInHtml } from './utils';

describe('readAndOptimizeImageAsDataUrl (browser / jsdom environment)', () => {
  it('preserves SVG files without raster optimization', async () => {
    const mockSvgResult = 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockSvgResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    try {
      const file = new File(['<svg></svg>'], 'image.svg', { type: 'image/svg+xml' });
      const res = await readAndOptimizeImageAsDataUrl(file);
      expect(res).toBe(mockSvgResult);
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });

  it('preserves GIF files without raster optimization', async () => {
    const mockGifResult = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockGifResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    try {
      const file = new File(['gifdata'], 'image.gif', { type: 'image/gif' });
      const res = await readAndOptimizeImageAsDataUrl(file);
      expect(res).toBe(mockGifResult);
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });

  it('optimizes standard image files to JPEG with white background for compatibility', async () => {
    const mockRawResult = 'data:image/png;base64,originalrawdata';
    const mockJpegResult = 'data:image/jpeg;base64,compressedjpegdata';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockRawResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    class MockImage {
      naturalWidth = 3200;
      naturalHeight = 2400;
      width = 3200;
      height = 2400;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    const fillRectMock = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({
            fillStyle: '',
            fillRect: fillRectMock,
            drawImage: vi.fn(),
          }),
          toDataURL: (format: string) => {
            if (format === 'image/jpeg') return mockJpegResult;
            return 'data:image/jpeg;base64,fallback';
          },
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const file = new File(['pngdata'], 'photo.png', { type: 'image/png' });
      const res = await readAndOptimizeImageAsDataUrl(file);
      expect(res).toBe(mockJpegResult);
      expect(fillRectMock).toHaveBeenCalled();
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });

  it('keeps rawDataUrl when JPEG image is already within bounds and small', async () => {
    const mockRawResult = 'data:image/jpeg;base64,tinyjpeg';
    const mockLargerJpegResult = 'data:image/jpeg;base64,largercompresseddataforverytinyinput';
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      result = mockRawResult;
      onload: (() => void) | null = null;
      readAsDataURL() {
        if (this.onload) this.onload();
      }
    };

    class MockImage {
      naturalWidth = 200;
      naturalHeight = 100;
      width = 200;
      height = 100;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({
            fillRect: vi.fn(),
            drawImage: vi.fn(),
          }),
          toDataURL: () => mockLargerJpegResult,
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const file = new File(['jpegdata'], 'tiny.jpg', { type: 'image/jpeg' });
      const res = await readAndOptimizeImageAsDataUrl(file);
      expect(res).toBe(mockRawResult);
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });

  it('rejects on FileReader error', async () => {
    const mockError = new Error('read error');
    const originalFileReader = (globalThis as unknown as { FileReader: unknown }).FileReader;

    (globalThis as unknown as { FileReader: unknown }).FileReader = class {
      error = mockError;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        if (this.onerror) this.onerror();
      }
    };

    try {
      const file = new File(['data'], 'photo.png', { type: 'image/png' });
      await expect(readAndOptimizeImageAsDataUrl(file)).rejects.toThrow('read error');
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = originalFileReader;
    }
  });
});

describe('optimizeDataUrlImage (browser / jsdom environment)', () => {
  it('returns original string when not a data:image/ URL', async () => {
    expect(await optimizeDataUrlImage('')).toBe('');
    expect(await optimizeDataUrlImage('https://example.com/image.png')).toBe('https://example.com/image.png');
  });

  it('preserves SVG and GIF data URLs', async () => {
    const svgUrl = 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=';
    const gifUrl = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    expect(await optimizeDataUrlImage(svgUrl)).toBe(svgUrl);
    expect(await optimizeDataUrlImage(gifUrl)).toBe(gifUrl);
  });

  it('converts WebP data URLs to JPEG for Google Docs compatibility', async () => {
    const inputWebp = 'data:image/webp;base64,smallwebp';
    const mockJpegResult = 'data:image/jpeg;base64,convertedjpeg';
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    class MockImage {
      naturalWidth = 800;
      naturalHeight = 600;
      width = 800;
      height = 600;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({
            fillRect: vi.fn(),
            drawImage: vi.fn(),
          }),
          toDataURL: () => mockJpegResult,
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const res = await optimizeDataUrlImage(inputWebp);
      expect(res).toBe(mockJpegResult);
    } finally {
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });

  it('optimizes large uncompressed PNG data URLs to JPEG', async () => {
    const largePng = 'data:image/png;base64,' + 'A'.repeat(300_000);
    const mockJpegResult = 'data:image/jpeg;base64,compressedjpeg';
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    class MockImage {
      naturalWidth = 3840;
      naturalHeight = 2160;
      width = 3840;
      height = 2160;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({
            fillRect: vi.fn(),
            drawImage: vi.fn(),
          }),
          toDataURL: () => mockJpegResult,
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const res = await optimizeDataUrlImage(largePng);
      expect(res).toBe(mockJpegResult);
    } finally {
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });
});

describe('prepareHtmlForClipboard / convertWebpImagesInHtml', () => {
  it('returns original HTML if no images are present', async () => {
    const html = '<p>Test text without images</p>';
    expect(await convertWebpImagesInHtml(html)).toBe(html);
  });

  it('resamples images to target pixel width based on data-width', async () => {
    const inputHtml = '<div data-editor-image="true" data-width="35"><img src="data:image/jpeg;base64,largejpeg" /></div>';
    const mockJpegResult = 'data:image/jpeg;base64,smalljpeg';
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    class MockImage {
      naturalWidth = 1200;
      naturalHeight = 900;
      width = 1200;
      height = 900;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    let canvasWidth = 0;
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        const c = {
          width: 0,
          height: 0,
          getContext: () => ({
            fillRect: vi.fn(),
            drawImage: vi.fn(),
          }),
          toDataURL: () => mockJpegResult,
        };
        Object.defineProperty(c, 'width', {
          set(v: number) { canvasWidth = v; },
          get() { return canvasWidth; },
        });
        return c as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const result = await convertWebpImagesInHtml(inputHtml);
      expect(result).toContain('data:image/jpeg;base64,smalljpeg');
      expect(result).toContain('width="222"');
      expect(result).toMatch(/width:\s*35%/);
      expect(canvasWidth).toBe(222);
    } finally {
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });

  it('converts webp images to JPEG inside HTML string', async () => {
    const inputHtml = '<p>Intro</p><img src="data:image/webp;base64,webpdata" alt="test" /><p>Outro</p>';
    const mockJpegResult = 'data:image/jpeg;base64,jpegdata';
    const originalImage = (globalThis as unknown as { Image: unknown }).Image;

    class MockImage {
      naturalWidth = 400;
      naturalHeight = 300;
      width = 400;
      height = 300;
      onload: (() => void) | null = null;
      set src(_val: string) {
        setTimeout(() => {
          if (this.onload) this.onload();
        }, 0);
      }
    }
    (globalThis as unknown as { Image: unknown }).Image = MockImage;

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ({
            fillRect: vi.fn(),
            drawImage: vi.fn(),
          }),
          toDataURL: () => mockJpegResult,
        } as unknown as HTMLCanvasElement;
      }
      return originalCreateElement(tagName);
    });

    try {
      const result = await convertWebpImagesInHtml(inputHtml);
      expect(result).toContain('data:image/jpeg;base64,jpegdata');
      expect(result).not.toContain('data:image/webp;base64,webpdata');
    } finally {
      (globalThis as unknown as { Image: unknown }).Image = originalImage;
      vi.restoreAllMocks();
    }
  });
});
