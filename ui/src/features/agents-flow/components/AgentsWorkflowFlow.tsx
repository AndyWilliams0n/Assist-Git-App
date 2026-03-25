import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react'

import {
  Background,
  BackgroundVariant,
  type Connection,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeTypes,
  type NodeProps,
  Position,
  ReactFlow,
  type ReactFlowInstance,
  ReactFlowProvider,
  reconnectEdge,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { Chip } from '@/shared/components/chip'
import { useDashboardSettingsStore } from '@/shared/store/dashboard-settings'
import type { AgentStatus } from '@/shared/types/agents'

import { healthTone } from '@/features/agents-flow/utils'
import defaultLayout from './agents-flow-default-layout.json'

type WorkflowNodeTone = 'primary' | 'secondary' | 'accent' | 'pipeline' | 'graph' | 'error'

interface WorkflowNodeData extends Record<string, unknown> {
  title: string
  subtitle?: string
  description?: string
  agent?: AgentStatus
  tone?: WorkflowNodeTone
  bypassed?: boolean
  graphTag?: string
  isDark: boolean
}

type ThemeStyles = ReturnType<typeof getThemeStyles>
type SavedLayout = Record<string, { x: number; y: number }>

const WORKFLOW_LAYOUT_STORAGE_KEY = 'agents.workflow.layout.v8.langgraph-arch'
const NODE_SNAP_GRID: [number, number] = [24, 24]

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const toSavedLayout = (value: unknown): SavedLayout => {
  if (!isRecord(value)) {
    return {}
  }

  const normalized: SavedLayout = {}

  Object.entries(value).forEach(([id, position]) => {
    if (!isRecord(position)) {
      return
    }

    const x = Number(position.x)
    const y = Number(position.y)

    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return
    }

    normalized[id] = { x, y }
  })

  return normalized
}

const DEFAULT_LAYOUT = toSavedLayout(defaultLayout)

const loadSavedLayout = (storageKey: string): SavedLayout | null => {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const raw = window.localStorage.getItem(storageKey)

    if (!raw) {
      return null
    }

    const parsed = toSavedLayout(JSON.parse(raw))

    return Object.keys(parsed).length > 0 ? parsed : null
  } catch {
    return null
  }
}

const saveLayout = (storageKey: string, nodes: Node<WorkflowNodeData>[]) => {
  if (typeof window === 'undefined') {
    return
  }

  const payload: SavedLayout = {}

  nodes.forEach((node) => {
    payload[node.id] = { x: node.position.x, y: node.position.y }
  })

  window.localStorage.setItem(storageKey, JSON.stringify(payload))
}

const resolveInitialLayout = (storageKey: string): SavedLayout => {
  const savedLayout = loadSavedLayout(storageKey)

  return savedLayout ?? DEFAULT_LAYOUT
}

const applySavedLayout = (
  layout: SavedLayout,
  nodes: Node<WorkflowNodeData>[],
): Node<WorkflowNodeData>[] => {
  return nodes.map((node) => {
    const position = layout[node.id]

    if (!position) {
      return node
    }

    return { ...node, position: { x: position.x, y: position.y } }
  })
}

const hiddenHandleStyle: React.CSSProperties = {
  opacity: 0,
  width: 8,
  height: 8,
  border: 'none',
}

const WorkflowNode = ({ data }: NodeProps<Node<WorkflowNodeData>>) => {
  const health = data.agent ? healthTone(data.agent.health) : null
  const bypassed = Boolean(data.bypassed || data.agent?.bypassed)
  const active = Boolean(data.agent?.is_active) && !bypassed
  const styles = getThemeStyles(data.isDark)
  const healthColor =
    health?.label === 'healthy'
      ? 'success'
      : health?.label === 'degraded'
        ? 'warning'
        : health?.label === 'unconfigured'
          ? 'error'
          : 'grey'

  const graphTagColor =
    data.graphTag === 'ChatGraph'
      ? styles.primaryLine
      : data.graphTag === 'SpecGraph'
        ? styles.specLine
        : data.graphTag === 'TicketGraph'
          ? styles.successLine
          : styles.edgeDefault

  return (
    <div style={workflowNodeStyle(data.tone, data.isDark, bypassed)}>
      <Handle type='target' id='left' position={Position.Left} style={hiddenHandleStyle} />
      <Handle type='source' id='right' position={Position.Right} style={hiddenHandleStyle} />
      <Handle type='source' id='bottom-out' position={Position.Bottom} style={hiddenHandleStyle} />
      <Handle type='target' id='bottom-in' position={Position.Bottom} style={hiddenHandleStyle} />
      <Handle type='target' id='top' position={Position.Top} style={hiddenHandleStyle} />

      {data.graphTag ? (
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: graphTagColor }}>
          {data.graphTag.toUpperCase()}
        </div>
      ) : null}

      <div style={{ color: styles.textPrimary, fontSize: 15, fontWeight: 600 }}>
        {data.title}
      </div>

      {data.subtitle ? (
        <div style={{ color: styles.textSecondary, fontSize: 12 }}>{data.subtitle}</div>
      ) : null}

      {data.description ? (
        <div style={{ color: styles.textSecondary, fontSize: 12, lineHeight: 1.4 }}>
          {data.description}
        </div>
      ) : null}

      {data.agent ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
          <Chip color='grey' variant='outline'>
            {data.agent.role || 'agent'}
          </Chip>

          <Chip
            color={bypassed ? 'error' : active ? 'success' : 'grey'}
            variant={bypassed || active ? 'filled' : 'outline'}
          >
            {bypassed ? 'Bypassed' : active ? 'Active' : 'Idle'}
          </Chip>

          {bypassed ? (
            <Chip color='error' variant='outline'>
              Pass-through
            </Chip>
          ) : null}

          {health ? (
            <Chip color={healthColor} variant='outline'>
              {health.label}
            </Chip>
          ) : null}
        </div>
      ) : null}

      {data.agent?.provider ? (
        <div style={{ color: styles.textSecondary, fontSize: 12 }}>
          {data.agent.provider}
          {data.agent.model ? ` · ${data.agent.model}` : ''}
        </div>
      ) : null}
    </div>
  )
}

const DecisionNode = ({ data }: NodeProps<Node<WorkflowNodeData>>) => {
  const styles = getThemeStyles(data.isDark)

  return (
    <div style={decisionNodeWrapperStyle}>
      <Handle type='target' position={Position.Left} style={hiddenHandleStyle} />
      <Handle type='target' position={Position.Top} style={hiddenHandleStyle} />
      <Handle type='target' id='retry-in' position={Position.Bottom} style={hiddenHandleStyle} />
      <Handle type='source' position={Position.Right} id='pass' style={hiddenHandleStyle} />
      <Handle type='source' position={Position.Bottom} id='fail' style={hiddenHandleStyle} />
      <Handle type='source' id='retry-out' position={Position.Left} style={hiddenHandleStyle} />

      <div style={decisionDiamondStyle(styles)}>
        <div style={decisionLabelStyle(styles)}>{data.title}</div>
      </div>
    </div>
  )
}

const TerminalNode = ({ data }: NodeProps<Node<WorkflowNodeData>>) => {
  const styles = getThemeStyles(data.isDark)

  return (
    <div style={terminalNodeStyle(styles)}>
      <Handle type='target' position={Position.Left} style={hiddenHandleStyle} />
      <Handle type='source' position={Position.Right} style={hiddenHandleStyle} />
      <Handle type='target' position={Position.Top} style={hiddenHandleStyle} />
      <Handle type='source' position={Position.Bottom} style={hiddenHandleStyle} />

      <div style={{ color: styles.textPrimary, fontSize: 14, fontWeight: 600 }}>
        {data.title}
      </div>

      {data.subtitle ? (
        <div style={{ color: styles.textSecondary, fontSize: 12 }}>{data.subtitle}</div>
      ) : null}
    </div>
  )
}

const SectionHeaderNode = ({ data }: NodeProps<Node<WorkflowNodeData>>) => {
  const styles = getThemeStyles(data.isDark)
  const accentColor =
    data.tone === 'primary'
      ? styles.primaryLine
      : data.tone === 'graph'
        ? styles.specLine
        : styles.successLine

  return (
    <div style={sectionHeaderNodeStyle(styles, accentColor, data.isDark)}>
      <Handle type='target' position={Position.Left} style={hiddenHandleStyle} />
      <Handle type='source' position={Position.Right} style={hiddenHandleStyle} />

      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', color: accentColor }}>
        LANGGRAPH · STATEGRAPH
      </div>

      <div style={{ color: styles.textPrimary, fontSize: 17, fontWeight: 700 }}>
        {data.title}
      </div>

      {data.subtitle ? (
        <div style={{ color: styles.textSecondary, fontSize: 12, marginTop: 2 }}>
          {data.subtitle}
        </div>
      ) : null}
    </div>
  )
}

const nodeTypes: NodeTypes = {
  workflow: WorkflowNode,
  decision: DecisionNode,
  terminal: TerminalNode,
  sectionHeader: SectionHeaderNode,
}

const buildSharedNodes = (isDark: boolean): Node<WorkflowNodeData>[] => [
  {
    id: 'checkpointer',
    type: 'workflow',
    position: { x: 1200, y: -384 },
    data: {
      title: 'AsyncPostgresSaver',
      subtitle: 'Shared checkpointer · Supabase (DATABASE_URL)',
      description: 'Persists state at every node transition across all three graphs',
      tone: 'secondary',
      isDark,
    },
  },
]

const buildChatGraphNodes = (
  isDark: boolean,
  agent: (name: string) => AgentStatus | undefined,
  codeBuilderBypassed: boolean,
): Node<WorkflowNodeData>[] => [
  {
    id: 'chat-header',
    type: 'sectionHeader',
    position: { x: 0, y: -264 },
    data: {
      title: 'ChatGraph',
      subtitle: 'POST /api/orchestrator/submit · /api/orchestrator/chat · Slack inbound',
      tone: 'primary',
      isDark,
    },
  },
  {
    id: 'chat-start',
    type: 'terminal',
    position: { x: 48, y: 240 },
    data: { title: 'START', subtitle: 'asyncio.create_task(ainvoke)', isDark },
  },
  {
    id: 'chat-router',
    type: 'workflow',
    position: { x: 360, y: 216 },
    data: {
      title: 'router',
      subtitle: 'route_intent() · classifies intent from state',
      agent: agent('Orchestrator Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-chat',
    type: 'workflow',
    position: { x: 720, y: -240 },
    data: {
      title: 'chat',
      subtitle: '_run_general_workflow()',
      agent: agent('Orchestrator Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-research',
    type: 'workflow',
    position: { x: 720, y: -96 },
    data: {
      title: 'research',
      subtitle: 'asyncio.create_task() · background · SSE on complete',
      agent: agent('Research Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-sse-research',
    type: 'terminal',
    position: { x: 1080, y: -144 },
    data: {
      title: 'SSE Event',
      subtitle: 'research_complete · appended to conversation',
      isDark,
    },
  },
  {
    id: 'chat-node-jira',
    type: 'workflow',
    position: { x: 720, y: 48 },
    data: {
      title: 'jira',
      subtitle: '_run_jira_workflow() · ticket ops',
      agent: agent('Jira REST API Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-filesystem',
    type: 'workflow',
    position: { x: 720, y: 192 },
    data: {
      title: 'filesystem',
      subtitle: '_run_read_only_fs_workflow()',
      agent: agent('CLI Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-commands',
    type: 'workflow',
    position: { x: 720, y: 336 },
    data: {
      title: 'commands',
      subtitle: '_run_run_workflow() · CLI execution',
      agent: agent('CLI Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-slack',
    type: 'workflow',
    position: { x: 720, y: 480 },
    data: {
      title: 'slack',
      subtitle: '_run_slack_workflow() · post to channel',
      agent: agent('Slack Agent'),
      tone: 'primary',
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-node-build',
    type: 'workflow',
    position: { x: 720, y: 624 },
    data: {
      title: 'code_build',
      subtitle: '_run_codex_build_workflow() · Codex CLI impl',
      agent: agent('Code Builder Codex'),
      tone: 'pipeline',
      bypassed: codeBuilderBypassed,
      graphTag: 'ChatGraph',
      isDark,
    },
  },
  {
    id: 'chat-end',
    type: 'terminal',
    position: { x: 1080, y: 240 },
    data: { title: 'END', subtitle: 'state.result → assistant_reply', isDark },
  },
]

const buildSpecGraphNodes = (
  isDark: boolean,
  agent: (name: string) => AgentStatus | undefined,
): Node<WorkflowNodeData>[] => [
  {
    id: 'spec-header',
    type: 'sectionHeader',
    position: { x: 0, y: 888 },
    data: {
      title: 'AsyncSpecGraph',
      subtitle: 'POST /api/sdd/generate-async · DB-backed · BackgroundTasks · non-blocking',
      tone: 'graph',
      isDark,
    },
  },
  {
    id: 'spec-start',
    type: 'terminal',
    position: { x: 0, y: 1080 },
    data: { title: 'START', subtitle: 'POST /api/sdd/generate-async', isDark },
  },
  {
    id: 'spec-planner',
    type: 'workflow',
    position: { x: 336, y: 1080 },
    data: {
      title: 'planner_agent',
      subtitle: 'SDDPlannerAgent.process_prompt() · orchestrates generation',
      agent: agent('Planner Agent'),
      tone: 'graph',
      graphTag: 'SpecGraph',
      isDark,
    },
  },
  {
    id: 'spec-gen-req',
    type: 'workflow',
    position: { x: 720, y: 888 },
    data: {
      title: 'generate_requirements',
      subtitle: 'requirements.md · problem statement · constraints',
      agent: agent('SDD Spec Agent'),
      tone: 'graph',
      graphTag: 'SpecGraph',
      isDark,
    },
  },
  {
    id: 'spec-gen-design',
    type: 'workflow',
    position: { x: 720, y: 1080 },
    data: {
      title: 'generate_design',
      subtitle: 'design.md · architecture · component breakdown',
      agent: agent('SDD Spec Agent'),
      tone: 'graph',
      graphTag: 'SpecGraph',
      isDark,
    },
  },
  {
    id: 'spec-gen-tasks',
    type: 'workflow',
    position: { x: 720, y: 1272 },
    data: {
      title: 'generate_tasks',
      subtitle: 'tasks.md · implementation checklist',
      agent: agent('SDD Spec Agent'),
      tone: 'graph',
      graphTag: 'SpecGraph',
      isDark,
    },
  },
  {
    id: 'spec-save',
    type: 'workflow',
    position: { x: 1104, y: 1080 },
    data: {
      title: 'mark_spec_task_generated',
      subtitle: 'writes spec bundle · status=generated · DB update',
      tone: 'graph',
      graphTag: 'SpecGraph',
      isDark,
    },
  },
  {
    id: 'spec-end',
    type: 'terminal',
    position: { x: 1512, y: 1104 },
    data: { title: 'END', subtitle: 'status=generated · bundle ready', isDark },
  },
]

const buildTicketGraphNodes = (
  isDark: boolean,
  agent: (name: string) => AgentStatus | undefined,
  codeBuilderBypassed: boolean,
  codeReviewBypassed: boolean,
): Node<WorkflowNodeData>[] => [
  {
    id: 'ticket-header',
    type: 'sectionHeader',
    position: { x: 0, y: 1440 },
    data: {
      title: 'TicketPipelineGraph',
      subtitle: 'Dispatched by PipelineEngine · Semaphore(PIPELINE_MAX_CONCURRENT_TASKS)',
      tone: 'pipeline',
      isDark,
    },
  },
  {
    id: 'ticket-dispatch',
    type: 'terminal',
    position: { x: 48, y: 1656 },
    data: {
      title: 'PipelineEngine',
      subtitle: 'asyncio.create_task(ainvoke) · non-blocking dispatch',
      isDark,
    },
  },
  {
    id: 'ticket-fetch-context',
    type: 'workflow',
    position: { x: 360, y: 1656 },
    data: {
      title: 'fetch_context',
      subtitle: 'Jira parent + subtasks + attachments',
      agent: agent('Jira REST API Agent'),
      tone: 'pipeline',
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-sdd-spec',
    type: 'workflow',
    position: { x: 672, y: 1656 },
    data: {
      title: 'sdd_spec',
      subtitle: 'requirements.md · design.md · tasks.md',
      agent: agent('SDD Spec Agent'),
      tone: 'pipeline',
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-code-build',
    type: 'workflow',
    position: { x: 984, y: 1656 },
    data: {
      title: 'code_build',
      subtitle: 'Codex CLI autonomous implementation · sdd_bundle_path',
      agent: agent('Code Builder Codex'),
      tone: 'pipeline',
      bypassed: codeBuilderBypassed,
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-code-review',
    type: 'workflow',
    position: { x: 1296, y: 1656 },
    data: {
      title: 'code_review',
      subtitle: 'diff validation · review_passed boolean',
      agent: agent('Code Review Agent'),
      tone: 'pipeline',
      bypassed: codeReviewBypassed,
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-route-review',
    type: 'decision',
    position: { x: 1584, y: 1656 },
    data: {
      title: 'route_review',
      isDark,
    },
  },
  {
    id: 'ticket-git-handoff',
    type: 'workflow',
    position: { x: 1872, y: 1536 },
    data: {
      title: 'git_handoff',
      subtitle: 'branch description · push/PR · Git Content Agent',
      agent: agent('Git Content Agent'),
      tone: 'pipeline',
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-finalise-success',
    type: 'workflow',
    position: { x: 2160, y: 1536 },
    data: {
      title: 'finalise_success',
      subtitle: 'pipeline_runs → success · mark_agent_end()',
      tone: 'pipeline',
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-end-success',
    type: 'terminal',
    position: { x: 2448, y: 1536 },
    data: { title: 'END', subtitle: 'run complete', isDark },
  },
  {
    id: 'ticket-finalise-failed',
    type: 'workflow',
    position: { x: 1872, y: 1920 },
    data: {
      title: 'finalise_failed',
      subtitle: 'pipeline_runs → failed · max_retries exhausted',
      tone: 'error',
      graphTag: 'TicketGraph',
      isDark,
    },
  },
  {
    id: 'ticket-end-failed',
    type: 'terminal',
    position: { x: 2160, y: 1920 },
    data: { title: 'END', subtitle: 'run failed', isDark },
  },
]

const buildSharedEdges = (styles: ThemeStyles): Edge[] => [
  {
    id: 'checkpointer-chat',
    source: 'checkpointer',
    target: 'chat-start',
    type: 'bezier',
    label: 'checkpoint',
    style: { stroke: styles.edgeDefault, strokeDasharray: '4 4', strokeWidth: 1.4 },
  },
  {
    id: 'checkpointer-spec',
    source: 'checkpointer',
    target: 'spec-start',
    type: 'bezier',
    label: 'checkpoint',
    style: { stroke: styles.edgeDefault, strokeDasharray: '4 4', strokeWidth: 1.4 },
  },
  {
    id: 'checkpointer-ticket',
    source: 'checkpointer',
    target: 'ticket-dispatch',
    type: 'bezier',
    label: 'checkpoint',
    style: { stroke: styles.edgeDefault, strokeDasharray: '4 4', strokeWidth: 1.4 },
  },
]

const buildChatGraphEdges = (styles: ThemeStyles, codeBuilderBypassed: boolean): Edge[] => [
  {
    id: 'chat-start-router',
    source: 'chat-start',
    target: 'chat-router',
    type: 'smoothstep',
    label: 'ainvoke',
    style: { stroke: styles.primaryLine, strokeWidth: 2 },
  },
  {
    id: 'chat-router-chat',
    source: 'chat-router',
    target: 'chat-node-chat',
    type: 'smoothstep',
    label: 'chat',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-research',
    source: 'chat-router',
    target: 'chat-node-research',
    type: 'smoothstep',
    label: 'research_mcp',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-jira',
    source: 'chat-router',
    target: 'chat-node-jira',
    type: 'smoothstep',
    label: 'jira_api',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-filesystem',
    source: 'chat-router',
    target: 'chat-node-filesystem',
    type: 'smoothstep',
    label: 'read_only_fs',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-commands',
    source: 'chat-router',
    target: 'chat-node-commands',
    type: 'smoothstep',
    label: 'run_commands',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-slack',
    source: 'chat-router',
    target: 'chat-node-slack',
    type: 'smoothstep',
    label: 'slack_post',
    style: { stroke: styles.primaryLine, strokeWidth: 1.8 },
  },
  {
    id: 'chat-router-build',
    source: 'chat-router',
    target: 'chat-node-build',
    type: 'smoothstep',
    label: 'code_build',
    style: {
      stroke: codeBuilderBypassed ? styles.errorLine : styles.primaryLine,
      strokeWidth: 1.8,
      strokeDasharray: codeBuilderBypassed ? '6 4' : undefined,
    },
  },
  {
    id: 'chat-research-sse',
    source: 'chat-node-research',
    target: 'chat-sse-research',
    type: 'smoothstep',
    label: 'asyncio.create_task → SSE',
    style: { stroke: styles.primaryLine, strokeWidth: 1.4, strokeDasharray: '5 4' },
  },
  {
    id: 'chat-chat-end',
    source: 'chat-node-chat',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
  {
    id: 'chat-jira-end',
    source: 'chat-node-jira',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
  {
    id: 'chat-fs-end',
    source: 'chat-node-filesystem',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
  {
    id: 'chat-commands-end',
    source: 'chat-node-commands',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
  {
    id: 'chat-slack-end',
    source: 'chat-node-slack',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
  {
    id: 'chat-build-end',
    source: 'chat-node-build',
    target: 'chat-end',
    type: 'smoothstep',
    label: 'result',
  },
]

const buildSpecGraphEdges = (styles: ThemeStyles): Edge[] => [
  {
    id: 'spec-start-planner',
    source: 'spec-start',
    target: 'spec-planner',
    type: 'smoothstep',
    label: 'BackgroundTasks · non-blocking',
    style: { stroke: styles.specLine, strokeWidth: 2 },
  },
  {
    id: 'spec-planner-req',
    source: 'spec-planner',
    target: 'spec-gen-req',
    type: 'smoothstep',
    label: 'parallel',
    style: { stroke: styles.specLine, strokeWidth: 1.8 },
  },
  {
    id: 'spec-planner-design',
    source: 'spec-planner',
    target: 'spec-gen-design',
    type: 'smoothstep',
    label: 'parallel',
    style: { stroke: styles.specLine, strokeWidth: 1.8 },
  },
  {
    id: 'spec-planner-tasks',
    source: 'spec-planner',
    target: 'spec-gen-tasks',
    type: 'smoothstep',
    label: 'parallel',
    style: { stroke: styles.specLine, strokeWidth: 1.8 },
  },
  {
    id: 'spec-req-save',
    source: 'spec-gen-req',
    target: 'spec-save',
    type: 'smoothstep',
    label: 'result',
    style: { stroke: styles.specLine, strokeWidth: 1.6 },
  },
  {
    id: 'spec-design-save',
    source: 'spec-gen-design',
    target: 'spec-save',
    type: 'smoothstep',
    label: 'result',
    style: { stroke: styles.specLine, strokeWidth: 1.6 },
  },
  {
    id: 'spec-tasks-save',
    source: 'spec-gen-tasks',
    target: 'spec-save',
    type: 'smoothstep',
    label: 'result',
    style: { stroke: styles.specLine, strokeWidth: 1.6 },
  },
  {
    id: 'spec-save-end',
    source: 'spec-save',
    target: 'spec-end',
    type: 'smoothstep',
    label: 'status=generated',
    style: { stroke: styles.specLine, strokeWidth: 2 },
  },
]

const buildTicketGraphEdges = (
  styles: ThemeStyles,
  codeBuilderBypassed: boolean,
  codeReviewBypassed: boolean,
): Edge[] => [
  {
    id: 'ticket-dispatch-fetch',
    source: 'ticket-dispatch',
    target: 'ticket-fetch-context',
    type: 'smoothstep',
    label: 'ainvoke · semaphore acquired',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-fetch-sdd',
    source: 'ticket-fetch-context',
    target: 'ticket-sdd-spec',
    type: 'smoothstep',
    label: 'ticket context',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-sdd-build',
    source: 'ticket-sdd-spec',
    target: 'ticket-code-build',
    type: 'smoothstep',
    label: 'sdd_bundle_path',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-build-review',
    source: 'ticket-code-build',
    target: 'ticket-code-review',
    type: 'smoothstep',
    label: codeBuilderBypassed ? 'bypass' : 'build_result',
    style: {
      stroke: codeBuilderBypassed ? styles.errorLine : styles.successLine,
      strokeWidth: 2,
      strokeDasharray: codeBuilderBypassed ? '6 4' : undefined,
    },
  },
  {
    id: 'ticket-review-route',
    source: 'ticket-code-review',
    target: 'ticket-route-review',
    type: 'smoothstep',
    label: codeReviewBypassed ? 'bypass' : 'review_passed',
    style: {
      stroke: codeReviewBypassed ? styles.errorLine : styles.successLine,
      strokeWidth: 2,
      strokeDasharray: codeReviewBypassed ? '6 4' : undefined,
    },
  },
  {
    id: 'ticket-route-git',
    source: 'ticket-route-review',
    sourceHandle: 'pass',
    target: 'ticket-git-handoff',
    type: 'smoothstep',
    label: 'review_passed',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-route-retry',
    source: 'ticket-route-review',
    sourceHandle: 'retry-out',
    target: 'ticket-code-build',
    targetHandle: 'bottom-in',
    type: 'bezier',
    label: 'retry · attempt < max_retries',
    style: { stroke: styles.errorLine, strokeWidth: 2, strokeDasharray: '6 4' },
  },
  {
    id: 'ticket-route-failed',
    source: 'ticket-route-review',
    sourceHandle: 'fail',
    target: 'ticket-finalise-failed',
    type: 'smoothstep',
    label: 'exhausted',
    style: { stroke: styles.errorLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-git-success',
    source: 'ticket-git-handoff',
    target: 'ticket-finalise-success',
    type: 'smoothstep',
    label: 'push/PR ready',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-success-end',
    source: 'ticket-finalise-success',
    target: 'ticket-end-success',
    type: 'smoothstep',
    style: { stroke: styles.successLine, strokeWidth: 2 },
  },
  {
    id: 'ticket-failed-end',
    source: 'ticket-finalise-failed',
    target: 'ticket-end-failed',
    type: 'smoothstep',
    style: { stroke: styles.errorLine, strokeWidth: 2 },
  },
]

export type AgentsWorkflowFlowHandle = {
  exportFlow: () => string | null
}

type AgentsWorkflowFlowProps = {
  agents: AgentStatus[]
  wheelPanEnabled?: boolean
}

const AgentsWorkflowFlow = forwardRef<AgentsWorkflowFlowHandle, AgentsWorkflowFlowProps>(
  function AgentsWorkflowFlow({ agents, wheelPanEnabled = true }, ref) {
    const theme = useDashboardSettingsStore((state) => state.theme)
    const isDark = theme === 'dark'
    const reactFlowInstanceRef = useRef<ReactFlowInstance<Node<WorkflowNodeData>, Edge> | null>(
      null,
    )

    const { initialNodes, initialEdges } = useMemo(() => {
      const styles = getThemeStyles(isDark)
      const agentByName = new Map(agents.map((a) => [a.name.toLowerCase(), a]))
      const agent = (name: string) => agentByName.get(name.toLowerCase())

      const codeBuilderBypassed = Boolean(agent('Code Builder Codex')?.bypassed)
      const codeReviewBypassed = Boolean(agent('Code Review Agent')?.bypassed)

      const nodesBuilt: Node<WorkflowNodeData>[] = [
        ...buildSharedNodes(isDark),
        ...buildChatGraphNodes(isDark, agent, codeBuilderBypassed),
        ...buildSpecGraphNodes(isDark, agent),
        ...buildTicketGraphNodes(isDark, agent, codeBuilderBypassed, codeReviewBypassed),
      ]

      const edgesRaw: Edge[] = [
        ...buildSharedEdges(styles),
        ...buildChatGraphEdges(styles, codeBuilderBypassed),
        ...buildSpecGraphEdges(styles),
        ...buildTicketGraphEdges(styles, codeBuilderBypassed, codeReviewBypassed),
      ]

      const edgesBuilt = edgesRaw.map((edge) => ({
        ...edge,
        animated: true,
        reconnectable: true,
        labelStyle: { fontSize: 11, fontWeight: 500 },
        labelBgStyle: { fill: styles.surfaceMain, fillOpacity: 0.92 },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: String(edge.style?.stroke || styles.edgeDefault),
        },
      }))

      return {
        defaultNodes: nodesBuilt,
        initialNodes: applySavedLayout(resolveInitialLayout(WORKFLOW_LAYOUT_STORAGE_KEY), nodesBuilt),
        initialEdges: edgesBuilt,
      }
    }, [agents, isDark])

    const [nodes, setNodes, onNodesChange] = useNodesState<Node<WorkflowNodeData>>(initialNodes)
    const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

    useEffect(() => {
      setNodes(initialNodes)
      setEdges(initialEdges)
    }, [initialEdges, initialNodes, setEdges, setNodes])

    useEffect(() => {
      saveLayout(WORKFLOW_LAYOUT_STORAGE_KEY, nodes)
    }, [nodes])

    const onEdgeUpdate = useCallback(
      (oldEdge: Edge, newConnection: Connection) =>
        setEdges((currentEdges: Edge[]) => reconnectEdge(oldEdge, newConnection, currentEdges)),
      [setEdges],
    )

    const styles = getThemeStyles(isDark)

    useImperativeHandle(
      ref,
      () => ({
        exportFlow: () => {
          const flowState = reactFlowInstanceRef.current?.toObject()

          return flowState ? JSON.stringify(flowState, null, 2) : null
        },
      }),
      [],
    )

    return (
      <div className='h-full w-full' style={{ background: styles.canvasBackground }}>
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            colorMode={isDark ? 'dark' : 'light'}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onReconnect={onEdgeUpdate}
            nodesDraggable
            nodesConnectable={false}
            edgesFocusable
            edgesReconnectable
            elementsSelectable
            panOnScroll={wheelPanEnabled}
            zoomOnScroll={false}
            snapToGrid
            snapGrid={NODE_SNAP_GRID}
            onInit={(instance) => {
              reactFlowInstanceRef.current = instance
            }}
            fitView
            fitViewOptions={{ padding: 0.15, minZoom: 0.15, maxZoom: 1 }}
            proOptions={{ hideAttribution: true }}
            style={{ width: '100%', height: '100%' }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={24}
              size={1}
              color={styles.gridColor}
            />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
    )
  },
)

export default AgentsWorkflowFlow

const getThemeStyles = (isDark: boolean) => {
  if (isDark) {
    return {
      textPrimary: 'rgb(244 244 245)',
      textSecondary: 'rgb(161 161 170)',
      canvasBackground: 'oklch(0.145 0 0)',
      surfaceMain: 'rgba(39, 39, 42, 0.92)',
      surfaceSoft: 'rgba(39, 39, 42, 0.86)',
      borderSoft: 'rgba(255, 255, 255, 0.18)',
      primaryLine: 'rgba(125, 211, 252, 0.72)',
      specLine: 'rgba(192, 132, 252, 0.75)',
      edgeDefault: 'rgba(161, 161, 170, 0.52)',
      warningLine: 'rgba(251, 191, 36, 0.75)',
      errorLine: 'rgba(248, 113, 113, 0.78)',
      successLine: 'rgba(74, 222, 128, 0.82)',
      cardShadow: 'none',
      nodeBackground: 'rgba(24, 24, 27, 0.9)',
      gridColor: 'rgba(255, 255, 255, 0.16)',
    }
  }

  return {
    textPrimary: 'rgb(24 24 27)',
    textSecondary: 'rgb(82 82 91)',
    canvasBackground: 'oklch(1 0 0)',
    surfaceMain: 'rgba(255, 255, 255, 0.92)',
    surfaceSoft: 'rgba(255, 255, 255, 0.9)',
    borderSoft: 'rgba(39, 39, 42, 0.2)',
    primaryLine: 'rgba(3, 105, 161, 0.72)',
    specLine: 'rgba(124, 58, 237, 0.65)',
    edgeDefault: 'rgba(113, 113, 122, 0.45)',
    warningLine: 'rgba(202, 138, 4, 0.75)',
    errorLine: 'rgba(220, 38, 38, 0.72)',
    successLine: 'rgba(22, 163, 74, 0.75)',
    cardShadow: 'none',
    nodeBackground: 'rgba(255, 255, 255, 0.92)',
    gridColor: 'rgba(24, 24, 27, 0.13)',
  }
}

const workflowNodeStyle = (
  tone: WorkflowNodeTone | undefined,
  isDark: boolean,
  bypassed = false,
): React.CSSProperties => {
  const styles = getThemeStyles(isDark)

  const base: React.CSSProperties = {
    padding: 14,
    borderRadius: 14,
    minWidth: 220,
    maxWidth: 260,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    background: styles.nodeBackground,
    boxShadow: styles.cardShadow,
    border: `2px solid ${styles.borderSoft}`,
  }

  if (tone === 'accent') {
    if (bypassed) {
      return {
        ...base,
        border: `2px solid ${isDark ? 'rgba(248, 113, 113, 0.72)' : 'rgba(220, 38, 38, 0.62)'}`,
        background: isDark ? 'rgba(69, 10, 10, 0.45)' : 'rgba(254, 226, 226, 0.92)',
      }
    }

    return {
      ...base,
      border: `2px solid ${isDark ? 'rgba(125, 211, 252, 0.5)' : 'rgba(3, 105, 161, 0.35)'}`,
      background: isDark ? 'rgba(8, 47, 73, 0.48)' : 'rgba(224, 242, 254, 0.9)',
    }
  }

  if (tone === 'secondary') {
    return {
      ...base,
      border: `2px solid ${isDark ? 'rgba(251, 191, 36, 0.45)' : 'rgba(202, 138, 4, 0.35)'}`,
      background: isDark ? 'rgba(69, 26, 3, 0.38)' : 'rgba(254, 243, 199, 0.86)',
    }
  }

  if (tone === 'pipeline') {
    if (bypassed) {
      return {
        ...base,
        border: `2px solid ${isDark ? 'rgba(248, 113, 113, 0.72)' : 'rgba(220, 38, 38, 0.62)'}`,
        background: isDark ? 'rgba(69, 10, 10, 0.45)' : 'rgba(254, 226, 226, 0.92)',
      }
    }

    return {
      ...base,
      border: `2px solid ${isDark ? 'rgba(74, 222, 128, 0.52)' : 'rgba(22, 163, 74, 0.36)'}`,
      background: isDark ? 'rgba(5, 46, 22, 0.42)' : 'rgba(220, 252, 231, 0.85)',
    }
  }

  if (tone === 'graph') {
    return {
      ...base,
      border: `2px solid ${isDark ? 'rgba(192, 132, 252, 0.5)' : 'rgba(124, 58, 237, 0.35)'}`,
      background: isDark ? 'rgba(46, 16, 101, 0.4)' : 'rgba(237, 233, 254, 0.9)',
    }
  }

  if (tone === 'error') {
    return {
      ...base,
      border: `2px solid ${isDark ? 'rgba(248, 113, 113, 0.72)' : 'rgba(220, 38, 38, 0.62)'}`,
      background: isDark ? 'rgba(69, 10, 10, 0.45)' : 'rgba(254, 226, 226, 0.92)',
    }
  }

  return base
}

const decisionNodeWrapperStyle: React.CSSProperties = {
  width: 150,
  height: 150,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}

const decisionDiamondStyle = (styles: ThemeStyles): React.CSSProperties => ({
  width: 120,
  height: 120,
  borderRadius: 12,
  transform: 'rotate(45deg)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: styles.surfaceMain,
  border: `2px solid ${styles.successLine}`,
  boxShadow: styles.cardShadow,
})

const decisionLabelStyle = (styles: ThemeStyles): React.CSSProperties => ({
  transform: 'rotate(-45deg)',
  textAlign: 'center',
  maxWidth: 90,
  color: styles.textPrimary,
  fontSize: 11,
  fontWeight: 600,
})

const terminalNodeStyle = (styles: ThemeStyles): React.CSSProperties => ({
  padding: '10px 16px',
  borderRadius: 999,
  minWidth: 180,
  textAlign: 'center',
  background: styles.surfaceSoft,
  border: `2px solid ${styles.borderSoft}`,
  boxShadow: styles.cardShadow,
})

const sectionHeaderNodeStyle = (
  styles: ThemeStyles,
  accentColor: string,
  isDark: boolean,
): React.CSSProperties => ({
  padding: '10px 20px',
  borderRadius: 12,
  minWidth: 420,
  background: isDark ? 'rgba(24,24,27,0.96)' : 'rgba(255,255,255,0.97)',
  border: `2px solid ${accentColor}`,
  boxShadow: styles.cardShadow,
})
