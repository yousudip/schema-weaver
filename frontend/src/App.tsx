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
  status: string
  task_status: string | null
  created_at: string | null
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
    setResult(job.result || null)
    setAnalysis(job.analysis || null)
    setError(job.error || null)

    // Restore derived statuses from persisted analysis so loaded jobs
    // resume at the correct wizard step without re-running each stage
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
    setJobId(id)
    setAnalysis(null)
    setInferenceStatus('idle'); setEmbeddingStatus('idle')
    setMappings([]); setColumnStates({})
    resetAll()
    // Then load job data and restore statuses from persisted analysis
    const res = await fetch(`${apiBase}/api/v1/jobs/${id}`)
    if (!res.ok) return
    const data = await res.json()
    const job = data?.job
    if (!job) return
    setStatus(job.status || 'unknown')
    setTaskStatus(job.task_status || null)
    setStep(job.step || null)
    setResult(job.result || null)
    setAnalysis(job.analysis || null)
    setError(job.error || null)

    const a = job.analysis || {}
    if (a.schema_inference || a.selected_schema) setInferenceStatus('ok')
    if (a.generated_code) { setGeneratedCode(a.generated_code); setGenerateStatus('ok'); setCodeEdited(false) }
    if (a.cleaned_preview) { setCleanedPreview(a.cleaned_preview); setExecuteStatus('ok') }
    if (a.execution_log) setSandboxLog(a.execution_log)
    if (a.quality_report) setQualityReport(a.quality_report)
    if (a.validation_attempts) setValidationAttempts(a.validation_attempts)
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

      {/* ── Step Wizard ── */}
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

      <div className="main-layout">
        {/* ── Left: Recent Jobs ── */}
        <aside className="panel jobs-panel">
          <div className="panel-header">
            <div className="label">Recent Jobs</div>
            <button className="btn-ghost btn-sm" onClick={fetchJobs}>↻ Reload</button>
          </div>
          <ul className="jobs">
            {jobs.length === 0 && <li className="no-jobs">No jobs yet.</li>}
            {jobs.map(job => (
              <li key={job.job_id}>
                <div className={`job ${jobId === job.job_id ? 'job-active' : ''}`}>
                  <button className="job-main" onClick={() => handleSelectJob(job.job_id)}>
                    <div className="job-title">{job.filename}</div>
                    <div className="job-meta">
                      <span className={`status-dot status-${job.status}`} />
                      {job.status}
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

          {/* ── Step 1 & 2: Upload + Parse ── */}
          {currentStep <= 2 && (
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
          {currentStep === 3 && (
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
          {currentStep === 4 && columns.length > 0 && (
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
          {currentStep >= 4 && currentStep < 6 && inferenceStatus === 'ok' && (
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
          {currentStep === 6 && (
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

          {/* ── Job Status Row (always visible when job active) ── */}
          {jobId && (
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
    </div>
  )
}

export default App
