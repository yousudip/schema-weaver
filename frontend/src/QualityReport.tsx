/**
 * QualityReport — Task 5.2
 *
 * Displays the per-column data-quality report produced by the validation loop.
 * Shows fill rates, issues found, and validation attempt history.
 */
import { useState, useEffect } from 'react'
import type { ReactElement } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ColumnQuality {
  name: string
  source_name: string
  type: string
  present: boolean
  total_rows: number
  fill_count: number
  null_count: number
  fill_rate: number           // 0.0 – 1.0
  sample_values: string[]
  unique_count: number
  issues: string[]
}

export interface QualityReportData {
  total_rows: number
  total_columns: number
  overall_fill_rate: number   // 0.0 – 1.0
  pass: boolean
  columns: ColumnQuality[]
  read_error?: string
}

export interface ValidationAttempt {
  attempt: number
  run_ok: boolean
  verdict: 'pass' | 'pending' | 'crash' | 'no_output'
  fill_rate?: number
  code?: string
}

interface Props {
  report: QualityReportData
  attempts?: ValidationAttempt[]
  defaultCollapsed?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_ICONS: Record<string, string> = {
  string: '🔤', number: '🔢', date: '📅', boolean: '☑️', currency: '💰',
}

function fillColor(rate: number): string {
  if (rate >= 0.9) return '#16a34a'   // green
  if (rate >= 0.6) return '#d97706'   // amber
  return '#dc2626'                     // red
}

function fillBg(rate: number): string {
  if (rate >= 0.9) return '#dcfce7'
  if (rate >= 0.6) return '#fef3c7'
  return '#fee2e2'
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

// ─── Script viewer modal ──────────────────────────────────────────────────────

function ScriptModal({ attempt, code, onClose }: { attempt: number; code: string; onClose: () => void }): ReactElement {
  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleCopy = () => navigator.clipboard.writeText(code).catch(() => {})

  return (
    <div className="script-modal-overlay" onClick={onClose}>
      <div className="script-modal" onClick={e => e.stopPropagation()}>
        <div className="script-modal-header">
          <span className="script-modal-title">📄 Script — Attempt {attempt}</span>
          <div className="script-modal-actions">
            <button className="script-modal-btn" onClick={handleCopy} title="Copy to clipboard">⎘ Copy</button>
            <button className="script-modal-close" onClick={onClose} title="Close (Esc)">✕</button>
          </div>
        </div>
        <pre className="script-modal-code"><code>{code}</code></pre>
      </div>
    </div>
  )
}

// ─── Attempt badge ────────────────────────────────────────────────────────────

function AttemptBadge({ a, onViewScript }: { a: ValidationAttempt; onViewScript?: (a: ValidationAttempt) => void }): ReactElement {
  const icon = a.verdict === 'pass' ? '✅' : a.verdict === 'crash' ? '💥' : a.run_ok ? '🔄' : '❌'
  const label = a.verdict === 'pass' ? 'Passed' : a.verdict === 'crash' ? 'Crashed' : a.run_ok ? `${pct(a.fill_rate ?? 0)} fill` : 'No output'
  return (
    <span className="attempt-badge" data-verdict={a.verdict}>
      {icon} Attempt {a.attempt}: {label}
      {a.code && onViewScript && (
        <button
          className="attempt-view-script-btn"
          onClick={e => { e.stopPropagation(); onViewScript(a) }}
          title="View the Python script that ran for this attempt"
        >
          📄
        </button>
      )}
    </span>
  )
}

// ─── Main component ────────────────────────────────────────────────────────────

export function QualityReport({ report, attempts, defaultCollapsed = false }: Props): ReactElement {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const [scriptModal, setScriptModal] = useState<ValidationAttempt | null>(null)
  if (report.read_error) {

    return (
      <div className="quality-report quality-report-error">
        <span>⚠ Could not read output CSV: {report.read_error}</span>
      </div>
    )
  }

  const passedCols = report.columns.filter(c => c.fill_rate >= 0.9 && !c.issues.length).length
  const warnCols   = report.columns.filter(c => c.fill_rate >= 0.6 && c.fill_rate < 0.9).length
  const failCols   = report.columns.filter(c => c.fill_rate < 0.6 || !c.present).length

  return (
    <>
    {scriptModal && scriptModal.code && (
      <ScriptModal
        attempt={scriptModal.attempt}
        code={scriptModal.code}
        onClose={() => setScriptModal(null)}
      />
    )}
    <div className="quality-report">
      {/* ── Header ── */}
      <div className="quality-header" style={{ cursor: 'pointer' }} onClick={() => setCollapsed(v => !v)}>
        <div className="quality-title">
          <span className="quality-icon">{report.pass ? '✅' : '⚠️'}</span>
          <span>Data Quality Report</span>
          <span className={`quality-badge ${report.pass ? 'quality-badge-pass' : 'quality-badge-fail'}`}>
            {report.pass ? 'PASSED' : 'ISSUES FOUND'}
          </span>
          <span className="quality-collapse-toggle">{collapsed ? '▸ Show details' : '▾ Hide details'}</span>
        </div>

        {/* Summary pills */}
        <div className="quality-summary-pills">
          <span className="qpill qpill-rows">📊 {report.total_rows} rows</span>
          <span className="qpill qpill-cols">🗂 {report.total_columns} columns</span>
          <span className="qpill qpill-fill" style={{ background: fillBg(report.overall_fill_rate), color: fillColor(report.overall_fill_rate) }}>
            ⬤ {pct(report.overall_fill_rate)} overall fill
          </span>
          {passedCols > 0 && <span className="qpill qpill-pass">✓ {passedCols} clean</span>}
          {warnCols > 0   && <span className="qpill qpill-warn">⚠ {warnCols} partial</span>}
          {failCols > 0   && <span className="qpill qpill-fail">✕ {failCols} failed</span>}
        </div>

        {/* Validation attempt trail */}
        {attempts && attempts.length > 0 && (
          <div className="quality-attempts">
            <span className="quality-attempts-label">Validation loop:</span>
            {attempts.map(a => (
              <AttemptBadge key={a.attempt} a={a} onViewScript={setScriptModal} />
            ))}
          </div>
        )}
      </div>

      {/* ── Column table (collapsible) ── */}
      {!collapsed && <div className="quality-table-wrap">
        <table className="quality-table">
          <thead>
            <tr>
              <th>Column</th>
              <th>Type</th>
              <th>Fill rate</th>
              <th>Filled / Total</th>
              <th>Sample values</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            {report.columns.map(col => {
              const hasIssues = col.issues.length > 0 || !col.present
              return (
                <tr key={col.name} className={hasIssues ? 'quality-row-warn' : 'quality-row-ok'}>
                  <td className="quality-col-name">
                    <span className="quality-col-icon">{TYPE_ICONS[col.type] ?? '❓'}</span>
                    <span>{col.name}</span>
                    {col.source_name && col.source_name !== col.name && (
                      <span className="quality-col-source">← {col.source_name}</span>
                    )}
                  </td>
                  <td><span className="quality-type-badge">{col.type}</span></td>
                  <td>
                    <div className="quality-fill-bar-wrap">
                      <div
                        className="quality-fill-bar"
                        style={{
                          width: pct(col.fill_rate),
                          background: fillColor(col.fill_rate),
                        }}
                      />
                      <span className="quality-fill-pct" style={{ color: fillColor(col.fill_rate) }}>
                        {pct(col.fill_rate)}
                      </span>
                    </div>
                  </td>
                  <td className="quality-counts">
                    {col.present
                      ? <>{col.fill_count} / {col.total_rows}</>
                      : <span className="quality-missing">MISSING</span>}
                  </td>
                  <td className="quality-samples">
                    {col.sample_values.length > 0
                      ? col.sample_values.slice(0, 3).map((v, i) => (
                          <code key={i} className="quality-sample-val">{v}</code>
                        ))
                      : <span className="quality-empty-note">—</span>}
                  </td>
                  <td className="quality-issues">
                    {col.issues.length > 0
                      ? col.issues.map((iss, i) => (
                          <div key={i} className="quality-issue-item">⚠ {iss}</div>
                        ))
                      : <span className="quality-ok-note">✓ OK</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>}
    </div>
    </>
  )
}
