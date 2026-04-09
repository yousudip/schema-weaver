import { useEffect, useMemo, useState, useCallback } from 'react'
import type { ReactElement } from 'react'
import './App.css'
import { SchemaMapper } from './SchemaMapper'
import type { MappingEntry } from './SchemaMapper'
import { QualityReport } from './QualityReport'
import type { QualityReportData, ValidationAttempt } from './QualityReport'

// ─── Types ────────────────────────────────────────────────────────────────────

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

interface ColumnInference {
  source_name: string
  inferred_type: string
  suggested_name: string
  description: string
  confidence: number
}

interface SchemaInference {
  columns: ColumnInference[]
  notes?: string
}

interface Job {
  job_id: string
  filename: string
  purpose?: string
  status: string
  task_status: string | null
  file_count?: number
  created_at: string | null
}

interface JobFileEntry {
  file_id: string
  filename: string
  file_type: string | null
  status: string
  error: string | null
  has_preview: boolean
  has_schema: boolean
  has_code: boolean
  execution_ok: boolean
  quality_report: QualityReportData | null
  validation_attempts: ValidationAttempt[]
  created_at: string | null
  needs_extraction?: boolean
}


type ColumnState = 'pending' | 'accepted' | 'rejected'
type ReviewMode = 'cards' | 'map'
type AsyncStatus = 'idle' | 'running' | 'ok' | 'error'

interface CleanedPreview {
  columns: string[]
  sample_rows: Record<string, string>[]
  row_count: number
}

type ToastType = 'success' | 'error' | 'info'
interface Toast { id: string; type: ToastType; message: string }

// ─── Step definitions ─────────────────────────────────────────────────────────

const STEPS = [
  { id: 1, label: 'Upload',     icon: '📁' },
  { id: 2, label: 'Parse',      icon: '⚙️' },
  { id: 3, label: 'Infer',      icon: '🧠' },
  { id: 4, label: 'Review',     icon: '🔗' },
  { id: 5, label: 'Transform',  icon: '⚗️' },
  { id: 6, label: 'Export',     icon: '📤' },
]

// ─── Small helpers ────────────────────────────────────────────────────────────

function JsonTree({ data, label }: { data: JsonValue; label?: string }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  function toggle(path: string) {
    setCollapsed(prev => ({ ...prev, [path]: !prev[path] }))
  }
  function renderValue(value: JsonValue, path: string): ReactElement {
    if (value === null) return <span className="json-null">null</span>
    if (typeof value === 'string') return <span className="json-string">"{value}"</span>
    if (typeof value === 'number') return <span className="json-number">{value}</span>
    if (typeof value === 'boolean') return <span className="json-bool">{String(value)}</span>
    const isArray = Array.isArray(value)
    const keys = isArray ? value.map((_, i) => i) : Object.keys(value)
    const isCollapsed = collapsed[path]
    return (
      <div className="json-node">
        <button className="json-toggle" onClick={() => toggle(path)}>{isCollapsed ? '+' : '−'}</button>
        <span className="json-brace">{isArray ? '[' : '{'}</span>
        {!isCollapsed && (
          <div className="json-children">
            {keys.map(key => {
              const childPath = `${path}.${key}`
              const childValue = isArray ? value[key as number] : value[key as string]
              return (
                <div className="json-row" key={childPath}>
                  {!isArray && <span className="json-key">"{key}"</span>}
                  {!isArray && <span className="json-colon">: </span>}
                  {renderValue(childValue, childPath)}
                </div>
              )
            })}
          </div>
        )}
        <span className="json-brace">{isArray ? ']' : '}'}</span>
      </div>
    )
  }
  return (
    <div className="json-tree">
      {label && <div className="label">{label}</div>}
      {renderValue(data, label || 'root')}
    </div>
  )
}

function TypeBadge({ type }: { type: string }) {
  const map: Record<string, string> = {
    string: '🔤', number: '🔢', date: '📅', boolean: '☑️', currency: '💰',
  }
  return <span className={`type-badge type-${type}`}>{map[type] ?? '❓'} {type}</span>
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const cls = value >= 0.85 ? 'bar-high' : value >= 0.65 ? 'bar-mid' : 'bar-low'
  return (
    <div className="conf-bar-wrap">
      <div className={`conf-bar ${cls}`} style={{ width: `${pct}%` }} />
      <span className="conf-label">{pct}%</span>
    </div>
  )
}


function ToastContainer({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: string) => void }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type}`} onClick={() => dismiss(t.id)}>
          <span className="toast-icon">{t.type === 'success' ? '✅' : t.type === 'error' ? '❌' : 'ℹ️'}</span>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────

function App() {
  const [apiBase, setApiBase] = useState(import.meta.env.VITE_API_BASE || 'http://localhost:8010')
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState('')
  const [status, setStatus] = useState('idle')
  const [taskStatus, setTaskStatus] = useState<string | null>(null)
  const [step, setStep] = useState<string | null>(null)
  const [result, setResult] = useState<object | null>(null)
  const [analysis, setAnalysis] = useState<object | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<string[]>([])
  const [inferenceStatus, setInferenceStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [embeddingStatus, setEmbeddingStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [jobs, setJobs] = useState<Job[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [mappings, setMappings] = useState<MappingEntry[]>([])
  const [columnStates, setColumnStates] = useState<Record<string, ColumnState>>({})
  const [reviewMode, setReviewMode] = useState<ReviewMode>('cards')
  const [generateStatus, setGenerateStatus] = useState<AsyncStatus>('idle')
  const [executeStatus, setExecuteStatus] = useState<AsyncStatus>('idle')
  const [generatedCode, setGeneratedCode] = useState<string>('')
  const [sandboxLog, setSandboxLog] = useState<string>('')
  const [cleanedPreview, setCleanedPreview] = useState<CleanedPreview | null>(null)
  const [qualityReport, setQualityReport] = useState<QualityReportData | null>(null)
  const [validationAttempts, setValidationAttempts] = useState<ValidationAttempt[]>([])
  const [codeEdited, setCodeEdited] = useState(false)
  const [executeProgress, setExecuteProgress] = useState<string[]>([])
  const [showEventLog, setShowEventLog] = useState(false)
  const [showRawResult, setShowRawResult] = useState(false)
  const [showApiConfig, setShowApiConfig] = useState(false)

  // ── Phase 5: multi-file job state ─────────────────────────────────────────
  const [jobLoading, setJobLoading] = useState(false)
  const [showNewJobModal, setShowNewJobModal] = useState(false)
  const [newJobPurpose, setNewJobPurpose] = useState('')
  const [newJobDesc, setNewJobDesc] = useState('')
  const [newJobCreating, setNewJobCreating] = useState(false)
  const [activeJobPurpose, setActiveJobPurpose] = useState<string | null>(null)
  const [jobFiles, setJobFiles] = useState<JobFileEntry[]>([])
  const [jobFilesLoading, setJobFilesLoading] = useState(false)
  // Per-file pipeline progress keyed by file_id
  const [fileProgress, setFileProgress] = useState<Record<string, string[]>>({})
  const [fileStatus, setFileStatus] = useState<Record<string, AsyncStatus>>({})
  const [fileExtractStatus, setFileExtractStatus] = useState<Record<string, AsyncStatus>>({})
  const [fileUploadStatus, setFileUploadStatus] = useState<AsyncStatus>('idle')
  const [fileUploadInput, setFileUploadInput] = useState<File | null>(null)
  // Batch processing
  const [showBatchModal, setShowBatchModal] = useState(false)
  const [batchRunning, setBatchRunning] = useState(false)
  // Consolidation
  const [consolidating, setConsolidating] = useState(false)
  const [consolidationResult, setConsolidationResult] = useState<{
    consolidated_preview: { columns: string[]; sample_rows: Record<string, string>[]; row_count: number; file_count: number }
    column_mapping: { canonical_columns: string[]; file_mappings: Record<string, Record<string, string>>; notes?: string }
    merge_errors: string[]
    message: string
  } | null>(null)

  // ── Toast helpers ──────────────────────────────────────────────────────────
  const addToast = useCallback((type: ToastType, message: string) => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts(prev => [...prev, { id, type, message }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }, [])
  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // ── Derived schema state ───────────────────────────────────────────────────
  const schemaInference = (analysis as { schema_inference?: SchemaInference } | null)?.schema_inference
  const selectedSchema  = (analysis as { selected_schema?: SchemaInference } | null)?.selected_schema
  const columns: ColumnInference[] = schemaInference?.columns ?? []

  const overallHealth = columns.length
    ? columns.reduce((s, c) => s + c.confidence, 0) / columns.length
    : 0

  const healthLabel = overallHealth >= 0.9 ? 'Excellent' : overallHealth >= 0.75 ? 'Good'
    : overallHealth >= 0.6 ? 'Fair' : 'Needs Review'
  const healthClass = overallHealth >= 0.9 ? 'health-excellent' : overallHealth >= 0.75 ? 'health-good'
    : overallHealth >= 0.6 ? 'health-fair' : 'health-poor'

  // ── Current wizard step (6-step) ──────────────────────────────────────────
  const currentStep = useMemo(() => {
    if (status === 'idle' || status === 'uploading' || status === 'upload_failed') return 1
    if (status === 'queued' || status === 'processing') return 2
    if (status === 'completed' && inferenceStatus !== 'ok') return 3
    if (inferenceStatus === 'ok' && executeStatus !== 'ok') return 4
    if (executeStatus === 'ok') return 6
    return 4
  }, [status, inferenceStatus, executeStatus])

  // ── SSE stream ────────────────────────────────────────────────────────────
  const statusUrl = useMemo(() => jobId ? `${apiBase}/api/v1/jobs/${jobId}/status/stream` : '', [apiBase, jobId])

  useEffect(() => {
    if (!statusUrl) return
    setEvents([])
    const source = new EventSource(statusUrl)
    const push = (label: string, payload?: unknown) => {
      const ts = new Date().toLocaleTimeString()
      setEvents(prev => [`${ts} ${label}${payload !== undefined ? ': ' + JSON.stringify(payload) : ''}`, ...prev].slice(0, 30))
    }
    source.addEventListener('status', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        if (payload.job_id && payload.job_id !== jobId) return
        setStatus(payload.status || 'unknown')
        setTaskStatus(payload.task_status ?? null)
        if (payload.step) setStep(payload.step)
        push('status', payload)
        if (payload.status === 'completed') {
          handleRefresh()
          addToast('success', 'File parsed successfully!')
        }
        if (payload.status === 'failed') {
          handleRefresh()
          addToast('error', 'Processing failed.')
        }
      } catch { push('status (invalid payload)') }
    })
    source.addEventListener('heartbeat', () => push('heartbeat'))
    source.addEventListener('result', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        setResult(payload.result || null)
        setError(payload.error || null)
        push('result', payload)
      } catch { push('result (invalid payload)') }
    })
    source.onerror = () => source.close()
    return () => source.close()
  }, [statusUrl])

  // ── API helpers ───────────────────────────────────────────────────────────
  async function fetchJobs() {
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs`)
      if (!res.ok) return
      const data = await res.json()
      setJobs(data.jobs || [])
    } catch { /* network error */ }
  }

  useEffect(() => { fetchJobs() }, [apiBase])

  // Auto-refresh sidebar job list while sandbox is running so the status dot updates
  useEffect(() => {
    if (executeStatus !== 'running') return
    const id = setInterval(fetchJobs, 3000)
    return () => clearInterval(id)
  }, [executeStatus])

  async function handleRefresh() {
    if (!jobId) return
    const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}`)
    if (!res.ok) return
    const data = await res.json()
    const job = data?.job
    if (!job) return
    setStatus(job.status || 'unknown')
    setTaskStatus(job.task_status || null)
    setStep(job.step || null)
    setError(job.error || null)

    // Multi-file job — don't restore wizard state, just keep multi-file view active
    if (job.purpose) {
      setActiveJobPurpose(job.purpose)
      return
    }

    // Legacy single-file job — restore wizard state
    setResult(job.result || null)
    setAnalysis(job.analysis || null)
    const analysis = job.analysis || {}
    if (analysis.schema_inference || analysis.selected_schema) {
      setInferenceStatus('ok')
    }
    if (analysis.generated_code) {
      setGeneratedCode(analysis.generated_code)
      setGenerateStatus('ok')
      setCodeEdited(false)
    }
    if (analysis.cleaned_preview) {
      setCleanedPreview(analysis.cleaned_preview)
      setExecuteStatus('ok')
    }
    if (analysis.execution_log) {
      setSandboxLog(analysis.execution_log)
    }
    if (analysis.quality_report) setQualityReport(analysis.quality_report)
    if (analysis.validation_attempts) setValidationAttempts(analysis.validation_attempts)
  }

  async function handleUpload() {
    if (!file) return
    setStatus('uploading')
    setResult(null); setAnalysis(null); setError(null)
    setInferenceStatus('idle'); setEmbeddingStatus('idle')
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await fetch(`${apiBase}/api/v1/upload`, { method: 'POST', body: form })
      if (!res.ok) { setStatus('upload_failed'); addToast('error', 'Upload failed.'); return }
      const data = await res.json()
      setJobId(data.job_id)
      setStatus('queued')
      fetchJobs()
      addToast('info', `Uploaded ${file.name} — processing...`)
    } catch { setStatus('upload_failed'); addToast('error', 'Network error on upload.') }
  }

  async function handleInfer() {
    if (!jobId) return
    setInferenceStatus('running')
    addToast('info', 'Running AI schema inference...')
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/infer`, { method: 'POST' })
      if (!res.ok) { setInferenceStatus('error'); addToast('error', 'Inference request failed.'); return }
      const data = await res.json()
      if (data.status !== 'ok') { setInferenceStatus('error'); addToast('error', data.message || 'Inference failed.'); return }
      setAnalysis(data.analysis || null)
      setInferenceStatus('ok')
      const cols: ColumnInference[] = data.analysis?.schema_inference?.columns ?? []
      const initStates: Record<string, ColumnState> = {}
      cols.forEach(c => { initStates[c.source_name] = 'pending' })
      setColumnStates(initStates)
      addToast('success', `Schema inferred — ${cols.length} columns detected!`)
    } catch { setInferenceStatus('error'); addToast('error', 'Network error during inference.') }
  }

  async function handleSelectSchema() {
    if (!jobId) return
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/schema/select`, { method: 'POST' })
      if (!res.ok) { addToast('error', 'Schema confirmation failed.'); return }
      const data = await res.json()
      if (data.status !== 'ok') { addToast('error', data.message || 'Schema confirmation failed.'); return }
      setAnalysis(data.analysis || null)
      addToast('success', 'Schema confirmed ✓')
    } catch { addToast('error', 'Network error.') }
  }

  async function handleBuildEmbeddings() {
    if (!jobId) return
    setEmbeddingStatus('running')
    addToast('info', 'Building vector embeddings...')
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/schema/embeddings`, { method: 'POST' })
      if (!res.ok) { setEmbeddingStatus('error'); addToast('error', 'Embedding build failed.'); return }
      const data = await res.json()
      if (data.status !== 'ok') { setEmbeddingStatus('error'); addToast('error', data.message || 'Embedding failed.'); return }
      setEmbeddingStatus('ok')
      addToast('success', 'Embeddings stored — semantic matching enabled! 🎯')
    } catch { setEmbeddingStatus('error'); addToast('error', 'Network error during embedding.') }
  }

  async function handleGenerate() {
    if (!jobId) return
    setGenerateStatus('running')
    addToast('info', 'Generating cleaning script with GPT...')
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/generate`, { method: 'POST' })
      if (!res.ok) { setGenerateStatus('error'); addToast('error', 'Code generation failed.'); return }
      const data = await res.json()
      if (data.status !== 'ok') { setGenerateStatus('error'); addToast('error', data.message || 'Code generation failed.'); return }
      setGeneratedCode(data.code)
      setCodeEdited(false)
      setAnalysis(data.analysis)
      setGenerateStatus('ok')
      addToast('success', 'Cleaning script generated! Review and run it. ⚗️')
    } catch { setGenerateStatus('error'); addToast('error', 'Network error during code generation.') }
  }

  async function handleExecute() {
    if (!jobId) return
    setExecuteStatus('running')
    setSandboxLog('')
    setCleanedPreview(null)
    setQualityReport(null)
    setValidationAttempts([])
    setExecuteProgress([])
    addToast('info', 'Running script in Docker sandbox...')
    try {
      const reqBody = codeEdited ? JSON.stringify({ code: generatedCode }) : '{}'
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/execute/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: reqBody,
      })
      if (!res.ok || !res.body) { setExecuteStatus('error'); fetchJobs(); addToast('error', 'Execution request failed.'); return }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          let eventType = 'message'
          let dataLine = ''
          for (const line of part.split('\n')) {
            if (line.startsWith('event: ')) eventType = line.slice(7).trim()
            if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
          }
          if (!dataLine) continue
          try {
            const data = JSON.parse(dataLine)
            if (eventType === 'attempt_start') {
              setExecuteProgress(prev => [...prev, `🔄 Attempt ${data.attempt}/${data.total}: Running script...`])
            } else if (eventType === 'attempt_result') {
              const fillPct = Math.round((data.fill_rate ?? 0) * 100)
              const icon = data.pass ? '✅' : '⚠️'
              setExecuteProgress(prev => [...prev, `${icon} Attempt ${data.attempt}: ${fillPct}% fill${data.pass ? ' — passed!' : ' — quality issues, fixing...'}`])
              setValidationAttempts(prev => {
                const next = prev.filter(a => a.attempt !== data.attempt)
                return [...next, { attempt: data.attempt, run_ok: true, verdict: data.pass ? 'pass' : 'pending', fill_rate: data.fill_rate }]
              })
            } else if (eventType === 'attempt_crash') {
              setExecuteProgress(prev => [...prev, `💥 Attempt ${data.attempt}: Crashed — applying reflexion fix...`])
              setValidationAttempts(prev => {
                const next = prev.filter(a => a.attempt !== data.attempt)
                return [...next, { attempt: data.attempt, run_ok: false, verdict: 'crash' }]
              })
            } else if (eventType === 'llm_fixing') {
              setExecuteProgress(prev => [...prev, `🤖 Attempt ${data.attempt}: Asking LLM to rewrite script...`])
            } else if (eventType === 'complete') {
              setSandboxLog(data.sandbox_log || '')
              if (data.quality_report) setQualityReport(data.quality_report)
              if (data.validation_attempts) setValidationAttempts(data.validation_attempts)
              if (data.status !== 'ok' || !data.cleaned_preview) {
                setExecuteStatus('error'); fetchJobs()
                addToast('error', 'Sandbox execution failed — check log for details.')
              } else {
                setCleanedPreview(data.cleaned_preview)
                setExecuteStatus('ok'); fetchJobs()
                const qr = data.quality_report
                const fillPct = qr ? Math.round(qr.overall_fill_rate * 100) : 100
                const passed = qr?.pass !== false
                addToast('success', `✅ ${data.cleaned_preview.row_count} rows cleaned · ${fillPct}% fill rate${passed ? '' : ' ⚠ quality issues found'}`)
              }
            } else if (eventType === 'error') {
              setExecuteStatus('error'); fetchJobs()
              addToast('error', `Execution error: ${data.message}`)
            }
          } catch { /* ignore SSE parse errors */ }
        }
      }
    } catch { setExecuteStatus('error'); fetchJobs(); addToast('error', 'Network error during execution.') }
  }

  function resetAll() {
    setGenerateStatus('idle'); setExecuteStatus('idle')
    setGeneratedCode(''); setSandboxLog(''); setCleanedPreview(null); setCodeEdited(false)
    setQualityReport(null); setValidationAttempts([]); setExecuteProgress([])
  }

  async function handleSelectJob(id: string) {
    // Reset all derived state first
    setJobLoading(true)
    setJobId(id)
    setStatus('idle')
    setAnalysis(null)
    setInferenceStatus('idle'); setEmbeddingStatus('idle')
    setMappings([]); setColumnStates({})
    setActiveJobPurpose(null); setJobFiles([])
    setFileProgress({}); setFileStatus({})
    setConsolidationResult(null)
    resetAll()

    try {
    // Load job data
    const res = await fetch(`${apiBase}/api/v1/jobs/${id}`)
    if (!res.ok) return
    const data = await res.json()
    const job = data?.job
    if (!job) return
    setStatus(job.status || 'unknown')
    setTaskStatus(job.task_status || null)
    setStep(job.step || null)
    setError(job.error || null)

    // Multi-file job (has purpose, no single file)
    if (job.purpose) {
      setActiveJobPurpose(job.purpose)
      setResult(null); setAnalysis(null)
      // Hydrate consolidation result if a previous consolidation exists
      const ja = job.analysis || {}
      if (ja.consolidated_preview && ja.column_mapping) {
        setConsolidationResult({
          consolidated_preview: ja.consolidated_preview,
          column_mapping: ja.column_mapping,
          merge_errors: ja.merge_errors || [],
          message: ja.consolidation_message || 'Previously consolidated output',
        })
      }
      fetchJobFiles(id)
      return
    }

    // Legacy single-file job — restore wizard state from persisted analysis
    setResult(job.result || null)
    setAnalysis(job.analysis || null)
    const a = job.analysis || {}
    if (a.schema_inference || a.selected_schema) setInferenceStatus('ok')
    if (a.generated_code) { setGeneratedCode(a.generated_code); setGenerateStatus('ok'); setCodeEdited(false) }
    if (a.cleaned_preview) { setCleanedPreview(a.cleaned_preview); setExecuteStatus('ok') }
    if (a.execution_log) setSandboxLog(a.execution_log)
    if (a.quality_report) setQualityReport(a.quality_report)
    if (a.validation_attempts) setValidationAttempts(a.validation_attempts)
    } finally {
      setJobLoading(false)
    }
  }

  async function handleDeleteJob(id: string) {
    await fetch(`${apiBase}/api/v1/jobs/${id}`, { method: 'DELETE' })
    if (jobId === id) {
      setJobId(''); setStatus('idle'); setTaskStatus(null); setStep(null)
      setResult(null); setAnalysis(null); setError(null)
      setInferenceStatus('idle'); setEmbeddingStatus('idle')
      setMappings([]); setColumnStates({})
      resetAll()
    }
    fetchJobs()
    addToast('info', 'Job deleted.')
  }

  // ── Phase 5: multi-file job handlers ─────────────────────────────────────

  async function handleCreateJob() {
    if (!newJobPurpose.trim()) return
    setNewJobCreating(true)
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/new`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purpose: newJobPurpose.trim(), description: newJobDesc.trim() || null }),
      })
      if (!res.ok) { addToast('error', 'Failed to create job.'); return }
      const data = await res.json()
      setShowNewJobModal(false)
      setNewJobPurpose(''); setNewJobDesc('')
      await fetchJobs()
      // Select the new job
      setJobId(data.job_id)
      setActiveJobPurpose(newJobPurpose.trim())
      setJobFiles([])
      setStatus('ready')
      addToast('success', `Job created: ${data.purpose}`)
    } catch { addToast('error', 'Network error.') }
    finally { setNewJobCreating(false) }
  }

  async function fetchJobFiles(jid: string) {
    setJobFilesLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jid}/files`)
      if (!res.ok) return
      const data = await res.json()
      setJobFiles(data.files || [])
      // Note: do NOT call setActiveJobPurpose here — purpose is already managed by handleSelectJob
    } catch { /* network */ }
    finally { setJobFilesLoading(false) }
  }

  async function handleAddFileToJob() {
    if (!fileUploadInput || !jobId) return
    setFileUploadStatus('running')
    const form = new FormData()
    form.append('file', fileUploadInput)
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files`, { method: 'POST', body: form })
      if (!res.ok) { setFileUploadStatus('error'); addToast('error', 'File upload failed.'); return }
      const data = await res.json()
      setFileUploadStatus('idle')
      setFileUploadInput(null)
      addToast('success', `${data.filename} uploaded (${data.file_type}) — ${data.status}`)
      fetchJobFiles(jobId)
    } catch { setFileUploadStatus('error'); addToast('error', 'Network error on upload.') }
  }

  async function handleRemoveJobFile(fileId: string) {
    if (!jobId) return
    await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}`, { method: 'DELETE' })
    fetchJobFiles(jobId)
    addToast('info', 'File removed.')
  }

  async function handleFileInfer(fileId: string) {
    if (!jobId) return
    setFileStatus(p => ({ ...p, [fileId]: 'running' }))
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}/infer`, { method: 'POST' })
      const data = await res.json()
      if (data.status !== 'ok') { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', data.message || 'Inference failed.'); return }
      setFileStatus(p => ({ ...p, [fileId]: 'ok' }))
      addToast('success', 'Schema inferred!')
      fetchJobFiles(jobId)
    } catch { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', 'Inference network error.') }
  }

  async function handleFileSelectSchema(fileId: string) {
    if (!jobId) return
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}/schema/select`, { method: 'POST' })
      const data = await res.json()
      if (data.status !== 'ok') { addToast('error', data.message || 'Schema confirmation failed.'); return }
      addToast('success', 'Schema confirmed ✓')
      fetchJobFiles(jobId)
    } catch { addToast('error', 'Network error.') }
  }

  async function handleFileGenerate(fileId: string) {
    if (!jobId) return
    setFileStatus(p => ({ ...p, [fileId]: 'running' }))
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}/generate`, { method: 'POST' })
      const data = await res.json()
      if (data.status !== 'ok') { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', data.message || 'Code gen failed.'); return }
      setFileStatus(p => ({ ...p, [fileId]: 'ok' }))
      addToast('success', 'Script generated!')
      fetchJobFiles(jobId)
    } catch { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', 'Network error.') }
  }

  async function handleFileExecute(fileId: string) {
    if (!jobId) return
    setFileStatus(p => ({ ...p, [fileId]: 'running' }))
    setFileProgress(p => ({ ...p, [fileId]: [] }))
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}/execute/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      if (!res.ok || !res.body) { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', 'Execution request failed.'); return }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const part of parts) {
          let eventType = 'message'; let dataLine = ''
          for (const line of part.split('\n')) {
            if (line.startsWith('event: ')) eventType = line.slice(7).trim()
            if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
          }
          if (!dataLine) continue
          try {
            const d = JSON.parse(dataLine)
            if (eventType === 'attempt_start') {
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), `🔄 Attempt ${d.attempt}/${d.total}...`] }))
            } else if (eventType === 'attempt_result') {
              const fillPct = Math.round((d.fill_rate ?? 0) * 100)
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), `${d.pass ? '✅' : '⚠️'} Attempt ${d.attempt}: ${fillPct}% fill`] }))
            } else if (eventType === 'attempt_crash') {
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), `💥 Attempt ${d.attempt}: crashed`] }))
            } else if (eventType === 'llm_fixing') {
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), `🤖 LLM rewriting script...`] }))
            } else if (eventType === 'complete') {
              setFileStatus(p => ({ ...p, [fileId]: d.status === 'ok' ? 'ok' : 'error' }))
              if (d.status === 'ok') addToast('success', `File cleaned successfully!`)
              else addToast('error', 'Execution failed — check logs.')
              fetchJobFiles(jobId)
            } else if (eventType === 'error') {
              setFileStatus(p => ({ ...p, [fileId]: 'error' }))
              addToast('error', `Error: ${d.message}`)
            }
          } catch { /* ignore */ }
        }
      }
    } catch { setFileStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', 'Network error.') }
  }

  // ── Shared: run full infer→select→generate→execute pipeline for one file ────
  async function runFilePipeline(fid: string, jid: string) {
    // Step 1: Infer
    setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '🧠 Inferring schema…'] }))
    setFileStatus(p => ({ ...p, [fid]: 'running' }))
    const ir = await fetch(`${apiBase}/api/v1/jobs/${jid}/files/${fid}/infer`, { method: 'POST' })
    const id = await ir.json()
    if (id.status !== 'ok') {
      setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `❌ Infer failed: ${id.message}`] }))
      setFileStatus(p => ({ ...p, [fid]: 'error' }))
      return false
    }
    setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '✅ Schema inferred'] }))

    // Step 2: Auto-confirm schema
    await fetch(`${apiBase}/api/v1/jobs/${jid}/files/${fid}/schema/select`, { method: 'POST' })

    // Step 3: Generate
    setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '⚗️ Generating cleaning script…'] }))
    const gr = await fetch(`${apiBase}/api/v1/jobs/${jid}/files/${fid}/generate`, { method: 'POST' })
    const gd = await gr.json()
    if (gd.status !== 'ok') {
      setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `❌ Generate failed: ${gd.message}`] }))
      setFileStatus(p => ({ ...p, [fid]: 'error' }))
      return false
    }
    setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '✅ Script generated'] }))

    // Step 4: Execute (SSE)
    setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '▶ Executing in sandbox…'] }))
    setFileStatus(p => ({ ...p, [fid]: 'running' }))
    const er = await fetch(`${apiBase}/api/v1/jobs/${jid}/files/${fid}/execute/stream`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    })
    if (!er.ok || !er.body) { setFileStatus(p => ({ ...p, [fid]: 'error' })); return false }
    const reader = er.body.getReader(); const decoder = new TextDecoder(); let buf = ''
    while (true) {
      const { done, value } = await reader.read(); if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n'); buf = parts.pop() ?? ''
      for (const part of parts) {
        let eventType = 'message'; let dataLine = ''
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
        }
        if (!dataLine) continue
        try {
          const d = JSON.parse(dataLine)
          if (eventType === 'attempt_start') {
            setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `🔄 Attempt ${d.attempt}/${d.total}…`] }))
          } else if (eventType === 'attempt_result') {
            const pct = Math.round((d.fill_rate ?? 0) * 100)
            setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `${d.pass ? '✅' : '⚠️'} Attempt ${d.attempt}: ${pct}% fill`] }))
          } else if (eventType === 'attempt_crash') {
            setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `💥 Attempt ${d.attempt}: crashed — self-healing…`] }))
          } else if (eventType === 'complete') {
            setFileStatus(p => ({ ...p, [fid]: d.status === 'ok' ? 'ok' : 'error' }))
            fetchJobFiles(jid)
            return d.status === 'ok'
          } else if (eventType === 'error') {
            setFileStatus(p => ({ ...p, [fid]: 'error' }))
            return false
          }
        } catch { /* ignore */ }
      }
    }
    return false
  }

  // ── PDF extract & tabularize → then auto-run full pipeline ──────────────────
  async function handleFileExtract(fileId: string) {
    if (!jobId) return
    setFileExtractStatus(p => ({ ...p, [fileId]: 'running' }))
    setFileProgress(p => ({ ...p, [fileId]: [] }))
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fileId}/extract/stream`, { method: 'POST' })
      if (!res.ok || !res.body) {
        setFileExtractStatus(p => ({ ...p, [fileId]: 'error' }))
        addToast('error', 'Extract request failed.')
        return
      }

      let extractOk = false
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const part of parts) {
          let eventType = 'message'; let dataLine = ''
          for (const line of part.split('\n')) {
            if (line.startsWith('event: ')) eventType = line.slice(7).trim()
            if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
          }
          if (!dataLine) continue
          try {
            const d = JSON.parse(dataLine)
            if (eventType === 'detecting') {
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), '🔍 Detecting PDF type…'] }))
            } else if (eventType === 'extracting') {
              const label = d.method === 'image' ? '🖼 Running vision OCR…' : '📄 Extracting text…'
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), label] }))
            } else if (eventType === 'tabularizing') {
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), '🤖 LLM tabularizing data…'] }))
            } else if (eventType === 'complete') {
              extractOk = true
              setFileExtractStatus(p => ({ ...p, [fileId]: 'ok' }))
              setFileProgress(p => ({ ...p, [fileId]: [...(p[fileId] || []), '✅ Extraction complete — running pipeline…'] }))
            } else if (eventType === 'error') {
              setFileExtractStatus(p => ({ ...p, [fileId]: 'error' }))
              addToast('error', `Extraction error: ${d.message}`)
            }
          } catch { /* ignore */ }
        }
      }

      if (extractOk) {
        const ok = await runFilePipeline(fileId, jobId)
        if (ok) addToast('success', 'PDF fully processed!')
        else addToast('error', 'PDF extracted but pipeline failed — check progress.')
        fetchJobFiles(jobId)
      }
    } catch { setFileExtractStatus(p => ({ ...p, [fileId]: 'error' })); addToast('error', 'Network error during extraction.') }
  }

  // ── Batch: run full pipeline on all eligible files ────────────────────────
  async function handleBatchProcess() {
    if (!jobId) return
    setShowBatchModal(false)
    setBatchRunning(true)
    addToast('info', 'Batch processing started…')

    // Include PDFs that have been extracted (has_preview) or need extraction first
    const eligible = jobFiles.filter(f =>
      (f.has_preview && f.file_type !== 'pdf') ||
      (f.file_type === 'pdf' && (f.has_preview || f.needs_extraction))
    )
    for (const f of eligible) {
      const fid = f.file_id
      try {
        // For PDFs that still need extraction: run extract/stream first
        if (f.file_type === 'pdf' && f.needs_extraction) {
          setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '🔍 Extracting PDF…'] }))
          setFileExtractStatus(p => ({ ...p, [fid]: 'running' }))
          const extractRes = await fetch(`${apiBase}/api/v1/jobs/${jobId}/files/${fid}/extract/stream`, { method: 'POST' })
          if (!extractRes.ok || !extractRes.body) {
            setFileExtractStatus(p => ({ ...p, [fid]: 'error' }))
            addToast('error', `Could not extract ${f.filename}`)
            continue
          }
          let extractOk = false
          const extractReader = extractRes.body.getReader(); const extractDecoder = new TextDecoder(); let extractBuf = ''
          while (true) {
            const { done, value } = await extractReader.read(); if (done) break
            extractBuf += extractDecoder.decode(value, { stream: true })
            const parts = extractBuf.split('\n\n'); extractBuf = parts.pop() ?? ''
            for (const part of parts) {
              let eventType = 'message'; let dataLine = ''
              for (const line of part.split('\n')) {
                if (line.startsWith('event: ')) eventType = line.slice(7).trim()
                if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
              }
              if (!dataLine) continue
              try {
                const d = JSON.parse(dataLine)
                if (eventType === 'detecting') {
                  setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '🔍 Detecting PDF type…'] }))
                } else if (eventType === 'extracting') {
                  const label = d.method === 'image' ? '🖼 Running vision OCR…' : '📄 Extracting text…'
                  setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), label] }))
                } else if (eventType === 'tabularizing') {
                  setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '🤖 LLM tabularizing data…'] }))
                } else if (eventType === 'complete') {
                  extractOk = true
                  setFileExtractStatus(p => ({ ...p, [fid]: 'ok' }))
                  setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), '✅ PDF extracted'] }))
                } else if (eventType === 'error') {
                  setFileExtractStatus(p => ({ ...p, [fid]: 'error' }))
                  setFileProgress(p => ({ ...p, [fid]: [...(p[fid] || []), `❌ Extraction failed: ${d.message}`] }))
                }
              } catch { /* ignore */ }
            }
          }
          if (!extractOk) continue
        }

        // Run full infer → select → generate → execute pipeline
        const ok = await runFilePipeline(fid, jobId)
        if (ok) addToast('success', `✅ ${f.filename} cleaned!`)
        else addToast('error', `❌ ${f.filename} failed.`)

      } catch (err) {
        setFileStatus(p => ({ ...p, [fid]: 'error' }))
        addToast('error', `Error processing ${f.filename}`)
      }
    }

    setBatchRunning(false)
    addToast('success', 'Batch processing complete!')
    fetchJobFiles(jobId)
  }

  // ── Consolidation ─────────────────────────────────────────────────────────
  async function handleConsolidate() {
    if (!jobId) return
    setConsolidating(true)
    setConsolidationResult(null)
    try {
      const res = await fetch(`${apiBase}/api/v1/jobs/${jobId}/consolidate/stream`, { method: 'POST' })
      if (!res.ok || !res.body) { addToast('error', 'Consolidation failed to start.'); return }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const lines = part.trim().split('\n')
          let eventType = '', dataStr = ''
          for (const l of lines) {
            if (l.startsWith('event: ')) eventType = l.slice(7).trim()
            else if (l.startsWith('data: ')) dataStr = l.slice(6).trim()
          }
          if (!dataStr) continue
          try {
            const d = JSON.parse(dataStr)
            if (eventType === 'complete' && d.status === 'ok') {
              setConsolidationResult(d)
              addToast('success', d.message || 'Files consolidated!')
            } else if (eventType === 'error') {
              addToast('error', d.message || 'Consolidation failed.')
            }
          } catch (e) { console.error('[consolidate] parse error:', e, 'raw:', dataStr?.slice(0, 100)) }
        }
      }
    } catch { addToast('error', 'Network error during consolidation.') }
    finally { setConsolidating(false) }
  }

  // ── Card-view helpers ─────────────────────────────────────────────────────
  function acceptColumn(name: string) {
    setColumnStates(prev => ({ ...prev, [name]: 'accepted' }))
  }
  function rejectColumn(name: string) {
    setColumnStates(prev => ({ ...prev, [name]: 'rejected' }))
  }
  function acceptAllCards() {
    const next: Record<string, ColumnState> = {}
    columns.forEach(c => { next[c.source_name] = 'accepted' })
    setColumnStates(next)
    addToast('success', `All ${columns.length} columns accepted!`)
  }



  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="app">
      <ToastContainer toasts={toasts} dismiss={dismissToast} />

      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-logo">
          <span className="logo-icon">🪡</span>
          <div>
            <h1>Schema Weaver</h1>
            <p>AI-native data consolidation — upload any file, get a clean schema.</p>
          </div>
        </div>
        <button className="btn-ghost" onClick={() => setShowApiConfig(v => !v)}>
          ⚙️ Config
        </button>
      </header>

      {showApiConfig && (
        <section className="panel panel-config">
          <label className="config-label">
            API Base URL
            <input type="text" value={apiBase} onChange={e => setApiBase(e.target.value)} placeholder="http://localhost:8010" />
          </label>
        </section>
      )}

      {/* ── Step Wizard — hidden for multi-file jobs (they have their own panel) ── */}
      {!activeJobPurpose && !jobLoading && (
        <section className="panel step-wizard-panel">
          <div className="step-wizard">
            {STEPS.map((s, i) => {
              const done = s.id < currentStep
              const active = s.id === currentStep
              return (
                <div key={s.id} className={`step ${done ? 'step-done' : active ? 'step-active' : 'step-pending'}`}>
                  <div className="step-icon-wrap">
                    <div className="step-icon">{done ? '✅' : s.icon}</div>
                  </div>
                  <div className="step-label">{s.label}</div>
                  {i < STEPS.length - 1 && <div className={`step-line ${done ? 'step-line-done' : ''}`} />}
                </div>
              )
            })}
          </div>
        </section>
      )}

      <div className="main-layout">
        {/* ── Left: Recent Jobs ── */}
        <aside className="panel jobs-panel">
          <div className="panel-header">
            <div className="label">Recent Jobs</div>
            <div style={{ display: 'flex', gap: 4 }}>
              <button className="btn-primary btn-sm" onClick={() => setShowNewJobModal(true)}>+ New</button>
              <button className="btn-ghost btn-sm" onClick={fetchJobs}>↻</button>
            </div>
          </div>
          <ul className="jobs">
            {jobs.length === 0 && <li className="no-jobs">No jobs yet.</li>}
            {jobs.map(job => (
              <li key={job.job_id}>
                <div className={`job ${jobId === job.job_id ? 'job-active' : ''}`}>
                  <button className="job-main" onClick={() => handleSelectJob(job.job_id)}>
                    <div className="job-title">
                      {job.purpose
                        ? <><span className="job-purpose-badge">📋</span> {job.purpose}</>
                        : job.filename}
                    </div>
                    <div className="job-meta">
                      <span className={`status-dot status-${job.status}`} />
                      {job.status}
                      {job.file_count != null && job.file_count > 0 && (
                        <span className="job-file-count">{job.file_count} file{job.file_count !== 1 ? 's' : ''}</span>
                      )}
                    </div>
                  </button>
                  <button className="btn-danger btn-sm" onClick={() => handleDeleteJob(job.job_id)}>✕</button>
                </div>
              </li>
            ))}
          </ul>
        </aside>

        {/* ── Right: Main content ── */}
        <div className="content-col">

          {/* ── Loading state while switching jobs ── */}
          {jobLoading && (
            <section className="panel" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
              Loading job…
            </section>
          )}

          {/* ── Multi-file job view (Phase 5) ── */}
          {!jobLoading && activeJobPurpose && (
            <>
              <section className="panel">
                <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span className="step-badge">Job</span>
                    {activeJobPurpose}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {jobFiles.some(f =>
                      (f.has_preview && f.file_type !== 'pdf') ||
                      (f.file_type === 'pdf' && (f.has_preview || f.needs_extraction))
                    ) && (
                      <button
                        className="btn-primary btn-sm"
                        onClick={() => setShowBatchModal(true)}
                        disabled={batchRunning}
                        title="Automatically run Infer → Generate → Execute on all eligible files"
                      >
                        {batchRunning ? '⏳ Processing…' : '🚀 Process All'}
                      </button>
                    )}
                    {jobFiles.some(f => f.execution_ok) && (
                      <button
                        className="btn-success btn-sm"
                        onClick={handleConsolidate}
                        disabled={consolidating}
                        title="Merge all cleaned files into a single unified table"
                      >
                        {consolidating ? '⏳ Merging…' : '⬇ Export All'}
                      </button>
                    )}
                    <span className="job-id-val">{jobId.slice(0, 10)}…</span>
                  </div>
                </div>

                {/* File upload strip */}
                <div className="mf-upload-row">
                  <input
                    type="file"
                    id="mf-file-input"
                    accept=".csv,.xlsx,.xls,.pdf,.jpg,.jpeg,.png"
                    onChange={e => setFileUploadInput(e.target.files?.[0] || null)}
                    style={{ display: 'none' }}
                  />
                  <label htmlFor="mf-file-input" className="mf-file-label">
                    {fileUploadInput ? `📄 ${fileUploadInput.name}` : '📁 Choose file to add…'}
                  </label>
                  <button
                    className="btn-primary btn-sm"
                    onClick={handleAddFileToJob}
                    disabled={!fileUploadInput || fileUploadStatus === 'running'}
                  >
                    {fileUploadStatus === 'running' ? '⏳ Uploading…' : '+ Add File'}
                  </button>
                </div>

                {/* File list */}
                {jobFilesLoading && <div className="progress-banner"><div className="progress-bar-indeterminate" /></div>}
                {jobFiles.length === 0 && !jobFilesLoading && (
                  <div className="mf-empty">No files yet — add your first file above.</div>
                )}
                {jobFiles.map(f => {
                  const fst = fileStatus[f.file_id] ?? 'idle'
                  const fest = fileExtractStatus[f.file_id] ?? 'idle'
                  const progress = fileProgress[f.file_id] ?? []
                  const qr = f.quality_report
                  const fillPct = qr ? Math.round(qr.overall_fill_rate * 100) : null
                  const statusLabel: Record<string, string> = {
                    pending: 'pending', ready: 'ready', inferring: 'inferring',
                    generating: 'generating', executing: 'executing',
                    validated: 'validated', failed: 'failed',
                  }
                  return (
                    <div key={f.file_id} className={`mf-file-card mf-file-${f.status}`}>
                      <div className="mf-file-top">
                        <div className="mf-file-info">
                          <span className="mf-file-type-badge">{f.file_type ?? '?'}</span>
                          <span className="mf-file-name">{f.filename}</span>
                          <span className={`mf-file-status mf-status-${f.status}`}>{statusLabel[f.status] ?? f.status}</span>
                          {fillPct !== null && (
                            <span className={`mf-fill-badge ${fillPct >= 90 ? 'fill-good' : fillPct >= 70 ? 'fill-warn' : 'fill-bad'}`}>
                              {fillPct}% fill
                            </span>
                          )}
                        </div>
                        <div className="mf-file-actions">
                          {f.has_preview && !f.has_schema && (
                            <button className="btn-sm btn-secondary" onClick={() => handleFileInfer(f.file_id)} disabled={fst === 'running'}>
                              🧠 Infer
                            </button>
                          )}
                          {f.has_schema && (
                            <button className="btn-sm btn-ghost" onClick={() => handleFileSelectSchema(f.file_id)}>
                              💾 Confirm
                            </button>
                          )}
                          {f.has_schema && !f.has_code && (
                            <button className="btn-sm btn-secondary" onClick={() => handleFileGenerate(f.file_id)} disabled={fst === 'running'}>
                              ⚗️ Generate
                            </button>
                          )}
                          {f.has_code && (
                            <button className="btn-sm btn-primary" onClick={() => handleFileExecute(f.file_id)} disabled={fst === 'running'}>
                              {fst === 'running' ? '⏳ Running…' : '▶ Execute'}
                            </button>
                          )}
                          {f.status === 'validated' && (
                            <a
                              href={`${apiBase}/api/v1/jobs/${jobId}/files/${f.file_id}/download`}
                              className="btn-sm btn-primary"
                              download
                            >⬇ Download</a>
                          )}
                          <button className="btn-sm btn-danger" onClick={() => handleRemoveJobFile(f.file_id)}>✕</button>
                        </div>
                      </div>

                      {f.error && <div className="mf-file-error">⚠ {f.error}</div>}

                      {/* PDF: needs extraction */}
                      {f.file_type === 'pdf' && f.needs_extraction && (
                        <div className="mf-file-info-note">
                          📄 This PDF needs to be extracted before it can be processed.
                          AI will detect whether it is text-based or image-based and tabularize the content.
                          <button
                            className="btn-sm btn-extract"
                            onClick={() => handleFileExtract(f.file_id)}
                            disabled={fest === 'running'}
                          >
                            {fest === 'running' ? '⏳ Extracting…' : '🔍 Extract & Tabularize'}
                          </button>
                        </div>
                      )}

                      {/* Live progress for this file */}
                      {progress.length > 0 && (
                        <div className="execute-progress-live" style={{ marginTop: '0.5rem' }}>
                          {progress.map((line, i) => <div key={i} className="execute-progress-line">{line}</div>)}
                          {fst === 'running' && <div className="execute-progress-line execute-progress-dots">⏳ working…</div>}
                        </div>
                      )}

                      {/* Quality report inline — collapsed by default to keep cards compact */}
                      {qr && f.validation_attempts.length > 0 && (
                        <QualityReport report={qr} attempts={f.validation_attempts} defaultCollapsed={true} />
                      )}
                    </div>
                  )
                })}
              </section>

              {/* ── Consolidation result panel ── */}
              {consolidationResult && (
                <section className="panel consolidation-panel">
                  <div className="consolidation-header">
                    <div className="consolidation-title">
                      <span>🔗 Consolidated Output</span>
                      <span className="consolidation-badge">
                        {consolidationResult.consolidated_preview.file_count} files · {consolidationResult.consolidated_preview.row_count} rows · {consolidationResult.consolidated_preview.columns.length} columns
                      </span>
                    </div>
                    <a
                      href={`${apiBase}/api/v1/jobs/${jobId}/consolidate/download`}
                      className="btn-success btn-sm"
                      download
                    >
                      ⬇ Download CSV
                    </a>
                  </div>

                  {consolidationResult.column_mapping.notes && (
                    <p className="consolidation-notes">💡 {consolidationResult.column_mapping.notes}</p>
                  )}

                  {consolidationResult.merge_errors.length > 0 && (
                    <div className="consolidation-errors">
                      {consolidationResult.merge_errors.map((e, i) => <div key={i}>⚠ {e}</div>)}
                    </div>
                  )}

                  {/* Column mapping table */}
                  <details className="consolidation-mapping-details">
                    <summary>📋 Column mapping ({consolidationResult.consolidated_preview.columns.length} unified columns)</summary>
                    <div className="consolidation-mapping-table-wrap">
                      <table className="consolidation-mapping-table">
                        <thead>
                          <tr>
                            <th>Canonical column</th>
                            {Object.values(consolidationResult.column_mapping.file_mappings).length > 0 &&
                              Object.keys(consolidationResult.column_mapping.file_mappings).map(fid => {
                                const f = jobFiles.find(jf => jf.id === fid)
                                return <th key={fid}>{f?.filename ?? fid}</th>
                              })
                            }
                          </tr>
                        </thead>
                        <tbody>
                          {consolidationResult.column_mapping.canonical_columns.map(col => (
                            <tr key={col}>
                              <td><code>{col}</code></td>
                              {Object.entries(consolidationResult.column_mapping.file_mappings).map(([fid, mapping]) => {
                                const srcCol = Object.entries(mapping).find(([, v]) => v === col)?.[0]
                                return (
                                  <td key={fid} className={srcCol ? 'mapping-present' : 'mapping-absent'}>
                                    {srcCol ? <code>{srcCol}</code> : <span className="mapping-null">—</span>}
                                  </td>
                                )
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>

                  {/* Data preview */}
                  <div className="consolidation-preview-wrap">
                    <div className="consolidation-preview-label">Preview (first {consolidationResult.consolidated_preview.sample_rows.length} rows)</div>
                    <div style={{ overflowX: 'auto' }}>
                      <table className="consolidation-preview-table">
                        <thead>
                          <tr>{consolidationResult.consolidated_preview.columns.map(c => <th key={c}>{c}</th>)}</tr>
                        </thead>
                        <tbody>
                          {consolidationResult.consolidated_preview.sample_rows.map((row, i) => (
                            <tr key={i}>
                              {consolidationResult.consolidated_preview.columns.map(c => (
                                <td key={c}>{row[c] ?? <span className="mapping-null">—</span>}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </section>
              )}
            </>
          )}

          {/* ── Step 1 & 2: Upload + Parse (single-file legacy mode) ── */}
          {!jobLoading && !activeJobPurpose && currentStep <= 2 && (
            <section className="panel">
              <div className="panel-title">
                <span className="step-badge">Step 1</span>
                Upload Your File
              </div>
              <div className="upload-zone">
                <input
                  type="file"
                  id="file-input"
                  accept=".csv,.xlsx,.xls,.pdf"
                  onChange={e => setFile(e.target.files?.[0] || null)}
                />
                <label htmlFor="file-input" className="upload-label">
                  {file ? (
                    <>📄 <strong>{file.name}</strong><br /><small>{(file.size / 1024).toFixed(1)} KB</small></>
                  ) : (
                    <>📁 Choose a file<br /><small>CSV, Excel, or PDF</small></>
                  )}
                </label>
              </div>
              <button
                className="btn-primary btn-full"
                onClick={handleUpload}
                disabled={!file || status === 'uploading' || status === 'queued' || status === 'processing'}
              >
                {status === 'uploading' ? '⏳ Uploading...'
                  : status === 'queued' || status === 'processing' ? '⚙️ Parsing...'
                  : '🚀 Upload & Parse'}
              </button>

              {(status === 'queued' || status === 'processing') && (
                <div className="progress-banner">
                  <div className="progress-bar-indeterminate" />
                  <span>Parsing file… step: <strong>{step ?? '…'}</strong></span>
                </div>
              )}

              {error && <div className="error-banner">❌ {error}</div>}
            </section>
          )}

          {/* ── Step 3: AI Inference ── */}
          {!jobLoading && !activeJobPurpose && currentStep === 3 && (
            <section className="panel">
              <div className="panel-title">
                <span className="step-badge">Step 2</span>
                AI Schema Inference
              </div>
              <div className="parsed-summary">
                <div className="summary-icon">✅</div>
                <div>
                  <div className="summary-title">File parsed successfully</div>
                  <div className="summary-sub">
                    {(result as { preview?: { row_count?: number; columns?: string[] } } | null)?.preview?.row_count ?? '?'} rows ·{' '}
                    {(result as { preview?: { columns?: string[] } } | null)?.preview?.columns?.length ?? '?'} columns detected
                  </div>
                </div>
              </div>
              <button
                className="btn-primary btn-full"
                onClick={handleInfer}
                disabled={inferenceStatus === 'running'}
              >
                {inferenceStatus === 'running' ? '🧠 Analysing with AI...' : '🧠 Run AI Schema Inference'}
              </button>
              {inferenceStatus === 'running' && (
                <div className="progress-banner">
                  <div className="progress-bar-indeterminate" />
                  <span>GPT-5 is reading your data…</span>
                </div>
              )}
            </section>
          )}

          {/* ── Step 4: Schema Review — Card or Map view ── */}
          {!jobLoading && !activeJobPurpose && currentStep === 4 && columns.length > 0 && (
            <section className={`panel ${reviewMode === 'map' ? 'panel-mapper' : ''}`}>

              {/* Title + view toggle */}
              <div className="panel-title panel-title-row">
                <div>
                  <span className="step-badge">Step 3</span>
                  Review Schema Mapping
                </div>
                <div className="view-toggle">
                  <button
                    className={`view-toggle-btn ${reviewMode === 'cards' ? 'view-toggle-active' : ''}`}
                    onClick={() => setReviewMode('cards')}
                    title="Card view — readable detail cards with accept/reject"
                  >
                    ☰ Cards
                  </button>
                  <button
                    className={`view-toggle-btn ${reviewMode === 'map' ? 'view-toggle-active' : ''}`}
                    onClick={() => setReviewMode('map')}
                    title="Map view — visual drag-and-drop flow diagram"
                  >
                    ⬡ Map
                  </button>
                </div>
              </div>

              {/* Health Score Banner */}
              <div className={`health-banner ${healthClass}`}>
                <div className="health-score-wrap">
                  <div className="health-score">{Math.round(overallHealth * 100)}%</div>
                  <div>
                    <div className="health-title">Data Health Score — {healthLabel}</div>
                    <div className="health-sub">
                      {columns.length} columns ·{' '}
                      {reviewMode === 'cards'
                        ? `${Object.values(columnStates).filter(s => s === 'accepted').length} accepted · ${Object.values(columnStates).filter(s => s === 'rejected').length} rejected`
                        : `${mappings.filter(m => m.accepted).length}/${mappings.length} accepted`
                      }
                    </div>
                  </div>
                </div>
                <div className="health-bar-outer">
                  <div className="health-bar-inner" style={{ width: `${overallHealth * 100}%` }} />
                </div>
              </div>

              {/* Notes from LLM */}
              {schemaInference?.notes && (
                <div className="notes-banner">
                  💡 <em>{schemaInference.notes}</em>
                </div>
              )}

              {/* ── CARD VIEW ── */}
              {reviewMode === 'cards' && (
                <>
                  <div className="column-cards-header">
                    <span>{columns.length} columns</span>
                    <button className="btn-accept-all" onClick={acceptAllCards}>✅ Accept All</button>
                  </div>
                  <div className="column-cards">
                    {columns.map(col => {
                      const state = columnStates[col.source_name] ?? 'pending'
                      return (
                        <div key={col.source_name} className={`col-card col-card-${state}`}>
                          <div className="col-card-top">
                            <div className="col-mapping">
                              <span className="col-source">{col.source_name}</span>
                              <span className="col-arrow">→</span>
                              <span className="col-target">{col.suggested_name}</span>
                            </div>
                            <TypeBadge type={col.inferred_type} />
                          </div>
                          <div className="col-desc">{col.description}</div>
                          <ConfidenceBar value={col.confidence} />
                          <div className="col-actions">
                            {state === 'accepted' ? (
                              <span className="col-accepted">✅ Accepted</span>
                            ) : state === 'rejected' ? (
                              <span className="col-rejected">❌ Rejected</span>
                            ) : (
                              <>
                                <button className="btn-accept" onClick={() => acceptColumn(col.source_name)}>✓ Accept</button>
                                <button className="btn-reject" onClick={() => rejectColumn(col.source_name)}>✕ Reject</button>
                              </>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </>
              )}

              {/* ── MAP VIEW ── */}
              {reviewMode === 'map' && (
                <>
                  <SchemaMapper columns={columns} onMappingsChange={setMappings} />

                  {/* Accepted mappings summary table */}
                  {mappings.some(m => m.accepted) && (
                    <div className="mapping-summary">
                      <div className="mapping-summary-title">Accepted Mappings</div>
                      <table className="mapping-table">
                        <thead>
                          <tr><th>Source</th><th>→</th><th>Target</th><th>Confidence</th></tr>
                        </thead>
                        <tbody>
                          {mappings.filter(m => m.accepted).map(m => (
                            <tr key={`${m.source}-${m.target}`}>
                              <td><code>{m.source}</code></td>
                              <td className="arrow-cell">→</td>
                              <td><code>{m.target}</code></td>
                              <td><ConfidenceBar value={m.confidence} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}

              {/* Confirm + Embed (both views) */}
              <div className="review-actions">
                <button className="btn-primary" onClick={handleSelectSchema}>
                  💾 Confirm Schema
                </button>
                <button
                  className="btn-secondary"
                  onClick={handleBuildEmbeddings}
                  disabled={embeddingStatus === 'running' || !selectedSchema}
                  title={!selectedSchema ? 'Confirm schema first' : ''}
                >
                  {embeddingStatus === 'running' ? '⏳ Embedding...' : '🔮 Build Embeddings'}
                </button>
              </div>
              {embeddingStatus === 'running' && (
                <div className="progress-banner">
                  <div className="progress-bar-indeterminate" />
                  <span>Generating vector embeddings for semantic search…</span>
                </div>
              )}
            </section>
          )}

          {/* ── Step 5: Transform — code gen + sandbox execution ── */}
          {!jobLoading && !activeJobPurpose && currentStep >= 4 && currentStep < 6 && inferenceStatus === 'ok' && (
            <section className="panel">
              <div className="panel-title">
                <span className="step-badge">Step 4</span>
                Generate &amp; Execute Cleaning Script
              </div>

              {/* Generate button */}
              {generateStatus === 'idle' && (
                <div className="transform-intro">
                  <p>Schema confirmed ✅  GPT will now write a pandas script to clean and normalise your data.</p>
                  <button className="btn-primary btn-full" onClick={handleGenerate}>
                    ⚗️ Generate Cleaning Script
                  </button>
                </div>
              )}
              {generateStatus === 'running' && (
                <div className="progress-banner">
                  <div className="progress-bar-indeterminate" />
                  <span>GPT is writing your cleaning script…</span>
                </div>
              )}
              {generateStatus === 'error' && (
                <div className="error-banner">
                  ❌ Code generation failed.
                  <button className="btn-ghost btn-sm" onClick={handleGenerate}>Retry</button>
                </div>
              )}

              {/* Code viewer / editor */}
              {(generateStatus === 'ok' || generatedCode) && (
                <>
                  <div className="code-block-header">
                    <span className="code-block-title">🐍 Generated Python Script {codeEdited && <span className="code-edited-badge">edited</span>}</span>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn-ghost btn-sm" onClick={() => { setGeneratedCode(''); setGenerateStatus('idle'); setCodeEdited(false) }}>↺ Regenerate</button>
                      <button className="btn-ghost btn-sm" onClick={() => navigator.clipboard?.writeText(generatedCode)}>⎘ Copy</button>
                    </div>
                  </div>
                  <textarea
                    className="code-block-editor"
                    value={generatedCode}
                    onChange={e => { setGeneratedCode(e.target.value); setCodeEdited(true) }}
                    spellCheck={false}
                    rows={Math.min(generatedCode.split('\n').length + 2, 30)}
                  />

                  {/* Run button */}
                  {executeStatus !== 'ok' && (
                    <button
                      className="btn-primary btn-full"
                      onClick={handleExecute}
                      disabled={executeStatus === 'running' || !generatedCode}
                    >
                      {executeStatus === 'running' ? '⏳ Running in sandbox…' : '▶ Run in Docker Sandbox'}
                    </button>
                  )}
                  {executeStatus === 'running' && (
                    <div className="progress-banner">
                      <div className="progress-bar-indeterminate" />
                      <span>Executing in isolated Docker container…</span>
                      {executeProgress.length > 0 && (
                        <div className="execute-progress-live">
                          {executeProgress.map((line, i) => (
                            <div key={i} className="execute-progress-line">{line}</div>
                          ))}
                          <div className="execute-progress-line execute-progress-dots">⏳ working…</div>
                        </div>
                      )}
                    </div>
                  )}
                  {executeStatus === 'error' && (
                    <div className="error-banner">
                      ❌ Execution failed.
                      <button className="btn-ghost btn-sm" onClick={handleExecute}>Retry</button>
                    </div>
                  )}
                </>
              )}

              {/* Sandbox log */}
              {sandboxLog && (
                <details className="sandbox-log-wrap">
                  <summary className="sandbox-log-title">📋 Sandbox log</summary>
                  <pre className="sandbox-log">{sandboxLog}</pre>
                </details>
              )}

              {/* Quality Report */}
              {qualityReport && (
                <QualityReport
                  report={qualityReport}
                  attempts={validationAttempts}
                />
              )}

              {/* Cleaned data preview */}
              {cleanedPreview && (
                <div className="cleaned-preview">
                  <div className="cleaned-preview-header">
                    <span>✅ {cleanedPreview.row_count} rows cleaned · {cleanedPreview.columns.length} columns</span>
                    <a
                      href={`${apiBase}/api/v1/jobs/${jobId}/download`}
                      className="btn-primary btn-sm"
                      download
                    >
                      ⬇ Download CSV
                    </a>
                  </div>
                  <div className="cleaned-table-wrap">
                    <table className="cleaned-table">
                      <thead>
                        <tr>{cleanedPreview.columns.map(c => <th key={c}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {cleanedPreview.sample_rows.map((row, i) => (
                          <tr key={i}>
                            {cleanedPreview.columns.map(c => <td key={c}>{row[c] ?? ''}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="cleaned-note">Showing first {cleanedPreview.sample_rows.length} of {cleanedPreview.row_count} rows</p>
                </div>
              )}
            </section>
          )}

          {/* ── Step 6: Done ── */}
          {!jobLoading && !activeJobPurpose && currentStep === 6 && (
            <section className="panel">
              <div className="panel-title">
                <span className="step-badge step-badge-done">Done</span>
                Pipeline Complete 🎉
              </div>
              <div className="done-banner">
                <div className="done-icon">🎯</div>
                <div>
                  <div className="done-title">Data Weaved Successfully!</div>
                  <div className="done-sub">
                    {cleanedPreview?.row_count ?? 0} rows cleaned · {cleanedPreview?.columns.length ?? 0} columns · ready to download
                  </div>
                </div>
              </div>
              <div className="done-stats">
                <div className="stat-card">
                  <div className="stat-num">{cleanedPreview?.row_count ?? '—'}</div>
                  <div className="stat-lbl">Rows</div>
                </div>
                <div className="stat-card">
                  <div className="stat-num">{cleanedPreview?.columns.length ?? '—'}</div>
                  <div className="stat-lbl">Columns</div>
                </div>
                <div className="stat-card">
                  <div className="stat-num">
                    {qualityReport
                      ? `${Math.round(qualityReport.overall_fill_rate * 100)}%`
                      : `${Math.round(overallHealth * 100)}%`}
                  </div>
                  <div className="stat-lbl">Fill Rate</div>
                </div>
                <div className="stat-card">
                  <div className="stat-num">{Math.round(overallHealth * 100)}%</div>
                  <div className="stat-lbl">Schema Health</div>
                </div>
              </div>
              <a
                href={`${apiBase}/api/v1/jobs/${jobId}/download`}
                className="btn-primary btn-full"
                download
              >
                ⬇ Download Cleaned CSV
              </a>
              <button className="btn-outline btn-full" style={{ marginTop: 10 }} onClick={() => {
                setStatus('idle'); setJobId(''); setInferenceStatus('idle')
                setEmbeddingStatus('idle'); setMappings([]); setFile(null)
                resetAll()
              }}>
                ➕ Process Another File
              </button>

              {/* Quality report in export panel */}
              {qualityReport && (
                <div style={{ marginTop: '1.5rem' }}>
                  <QualityReport
                    report={qualityReport}
                    attempts={validationAttempts}
                  />
                </div>
              )}
            </section>
          )}

          {/* ── Job Status Row (single-file mode only) ── */}
          {!jobLoading && !activeJobPurpose && jobId && (
            <section className="panel panel-status">
              <div className="status-grid">
                <div>
                  <div className="label">Job ID</div>
                  <div className="job-id-val">{jobId.slice(0, 12)}…</div>
                </div>
                <div>
                  <div className="label">Status</div>
                  <div className={`badge badge-${status}`}>{status}</div>
                </div>
                <div>
                  <div className="label">Task</div>
                  <div className={`badge badge-${taskStatus || 'none'}`}>{taskStatus || '—'}</div>
                </div>
                <div>
                  <div className="label">Step</div>
                  <div className="step-val">{step || '—'}</div>
                </div>
              </div>
            </section>
          )}

          {/* ── Raw Result (collapsible) ── */}
          {result && (
            <section className="panel panel-raw">
              <div className="panel-header">
                <div className="label">Raw Result</div>
                <button className="btn-ghost btn-sm" onClick={() => setShowRawResult(v => !v)}>
                  {showRawResult ? '− Collapse' : '+ Expand'}
                </button>
              </div>
              {showRawResult && <JsonTree data={result as JsonValue} />}
            </section>
          )}

          {/* ── Event Log (collapsible) ── */}
          <section className="panel panel-log">
            <div className="panel-header">
              <div className="label">Event Log</div>
              <button className="btn-ghost btn-sm" onClick={() => setShowEventLog(v => !v)}>
                {showEventLog ? '− Hide' : '+ Show'}
              </button>
            </div>
            {showEventLog && (
              <ul className="event-log">
                {events.length === 0 && <li>No events yet.</li>}
                {events.map((e, i) => <li key={`${e}-${i}`}>{e}</li>)}
              </ul>
            )}
          </section>

        </div>
      </div>
      {/* ── Batch Process Modal ── */}
      {showBatchModal && (
        <div className="modal-overlay" onClick={() => setShowBatchModal(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-title">🚀 Batch Process All Files</div>
            <div className="batch-modal-info">
              <div className="batch-modal-warning">
                <span className="batch-warning-icon">⚠️</span>
                <div>
                  <strong>Auto-pilot mode</strong> — AI will make all decisions automatically.
                  Schema mappings, column selections, and cleaning strategies will be chosen
                  without manual confirmation. You can review and re-run individual files
                  afterwards.
                </div>
              </div>
              <div className="batch-modal-steps">
                <div className="batch-step">🔍 <strong>Extract</strong> — PDFs are detected (text/image) and tabularized via AI</div>
                <div className="batch-step">🧠 <strong>Infer</strong> — AI analyses each file's structure</div>
                <div className="batch-step">✅ <strong>Auto-confirm</strong> — Best schema selected automatically</div>
                <div className="batch-step">⚗️ <strong>Generate</strong> — Cleaning script written per file</div>
                <div className="batch-step">▶ <strong>Execute</strong> — Script runs in sandbox with self-healing</div>
              </div>
              <div className="batch-modal-scope">
                <strong>{jobFiles.filter(f =>
                  (f.has_preview && f.file_type !== 'pdf') ||
                  (f.file_type === 'pdf' && (f.has_preview || f.needs_extraction))
                ).length}</strong> eligible file(s) will be processed.
                {jobFiles.some(f => f.file_type === 'pdf' && f.needs_extraction) && (
                  <span> PDF files will be extracted and tabularized automatically before processing.</span>
                )}
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => setShowBatchModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={handleBatchProcess}>
                🚀 Run All Files
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── New Job Modal ── */}
      {showNewJobModal && (
        <div className="modal-overlay" onClick={() => setShowNewJobModal(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-title">Create New Multi-File Job</div>
            <label className="modal-label">
              Job Purpose <span className="modal-required">*</span>
              <input
                className="modal-input"
                type="text"
                placeholder="e.g. Invoice Processing — Q1 2025"
                value={newJobPurpose}
                onChange={e => setNewJobPurpose(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreateJob()}
                autoFocus
              />
            </label>
            <label className="modal-label">
              Description <span className="modal-optional">(optional)</span>
              <textarea
                className="modal-input modal-textarea"
                placeholder="Additional context about this job..."
                value={newJobDesc}
                onChange={e => setNewJobDesc(e.target.value)}
                rows={3}
              />
            </label>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => setShowNewJobModal(false)}>Cancel</button>
              <button
                className="btn-primary"
                onClick={handleCreateJob}
                disabled={!newJobPurpose.trim() || newJobCreating}
              >
                {newJobCreating ? '⏳ Creating…' : '✓ Create Job'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
