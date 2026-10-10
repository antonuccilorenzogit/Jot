import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { ShareExportModal } from './ShareExportModal';
import type { ArchiveSession } from '../../bridge';

const mockSession: ArchiveSession = {
  name: 'Lezione di Anatomia.mp3',
  completed_at_iso: '2026-08-03T00:00:00Z',
  html_path: '/path/to/Sbobina.html',
  effective_model: 'gemini-2.5-pro',
  input_path: '/path/to/lezione.mp3',
  session_dir: '/path/to/session_dir',
};

describe('ShareExportModal', () => {
  beforeEach(() => {
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it('renders nothing when session is null', () => {
    render(<ShareExportModal session={null} onClose={vi.fn()} />);
    expect(screen.queryByText('Esporta Pacchetto Sbobina')).toBeNull();
  });

  it('renders session name and options when session is provided', () => {
    render(<ShareExportModal session={mockSession} onClose={vi.fn()} />);
    expect(screen.getByText('Esporta Pacchetto Sbobina')).toBeTruthy();
    expect(screen.getByText('Lezione di Anatomia.mp3')).toBeTruthy();
    expect(screen.getByText('Sbobina + Audio (Completo)')).toBeTruthy();
    expect(screen.getByText('Solo Sbobina (Leggero)')).toBeTruthy();
    expect(screen.getByText('Solo Audio')).toBeTruthy();
  });

  it('switches option selection when clicking option cards', () => {
    render(<ShareExportModal session={mockSession} onClose={vi.fn()} />);
    const soloSbobinaCard = screen.getByText('Solo Sbobina (Leggero)');
    fireEvent.click(soloSbobinaCard);
    expect(screen.getByText('Solo Sbobina (Leggero)')).toBeTruthy();
  });

  it('triggers export API call when clicking Esporta Pacchetto button', async () => {
    const exportMock = vi.fn().mockResolvedValue({
      ok: true,
      audio_included: true,
      target_path: '/saved/path/lezione.sbobina',
    });
    (window as unknown as { pywebview: { api: { export_sbobina_package: typeof exportMock } } }).pywebview = {
      api: {
        export_sbobina_package: exportMock,
      },
    };

    render(<ShareExportModal session={mockSession} onClose={vi.fn()} />);
    const exportBtn = screen.getByText('Esporta Pacchetto (.sbobina)');
    fireEvent.click(exportBtn);

    await waitFor(() => {
      expect(exportMock).toHaveBeenCalledWith('/path/to/session_dir', 'full');
      expect(screen.getByText(/Pacchetto \.sbobina salvato con successo/)).toBeTruthy();
      expect(screen.getByText('Apri cartella del pacchetto')).toBeTruthy();
    });
  });

  it('calls onClose when X button is clicked', () => {
    const onClose = vi.fn();
    render(<ShareExportModal session={mockSession} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Chiudi finestra'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
