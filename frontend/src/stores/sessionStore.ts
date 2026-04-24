import { fetchEventSource } from '@microsoft/fetch-event-source';
import { defineStore } from 'pinia';

const API_BASE_URL = 'http://localhost:8000/api/v1';
const SESSION_LOAD_TIMEOUT_MS = 15000;

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

interface SseEnvelope {
  event?: string;
  data?: unknown;
}

let activeStreamController: AbortController | null = null;

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
    chatMessages: [] as ChatMessage[],
    executionTraces: [] as ExecutionTrace[],
    isStreaming: false,
    sessionHistory: [] as SessionSummary[],
    isLoadingHistory: false,
    isLoadingSession: false,
  }),

  actions: {
    appendAssistantChunk(messageId: string, chunk: string) {
      const assistantMessage = this.chatMessages.find((message) => message.id === messageId);
      if (assistantMessage) {
        assistantMessage.content += chunk;
      }
    },

    pushTrace(type: ExecutionTrace['type'], label: string, payload: unknown) {
      this.executionTraces.push({
        id: createId(),
        type,
        label,
        payload,
        createdAt: new Date().toISOString(),
      });
    },

    removeEmptyAssistantMessage(messageId: string) {
      const messageIndex = this.chatMessages.findIndex((message) => message.id === messageId);
      if (messageIndex >= 0 && !this.chatMessages[messageIndex].content.trim()) {
        this.chatMessages.splice(messageIndex, 1);
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
        this.pushTrace('error', 'sessions.fetch_failed', { message: getErrorMessage(error) });
      } finally {
        this.isLoadingHistory = false;
      }
    },

    async loadSession(sessionId: string) {
      this.isLoadingSession = true;
      this.chatMessages = [];
      this.executionTraces = [];
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

        for (const log of payload.execution_logs) {
          if (log.role === 'user') {
            this.chatMessages.push({
              id: log.id,
              role: 'user',
              content: log.content ?? '',
            });
            continue;
          }

          if (log.role === 'assistant') {
            if (log.content != null) {
              this.chatMessages.push({
                id: log.id,
                role: 'assistant',
                content: log.content,
              });
            }

            const toolCalls = Array.isArray(log.tool_calls) ? log.tool_calls : [];
            for (const toolCall of toolCalls) {
              this.executionTraces.push({
                id: toolCall.id ?? createId(),
                type: 'tool_call',
                label: toolCall.name ?? 'tool.call',
                payload: toolCall,
                createdAt: log.created_at,
              });
            }

            continue;
          }

          if (log.role === 'tool') {
            const metadata = (!Array.isArray(log.tool_calls) ? log.tool_calls : null) as PersistedToolResultMeta | null;
            this.executionTraces.push({
              id: log.id,
              type: 'tool_result',
              label: metadata?.name ?? 'tool.result',
              payload: {
                id: metadata?.tool_call_id,
                name: metadata?.name,
                result: parsePersistedToolResult(log.content),
              },
              createdAt: log.created_at,
            });

            continue;
          }

          this.executionTraces.push({
            id: log.id,
            type: 'status',
            label: log.role,
            payload: log.content ?? log.tool_calls,
            createdAt: log.created_at,
          });
        }

        this.executionTraces.push({
          id: createId(),
          type: 'status',
          label: 'history.loaded',
          payload: {
            message: 'History loaded',
            sessionId: payload.id,
          },
          createdAt: new Date().toISOString(),
        });

        this.activeSessionId = payload.id;
        return payload;
      } catch (error) {
        const isTimeout = error instanceof DOMException && error.name === 'AbortError';
        this.pushTrace('error', 'session.load_failed', {
          sessionId,
          kind: isTimeout ? 'timeout' : 'request',
          message: isTimeout
            ? `Session history request timed out after ${SESSION_LOAD_TIMEOUT_MS / 1000}s.`
            : getErrorMessage(error),
        });
      } finally {
        window.clearTimeout(timeoutId);
        this.isLoadingSession = false;
      }
    },

    clearSession() {
      this.activeSessionId = null;
      this.chatMessages = [];
      this.executionTraces = [];
    },

    async fetchAgents() {
      try {
        const response = await fetch(`${API_BASE_URL}/agents`);
        if (!response.ok) {
          throw new Error(`Failed to load agents (${response.status}).`);
        }

        const payload = (await response.json()) as AgentListResponse;
        this.agents = payload.items;
      } catch (error) {
        this.pushTrace('error', 'agents.fetch_failed', { message: getErrorMessage(error) });
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
        this.activeSessionId = payload.id;
        this.chatMessages = [];
        this.executionTraces = [];
        this.pushTrace('status', 'session.created', {
          sessionId: payload.id,
          agentId: payload.agent_id,
        });
      } catch (error) {
        this.pushTrace('error', 'session.create_failed', { message: getErrorMessage(error) });
        throw error;
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

      if (this.isStreaming) {
        return;
      }

      if (activeStreamController) {
        activeStreamController.abort();
      }

      const assistantMessageId = createId();
      const streamController = new AbortController();
      let sawDoneEvent = false;
      let sawTokenEvent = false;
      activeStreamController = streamController;

      this.chatMessages.push({
        id: createId(),
        role: 'user',
        content: trimmedPrompt,
      });
      this.chatMessages.push({
        id: assistantMessageId,
        role: 'assistant',
        content: '',
      });
      this.pushTrace('status', 'stream.started', {
        sessionId: this.activeSessionId,
      });
      this.isStreaming = true;

      try {
        await fetchEventSource(`${API_BASE_URL}/sessions/${this.activeSessionId}/run`, {
          method: 'POST',
          headers: {
            Accept: 'text/event-stream',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ prompt: trimmedPrompt }),
          signal: streamController.signal,
          openWhenHidden: true,
          async onopen(response) {
            if (!response.ok) {
              const errorPayload = (await response.json().catch(() => null)) as { detail?: string } | null;
              throw new Error(errorPayload?.detail ?? `Stream request failed (${response.status}).`);
            }

            const contentType = response.headers.get('content-type') ?? '';
            if (!contentType.includes('text/event-stream')) {
              throw new Error('Unexpected response type from the streaming endpoint.');
            }
          },
          onmessage: (message) => {
            if (!message.data) {
              return;
            }

            let payload: SseEnvelope;
            try {
              payload = JSON.parse(message.data) as SseEnvelope;
            } catch {
              this.pushTrace('error', 'stream.invalid_payload', { raw: message.data });
              return;
            }

            switch (payload.event) {
              case 'token': {
                sawTokenEvent = true;
                this.appendAssistantChunk(assistantMessageId, String(payload.data ?? ''));
                break;
              }
              case 'tool_call': {
                const toolCall = payload.data as { id?: string; name?: string; arguments?: unknown } | undefined;
                this.pushTrace('tool_call', toolCall?.name ?? 'tool.call', toolCall ?? null);
                break;
              }
              case 'tool_result': {
                const toolResult = payload.data as { id?: string; name?: string; result?: unknown } | undefined;
                this.pushTrace('tool_result', toolResult?.name ?? 'tool.result', toolResult ?? null);
                break;
              }
              case 'error': {
                const messageText = String(payload.data ?? 'The stream reported an unknown error.');
                this.pushTrace('error', 'stream.error', { message: messageText });
                throw new Error(messageText);
              }
              case 'done': {
                sawDoneEvent = true;
                this.pushTrace('status', 'stream.completed', { sessionId: this.activeSessionId });
                break;
              }
              default: {
                this.pushTrace('status', payload.event ?? 'stream.event', payload.data ?? null);
              }
            }
          },
          onclose: () => {
            if (!sawDoneEvent) {
              throw new Error('The event stream disconnected before completion.');
            }
          },
          onerror: (error) => {
            throw error instanceof Error
              ? error
              : new Error('The event stream disconnected unexpectedly.');
          },
        });
      } catch (error) {
        const message = getErrorMessage(error);
        const abortedAfterCompletion = sawDoneEvent && error instanceof DOMException && error.name === 'AbortError';
        if (!abortedAfterCompletion) {
          this.pushTrace('error', 'stream.disconnected', { message });
        }

        if (!sawTokenEvent) {
          this.removeEmptyAssistantMessage(assistantMessageId);
        }

        if (!abortedAfterCompletion) {
          throw error;
        }
      } finally {
        this.isStreaming = false;
        if (!sawTokenEvent) {
          this.removeEmptyAssistantMessage(assistantMessageId);
        }

        if (activeStreamController === streamController) {
          activeStreamController = null;
        }
      }
    },
  },
});