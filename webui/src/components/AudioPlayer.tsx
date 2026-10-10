import { reportClientError } from '../diagnostics';
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Keyboard, Link, Pause, Play, RefreshCw, RotateCcw, SkipBack, SkipForward, Unlink, Volume2 } from 'lucide-react';
import { ConfirmActionModal } from './modals/ConfirmActionModal';
import { AUDIO_SEEK_EVENT, type AudioSeekDetail } from '../audioSeek';

interface AudioPlayerProps {
  src: string;
  initialTime?: number;
  initialPlaybackRate?: number;
  initialVolume?: number;
  onStateChange?: (state: { currentTime: number; playbackRate: number; volume: number }) => void;
  onRelink?: () => Promise<boolean | undefined>;
  onRemoveAudio?: () => Promise<boolean | undefined> | void;
}

const PLAYBACK_RATES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3];

const INTERACTIVE_ARIA_ROLES = new Set([
  'button', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
  'option', 'tab', 'treeitem', 'slider', 'spinbutton', 'combobox',
  'radio', 'checkbox', 'switch',
]);

const isEditableTarget = (target: EventTarget | null): boolean => {
  if (!target) return false;
  const el = target as HTMLElement;
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable) return true;
  if (el.tagName === 'BUTTON' || el.tagName === 'A') return true;
  const role = el.getAttribute('role');
  return role !== null && INTERACTIVE_ARIA_ROLES.has(role);
};

export function AudioPlayer({ src, initialTime, initialPlaybackRate, initialVolume, onStateChange, onRelink, onRemoveAudio }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(initialPlaybackRate ?? 1);
  const [volume, setVolume] = useState(initialVolume ?? 1);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [isSpeedOpen, setIsSpeedOpen] = useState(false);
  const [speedPanelPos, setSpeedPanelPos] = useState({ bottom: 0, left: 0 });
  const speedBtnRef = useRef<HTMLButtonElement>(null);
  const speedPanelRef = useRef<HTMLDivElement>(null);
  const [isRelinking, setIsRelinking] = useState(false);
  const [showAudioMenu, setShowAudioMenu] = useState(false);
  const [showConfirmRemove, setShowConfirmRemove] = useState(false);
  const audioMenuRef = useRef<HTMLDivElement>(null);
  const shortcutsRef = useRef<HTMLDivElement>(null);
  const pendingInitialTimeRef = useRef<number | null>(initialTime ?? null);
  const playbackRateRef = useRef(initialPlaybackRate ?? 1);
  const volumeRef = useRef(initialVolume ?? 1);
  const durationRef = useRef(0);
  const onStateChangeRef = useRef(onStateChange);
  useEffect(() => { onStateChangeRef.current = onStateChange; }, [onStateChange]);
  useEffect(() => { durationRef.current = duration; }, [duration]);

  // Jump requests coming from the notes (time chips on the headings).
  useEffect(() => {
    const onSeek = (event: Event) => {
      const audio = audioRef.current;
      const detail = (event as CustomEvent<AudioSeekDetail>).detail;
      if (!audio || !detail || !Number.isFinite(detail.time)) return;
      const max = isFinite(audio.duration) && audio.duration > 0 ? audio.duration : detail.time;
      audio.currentTime = Math.max(0, Math.min(detail.time, max));
      setCurrentTime(audio.currentTime);
      if (detail.play !== false) {
        void audio.play()?.catch?.(() => {});
      }
    };
    window.addEventListener(AUDIO_SEEK_EVENT, onSeek);
    return () => window.removeEventListener(AUDIO_SEEK_EVENT, onSeek);
  }, []);

  useEffect(() => {
    if (!audioRef.current) return;
    audioRef.current.volume = volume;
    audioRef.current.playbackRate = playbackRate;
  }, [volume, playbackRate]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
    audio.pause();
    audio.currentTime = 0;
    pendingInitialTimeRef.current = initialTime ?? null;
    audio.load();

    const syncDuration = () => {
      if (isFinite(audio.duration) && audio.duration > 0) {
        setDuration(audio.duration);
      }
    };

    syncDuration();
    const timeoutId = window.setTimeout(syncDuration, 300);
    return () => window.clearTimeout(timeoutId);
  }, [initialTime, src]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play();
      setIsPlaying(true);
      return;
    }
    audio.pause();
    setIsPlaying(false);
  }, []);

  const togglePlayRef = useRef(togglePlay);
  useEffect(() => { togglePlayRef.current = togglePlay; }, [togglePlay]);

  const skip = useCallback((amount: number) => {
    if (!audioRef.current) return;
    let next = audioRef.current.currentTime + amount;
    if (next < 0) next = 0;
    const dur = durationRef.current;
    if (dur > 0 && next > dur) next = dur;
    audioRef.current.currentTime = next;
    setCurrentTime(next);
  }, []);

  const skipRef = useRef(skip);
  useEffect(() => { skipRef.current = skip; }, [skip]);

  const adjustVolume = useCallback((delta: number) => {
    const newVol = Math.max(0, Math.min(1, volumeRef.current + delta));
    volumeRef.current = newVol;
    setVolume(newVol);
    if (audioRef.current) audioRef.current.volume = newVol;
    onStateChangeRef.current?.({ currentTime: audioRef.current?.currentTime ?? 0, playbackRate: playbackRateRef.current, volume: newVol });
  }, []);

  const adjustVolumeRef = useRef(adjustVolume);
  useEffect(() => { adjustVolumeRef.current = adjustVolume; }, [adjustVolume]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'F4' && !e.altKey && !e.ctrlKey && !e.shiftKey) {
        const el = e.target as HTMLElement;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return;
        e.preventDefault();
        togglePlayRef.current();
        return;
      }
      if (isEditableTarget(e.target)) return;
      switch (e.code) {
        case 'Space':
          if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
            e.preventDefault();
            togglePlayRef.current();
          }
          break;
        case 'ArrowLeft':
          if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); skipRef.current(-10); }
          break;
        case 'ArrowRight':
          if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); skipRef.current(10); }
          break;
        case 'ArrowUp':
          if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); adjustVolumeRef.current(0.05); }
          break;
        case 'ArrowDown':
          if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); adjustVolumeRef.current(-0.05); }
          break;
      }
    };
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, []);

  useEffect(() => {
    if (!showShortcuts) return;
    const handler = (e: PointerEvent) => {
      if (shortcutsRef.current && !shortcutsRef.current.contains(e.target as Node)) {
        setShowShortcuts(false);
      }
    };
    document.addEventListener('pointerdown', handler);
    return () => document.removeEventListener('pointerdown', handler);
  }, [showShortcuts]);

  useEffect(() => {
    if (!showAudioMenu) return;
    const handler = (e: PointerEvent) => {
      if (audioMenuRef.current && !audioMenuRef.current.contains(e.target as Node)) {
        setShowAudioMenu(false);
      }
    };
    document.addEventListener('pointerdown', handler);
    return () => document.removeEventListener('pointerdown', handler);
  }, [showAudioMenu]);

  const toggleSpeedOpen = () => {
    if (!isSpeedOpen && speedBtnRef.current) {
      const rect = speedBtnRef.current.getBoundingClientRect();
      const estimatedWidth = 60;
      const centeredLeft = rect.left + (rect.width - estimatedWidth) / 2;
      setSpeedPanelPos({
        bottom: Math.max(10, window.innerHeight - rect.top + 6),
        left: Math.round(Math.max(8, Math.min(window.innerWidth - estimatedWidth - 8, centeredLeft))),
      });
    }
    setIsSpeedOpen(prev => !prev);
  };

  useLayoutEffect(() => {
    if (!isSpeedOpen || !speedBtnRef.current) return;
    const btnRect = speedBtnRef.current.getBoundingClientRect();
    const measuredWidth = speedPanelRef.current?.getBoundingClientRect().width;
    const panelWidth = measuredWidth && measuredWidth > 0 ? measuredWidth : 60;
    const centeredLeft = btnRect.left + (btnRect.width - panelWidth) / 2;
    const clampedLeft = Math.max(8, Math.min(window.innerWidth - panelWidth - 8, centeredLeft));
    const newBottom = Math.max(10, window.innerHeight - btnRect.top + 6);
    const newLeft = Math.round(clampedLeft);
    setSpeedPanelPos(prev => {
      if (prev.bottom === newBottom && prev.left === newLeft) return prev;
      return { bottom: newBottom, left: newLeft };
    });
  }, [isSpeedOpen]);

  const handleSpeedSelect = (r: number) => {
    setIsSpeedOpen(false);
    playbackRateRef.current = r;
    setPlaybackRate(r);
    onStateChangeRef.current?.({ currentTime, playbackRate: r, volume: volumeRef.current });
  };

  useEffect(() => {
    if (!isSpeedOpen) return;
    const handler = (e: PointerEvent | MouseEvent) => {
      const target = e.target as Node;
      if (speedBtnRef.current?.contains(target) || speedPanelRef.current?.contains(target)) return;
      setIsSpeedOpen(false);
    };
    const handleScroll = (e: Event) => {
      if (speedPanelRef.current?.contains(e.target as Node)) return;
      setIsSpeedOpen(false);
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsSpeedOpen(false);
      }
    };
    document.addEventListener('pointerdown', handler, true);
    document.addEventListener('mousedown', handler, true);
    document.addEventListener('keydown', handleKeyDown, true);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', handleScroll, true);
    return () => {
      document.removeEventListener('pointerdown', handler, true);
      document.removeEventListener('mousedown', handler, true);
      document.removeEventListener('keydown', handleKeyDown, true);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', handleScroll, true);
    };
  }, [isSpeedOpen]);

  const handleTimeUpdate = () => {
    if (!audioRef.current) return;
    const t = audioRef.current.currentTime;
    setCurrentTime(t);
    if (isFinite(audioRef.current.duration) && audioRef.current.duration > 0) {
      setDuration(audioRef.current.duration);
    }
    onStateChangeRef.current?.({ currentTime: t, playbackRate: playbackRateRef.current, volume: volumeRef.current });
  };

  const handleLoadedMetadata = () => {
    if (!audioRef.current) return;
    audioRef.current.playbackRate = playbackRate;
    audioRef.current.volume = volume;
    if (isFinite(audioRef.current.duration)) {
      setDuration(audioRef.current.duration);
    }
    if (pendingInitialTimeRef.current !== null && pendingInitialTimeRef.current > 0) {
      const t = pendingInitialTimeRef.current;
      pendingInitialTimeRef.current = null;
      audioRef.current.currentTime = t;
      setCurrentTime(t);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (!audioRef.current) return;
    audioRef.current.currentTime = time;
    setCurrentTime(time);
  };

  const handleVolume = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = parseFloat(e.target.value);
    volumeRef.current = v;
    setVolume(v);
    onStateChangeRef.current?.({ currentTime, playbackRate: playbackRateRef.current, volume: v });
  };

  const formatTime = (time: number) => {
    if (isNaN(time) || !isFinite(time)) return '0:00';
    const min = Math.floor(time / 60);
    const sec = Math.floor(time % 60);
    return `${min}:${sec < 10 ? '0' : ''}${sec}`;
  };

  const handleRelink = async () => {
    if (isRelinking) return;
    setIsRelinking(true);
    try {
      await onRelink?.();
    } catch (e) {
      reportClientError('Failed to relink audio:', e);
    } finally {
      setIsRelinking(false);
    }
  };

  const [isRemovingAudio, setIsRemovingAudio] = useState(false);

  const handleRemoveAudio = async () => {
    if (isRemovingAudio) return;
    setIsRemovingAudio(true);
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        setIsPlaying(false);
      }
      await onRemoveAudio?.();
    } catch (e) {
      reportClientError('Failed to remove audio:', e);
    } finally {
      setIsRemovingAudio(false);
    }
  };

  return (
    <div
      className="flex w-full flex-wrap items-center gap-2 px-0.5 py-1.5"
      style={{ background: 'transparent' }}
    >
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onLoadedData={handleLoadedMetadata}
        onCanPlay={handleLoadedMetadata}
        onDurationChange={e => {
          if (isFinite(e.currentTarget.duration)) setDuration(e.currentTarget.duration);
        }}
        onEnded={() => setIsPlaying(false)}
      />

      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={togglePlay}
          className={`player-control group ${isPlaying ? 'is-active' : ''}`}
          aria-label={isPlaying ? 'Metti in pausa' : 'Avvia riproduzione'}
        >
          {isPlaying ? <Pause className="h-4 w-4 transition-transform duration-150 group-hover:scale-105" strokeWidth={2.2} /> : <Play className="ml-[1px] h-4 w-4 fill-current transition-transform duration-150 group-hover:scale-105" strokeWidth={2.2} />}
        </button>
        <button type="button" onClick={() => skip(-10)} className="player-control group" aria-label="Indietro di 10 secondi">
          <SkipBack className="h-4 w-4 transition-transform duration-150 group-hover:-translate-x-0.5" />
        </button>
        <button type="button" onClick={() => skip(10)} className="player-control group" aria-label="Avanti di 10 secondi">
          <SkipForward className="h-4 w-4 transition-transform duration-150 group-hover:translate-x-0.5" />
        </button>
      </div>

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <input
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          className="custom-scrubber min-w-0 flex-1"
          style={{ '--progress': duration ? `${(currentTime / duration) * 100}%` : '0%' } as React.CSSProperties}
        />
        <span className="shrink-0 pr-0.5 text-[11px] font-semibold tabular-nums" style={{ color: 'var(--text-muted)' }}>
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <div className="player-speed-wrap relative" aria-label="Velocita di riproduzione">
          <select
            value={playbackRate}
            onChange={e => {
              const r = parseFloat(e.target.value);
              playbackRateRef.current = r;
              setPlaybackRate(r);
              onStateChangeRef.current?.({ currentTime, playbackRate: r, volume: volumeRef.current });
            }}
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
          >
            {PLAYBACK_RATES.map(rate => (
              <option key={rate} value={rate}>
                {rate}x
              </option>
            ))}
          </select>
          <button
            ref={speedBtnRef}
            type="button"
            onClick={toggleSpeedOpen}
            className={`player-speed-btn${isSpeedOpen ? ' is-active' : ''}`}
            title="Velocità di riproduzione"
            aria-haspopup="listbox"
            aria-expanded={isSpeedOpen}
          >
            <span className="text-xs font-semibold">{playbackRate}x</span>
            <ChevronDown
              size={10}
              style={{ opacity: 0.6, marginLeft: 2, flexShrink: 0 }}
              className={`transition-transform duration-150 ${isSpeedOpen ? 'rotate-180' : ''}`}
            />
          </button>
          {isSpeedOpen && createPortal(
            <div
              ref={speedPanelRef}
              role="listbox"
              aria-label="Velocità di riproduzione"
              className="editor-dropdown-panel player-speed-dropdown-panel open-up"
              style={{
                position: 'fixed',
                bottom: `${speedPanelPos.bottom}px`,
                left: `${speedPanelPos.left}px`,
                zIndex: 9999,
                minWidth: '60px',
                maxHeight: '240px',
                overflowY: 'auto',
              }}
            >
              {PLAYBACK_RATES.map(rate => {
                const isActive = playbackRate === rate;
                return (
                  <button
                    key={rate}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    className={`editor-dropdown-item${isActive ? ' is-active' : ''}`}
                    style={{ justifyContent: 'center', padding: '5px 8px', fontSize: '13px' }}
                    onClick={() => handleSpeedSelect(rate)}
                  >
                    <span>{rate}x</span>
                  </button>
                );
              })}
            </div>,
            document.body
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Volume2 className="h-3.5 w-3.5" style={{ color: 'var(--text-muted)' }} />
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={volume}
            onChange={handleVolume}
            className="custom-volume w-16"
            style={{ '--progress': `${volume * 100}%` } as React.CSSProperties}
          />
        </div>
        <button type="button" onClick={() => skip(-duration)} className="player-control group/rewind" aria-label="Torna all'inizio">
          <RotateCcw className="h-4 w-4 transition-transform duration-300 ease-out group-hover/rewind:-rotate-45 group-hover/rewind:scale-105" />
        </button>
        <div className="relative" ref={shortcutsRef}>
          <button
            type="button"
            className={`player-control ${showShortcuts ? 'is-active' : ''}`}
            aria-label="Scorciatoie da tastiera"
            onClick={() => setShowShortcuts(v => !v)}
          >
            <Keyboard className="h-3.5 w-3.5" />
          </button>
          {showShortcuts && (
            <div
              className="absolute bottom-full right-0 mb-2 z-50 rounded-lg border p-3 text-xs"
              style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border-subtle)', color: 'var(--text-muted)', minWidth: '230px', boxShadow: 'var(--shadow-strong)' }}
            >
              <div className="mb-2 font-semibold text-[11px]" style={{ color: 'var(--text-primary)' }}>Scorciatoie da tastiera</div>
              {([
                ['Spazio', 'Pausa / Riprendi'],
                ['F4', 'Pausa / Riprendi (in editor)'],
                ['\u2190 \u2192', 'Salta \u00b110 secondi'],
                ['\u2191 \u2193', 'Volume \u00b15%'],
              ] as [string, string][]).map(([key, desc]) => (
                <div key={key} className="flex items-center justify-between gap-4 py-0.5">
                  <kbd
                    className="rounded px-1.5 py-0.5 text-[10px] font-mono font-medium shrink-0"
                    style={{ background: 'var(--bg-base)', border: '1px solid var(--border-subtle)' }}
                  >{key}</kbd>
                  <span className="text-right">{desc}</span>
                </div>
              ))}
              <div className="mt-2 pt-2 text-[10px] leading-snug" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                Le scorciatoie freccia e Spazio sono attive solo quando il focus non è su un elemento interattivo (editor, pulsanti, ecc.)
              </div>
            </div>
          )}
        </div>
        {(onRelink || onRemoveAudio) && (
          <div className="relative" ref={audioMenuRef}>
            <button
              type="button"
              className={`player-control ${showAudioMenu ? 'is-active' : ''}`}
              aria-label="Opzioni audio collegato"
              title="Opzioni audio"
              onClick={() => setShowAudioMenu(v => !v)}
            >
              <Link className="h-3.5 w-3.5" />
            </button>
            {showAudioMenu && (
              <div
                className="absolute bottom-full right-0 mb-2 z-50 rounded-lg border p-1 text-xs min-w-[200px]"
                style={{
                  background: 'var(--bg-elevated)',
                  borderColor: 'var(--border-subtle)',
                  boxShadow: 'var(--shadow-strong)',
                }}
              >
                {onRelink && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowAudioMenu(false);
                      void handleRelink();
                    }}
                    disabled={isRelinking}
                    className="kebab-item text-xs"
                    style={{ padding: '6px 10px', fontSize: '13px' }}
                  >
                    <RefreshCw className="w-3.5 h-3.5 shrink-0" />
                    <span>Sostituisci file audio...</span>
                  </button>
                )}
                {onRemoveAudio && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowAudioMenu(false);
                      setShowConfirmRemove(true);
                    }}
                    disabled={isRemovingAudio}
                    className="kebab-item is-danger text-xs"
                    style={{ padding: '6px 10px', fontSize: '13px' }}
                  >
                    <Unlink className="w-3.5 h-3.5 shrink-0" />
                    <span>Rimuovi audio collegato</span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <ConfirmActionModal
        isOpen={showConfirmRemove}
        title="Rimuovere l'audio collegato?"
        description="L'audio verrà scollegato da questa sbobina. Il file originale sul tuo computer non verrà cancellato."
        confirmLabel={isRemovingAudio ? 'Rimozione...' : 'Rimuovi audio'}
        cancelLabel="Annulla"
        onClose={() => setShowConfirmRemove(false)}
        onConfirm={async () => {
          setShowConfirmRemove(false);
          await handleRemoveAudio();
        }}
      />
    </div>
  );
}
