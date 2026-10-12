import type { Dispatch } from 'react';
import type {
  FileDescriptor,
  FileDonePayload,
  FileFailedPayload,
  ProcessDonePayload,
  ProcessingAction,
  SetCurrentFilePayload,
  WorkDonePayload,
  WorkTotalsPayload,
} from './appState';

export interface ValidationCheck {
  id: string;
  label: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
  details?: string;
}

export interface ValidationResult {
  ok: boolean;
  summary: string;
  checks: ValidationCheck[];
  has_warnings?: boolean;
}

export interface ModelQuota {
  model_id: string;
  limit: number;
  used_today: number;
  remaining: number;
  is_exhausted: boolean;
}

export interface KeyProfile {
  id: string;
  label: string;
  masked_key: string;
  is_primary: boolean;
  operational_status?: string;
  models?: Record<string, ModelQuota>;
}

export interface ProjectModelLimit {
  model_name?: string;
  rpd_limit?: number | null;
  rpm_limit?: number | null;
  tpm_limit?: number | null;
  source?: 'configured' | 'user_observed' | 'ai_studio_snapshot' | 'unknown';
  quota_state?: 'normal' | 'rpd_exhausted' | 'rate_limited' | 'unknown';
  updated_at?: string | null;
}

export interface TelemetryStats {
  requests_sent?: number;
  responses_succeeded?: number;
  final_failures?: number;
  retries_total?: number;
  retries_by_type?: Record<string, number>;
  last_request_iso?: string | null;
}

export interface WorkStats {
  chunks_completed?: number;
  revisions_completed?: number;
  sbobine_completed?: number;
}

export interface CredentialProfile {
  id?: string;
  masked_key: string;
  label?: string;
  is_primary?: boolean;
  operational_status?:
    | 'unused'
    | 'active'
    | 'temporarily_failing'
    | 'invalid'
    | 'permission_denied'
    | 'request_error'
    | 'unknown';
  key_type?: 'authorization_key' | 'standard_legacy' | 'unknown';
  project_id?: string | null;
  last_error_code?: number | null;
  last_error_message?: string | null;
  last_error_iso?: string | null;
  last_used_iso?: string | null;
  exhausted_models?: string[];
}

export interface ApiUsageResult {
  schema_version?: number;
  quota_date: string;
  next_reset_info: string;
  primary_status?:
    | 'operational'
    | 'rate_limited'
    | 'quota_exhausted'
    | 'credential_error'
    | 'degraded'
    | 'unknown';
  status_message?: string;
  retry_after_seconds?: number | null;
  project_limits?: Record<string, ProjectModelLimit>;
  telemetry?: TelemetryStats;
  work_stats?: WorkStats;
  credentials?: CredentialProfile[];
  is_degraded_mode: boolean;
  degraded_reason?: string | null;
  keys?: KeyProfile[];
  total_requests_remaining?: number;
  estimated_sbobine_remaining?: number;
}




export interface ModelOption {
  id: string;
  label: string;
  summary: string;
  default_chunk_minutes: number;
  phase1_temperature?: number;
  is_default?: boolean;
}

export type CredentialStorageState = 'protected' | 'session_only' | 'legacy_plaintext' | 'absent';
export interface CredentialStorage {
  primary: CredentialStorageState;
  fallback: CredentialStorageState;
}

export interface SettingsPayload {
  api_key?: string;
  fallback_keys?: string[];
  preferred_model?: string;
  fallback_models?: string[];
  available_models?: ModelOption[];
  has_protected_key?: boolean;
  api_key_insecure?: boolean;
  api_key_insecure_reason?: string;
  credential_storage?: CredentialStorage;
  config_recovered_from?: string;
  configuredFallbackKeyCount?: number;
  configured_fallback_key_count?: number;
}

export interface ArchiveSession {
  name: string;
  completed_at_iso: string;
  last_opened_at_iso?: string;
  html_path: string;
  effective_model: string;
  input_path: string;
  input_size?: number;
  session_dir: string;
  duration_sec?: number;
  completion_status?: 'completed' | 'completed_with_warnings';
  revision_failed_blocks?: number[];
  kind?: 'audio' | 'notes';
  notes_info?: { total_slides: number; book_name?: string | null; book_pages?: string };
  /** Course the lesson belongs to (archive grouping). */
  course?: string;
  /** Slides/book attached to an audio lesson. */
  sources?: { slides_name?: string | null; book_name?: string | null; book_pages?: string };
  /** In-app copy of the lesson summary ("sintesi"). */
  summary_html?: string;
  /** Documents/jot/<corso> with Lezioni and Sintesi. */
  course_folder?: string;
  lesson_number?: number;
  /** yyyy-mm-dd */
  lesson_date?: string;
}

export interface QuotaSnapshot {
  used: number;
  limit: number;
  remaining: number;
  exhausted: boolean;
  has_reserve: boolean;
  reset_at: string;
}

export interface LessonSuggestion {
  ok: boolean;
  title?: string | null;
  chapter?: { title: string; pages: string; count: number } | null;
  error?: string;
}

export interface DocumentDescriptor {
  path: string;
  name: string;
  size: number;
  pages: number;
  format: string;
}

export interface DocumentPickResult {
  ok: boolean;
  cancelled?: boolean;
  file?: DocumentDescriptor;
  error?: string;
}

export interface SearchSnippet {
  before: string;
  match: string;
  after: string;
}

export interface SearchSessionResult {
  session_dir: string;
  name: string;
  html_path: string;
  completed_at_iso: string;
  snippets: SearchSnippet[];
  match_count: number;
}

export interface ArchiveFolder {
  id: string;
  name: string;
  color: string;
  session_dirs: string[];
}

export interface LowDiskWarning {
  needed_bytes: number;
  free_bytes: number;
  location: string;
  kind: string;
  file_name?: string;
}

export interface StartProcessingResult {
  ok: boolean;
  error?: string;
  low_disk_warning?: LowDiskWarning;
}

export interface SaveHtmlResult {
  ok: boolean;
  saved?: boolean;
  error?: string;
}

export type JotBridge = BridgeCallbacks | null;

export interface UpdateDownloadProgressPayload {
  status: 'downloading' | 'verifying' | 'installing' | 'done' | 'error';
  bytes_done: number;
  bytes_total: number;
  error?: string;
}

export interface StepTimePayload {
  kind: string;
  seconds: number;
  done?: number;
  total?: number;
}

export interface RetryStatePayload {
  state: 'idle' | 'cooling_down' | 'probing' | 'exhausted' | 'paused';
  reason?: string;
  model?: string;
  attempt?: number;
  max_attempts?: number;
  next_retry_at?: string | null;
  seconds_remaining?: number | null;
  recommended_retry_at?: string | null;
}

export interface BridgeCallbacks {
  appendConsole: (msg: string) => void;
  updateProgress: (value: number) => void;
  updatePhase: (text: string) => void;
  updateModel: (model: string) => void;
  processDone: (data: ProcessDonePayload) => void;
  setWorkTotals: (data: WorkTotalsPayload) => void;
  updateWorkDone: (data: WorkDonePayload) => void;
  registerStepTime: (data: StepTimePayload) => void;
  setCurrentFile: (data: SetCurrentFilePayload) => void;
  fileDone: (data: FileDonePayload) => void;
  fileFailed: (data: FileFailedPayload) => void;
  askRegenerate: (data: { filename: string; mode?: 'completed' | 'resume'; sessionDir?: string }) => void;
  askNewKey: () => void;
  dismissNewKey: () => void;
  filesDropped: (files: FileDescriptor[]) => void;
  updateDownloadProgress: (data: UpdateDownloadProgressPayload) => void;
  apiUsageUpdated?: (data: ApiUsageResult) => void;
  retryStateChanged?: (data: RetryStatePayload) => void;
  requestQuitConfirmation?: () => void;
}

export interface PywebviewApi {
  load_settings?: () => Promise<SettingsPayload>;
  save_settings?: (
    apiKey: string | null,
    fallbackKeys: string[] | null,
    preferredModel: string,
    fallbackModels: string[],
  ) => Promise<{ ok: boolean; error?: string; credential_storage?: CredentialStorage; api_key_insecure?: boolean; api_key_insecure_reason?: string }>;
  ask_files?: () => Promise<FileDescriptor[]>;
  ask_media_file?: () => Promise<FileDescriptor | null>;
  ask_document_file?: (purpose: 'slides' | 'book') => Promise<DocumentPickResult>;
  inspect_document?: (path: string, purpose: 'slides' | 'book') => Promise<DocumentPickResult>;
  suggest_lesson?: (audioPath: string | null, slidesPath: string | null, bookPath: string | null) => Promise<LessonSuggestion>;
  get_quota_snapshot?: (preferredModel?: string | null, fallbackModels?: string[] | null) => Promise<{ ok: boolean; result?: QuotaSnapshot; error?: string }>;
  recommend_models?: (apiKey?: string | null) => Promise<{ ok: boolean; preferred_model?: string; fallback_models?: string[]; error?: string }>;
  set_session_course?: (sessionDir: string, course: string | null) => Promise<{ ok: boolean; course?: string | null; error?: string }>;
  check_path_exists?: (path: string) => Promise<{ ok: boolean; exists: boolean }>;
  collect_dropped_files?: (names: string[]) => Promise<{ ok: boolean }>;
  start_processing?: (
    files: FileDescriptor[],
    apiKey: string,
    resumeSession: boolean,
    preferredModel: string,
    fallbackModels: string[],
    overrideLowDisk?: boolean,
    forceRetry?: boolean,
  ) => Promise<StartProcessingResult>;
  stop_processing?: () => Promise<{ ok: boolean }>;
  close_window?: () => Promise<{ ok: boolean }>;
  is_processing_active?: () => Promise<{ ok: boolean; active?: boolean }>;
  answer_regenerate?: (regenerate: boolean | null) => Promise<{ ok: boolean }>;
  answer_new_key?: (key: string) => Promise<{ ok: boolean }>;
  open_file?: (path: string) => Promise<{ ok: boolean; error?: string }>;
  open_url?: (url: string) => Promise<{ ok: boolean; error?: string }>;
  read_html_content?: (path: string) => Promise<{ ok: boolean; content?: string; error?: string }>;
  save_html_content?: (path: string, content: string, generation?: number) => Promise<SaveHtmlResult>;
  stream_media_file?: (path: string, sessionDir?: string) => Promise<{ ok: boolean; url?: string; has_audio?: boolean; error?: string }>;
  show_notification?: (title: string, message: string) => Promise<void>;
  flash_window?: () => Promise<{ ok: boolean; error?: string }>;
  validate_environment?: (
    apiKey?: string,
    checkApiKey?: boolean,
    preferredModel?: string,
    fallbackModels?: string[],
  ) => Promise<{ ok: boolean; result?: ValidationResult; error?: string }>;
  get_session_storage_info?: () => Promise<{ ok: boolean; total_bytes?: number; total_sessions?: number; session_root?: string; error?: string }>;
  cleanup_old_sessions?: (maxAgeDays?: number, dryRun?: boolean) => Promise<{ ok: boolean; removed?: number; freed_bytes?: number; errors?: number; candidates?: number; preserved_completed?: number; missing_completed_html?: number; error?: string }>;
  cleanup_completed_sessions?: (maxAgeDays?: number, dryRun?: boolean) => Promise<{ ok: boolean; removed?: number; freed_bytes?: number; errors?: number; candidates?: number; preserved_completed?: number; missing_completed_html?: number; error?: string }>;
  get_completed_sessions?: (limit?: number) => Promise<{ ok: boolean; sessions?: ArchiveSession[]; total?: number; error?: string }>;
  delete_session?: (sessionDir: string) => Promise<{ ok: boolean; error?: string }>;
  update_session_input_path?: (sessionDir: string, newPath: string) => Promise<{ ok: boolean; error?: string }>;
  remove_session_audio?: (sessionDir: string) => Promise<{ ok: boolean; error?: string }>;
  touch_session_opened?: (sessionDir: string) => Promise<{ ok: boolean; last_opened_at_iso?: string; error?: string }>;
  open_session_folder?: () => Promise<{ ok: boolean; error?: string }>;
  ask_session_folder?: () => Promise<{ ok: boolean; path?: string; cancelled?: boolean; error?: string }>;
  move_session_root?: (newPath: string) => Promise<{ ok: boolean; started?: boolean; error?: string }>;
  get_session_move_status?: () => Promise<{ status: string; moved?: number; total?: number; error?: string | null; old_root?: string; new_root?: string }>;
  download_and_install_update?: (version: string) => Promise<{ ok: boolean; status?: string; error?: string }>;
  save_theme_preference?: (theme: 'light' | 'dark') => Promise<void>;
  get_archive_folders?: () => Promise<{ ok: boolean; folders: ArchiveFolder[]; error?: string }>;
  save_archive_folders?: (folders: ArchiveFolder[]) => Promise<{ ok: boolean; error?: string }>;
  search_sessions?: (query: string, limit?: number) => Promise<{ ok: boolean; results?: SearchSessionResult[]; total?: number; error?: string }>;
  retry_failed_revision_blocks?: (sessionDir: string) => Promise<{
    ok: boolean;
    error?: string;
    retried_blocks?: number[];
    remaining_failed_blocks?: number[];
    html_path?: string;
    session_dir?: string;
    effective_model?: string;
    completion_status?: 'completed' | 'completed_with_warnings';
    cancelled?: boolean;
    quota_exhausted?: boolean;
    conflict?: boolean;
  }>;
  export_sbobina_package?: (
    sessionDir: string,
    exportType?: 'full' | 'text_only' | 'audio_only',
    targetPath?: string,
  ) => Promise<{
    ok: boolean;
    error?: string;
    cancelled?: boolean;
    target_path?: string;
    include_mode?: string;
    audio_included?: boolean;
    size_bytes?: number;
  }>;
  import_sbobina_package?: (
    packagePath?: string,
  ) => Promise<{
    ok: boolean;
    error?: string;
    cancelled?: boolean;
    session_dir?: string;
    name?: string;
    html_path?: string;
    has_audio?: boolean;
  }>;
  get_api_usage?: (
    apiKey?: string,
    fallbackKeys?: string[],
    preferredModel?: string,
    fallbackModels?: string[],
    forceRefresh?: boolean,
  ) => Promise<{ ok: boolean; result?: ApiUsageResult; error?: string }>;
  get_diagnostic_report?: (
    apiKey?: string,
    fallbackKeys?: string[],
    preferredModel?: string,
    fallbackModels?: string[],
    sessionDir?: string,
    frontendVersion?: string,
  ) => Promise<{ ok: boolean; report?: string; error?: string }>;
  list_diagnostic_sessions?: () => Promise<{ ok: boolean; sessions?: Array<{ path: string; label: string }>; error?: string }>;
  export_diagnostics?: (sessionDir?: string, frontendVersion?: string) => Promise<{ ok: boolean; target_path?: string; cancelled?: boolean; error?: string }>;
  record_frontend_event?: (kind: string, message?: string, stack?: string) => Promise<{ ok: boolean; error?: string }>;
  open_logs_folder?: () => Promise<{ ok: boolean; error?: string }>;
  upload_browser_files?: (files: File[]) => Promise<FileDescriptor[]>;
  set_browser_scenario?: (scenario: string) => Promise<{ ok: boolean; scenario?: string; error?: string }>;
}


declare global {
  interface Window {
    pywebview?: {
      api?: PywebviewApi;
    };
    jotBridge?: JotBridge;
  }
}

export function createBridge(options: {
  dispatch: Dispatch<ProcessingAction>;
  appendConsole: (msg: string) => void;
  onRegenerate: (data: { filename: string; mode?: 'completed' | 'resume'; sessionDir?: string }) => void;
  onAskNewKey: () => void;
  onDismissNewKey: () => void;
  onBatchDone: (data: ProcessDonePayload) => void;
  onFileDone: (data: FileDonePayload) => void;
  onFileFailed?: (data: FileFailedPayload) => void;
  onFilesDropped: (files: FileDescriptor[]) => void;
  onBatchStart: () => void;
  onDownloadProgress?: (data: UpdateDownloadProgressPayload) => void;
  onApiUsageUpdated?: (data: ApiUsageResult) => void;
  onRetryStateChanged?: (data: RetryStatePayload) => void;
  onRequestQuitConfirmation?: () => void;
}): BridgeCallbacks {
  const {
    dispatch,
    appendConsole,
    onRegenerate,
    onAskNewKey,
    onDismissNewKey,
    onBatchDone,
    onFileDone,
    onFileFailed,
    onFilesDropped,
    onBatchStart,
    onDownloadProgress,
    onApiUsageUpdated,
    onRetryStateChanged,
    onRequestQuitConfirmation,
  } = options;
  let lastPhaseMessage = '';

  return {
    appendConsole,
    updateProgress: value => dispatch({ type: 'bridge/update_progress', value }),
    updatePhase: text => {
      const normalized = String(text ?? '').trim();
      if (!normalized || normalized === lastPhaseMessage) return;
      lastPhaseMessage = normalized;
      onBatchStart();
      dispatch({ type: 'bridge/update_phase', text: normalized });
      appendConsole(normalized);
    },
    updateModel: model => dispatch({ type: 'bridge/update_model', model }),
    processDone: data => {
      dispatch({ type: 'bridge/process_done', data });
      onBatchDone(data);
    },
    setWorkTotals: data => dispatch({ type: 'bridge/set_work_totals', data }),
    updateWorkDone: data => dispatch({ type: 'bridge/update_work_done', data }),
    registerStepTime: () => {},
    setCurrentFile: data => { onBatchStart(); dispatch({ type: 'bridge/set_current_file', data }); },
    fileDone: data => {
      dispatch({ type: 'bridge/file_done', data });
      onFileDone(data);
    },
    fileFailed: data => {
      dispatch({ type: 'bridge/file_failed', data });
      onFileFailed?.(data);
    },
    askRegenerate: onRegenerate,
    askNewKey: onAskNewKey,
    dismissNewKey: onDismissNewKey,
    filesDropped: onFilesDropped,
    updateDownloadProgress: data => { onDownloadProgress?.(data); },
    apiUsageUpdated: data => { onApiUsageUpdated?.(data); },
    retryStateChanged: data => { onRetryStateChanged?.(data); },
    requestQuitConfirmation: () => { onRequestQuitConfirmation?.(); },
  };
}
