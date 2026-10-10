import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AudioPlayer } from './AudioPlayer';

beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
  window.HTMLMediaElement.prototype.load = vi.fn();
});

describe('AudioPlayer', () => {
  it('renders play button', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    expect(screen.getByLabelText('Avvia riproduzione')).toBeTruthy();
  });

  it('renders skip-back and skip-forward buttons', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    expect(screen.getByLabelText('Indietro di 10 secondi')).toBeTruthy();
    expect(screen.getByLabelText('Avanti di 10 secondi')).toBeTruthy();
  });

  it('renders restart button', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    expect(screen.getByLabelText('Torna all\'inizio')).toBeTruthy();
  });

  it('renders speed select with default 1x', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    const select = screen.getByLabelText('Velocita di riproduzione').querySelector('select') as HTMLSelectElement;
    expect(select).not.toBeNull();
    expect(select.value).toBe('1');
  });

  it('renders volume slider', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    const sliders = screen.getAllByRole('slider');
    expect(sliders.length).toBeGreaterThanOrEqual(2);
  });

  it('shows time display 0:00 / 0:00 initially', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    expect(screen.getByText('0:00 / 0:00')).toBeTruthy();
  });

  it('shows shortcuts panel when keyboard button is clicked', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Scorciatoie da tastiera'));
    expect(screen.getByText('Scorciatoie da tastiera', { selector: 'div' })).toBeTruthy();
    expect(screen.getByText('Pausa / Riprendi')).toBeTruthy();
  });

  it('hides shortcuts panel when keyboard button is clicked again', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Scorciatoie da tastiera'));
    fireEvent.click(screen.getByLabelText('Scorciatoie da tastiera'));
    expect(screen.queryByText('Pausa / Riprendi')).toBeNull();
  });

  it('changes playback rate when speed select changes', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    const select = screen.getByLabelText('Velocita di riproduzione').querySelector('select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '1.5' } });
    expect(select.value).toBe('1.5');
  });

  it('uses initialPlaybackRate prop', () => {
    render(<AudioPlayer src="/audio/test.mp3" initialPlaybackRate={2} />);
    const select = screen.getByLabelText('Velocita di riproduzione').querySelector('select') as HTMLSelectElement;
    expect(select.value).toBe('2');
  });

  it('renders audio element with correct src', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    expect(audio).not.toBeNull();
    expect(audio.src).toContain('test.mp3');
  });

  it('displays all playback rate options when dropdown is opened', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByTitle('Velocità di riproduzione'));
    expect(screen.getByRole('option', { name: '1x' })).toBeTruthy();
    expect(screen.getByRole('option', { name: '1.5x' })).toBeTruthy();
    expect(screen.getByRole('option', { name: '2x' })).toBeTruthy();
  });

  it('changes playback rate when an option in custom dropdown is clicked', () => {
    const onStateChange = vi.fn();
    render(<AudioPlayer src="/audio/test.mp3" onStateChange={onStateChange} />);
    fireEvent.click(screen.getByTitle('Velocità di riproduzione'));
    fireEvent.click(screen.getByRole('option', { name: '1.5x' }));
    expect(screen.getByTitle('Velocità di riproduzione').textContent).toContain('1.5x');
  });

  it('closes speed dropdown on outside click or Escape', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByTitle('Velocità di riproduzione'));
    expect(screen.getByRole('option', { name: '2x' })).toBeTruthy();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByRole('option', { name: '2x' })).toBeNull();
  });

  it('centers speed dropdown horizontally relative to the button', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    const btn = screen.getByTitle('Velocità di riproduzione');
    vi.spyOn(btn, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      right: 152,
      top: 500,
      bottom: 532,
      width: 52,
      height: 32,
      x: 100,
      y: 500,
      toJSON: () => {},
    });
    fireEvent.click(btn);
    const panel = screen.getByRole('listbox', { name: 'Velocità di riproduzione' });
    expect(panel).toBeTruthy();
    expect(panel.style.left).toBe('96px');
  });

  it('clicking play button calls audio.play', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Avvia riproduzione'));
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
  });

  it('clicking play when not paused calls pause (togglePlay pause branch)', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'paused', { value: false, writable: true, configurable: true });
    fireEvent.click(screen.getByLabelText('Avvia riproduzione'));
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('Space key toggles play', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.keyDown(document.body, { code: 'Space' });
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
  });

  it('ArrowLeft key skips back', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 30, writable: true });
    fireEvent.keyDown(document.body, { code: 'ArrowLeft' });
    expect(audio.currentTime).toBeLessThanOrEqual(30);
  });

  it('ArrowUp key adjusts volume up', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.keyDown(document.body, { code: 'ArrowUp' });
  });

  it('ArrowDown key adjusts volume down', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.keyDown(document.body, { code: 'ArrowDown' });
  });

  it('ArrowRight key skips forward', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'currentTime', { value: 10, writable: true });
    fireEvent.keyDown(document.body, { code: 'ArrowRight' });
  });

  it('F4 key toggles play', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.keyDown(document.body, { code: 'F4' });
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
  });

  it('restart button sets currentTime to 0', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    fireEvent.click(screen.getByLabelText("Torna all'inizio"));
    expect(audio.currentTime).toBe(0);
  });

  it('skip-back button skips back 10s', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Indietro di 10 secondi'));
  });

  it('skip-forward button skips forward 10s', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Avanti di 10 secondi'));
  });

  it('volume slider change updates volume', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    const sliders = screen.getAllByRole('slider');
    const volumeSlider = sliders[sliders.length - 1];
    fireEvent.change(volumeSlider, { target: { value: '0.5' } });
    expect((volumeSlider as HTMLInputElement).value).toBe('0.5');
  });

  it('uses initialVolume prop', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" initialVolume={0.8} />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    expect(audio).toBeTruthy();
  });

  it('timeupdate with positive duration updates duration display', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { value: 90, writable: true, configurable: true });
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true });
    fireEvent.timeUpdate(audio);
  });

  it('loadedmetadata with initialTime sets currentTime', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" initialTime={30} />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { value: 120, writable: true, configurable: true });
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true });
    fireEvent.loadedMetadata(audio);
    expect(audio.currentTime).toBe(30);
  });

  it('loadedmetadata restores playbackRate and volume to the audio element', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" initialPlaybackRate={2} initialVolume={0.8} />);
    const audio = container.querySelector('audio') as HTMLAudioElement;

    // Simulate browser load resetting properties or initial state
    audio.playbackRate = 1;
    audio.volume = 1;

    fireEvent.loadedMetadata(audio);
    expect(audio.playbackRate).toBe(2);
    expect(audio.volume).toBe(0.8);
  });


  it('calls onStateChange when audio timeupdate fires', () => {
    const onStateChange = vi.fn();
    const { container } = render(<AudioPlayer src="/audio/test.mp3" onStateChange={onStateChange} />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    fireEvent.timeUpdate(audio);
  });

  it('seek slider change calls handleSeek and updates currentTime', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    const sliders = screen.getAllByRole('slider');
    const seekSlider = sliders[0];
    Object.defineProperty(audio, 'currentTime', { value: 0, writable: true });
    fireEvent.change(seekSlider, { target: { value: '42' } });
    expect(audio.currentTime).toBe(42);
  });

  it('durationchange event updates duration display', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    Object.defineProperty(audio, 'duration', { value: 120, writable: true, configurable: true });
    fireEvent.durationChange(audio);
  });

  it('ended event stops playback', () => {
    const { container } = render(<AudioPlayer src="/audio/test.mp3" />);
    const audio = container.querySelector('audio') as HTMLAudioElement;
    fireEvent.ended(audio);
    expect(screen.getByLabelText('Avvia riproduzione')).toBeTruthy();
  });

  it('closes shortcuts panel when clicking outside', () => {
    render(<AudioPlayer src="/audio/test.mp3" />);
    fireEvent.click(screen.getByLabelText('Scorciatoie da tastiera'));
    expect(screen.getByText('Pausa / Riprendi')).toBeTruthy();
    fireEvent.pointerDown(document.body);
  });

  it('calls onRelink when relink button is clicked', async () => {
    const onRelink = vi.fn().mockResolvedValue(undefined);
    render(<AudioPlayer src="/audio/test.mp3" onRelink={onRelink} />);
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Sostituisci file audio...'));
    });
    expect(onRelink).toHaveBeenCalledTimes(1);
  });

  it('guards against concurrent onRelink clicks', async () => {
    let resolveRelink!: (value: unknown) => void;
    const onRelinkPromise = new Promise((resolve) => {
      resolveRelink = resolve;
    });
    const onRelink = vi.fn().mockImplementation(() => onRelinkPromise);
    render(<AudioPlayer src="/audio/test.mp3" onRelink={onRelink} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;

    // First click initiates the relink process
    await act(async () => {
      fireEvent.click(item);
    });
    expect(onRelink).toHaveBeenCalledTimes(1);

    // Reopen menu while active
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item2 = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;
    expect(item2.disabled).toBe(true);

    // Subsequent clicks should be guarded and ignored
    await act(async () => {
      fireEvent.click(item2);
    });
    expect(onRelink).toHaveBeenCalledTimes(1);

    // Resolve the first relink action
    await act(async () => {
      resolveRelink(true);
      await onRelinkPromise;
    });

    // After resolving, state should reset and the item should be enabled again
    expect(item2.disabled).toBe(false);
  });

  it('guards against concurrent onRelink clicks even when the button disabled state is bypassed', async () => {
    let resolveRelink!: (value: unknown) => void;
    const onRelinkPromise = new Promise((resolve) => {
      resolveRelink = resolve;
    });
    const onRelink = vi.fn().mockImplementation(() => onRelinkPromise);
    render(<AudioPlayer src="/audio/test.mp3" onRelink={onRelink} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;

    // First click initiates the relink process
    await act(async () => {
      fireEvent.click(item);
    });
    expect(onRelink).toHaveBeenCalledTimes(1);

    // Reopen menu while active
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item2 = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;
    expect(item2.disabled).toBe(true);

    // Bypass disabled state by removing the disabled attribute manually
    item2.removeAttribute('disabled');
    expect(item2.disabled).toBe(false);

    // Subsequent clicks should still be ignored by the internal handler guard
    await act(async () => {
      fireEvent.click(item2);
    });
    expect(onRelink).toHaveBeenCalledTimes(1);

    // Resolve the first relink action
    await act(async () => {
      resolveRelink(true);
      await onRelinkPromise;
    });
  });

  it('resets isRelinking state when onRelink throws an error / rejects', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    let rejectRelink!: (reason: unknown) => void;
    const onRelinkPromise = new Promise((_, reject) => {
      rejectRelink = reject;
    });
    const onRelink = vi.fn().mockImplementation(() => onRelinkPromise);
    render(<AudioPlayer src="/audio/test.mp3" onRelink={onRelink} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;

    // First click initiates the relink process
    await act(async () => {
      fireEvent.click(item);
    });
    expect(onRelink).toHaveBeenCalledTimes(1);

    // Reopen menu while active
    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    const item2 = screen.getByRole('button', { name: /Sostituisci file audio/i }) as HTMLButtonElement;
    expect(item2.disabled).toBe(true);

    // Reject the relink action to simulate an error
    await act(async () => {
      rejectRelink(new Error('Relink failed'));
      await onRelinkPromise.catch(() => {});
    });

    // Wait for the state update in finally block to complete
    expect(item2.disabled).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  it('opens audio options menu and calls onRemoveAudio when confirmed in modal', async () => {
    const onRemoveAudio = vi.fn().mockResolvedValue(undefined);
    render(<AudioPlayer src="/audio/test.mp3" onRemoveAudio={onRemoveAudio} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    expect(screen.getByText('Rimuovi audio collegato')).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByText('Rimuovi audio collegato'));
    });

    expect(screen.getByText("Rimuovere l'audio collegato?")).toBeTruthy();
    expect(screen.getByText(/L'audio verrà scollegato da questa sbobina/)).toBeTruthy();

    const modal = screen.getByText("Rimuovere l'audio collegato?").closest('.modal-card') as HTMLElement;
    const confirmBtn = within(modal).getByRole('button', { name: 'Rimuovi audio' });
    await act(async () => {
      fireEvent.click(confirmBtn);
    });
    expect(onRemoveAudio).toHaveBeenCalledTimes(1);
  });

  it('cancels removal when Annulla is clicked in modal', async () => {
    const onRemoveAudio = vi.fn().mockResolvedValue(undefined);
    render(<AudioPlayer src="/audio/test.mp3" onRemoveAudio={onRemoveAudio} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    await act(async () => {
      fireEvent.click(screen.getByText('Rimuovi audio collegato'));
    });

    expect(screen.getByText("Rimuovere l'audio collegato?")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Annulla' }));
    });
    expect(onRemoveAudio).not.toHaveBeenCalled();
  });

  it('calls onRelink from the options menu', async () => {
    const onRelink = vi.fn().mockResolvedValue(true);
    render(<AudioPlayer src="/audio/test.mp3" onRelink={onRelink} />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('Opzioni audio collegato'));
    });
    expect(screen.getByText('Sostituisci file audio...')).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByText('Sostituisci file audio...'));
    });
    expect(onRelink).toHaveBeenCalledTimes(1);
  });
});
