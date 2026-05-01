import { fetchEventSource } from '@microsoft/fetch-event-source';
import { defineStore } from 'pinia';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';
const SESSION_LOAD_TIMEOUT_MS = 15000;
const STALE_STREAM_TIMEOUT_MS = 30000;

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  model_provider: string;
  target_model: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface ExecutionTrace {
  id: string;
  type: 'tool_call' | 'tool_result' | 'error' | 'status';
  label: string;
  payload: unknown;
  createdAt: string;
}

export interface SessionSummary {
  id: string;
  agent_id: string;
  status: string;
  start_time: string;
  end_time: string | null;
}

export interface SessionPaneData {
  messages: ChatMessage[];
  traces: ExecutionTrace[];
  isStreaming: boolean;
  agentId: string;
  agentName: string;
  status: string;
  lastStepSequence: number;
}

interface PersistedToolCall {
  id?: string;
  name?: string;
  arguments?: unknown;
}

interface PersistedToolResultMeta {
  name?: string;
  tool_call_id?: string;
}

interface ExecutionLogEntry {
  id: string;
  step_sequence: number;
  role: string;
  content: string | null;
  tool_calls: Record<string, unknown> | PersistedToolCall[] | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  created_at: string;
}

interface SessionLogsResponse {
  id: string;
  agent_id: string;
  status: string;
  start_time: string;
  end_time: string | null;
  execution_logs: ExecutionLogEntry[];
}

interface AgentListResponse {
  items: Agent[];
  count: number;
}

interface SessionCreateResponse {
  id: string;
  agent_id: string;
  status: string;
  start_time: string;
  end_time: string | null;
}

interface SessionRunAcceptedResponse {
  session_id: string;
  job_id: string;
  status: string;
  message: string;
  last_step_sequence: number | null;
}

interface SseEnvelope {
  event?: string;
  data?: unknown;
  step_sequence?: number;
}

function createId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'An unexpected error occurred.';
}

function parsePersistedToolResult(content: string | null): unknown {
  if (content == null) {
    return null;
  }

  try {
    return JSON.parse(content) as unknown;
  } catch {
    return content;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, unknown>;
}

function createSessionPaneData(): SessionPaneData {
  return {
    messages: [],
    traces: [],
    isStreaming: false,
    agentId: '',
    agentName: 'Unknown agent',
    status: 'active',
    lastStepSequence: 0,
  };
}

async function readResponseErrorMessage(response: Response): Promise<string | null> {
  const contentType = response.headers.get('content-type') ?? '';

  if (contentType.includes('application/json')) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    if (typeof payload?.detail === 'string' && payload.detail.trim()) {
      return payload.detail;
    }
  }

  const body = await response.text().catch(() => '');
  return body.trim() || null;
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    agents: [] as Agent[],
    activeSessionId: null as string | null,
    sessionData: {} as Record<string, SessionPaneData>,
    openTabs: [] as string[],
    streamControllers: {} as Record<string, AbortController | undefined>,
    sessionHistory: [] as SessionSummary[],
    isLoadingHistory: false,
    isLoadingSession: false,
  }),

  getters: {
    activeSessionData(state): SessionPaneData | null {
      if (!state.activeSessionId) {
        return null;
      }

      return state.sessionData[state.activeSessionId] ?? null;
    },

    activeMessages(): ChatMessage[] {
      return this.activeSessionData?.messages ?? [];
    },

    activeTraces(): ExecutionTrace[] {
      return this.activeSessionData?.traces ?? [];
    },

    activeIsStreaming(): boolean {
      return this.activeSessionData?.isStreaming ?? false;
    },
  },

  actions: {
    resolveAgentName(agentId: string, fallback = 'Unknown agent') {
      const agent = this.agents.find((item) => item.id === agentId);
      if (!agent) {
        return fallback;
      }

      return `${agent.name} · ${agent.target_model}`;
    },

    ensureSessionData(sessionId: string, overrides: Partial<SessionPaneData> = {}) {
      const existing = this.sessionData[sessionId];
      if (existing) {
        Object.assign(existing, overrides);
        return existing;
      }

      const pane = { ...createSessionPaneData(), ...overrides };
      this.sessionData[sessionId] = pane;
      return pane;
    },

    openTab(sessionId: string) {
      this.ensureSessionData(sessionId);
      if (!this.openTabs.includes(sessionId)) {
        this.openTabs.push(sessionId);
      }
      this.activeSessionId = sessionId;
    },

    switchTab(sessionId: string) {
      if (!this.openTabs.includes(sessionId)) {
        this.openTab(sessionId);
        return;
      }

      this.activeSessionId = sessionId;
    },

    stopSessionStream(sessionId: string) {
      const controller = this.streamControllers[sessionId];
      if (controller) {
        controller.abort();
        delete this.streamControllers[sessionId];
      }

      const pane = this.sessionData[sessionId];
      if (pane) {
        pane.isStreaming = false;
      }
    },

    closeTab(sessionId: string) {
      this.stopSessionStream(sessionId);

      this.openTabs = this.openTabs.filter((id) => id !== sessionId);
      delete this.sessionData[sessionId];

      if (this.activeSessionId === sessionId) {
        this.activeSessionId = this.openTabs.length > 0 ? this.openTabs[this.openTabs.length - 1] : null;
      }
    },

    upsertMessage(sessionId: string, message: ChatMessage) {
      const pane = this.ensureSessionData(sessionId);
      const existing = pane.messages.find((item) => item.id === message.id);

      if (existing) {
        existing.role = message.role;
        existing.content = message.content;
        return;
      }

      pane.messages.push(message);
    },

    ensureAssistantMessage(sessionId: string, messageId: string) {
      const pane = this.ensureSessionData(sessionId);
      const existing = pane.messages.find((item) => item.id === messageId);
      if (existing) {
        return existing;
      }

      const message = { id: messageId, role: 'assistant' as const, content: '' };
      pane.messages.push(message);
      return message;
    },

    appendAssistantChunk(sessionId: string, messageId: string, chunk: string) {
      const assistantMessage = this.ensureAssistantMessage(sessionId, messageId);
      assistantMessage.content += chunk;
    },

    pushTrace(
      sessionId: string,
      type: ExecutionTrace['type'],
      label: string,
      payload: unknown,
      traceId = createId(),
      createdAt = new Date().toISOString(),
    ) {
      const pane = this.ensureSessionData(sessionId);
      const existing = pane.traces.find((trace) => trace.id === traceId);

      if (existing) {
        existing.type = type;
        existing.label = label;
        existing.payload = payload;
        existing.createdAt = createdAt;
        return;
      }

      pane.traces.push({
        id: traceId,
        type,
        label,
        payload,
        createdAt,
      });
    },

    updateSessionHistory(sessionId: string, patch: Partial<SessionSummary>) {
      const existing = this.sessionHistory.find((session) => session.id === sessionId);
      if (existing) {
        Object.assign(existing, patch);
      }
    },

    hydrateSessionFromLogs(payload: SessionLogsResponse) {
      const pane = this.ensureSessionData(payload.id, {
        messages: [],
        traces: [],
        isStreaming: payload.status === 'running',
        agentId: payload.agent_id,
        agentName: this.resolveAgentName(payload.agent_id),
        status: payload.status,
        lastStepSequence: 0,
      });

      pane.messages = [];
      pane.traces = [];

      for (const log of payload.execution_logs) {
        pane.lastStepSequence = Math.max(pane.lastStepSequence, log.step_sequence);

        if (log.role === 'user') {
          pane.messages.push({
            id: log.id,
            role: 'user',
            content: log.content ?? '',
          });
          continue;
        }

        if (log.role === 'assistant') {
          if (log.content != null) {
            pane.messages.push({
              id: log.id,
              role: 'assistant',
              content: log.content,
            });
          }

          const toolCalls = Array.isArray(log.tool_calls) ? log.tool_calls : [];
          for (const toolCall of toolCalls) {
            this.pushTrace(
              payload.id,
              'tool_call',
              toolCall.name ?? 'tool.call',
              toolCall,
              toolCall.id ?? `${log.id}:tool-call`,
              log.created_at,
            );
          }

          continue;
        }

        if (log.role === 'tool') {
          const metadata = (!Array.isArray(log.tool_calls) ? log.tool_calls : null) as PersistedToolResultMeta | null;
          this.pushTrace(
            payload.id,
            'tool_result',
            metadata?.name ?? 'tool.result',
            {
              id: metadata?.tool_call_id,
              name: metadata?.name,
              result: parsePersistedToolResult(log.content),
            },
            log.id,
            log.created_at,
          );
          continue;
        }

        this.pushTrace(
          payload.id,
          'status',
          log.role,
          log.content ?? log.tool_calls,
          log.id,
          log.created_at,
        );
      }

      this.pushTrace(
        payload.id,
        'status',
        'history.loaded',
        {
          message: 'History loaded',
          sessionId: payload.id,
        },
      );

      return pane.lastStepSequence;
    },

    handleSessionEvent(sessionId: string, envelope: SseEnvelope) {
      const pane = this.ensureSessionData(sessionId);

      if (typeof envelope.step_sequence === 'number') {
        pane.lastStepSequence = Math.max(pane.lastStepSequence, envelope.step_sequence);
      }

      switch (envelope.event) {
        case 'user_message': {
          const payload = asRecord(envelope.data);
          this.upsertMessage(sessionId, {
            id: typeof payload?.id === 'string' ? payload.id : createId(),
            role: 'user',
            content: typeof payload?.content === 'string' ? payload.content : '',
          });
          break;
        }

        case 'assistant_message': {
          const payload = asRecord(envelope.data);
          this.upsertMessage(sessionId, {
            id: typeof payload?.id === 'string' ? payload.id : createId(),
            role: 'assistant',
            content: typeof payload?.content === 'string' ? payload.content : '',
          });
          break;
        }

        case 'token': {
          const payload = asRecord(envelope.data);
          const messageId = typeof payload?.id === 'string' ? payload.id : createId();
          this.appendAssistantChunk(sessionId, messageId, String(payload?.chunk ?? ''));
          break;
        }

        case 'tool_call': {
          const payload = asRecord(envelope.data);
          this.pushTrace(
            sessionId,
            'tool_call',
            typeof payload?.name === 'string' ? payload.name : 'tool.call',
            payload ?? envelope.data,
            typeof payload?.id === 'string'
              ? payload.id
              : (typeof payload?.log_id === 'string' ? payload.log_id : createId()),
            typeof payload?.created_at === 'string' ? payload.created_at : new Date().toISOString(),
          );
          break;
        }

        case 'tool_result': {
          const payload = asRecord(envelope.data);
          this.pushTrace(
            sessionId,
            'tool_result',
            typeof payload?.name === 'string' ? payload.name : 'tool.result',
            payload ?? envelope.data,
            typeof payload?.log_id === 'string' ? payload.log_id : createId(),
            typeof payload?.created_at === 'string' ? payload.created_at : new Date().toISOString(),
          );
          break;
        }

        case 'status': {
          const payload = asRecord(envelope.data);
          this.pushTrace(
            sessionId,
            'status',
            typeof payload?.role === 'string' ? payload.role : 'status',
            payload ?? envelope.data,
            typeof payload?.log_id === 'string' ? payload.log_id : createId(),
            typeof payload?.created_at === 'string' ? payload.created_at : new Date().toISOString(),
          );
          break;
        }

        case 'error': {
          const payload = asRecord(envelope.data);
          const message = typeof payload?.message === 'string'
            ? payload.message
            : String(envelope.data ?? 'The stream reported an unknown error.');
          this.pushTrace(
            sessionId,
            'error',
            'stream.error',
            payload ?? { message },
            typeof payload?.log_id === 'string' ? payload.log_id : createId(),
            typeof payload?.created_at === 'string' ? payload.created_at : new Date().toISOString(),
          );
          pane.status = 'failed';
          pane.isStreaming = false;
          this.updateSessionHistory(sessionId, {
            status: 'failed',
            end_time: new Date().toISOString(),
          });
          break;
        }

        case 'done': {
          const payload = asRecord(envelope.data);
          const statusValue = typeof payload?.status === 'string' ? payload.status : pane.status;
          pane.status = statusValue;
          pane.isStreaming = false;
          this.updateSessionHistory(sessionId, {
            status: statusValue,
            end_time: statusValue === 'running' ? null : new Date().toISOString(),
          });
          break;
        }

        default: {
          this.pushTrace(sessionId, 'status', envelope.event ?? 'stream.event', envelope.data ?? null);
        }
      }
    },

    async fetchSessions() {
      this.isLoadingHistory = true;
      try {
        const response = await fetch(`${API_BASE_URL}/sessions/`);
        if (!response.ok) {
          throw new Error(`Failed to load sessions (${response.status}).`);
        }
        this.sessionHistory = (await response.json()) as SessionSummary[];
      } catch (error) {
        if (this.activeSessionId) {
          this.pushTrace(this.activeSessionId, 'error', 'sessions.fetch_failed', { message: getErrorMessage(error) });
        }
      } finally {
        this.isLoadingHistory = false;
      }
    },

    async loadSession(sessionId: string) {
      this.isLoadingSession = true;
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), SESSION_LOAD_TIMEOUT_MS);

      try {
        const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/logs`, {
          signal: controller.signal,
        });
        if (!response.ok) {
          const detail = await readResponseErrorMessage(response);
          throw new Error(detail ?? `Failed to load session logs (${response.status}).`);
        }

        const payload = (await response.json()) as SessionLogsResponse;
        const lastStepSequence = this.hydrateSessionFromLogs(payload);
        this.openTab(payload.id);

        if (payload.status === 'running') {
          void this.subscribeToSession(payload.id, lastStepSequence);
        }

        return payload;
      } catch (error) {
        const isTimeout = error instanceof DOMException && error.name === 'AbortError';
        if (this.activeSessionId) {
          this.pushTrace(this.activeSessionId, 'error', 'session.load_failed', {
            sessionId,
            kind: isTimeout ? 'timeout' : 'request',
            message: isTimeout
              ? `Session history request timed out after ${SESSION_LOAD_TIMEOUT_MS / 1000}s.`
              : getErrorMessage(error),
          });
        }
      } finally {
        window.clearTimeout(timeoutId);
        this.isLoadingSession = false;
      }
    },

    clearSession() {
      if (!this.activeSessionId) {
        return;
      }

      this.closeTab(this.activeSessionId);
    },

    async fetchAgents() {
      try {
        const response = await fetch(`${API_BASE_URL}/agents`);
        if (!response.ok) {
          throw new Error(`Failed to load agents (${response.status}).`);
        }

        const payload = (await response.json()) as AgentListResponse;
        this.agents = payload.items;

        for (const [sessionId, pane] of Object.entries(this.sessionData)) {
          this.ensureSessionData(sessionId, {
            agentName: this.resolveAgentName(pane.agentId, pane.agentName),
          });
        }
      } catch (error) {
        if (this.activeSessionId) {
          this.pushTrace(this.activeSessionId, 'error', 'agents.fetch_failed', { message: getErrorMessage(error) });
        }
        throw error;
      }
    },

    async createSession(agentId: string) {
      if (!agentId) {
        throw new Error('Select an agent before creating a session.');
      }

      try {
        const response = await fetch(`${API_BASE_URL}/sessions/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ agent_id: agentId }),
        });

        if (!response.ok) {
          const errorPayload = (await response.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(errorPayload?.detail ?? `Failed to create session (${response.status}).`);
        }

        const payload = (await response.json()) as SessionCreateResponse;
        this.ensureSessionData(payload.id, {
          messages: [],
          traces: [],
          isStreaming: false,
          agentId: payload.agent_id,
          agentName: this.resolveAgentName(payload.agent_id),
          status: payload.status,
          lastStepSequence: 0,
        });
        this.openTab(payload.id);
        this.pushTrace(payload.id, 'status', 'session.created', {
          sessionId: payload.id,
          agentId: payload.agent_id,
        });

        const existing = this.sessionHistory.find((session) => session.id === payload.id);
        if (!existing) {
          this.sessionHistory.unshift(payload);
        }

        return payload;
      } catch (error) {
        if (this.activeSessionId) {
          this.pushTrace(this.activeSessionId, 'error', 'session.create_failed', { message: getErrorMessage(error) });
        }
        throw error;
      }
    },

    async subscribeToSession(sessionId: string, afterStep?: number) {
      const pane = this.ensureSessionData(sessionId);
      if (this.streamControllers[sessionId]) {
        return;
      }

      const streamController = new AbortController();
      const startAfterStep = afterStep ?? pane.lastStepSequence;
      let sawDoneEvent = false;
      this.streamControllers[sessionId] = streamController;
      pane.isStreaming = true;
      pane.status = 'running';
      this.updateSessionHistory(sessionId, { status: 'running', end_time: null });

      let staleTimer: ReturnType<typeof setTimeout> | null = null;

      const resetStaleTimer = () => {
        if (staleTimer !== null) {
          clearTimeout(staleTimer);
        }

        staleTimer = setTimeout(async () => {
          if (sawDoneEvent || streamController.signal.aborted) {
            return;
          }

          try {
            const res = await fetch(`${API_BASE_URL}/sessions/${sessionId}/logs`, {
              signal: streamController.signal,
            });

            if (!res.ok) {
              return;
            }

            const payload = (await res.json()) as SessionLogsResponse;

            if (payload.status === 'completed' || payload.status === 'failed') {
              sawDoneEvent = true;
              this.hydrateSessionFromLogs(payload);
              pane.isStreaming = false;
              pane.status = payload.status;
              this.updateSessionHistory(sessionId, {
                status: payload.status,
                end_time: payload.end_time ?? new Date().toISOString(),
              });
              streamController.abort();
            }
          } catch {
            // ignore – will retry on next timer tick or stream will resume
          }
        }, STALE_STREAM_TIMEOUT_MS);
      };

      try {
        await fetchEventSource(`${API_BASE_URL}/sessions/${sessionId}/subscribe?after_step=${startAfterStep}`, {
          method: 'GET',
          headers: {
            Accept: 'text/event-stream',
          },
          signal: streamController.signal,
          openWhenHidden: true,
          async onopen(response) {
            if (!response.ok) {
              const detail = await readResponseErrorMessage(response);
              throw new Error(detail ?? `Stream request failed (${response.status}).`);
            }

            const contentType = response.headers.get('content-type') ?? '';
            if (!contentType.includes('text/event-stream')) {
              throw new Error('Unexpected response type from the streaming endpoint.');
            }

            resetStaleTimer();
          },
          onmessage: (message) => {
            if (!message.data) {
              return;
            }

            resetStaleTimer();

            let payload: SseEnvelope;
            try {
              payload = JSON.parse(message.data) as SseEnvelope;
            } catch {
              this.pushTrace(sessionId, 'error', 'stream.invalid_payload', { raw: message.data });
              return;
            }

            this.handleSessionEvent(sessionId, payload);
            if (payload.event === 'done') {
              sawDoneEvent = true;
            }
          },
          onclose: () => {
            if (!sawDoneEvent && !streamController.signal.aborted) {
              throw new Error('The session event stream disconnected before completion.');
            }
          },
          onerror: (error) => {
            if (streamController.signal.aborted) {
              return;
            }

            throw error instanceof Error
              ? error
              : new Error('The session event stream disconnected unexpectedly.');
          },
        });
      } catch (error) {
        if (!streamController.signal.aborted) {
          pane.isStreaming = false;
          this.pushTrace(sessionId, 'error', 'stream.disconnected', { message: getErrorMessage(error) });
        }
      } finally {
        if (staleTimer !== null) {
          clearTimeout(staleTimer);
        }

        if (this.streamControllers[sessionId] === streamController) {
          delete this.streamControllers[sessionId];
        }

        if (!sawDoneEvent && !streamController.signal.aborted) {
          pane.isStreaming = false;
        }
      }
    },

    async runPrompt(prompt: string) {
      const trimmedPrompt = prompt.trim();
      if (!trimmedPrompt) {
        return;
      }

      if (!this.activeSessionId) {
        throw new Error('Create a session before running a prompt.');
      }

      const sessionId = this.activeSessionId;
      const pane = this.ensureSessionData(sessionId);
      if (pane.isStreaming) {
        return;
      }

      const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt: trimmedPrompt }),
      });

      if (!response.ok) {
        const detail = await readResponseErrorMessage(response);
        throw new Error(detail ?? `Failed to start session run (${response.status}).`);
      }

      const payload = (await response.json()) as SessionRunAcceptedResponse;
      pane.status = payload.status;
      pane.isStreaming = true;
      this.updateSessionHistory(sessionId, { status: payload.status, end_time: null });

      const replayAfterStep = payload.last_step_sequence == null
        ? pane.lastStepSequence
        : Math.max(payload.last_step_sequence - 1, 0);

      void this.subscribeToSession(sessionId, replayAfterStep);
    },
  },
});