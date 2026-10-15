import { normalizeSessionPath } from './utils';

export type FileItem = {
  id: string;
  name: string;
  size: number;
  duration: number;
  status: 'queued' | 'processing' | 'done' | 'error' | 'paused';
  progress: number;
  phase: number;
  phaseText?: string;
  errorText?: string;
  errorDetail?: string;
  retryable?: boolean;
  retryReason?: string;
  recommendedRetryAt?: string;
  forceRetry?: boolean;
  path?: string;
  outputHtml?: string;
  outputDir?: string;
  completedAt?: number;
  startedAt?: number;
  primaryModel?: string;
  effectiveModel?: string;
  resumeSession?: boolean;
  allowCompletedDestroy?: boolean;
  completionStatus?: 'completed' | 'completed_with_warnings';
  revisionFailedBlocks?: number[];
  isRetryingBlocks?: boolean;
  /** "notes" = Slide e appunti: path points to the slides (PDF/PPTX). */
  kind?: JobKind;
  notes?: NotesJobInfo;
  /** Name chosen on the "Nuova lezione" page and course for the archive. */
  title?: string;
  course?: string;
  /** Slides and book attached to an audio lesson. */
  lesson?: LessonJobInfo;
};

export type LessonJobInfo = {
  slidesPath?: string;
  slidesName?: string;
  slidesCount?: number;
  bookPath?: string;
  bookName?: string;
  /** Page selection of the book, e.g. "120-165". Empty = whole book. */
  bookPages?: string;
};

export type JobKind = 'audio' | 'notes';

export type NotesJobInfo = {
  /** Number of slides/pages of the slides file. */
  slides: number;
  bookPath?: string;
  bookName?: string;
  /** Page selection of the book, e.g. "120-165". Empty = whole book. */
  bookPages?: string;
  slidesPerChunk?: number;
  /** "auto" = only the book pages relevant to each block; "full" = whole excerpt. */
  bookMode?: BookMode;
};

export type BookMode = 'auto' | 'full';

export function isNotesJob(file: Pick<FileItem, 'kind'> | null | undefined): boolean {
  return file?.kind === 'notes';
}



export function getPendingFiles(files: FileItem[]): FileItem[] {
  return files.filter(f => f.status !== 'done');
}

/** Always returns a new sorted array. Wrap in useMemo to avoid per-render allocations. */
export function getDoneFiles(files: FileItem[]): FileItem[] {
  return [...files.filter(f => f.status === 'done')]
    .sort((a, b) => (b.completedAt ?? 0) - (a.completedAt ?? 0));
}

export type FileDescriptor = {
  id: string;
  path?: string;
  name: string;
  size: number;
  duration?: number;
  resume_session?: boolean;
  allow_completed_destroy?: boolean;
  force_retry?: boolean;
  kind?: JobKind;
  book_path?: string | null;
  book_pages?: string;
  slides_per_chunk?: number;
  book_mode?: BookMode;
  slides_path?: string | null;
  title?: string | null;
  course?: string | null;
};

export type AppStatus = 'idle' | 'processing' | 'canceling';

export type ProcessDonePayload = {
  cancelled?: boolean;
  completed?: number;
  completed_with_warnings?: number;
  failed?: number;
  paused?: number;
  total?: number;
  quota_exhausted?: boolean;
};

export function isSuccessfulProcessDone(data?: ProcessDonePayload | null): boolean {
  if (!data || data.cancelled) return false;
  return Number(data.completed ?? 0) > 0 && Number(data.completed_with_warnings ?? 0) === 0 && Number(data.failed ?? 0) === 0;
}

export type SetCurrentFilePayload = {
  index: number;
  id: string;
  total: number;
};

export type FileDonePayload = {
  index: number;
  id: string;
  output_html?: string;
  output_dir?: string;
  html_path?: string;
  session_dir?: string;
  primary_model?: string;
  effective_model?: string;
  completion_status?: 'completed' | 'completed_with_warnings';
  revision_failed_blocks?: number[];
};

export type FileFailedPayload = {
  index: number;
  id: string;
  error: string;
  error_detail?: string;
  retryable?: boolean;
  retry_reason?: string;
  recommended_retry_at?: string | null;
};

export type WorkTotalsPayload = {
  chunks?: number | null;
  macro?: number | null;
};

export type WorkDonePayload = {
  kind: 'chunks' | 'macro';
  done: number;
  total?: number | null;
};


export type ProcessingState = {
  files: FileItem[];
  structuralVersion: number;
  appState: AppStatus;
  currentPhase: string;
  currentModel: string;
  activeProgress: number;
  currentFileIndex: number;
  currentBatchTotal: number;
  workTotals: {
    chunks: number;
    macro: number;
  };
  workDone: {
    chunks: number;
    macro: number;
  };
};

export type ProcessingAction =
  | { type: 'queue/add'; files: FileItem[] }
  | { type: 'queue/prepend'; files: FileItem[] }
  | { type: 'queue/remove'; id: string }
  | { type: 'queue/reorder'; fromIndex: number; toIndex: number }
  | { type: 'queue/update_source'; id?: string; sessionDir?: string; path?: string; name?: string; size?: number; duration?: number }
  | { type: 'queue/clear_completed' }
  | { type: 'queue/retry_failed' }
  | { type: 'queue/retry_one'; id: string }
  | { type: 'queue/remap_session_roots'; oldRoot: string; newRoot: string }
  | { type: 'queue/update_revision_failed_blocks'; fileId?: string; sessionDir: string; blocks: number[]; htmlPath?: string; effectiveModel?: string }
  | { type: 'queue/set_retrying_blocks'; id: string; value: boolean }
  | { type: 'queue/clear_all' }
  | { type: 'app/set_status'; status: AppStatus }
  | { type: 'bridge/update_progress'; value: number }
  | { type: 'bridge/update_phase'; text: string }
  | { type: 'bridge/update_model'; model: string }
  | { type: 'bridge/process_done'; data: ProcessDonePayload }
  | { type: 'bridge/set_work_totals'; data: WorkTotalsPayload }
  | { type: 'bridge/update_work_done'; data: WorkDonePayload }
  | { type: 'bridge/set_current_file'; data: SetCurrentFilePayload }
  | { type: 'bridge/file_done'; data: FileDonePayload }
  | { type: 'bridge/file_failed'; data: FileFailedPayload };

export function createInitialProcessingState(initialFiles: FileItem[] = []): ProcessingState {
  return {
    files: initialFiles,
    structuralVersion: 0,
    appState: 'idle',
    currentPhase: '',
    currentModel: '',
    activeProgress: 0,
    currentFileIndex: 0,
    currentBatchTotal: 0,
    workTotals: {
      chunks: 0,
      macro: 0,
    },
    workDone: {
      chunks: 0,
      macro: 0,
    },
  };
}

export const initialProcessingState: ProcessingState = createInitialProcessingState();

export function processingReducer(state: ProcessingState, action: ProcessingAction): ProcessingState {
  switch (action.type) {
    case 'queue/add':
      return { ...state, structuralVersion: state.structuralVersion + 1, files: [...state.files, ...action.files] };
    case 'queue/prepend':
      return { ...state, structuralVersion: state.structuralVersion + 1, files: [...action.files, ...state.files] };
    case 'queue/remove':
      return { ...state, structuralVersion: state.structuralVersion + 1, files: state.files.filter(file => file.id !== action.id) };
    case 'queue/reorder': {
      const { fromIndex, toIndex } = action;
      if (fromIndex === toIndex) return state;
      if (fromIndex < 0 || fromIndex >= state.files.length) return state;
      if (toIndex < 0 || toIndex >= state.files.length) return state;
      const files = [...state.files];
      const [moved] = files.splice(fromIndex, 1);
      files.splice(toIndex, 0, moved);
      return { ...state, structuralVersion: state.structuralVersion + 1, files };
    }
    case 'queue/update_source':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        files: state.files.map(file =>
          (action.id ? file.id === action.id : false)
          || (action.sessionDir ? normalizeSessionPath(file.outputDir) === normalizeSessionPath(action.sessionDir) : false)
            ? {
                ...file,
                path: action.path ?? file.path,
                name: action.name ?? file.name,
                size: action.size ?? file.size,
                duration: action.duration ?? file.duration,
              }
            : file,
        ),
      };
    case 'queue/remap_session_roots': {
      const { oldRoot, newRoot } = action;
      if (!oldRoot || !newRoot) return state;
      const normOld = normalizeSessionPath(oldRoot);
      const cleanNew = newRoot.replace(/[/\\]+$/, '');
      let changed = false;
      const files = state.files.map(file => {
        let nextOutputDir = file.outputDir;
        let nextOutputHtml = file.outputHtml;
        let fileChanged = false;

        if (file.outputDir) {
          const normDir = normalizeSessionPath(file.outputDir);
          if (normDir === normOld) {
            nextOutputDir = cleanNew;
            fileChanged = true;
          } else if (normDir.startsWith(normOld + '/')) {
            const rel = normDir.slice(normOld.length + 1);
            nextOutputDir = `${cleanNew}/${rel}`;
            fileChanged = true;
          }
        }
        if (file.outputHtml) {
          const normHtml = normalizeSessionPath(file.outputHtml);
          if (normHtml === normOld) {
            nextOutputHtml = cleanNew;
            fileChanged = true;
          } else if (normHtml.startsWith(normOld + '/')) {
            const rel = normHtml.slice(normOld.length + 1);
            nextOutputHtml = `${cleanNew}/${rel}`;
            fileChanged = true;
          }
        }
        if (!fileChanged) return file;
        changed = true;
        return {
          ...file,
          outputDir: nextOutputDir,
          outputHtml: nextOutputHtml,
        };
      });
      if (!changed) return state;
      return { ...state, structuralVersion: state.structuralVersion + 1, files };
    }
    case 'queue/clear_completed':
      return { ...state, structuralVersion: state.structuralVersion + 1, files: state.files.filter(file => file.status !== 'done') };
    case 'queue/retry_failed':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        files: state.files.map(file =>
          file.status === 'error' || file.status === 'paused'
            ? { ...file, status: 'queued', progress: 0, phase: 0, phaseText: undefined, errorText: undefined, errorDetail: undefined, forceRetry: file.status === 'paused', retryable: undefined, retryReason: undefined, recommendedRetryAt: undefined, resumeSession: undefined }
            : file,
        ),
      };
    case 'queue/retry_one':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        files: state.files.map(file =>
          file.id === action.id && (file.status === 'error' || file.status === 'paused')
            ? { ...file, status: 'queued', progress: 0, phase: 0, phaseText: undefined, errorDetail: undefined, errorText: undefined, forceRetry: file.status === 'paused', retryable: undefined, retryReason: undefined, recommendedRetryAt: undefined, resumeSession: undefined }
            : file,
        ),
      };
    case 'queue/update_revision_failed_blocks': {
      const targetDir = normalizeSessionPath(action.sessionDir);
      const hasFileIdMatch = action.fileId
        ? state.files.some(file => file.id === action.fileId)
        : false;
      let changed = false;
      const files = state.files.map(file => {
        const matches = hasFileIdMatch
          ? file.id === action.fileId
          : normalizeSessionPath(file.outputDir) === targetDir;
        if (!matches) return file;
        changed = true;
        return {
          ...file,
          status: 'done' as const,
          isRetryingBlocks: false,
          revisionFailedBlocks: action.blocks,
          completionStatus: action.blocks.length > 0 ? ('completed_with_warnings' as const) : ('completed' as const),
          outputHtml: action.htmlPath ?? file.outputHtml,
          effectiveModel: action.effectiveModel ?? file.effectiveModel,
        };
      });
      if (!changed) return state;
      return { ...state, structuralVersion: state.structuralVersion + 1, files };
    }
    case 'queue/set_retrying_blocks': {
      const target = state.files.find(file => file.id === action.id);
      if (!target) return state;
      const updatedTarget: FileItem = {
        ...target,
        isRetryingBlocks: action.value,
        status: action.value ? ('processing' as const) : ('done' as const),
      };
      if (action.value) {
        const remaining = state.files.filter(file => file.id !== action.id);
        return {
          ...state,
          structuralVersion: state.structuralVersion + 1,
          files: [updatedTarget, ...remaining],
        };
      }
      const files = state.files.map(file => (file.id === action.id ? updatedTarget : file));
      return { ...state, structuralVersion: state.structuralVersion + 1, files };
    }
    case 'queue/clear_all':
      return { ...state, structuralVersion: state.structuralVersion + 1, files: state.files.filter(file => file.status === 'done') };
    case 'app/set_status':
      return { ...state, appState: action.status };
    case 'bridge/update_progress': {
      const next = Math.round(action.value * 100);
      if (state.activeProgress === next) return state;
      return { ...state, activeProgress: next };
    }
    case 'bridge/update_phase':
      if (state.currentPhase === action.text) return state;
      return { ...state, currentPhase: action.text };
    case 'bridge/update_model':
      if (state.currentModel === action.model) return state;
      return { ...state, currentModel: action.model };
    case 'bridge/process_done':
      return {
        ...state,
        structuralVersion: action.data?.cancelled ? state.structuralVersion + 1 : state.structuralVersion,
        appState: 'idle',
        currentPhase: '',
        currentModel: '',
        activeProgress: action.data?.cancelled ? 0 : state.activeProgress,
        currentFileIndex: 0,
        currentBatchTotal: 0,
        workTotals: action.data?.cancelled ? { chunks: 0, macro: 0 } : state.workTotals,
        workDone: action.data?.cancelled ? { chunks: 0, macro: 0 } : state.workDone,
        files: action.data?.cancelled
          ? state.files.map(file =>
              file.status === 'processing'
                ? { ...file, status: 'queued', progress: 0, phase: 0, phaseText: undefined, errorText: undefined, errorDetail: undefined, resumeSession: undefined }
                : file,
            )
          : state.files,
      };
    case 'bridge/set_work_totals':
      return {
        ...state,
        workTotals: {
          chunks: Number(action.data.chunks ?? state.workTotals.chunks ?? 0),
          macro: Number(action.data.macro ?? state.workTotals.macro ?? 0),
        },
      };
    case 'bridge/update_work_done': {
      const prev = state.workDone[action.data.kind];
      const next = Number(action.data.done ?? 0);
      if (prev === next) return state;
      return {
        ...state,
        workDone: {
          ...state.workDone,
          [action.data.kind]: next,
        },
      };
    }

    case 'bridge/set_current_file':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        appState: 'processing',
        currentPhase: '',
        currentModel: '',
        activeProgress: 0,
        currentFileIndex: action.data.index,
        currentBatchTotal: action.data.total,
        files: state.files.map(file =>
          file.id === action.data.id
            ? { ...file, status: 'processing', progress: 0, phase: 1, phaseText: undefined, errorText: undefined, errorDetail: undefined, forceRetry: undefined, resumeSession: undefined, startedAt: Date.now() }
            : file,
        ),
      };
    case 'bridge/file_done':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        activeProgress: 0,
        files: state.files.map(file =>
          file.id === action.data.id
            ? {
                ...file,
                status: 'done',
                progress: 100,
                phase: 3,
                outputHtml: action.data.output_html || action.data.html_path,
                outputDir: action.data.output_dir || action.data.session_dir,
                phaseText: undefined,
                errorText: undefined,
                errorDetail: undefined,
                completedAt: Date.now(),
                primaryModel: action.data.primary_model || undefined,
                effectiveModel: action.data.effective_model || undefined,
                completionStatus: action.data.completion_status || (Array.isArray(action.data.revision_failed_blocks) && action.data.revision_failed_blocks.length > 0 ? 'completed_with_warnings' : 'completed'),
                revisionFailedBlocks: Array.isArray(action.data.revision_failed_blocks) ? action.data.revision_failed_blocks : [],
              }
            : file,
        ),
      };
    case 'bridge/file_failed':
      return {
        ...state,
        structuralVersion: state.structuralVersion + 1,
        files: state.files.map(file =>
          file.id === action.data.id
            ? {
                ...file,
                status: (action.data.retry_reason === 'circuit_breaker_paused' || action.data.retryable) ? ('paused' as const) : ('error' as const),
                progress: 0,
                phase: 0,
                phaseText: (action.data.retry_reason === 'circuit_breaker_paused' || action.data.retryable) ? 'In pausa' : 'Errore',
                errorText: action.data.error || 'Elaborazione non completata.',
                errorDetail: action.data.error_detail || undefined,
                retryable: action.data.retryable,
                retryReason: action.data.retry_reason,
                recommendedRetryAt: action.data.recommended_retry_at ?? undefined,
              }
            : file,
        ),
      };
    default:
      return state;
  }
}
