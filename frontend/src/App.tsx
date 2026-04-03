import { useEffect, useMemo, useState } from 'react'
import './App.css'

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue }

function JsonTree({ data, label }: { data: JsonValue; label?: string }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  function toggle(path: string) {
    setCollapsed((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  function renderValue(value: JsonValue, path: string): JSX.Element {
    if (value === null) return <span className="json-null">null</span>
    if (typeof value === 'string') return <span className="json-string">"{value}"</span>
    if (typeof value === 'number') return <span className="json-number">{value}</span>
    if (typeof value === 'boolean') return <span className="json-bool">{String(value)}</span>

    const isArray = Array.isArray(value)
    const keys = isArray ? value.map((_, i) => i) : Object.keys(value)
    const isCollapsed = collapsed[path]

    return (
      <div className="json-node">
        <button className="json-toggle" onClick={() => toggle(path)}>
          {isCollapsed ? '+' : '−'}
        </button>
        <span className="json-brace">{isArray ? '[' : '{'}</span>
        {!isCollapsed && (
          <div className="json-children">
            {keys.map((key) => {
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

function App() {
  const [apiBase, setApiBase] = useState(
    import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  )
  const [file, setFile] = useState<File | null>(null)
  const [jobId, setJobId] = useState('')
  const [status, setStatus] = useState('idle')
  const [taskStatus, setTaskStatus] = useState<string | null>(null)
  const [step, setStep] = useState<string | null>(null)
  const [result, setResult] = useState<object | null>(null)
  const [analysis, setAnalysis] = useState<object | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<string[]>([])
  const [resultExpanded, setResultExpanded] = useState(false)
  const [previewExpanded, setPreviewExpanded] = useState(false)
  const [analysisExpanded, setAnalysisExpanded] = useState(false)
  const [inferenceStatus, setInferenceStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [inferenceError, setInferenceError] = useState<string | null>(null)
  const [embeddingStatus, setEmbeddingStatus] = useState<'idle' | 'running' | 'ok' | 'error'>('idle')
  const [embeddingError, setEmbeddingError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<
    { job_id: string; filename: string; status: string; task_status: string | null; created_at: string | null }[]
  >([])

  const statusUrl = useMemo(() => {
    return jobId ? `${apiBase}/api/v1/jobs/${jobId}/status/stream` : ''
  }, [apiBase, jobId])

  useEffect(() => {
    if (!statusUrl) return
    setEvents([])
    const source = new EventSource(statusUrl)
    const pushEvent = (label: string, payload?: unknown) => {
      const timestamp = new Date().toLocaleTimeString()
      const message =
        payload === undefined
          ? `${timestamp} ${label}`
          : `${timestamp} ${label}: ${JSON.stringify(payload)}`
      setEvents((prev) => [message, ...prev].slice(0, 20))
    }
    source.addEventListener('status', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        if (payload.job_id && payload.job_id !== jobId) return
        setStatus(payload.status || 'unknown')
        setTaskStatus(payload.task_status ?? null)
        if (payload.step) setStep(payload.step)
        pushEvent('status', payload)
        if (payload.status === 'completed' || payload.status === 'failed') {
          handleRefresh()
        }
      } catch {
        pushEvent('status (invalid payload)')
      }
    })
    source.addEventListener('heartbeat', () => {
      pushEvent('heartbeat')
    })
    source.addEventListener('error', (event) => {
      try {
        const data = (event as MessageEvent).data
        if (!data) {
          pushEvent('error (connection)')
          return
        }
        const payload = JSON.parse(data)
        pushEvent('error', payload)
      } catch {
        pushEvent('error (invalid payload)')
      }
    })
    source.addEventListener('result', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data)
        setResult(payload.result || null)
        setError(payload.error || null)
        pushEvent('result', payload)
        setStep(payload.result?.step || null)
      } catch {
        pushEvent('result (invalid payload)')
      }
    })
    source.onerror = () => {
      source.close()
    }
    return () => source.close()
  }, [statusUrl])

  async function fetchJobs() {
    const response = await fetch(`${apiBase}/api/v1/jobs`)
    if (!response.ok) return
    const data = await response.json()
    setJobs(data.jobs || [])
  }

  useEffect(() => {
    fetchJobs()
  }, [apiBase])

  async function handleUpload() {
    if (!file) return
    setStatus('uploading')
    setResult(null)
    setAnalysis(null)
    setError(null)
    setResultExpanded(false)
    setPreviewExpanded(false)
    setAnalysisExpanded(false)
    setInferenceStatus('idle')
    setInferenceError(null)
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${apiBase}/api/v1/upload`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      setStatus('upload_failed')
      return
    }
    const data = await response.json()
    setJobId(data.job_id)
    setStatus('queued')
    fetchJobs()
  }

  async function handleRefresh() {
    if (!jobId) return
    const response = await fetch(`${apiBase}/api/v1/jobs/${jobId}`)
    if (!response.ok) return
    const data = await response.json()
    setStatus(data?.job?.status || 'unknown')
    setTaskStatus(data?.job?.task_status || null)
    setStep(data?.job?.step || null)
    setResult(data?.job?.result || null)
    setAnalysis(data?.job?.analysis || null)
    setError(data?.job?.error || null)
  }

  const schemaInference = (analysis as { schema_inference?: JsonValue } | null)
    ?.schema_inference
  const selectedSchema = (analysis as { selected_schema?: JsonValue } | null)
    ?.selected_schema

  async function handleInfer() {
    if (!jobId) return
    setInferenceStatus('running')
    setInferenceError(null)
    const response = await fetch(`${apiBase}/api/v1/jobs/${jobId}/infer`, {
      method: 'POST',
    })
    if (!response.ok) {
      setInferenceStatus('error')
      setInferenceError('Inference failed.')
      return
    }
    const data = await response.json()
    if (data.status !== 'ok') {
      setInferenceStatus('error')
      setInferenceError(data.message || 'Inference failed.')
      return
    }
    setAnalysis(data.analysis || null)
    setInferenceStatus('ok')
    setAnalysisExpanded(true)
  }

  async function handleSelectSchema() {
    if (!jobId) return
    setInferenceStatus('running')
    setInferenceError(null)
    const response = await fetch(`${apiBase}/api/v1/jobs/${jobId}/schema/select`, {
      method: 'POST',
    })
    if (!response.ok) {
      setInferenceStatus('error')
      setInferenceError('Schema selection failed.')
      return
    }
    const data = await response.json()
    if (data.status !== 'ok') {
      setInferenceStatus('error')
      setInferenceError(data.message || 'Schema selection failed.')
      return
    }
    setAnalysis(data.analysis || null)
    setInferenceStatus('ok')
    setAnalysisExpanded(true)
  }

  async function handleBuildEmbeddings() {
    if (!jobId) return
    setEmbeddingStatus('running')
    setEmbeddingError(null)
    const response = await fetch(`${apiBase}/api/v1/jobs/${jobId}/schema/embeddings`, {
      method: 'POST',
    })
    if (!response.ok) {
      setEmbeddingStatus('error')
      setEmbeddingError('Embedding build failed.')
      return
    }
    const data = await response.json()
    if (data.status !== 'ok') {
      setEmbeddingStatus('error')
      setEmbeddingError(data.message || 'Embedding build failed.')
      return
    }
    setEmbeddingStatus('ok')
  }

  function handleSelectJob(selectedId: string) {
    setJobId(selectedId)
    setAnalysis(null)
    setAnalysisExpanded(false)
    setInferenceStatus('idle')
    setInferenceError(null)
    setEmbeddingStatus('idle')
    setEmbeddingError(null)
    handleRefresh()
  }

  async function handleDeleteJob(selectedId: string) {
    await fetch(`${apiBase}/api/v1/jobs/${selectedId}`, { method: 'DELETE' })
    if (jobId === selectedId) {
      setJobId('')
      setStatus('idle')
      setTaskStatus(null)
      setStep(null)
      setResult(null)
      setAnalysis(null)
      setError(null)
      setInferenceStatus('idle')
      setInferenceError(null)
      setEmbeddingStatus('idle')
      setEmbeddingError(null)
    }
    fetchJobs()
  }

  return (
    <div className="app">
      <header>
        <h1>Gamified Data Consolidator</h1>
        <p>Upload a file and watch real-time status updates.</p>
      </header>

      <section className="panel">
        <label>
          API Base URL
          <input
            type="text"
            value={apiBase}
            onChange={(event) => setApiBase(event.target.value)}
            placeholder="http://localhost:8000"
          />
        </label>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div className="label">Recent Jobs</div>
          <button onClick={fetchJobs}>Reload List</button>
        </div>
        <ul className="jobs">
          {jobs.length === 0 && <li>No jobs yet.</li>}
          {jobs.map((job) => (
            <li key={job.job_id}>
              <div className={jobId === job.job_id ? 'job active' : 'job'}>
                <button className="job-main" onClick={() => handleSelectJob(job.job_id)}>
                  <div className="job-title">{job.filename}</div>
                  <div className="job-meta">
                    {job.status} / {job.task_status ?? '—'}
                  </div>
                </button>
                <button
                  className="job-delete"
                  onClick={() => handleDeleteJob(job.job_id)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <label>
          Select file
          <input
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        <div className="actions">
          <button onClick={handleUpload} disabled={!file}>
            Upload
          </button>
          <button onClick={handleRefresh} disabled={!jobId}>
            Refresh
          </button>
          <button
            onClick={handleInfer}
            disabled={!jobId || status !== 'completed' || inferenceStatus === 'running'}
          >
            {inferenceStatus === 'running' ? 'Inferring...' : 'Run Inference'}
          </button>
          <button
            onClick={handleSelectSchema}
            disabled={!schemaInference || inferenceStatus === 'running'}
          >
            Use This Schema
          </button>
          <button
            onClick={handleBuildEmbeddings}
            disabled={!schemaInference || embeddingStatus === 'running'}
          >
            {embeddingStatus === 'running' ? 'Embedding...' : 'Build Embeddings'}
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="grid">
          <div>
            <div className="label">Job ID</div>
            <div className="value">{jobId || '—'}</div>
          </div>
          <div>
            <div className="label">Job Status</div>
            <div className={`value badge badge-${status}`}>{status}</div>
          </div>
          <div>
            <div className="label">Task Status</div>
            <div className={`value badge badge-${taskStatus || 'none'}`}>
              {taskStatus || '—'}
            </div>
          </div>
          <div>
            <div className="label">Step</div>
            <div className="value">{step || '—'}</div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div className="label">Result</div>
          <button
            className="toggle"
            onClick={() => setResultExpanded((prev) => !prev)}
            disabled={!result}
          >
            {resultExpanded ? '−' : '+'}
          </button>
        </div>
        {resultExpanded ? (
          result ? (
            <JsonTree data={result as JsonValue} />
          ) : (
            <pre>—</pre>
          )
        ) : (
          <pre>{result ? '{...}' : '—'}</pre>
        )}
        {result && (result as { preview?: unknown }).preview && (
          <>
            <div className="panel-header">
              <div className="label">Preview</div>
              <button
                className="toggle"
                onClick={() => setPreviewExpanded((prev) => !prev)}
              >
                {previewExpanded ? '−' : '+'}
              </button>
            </div>
            {previewExpanded ? (
              <JsonTree data={(result as { preview?: JsonValue }).preview as JsonValue} />
            ) : (
              <pre>{'{...}'}</pre>
            )}
          </>
        )}
        {error && (
          <>
            <div className="label">Error</div>
            <pre className="error">{error}</pre>
          </>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div className="label">
            Schema Inference
            {selectedSchema && <span className="badge badge-selected">Selected</span>}
          </div>
          <button
            className="toggle"
            onClick={() => setAnalysisExpanded((prev) => !prev)}
            disabled={!analysis}
          >
            {analysisExpanded ? '−' : '+'}
          </button>
        </div>
        {analysisExpanded ? (
          schemaInference ? (
            <JsonTree data={schemaInference as JsonValue} />
          ) : (
            <pre>—</pre>
          )
        ) : (
          <pre>{schemaInference ? '{...}' : '—'}</pre>
        )}
        {selectedSchema && (
          <>
            <div className="panel-header">
              <div className="label">Selected Schema</div>
            </div>
            <JsonTree data={selectedSchema as JsonValue} />
          </>
        )}
        {inferenceError && (
          <>
            <div className="label">Inference Error</div>
            <pre className="error">{inferenceError}</pre>
          </>
        )}
        {embeddingError && (
          <>
            <div className="label">Embedding Error</div>
            <pre className="error">{embeddingError}</pre>
          </>
        )}
      </section>

      <section className="panel">
        <div className="label">Event Log</div>
        <ul>
          {events.map((entry, index) => (
            <li key={`${entry}-${index}`}>{entry}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}

export default App
