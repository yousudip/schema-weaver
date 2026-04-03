/**
 * SchemaMapper — Task 4.2
 *
 * Visual drag-and-drop schema mapping using @xyflow/react.
 *
 * Layout:
 *   Left panel  — Source columns from the uploaded file
 *   Right panel — AI-suggested canonical target fields
 *   Edges       — AI-suggested mappings (dotted = pending, solid = accepted)
 *
 * User interactions:
 *   • Click an edge  → toggle accepted / pending
 *   • Drag handle    → draw a new mapping edge
 *   • Click ✕ button → remove a mapping
 *   • "Accept All"   → solidify all suggestions
 */

import { useCallback, useEffect, useId, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useEdgesState,
  useNodesState,
  getBezierPath,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  MarkerType,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// ─── Types ─────────────────────────────────────────────────────────────────────

export interface ColumnInference {
  source_name: string
  inferred_type: string
  suggested_name: string
  description: string
  confidence: number
}

interface MapperProps {
  columns: ColumnInference[]
  onMappingsChange?: (mappings: MappingEntry[]) => void
}

export interface MappingEntry {
  source: string
  target: string
  confidence: number
  accepted: boolean
}

// ─── Node data shapes ──────────────────────────────────────────────────────────

interface SourceNodeData extends Record<string, unknown> {
  label: string
  type: string
}

interface TargetNodeData extends Record<string, unknown> {
  label: string
  type: string
  description: string
}

interface EdgeData extends Record<string, unknown> {
  confidence: number
  accepted: boolean
  onRemove: (id: string) => void
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  string:   '#7c3aed',
  number:   '#0284c7',
  date:     '#0891b2',
  boolean:  '#16a34a',
  currency: '#b45309',
}

const TYPE_ICONS: Record<string, string> = {
  string: '🔤', number: '🔢', date: '📅', boolean: '☑️', currency: '💰',
}

// ─── Custom node: Source column ────────────────────────────────────────────────

function SourceNode({ data }: NodeProps) {
  const d = data as SourceNodeData
  const color = TYPE_COLORS[d.type] ?? '#6b7280'
  const icon  = TYPE_ICONS[d.type]  ?? '❓'
  return (
    <div className="mapper-node mapper-node-source" style={{ borderColor: color }}>
      <div className="mapper-node-icon" style={{ background: color }}>{icon}</div>
      <div className="mapper-node-body">
        <div className="mapper-node-name">{d.label}</div>
        <div className="mapper-node-type" style={{ color }}>{d.type}</div>
      </div>
      <Handle type="source" position={Position.Right} className="mapper-handle" />
    </div>
  )
}

// ─── Custom node: Target field ─────────────────────────────────────────────────

function TargetNode({ data }: NodeProps) {
  const d = data as TargetNodeData
  const color = TYPE_COLORS[d.type] ?? '#6b7280'
  return (
    <div className="mapper-node mapper-node-target" style={{ borderColor: color }}>
      <Handle type="target" position={Position.Left} className="mapper-handle" />
      <div className="mapper-node-body">
        <div className="mapper-node-name">{d.label}</div>
        <div className="mapper-node-type" style={{ color }}>{d.description}</div>
      </div>
    </div>
  )
}

// ─── Custom edge ───────────────────────────────────────────────────────────────

function MappingEdge(props: EdgeProps) {
  const {
    id, sourceX, sourceY, targetX, targetY,
    sourcePosition, targetPosition, data, selected,
  } = props
  const d = data as EdgeData
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  })
  const pct        = Math.round((d?.confidence ?? 0) * 100)
  const isAccepted = Boolean(d?.accepted)

  const strokeColor = isAccepted ? '#16a34a' : '#6d28d9'
  const strokeWidth = isAccepted ? 2.5 : 1.5
  const strokeDash  = isAccepted ? undefined : '6 4'
  const labelBg     = isAccepted ? '#dcfce7' : '#ede9fe'
  const labelFg     = isAccepted ? '#15803d' : '#5b21b6'

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{ stroke: strokeColor, strokeWidth, strokeDasharray: strokeDash }}
        markerEnd={isAccepted ? MarkerType.ArrowClosed : undefined}
      />
      <EdgeLabelRenderer>
        <div
          className={`mapper-edge-label${selected ? ' mapper-edge-label-selected' : ''}`}
          style={{
            transform: `translate(-50%,-50%) translate(${labelX}px,${labelY}px)`,
            background: labelBg,
            color: labelFg,
          }}
        >
          <span className="mapper-edge-pct">{pct}%</span>
          {isAccepted && <span className="mapper-edge-check">✓</span>}
          <button
            className="mapper-edge-remove"
            onClick={(e) => { e.stopPropagation(); d?.onRemove(id) }}
          >✕</button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

// ─── Node / edge type maps ─────────────────────────────────────────────────────

const nodeTypes = { source: SourceNode, target: TargetNode }
const edgeTypes = { mapping: MappingEdge }

// ─── Main component ────────────────────────────────────────────────────────────

const NODE_HEIGHT = 72
const NODE_GAP    = 16
const SOURCE_X    = 60
const TARGET_X    = 540

export function SchemaMapper({ columns, onMappingsChange }: MapperProps) {
  const uid = useId()

  // ── Build initial nodes ──────────────────────────────────────────────────
  const initialNodes: Node[] = useMemo(() => {
    const src: Node[] = columns.map((col, i) => ({
      id:   `src-${col.source_name}`,
      type: 'source',
      position: { x: SOURCE_X, y: i * (NODE_HEIGHT + NODE_GAP) + 40 },
      data: { label: col.source_name, type: col.inferred_type } as SourceNodeData,
      draggable: true,
    }))

    const seen = new Set<string>()
    const tgt: Node[] = []
    columns.forEach((col, i) => {
      if (!seen.has(col.suggested_name)) {
        seen.add(col.suggested_name)
        tgt.push({
          id:   `tgt-${col.suggested_name}`,
          type: 'target',
          position: { x: TARGET_X, y: i * (NODE_HEIGHT + NODE_GAP) + 40 },
          data: {
            label: col.suggested_name,
            type: col.inferred_type,
            description: col.description,
          } as TargetNodeData,
          draggable: true,
        })
      }
    })
    return [...src, ...tgt]
  }, [columns])

  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // ── removeEdge (stable reference) ───────────────────────────────────────
  const removeEdge = useCallback((id: string) => {
    setEdges((es: Edge[]) => es.filter((e: Edge) => e.id !== id))
  }, [setEdges])

  // ── Initialize edges once on mount ───────────────────────────────────────
  useEffect(() => {
    const initial: Edge[] = columns.map(col => ({
      id:       `e-${col.source_name}-${col.suggested_name}`,
      source:   `src-${col.source_name}`,
      target:   `tgt-${col.suggested_name}`,
      type:     'mapping',
      animated: true,
      data:     { confidence: col.confidence, accepted: false, onRemove: removeEdge } as EdgeData,
    }))
    setEdges(initial)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid])

  // ── Toggle accepted on edge click ────────────────────────────────────────
  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setEdges((es: Edge[]) =>
      es.map((e: Edge) => {
        if (e.id !== edge.id) return e
        const wasAccepted = Boolean((e.data as EdgeData).accepted)
        return {
          ...e,
          animated: wasAccepted,
          data: { ...(e.data as EdgeData), accepted: !wasAccepted } as EdgeData,
        }
      })
    )
  }, [setEdges])

  // ── User draws a new edge ────────────────────────────────────────────────
  const onConnect = useCallback((connection: Connection) => {
    const newEdge: Edge = {
      id:       `e-${connection.source}-${connection.target}-${Date.now()}`,
      source:   connection.source ?? '',
      target:   connection.target ?? '',
      type:     'mapping',
      animated: false,
      data:     { confidence: 1.0, accepted: true, onRemove: removeEdge } as EdgeData,
    }
    setEdges((es: Edge[]) => addEdge(newEdge, es))
  }, [setEdges, removeEdge])

  // ── Accept all edges ─────────────────────────────────────────────────────
  const acceptAll = useCallback(() => {
    setEdges((es: Edge[]) =>
      es.map((e: Edge) => ({
        ...e,
        animated: false,
        data: { ...(e.data as EdgeData), accepted: true } as EdgeData,
      }))
    )
  }, [setEdges])

  // ── Notify parent ────────────────────────────────────────────────────────
  useEffect(() => {
    const mappings: MappingEntry[] = edges.map((e: Edge) => {
      const d = e.data as EdgeData
      return {
        source:     e.source.replace(/^src-/, ''),
        target:     e.target.replace(/^tgt-/, ''),
        confidence: d?.confidence ?? 0,
        accepted:   Boolean(d?.accepted),
      }
    })
    onMappingsChange?.(mappings)
  }, [edges, onMappingsChange])

  const acceptedCount = edges.filter((e: Edge) => Boolean((e.data as EdgeData).accepted)).length

  return (
    <div className="schema-mapper-wrap">
      {/* Toolbar */}
      <div className="mapper-toolbar">
        <div className="mapper-toolbar-left">
          <span className="mapper-stat">{edges.length} mappings</span>
          <span className="mapper-stat mapper-stat-accepted">{acceptedCount} accepted</span>
        </div>
        <div className="mapper-toolbar-right">
          <span className="mapper-hint">Click edge to accept · Drag handle to add · ✕ to remove</span>
          <button className="btn-accept-all" onClick={acceptAll}>✅ Accept All</button>
        </div>
      </div>

      {/* Column labels */}
      <div className="mapper-col-labels">
        <span style={{ marginLeft: SOURCE_X }}>Source (uploaded file)</span>
        <span style={{ marginLeft: 'auto', marginRight: 80 }}>Target (canonical schema)</span>
      </div>

      {/* React Flow canvas */}
      <div className="mapper-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onEdgeClick={onEdgeClick}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.4}
          defaultEdgeOptions={{ type: 'mapping' }}
          style={{ background: '#0f0a1e' }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#2d1d6e" gap={20} size={1} />
          <Controls />
          <MiniMap
            nodeColor={(n) => n.type === 'source' ? '#7c3aed' : '#0284c7'}
            maskColor="rgba(0,0,0,0.6)"
            style={{ background: '#1e1044' }}
          />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="mapper-legend">
        <span className="legend-item">
          <span className="legend-line legend-dotted" /> AI suggestion (pending)
        </span>
        <span className="legend-item">
          <span className="legend-line legend-solid" /> Accepted mapping
        </span>
      </div>
    </div>
  )
}
