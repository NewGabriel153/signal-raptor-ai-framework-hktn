<template>
  <main class="dark h-screen overflow-hidden bg-slate-950 text-slate-100">
    <div class="relative isolate flex h-full">
      <div class="pointer-events-none absolute inset-0 overflow-hidden">
        <div class="absolute left-[-8rem] top-[-6rem] h-72 w-72 rounded-full bg-cyan-400/18 blur-3xl" />
        <div class="absolute bottom-[-10rem] right-[-3rem] h-96 w-96 rounded-full bg-amber-400/14 blur-3xl" />
        <div class="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:64px_64px] opacity-20" />
      </div>

      <!-- Session History Sidebar -->
      <nav class="relative z-10 flex h-full w-64 shrink-0 flex-col border-r border-white/10 bg-slate-900/80 backdrop-blur-xl">
        <div class="border-b border-white/10 px-3 py-3 space-y-2">
          <button
            class="w-full rounded-xl border border-cyan-300/30 bg-cyan-300/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100 transition hover:border-cyan-200/60 hover:bg-cyan-300/20"
            @click="handleNewSession"
          >
            + New Session
          </button>
          <button
            class="w-full rounded-xl border border-amber-300/30 bg-amber-300/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.2em] text-amber-100 transition hover:border-amber-200/60 hover:bg-amber-300/20"
            @click="showAgentModal = true"
          >
            + New Agent
          </button>
          <button
            class="w-full rounded-xl border border-emerald-300/30 bg-emerald-300/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-100 transition hover:border-emerald-200/60 hover:bg-emerald-300/20"
            @click="showToolModal = true"
          >
            + Register Tool
          </button>
        </div>

        <div class="border-b border-white/10 px-4 py-5">
          <p class="text-[0.65rem] font-medium uppercase tracking-[0.4em] text-cyan-300/70">Observability</p>
          <h2 class="mt-1.5 text-sm font-semibold text-white">Session History</h2>
        </div>

        <div class="flex-1 overflow-y-auto px-2 py-2">
          <div v-if="isLoadingHistory" class="flex items-center justify-center py-8">
            <div class="h-5 w-5 animate-spin rounded-full border-2 border-cyan-300/30 border-t-cyan-300" />
          </div>

          <div v-else-if="!sessionHistory.length" class="px-2 py-6 text-center text-xs text-slate-500">
            No past sessions found.
          </div>

          <button
            v-for="session in sessionHistory"
            :key="session.id"
            class="mb-1 w-full rounded-xl px-3 py-2.5 text-left transition"
            :class="session.id === activeSessionId
              ? 'border border-cyan-300/30 bg-cyan-300/10 text-cyan-100'
              : 'border border-transparent text-slate-400 hover:border-white/10 hover:bg-white/5 hover:text-slate-200'"
            @click="handleLoadSession(session.id)"
          >
            <p class="truncate text-xs font-medium">{{ session.id.slice(0, 8) }}</p>
            <p class="mt-0.5 text-[0.65rem] text-slate-500">
              {{ formatSessionDate(session.start_time) }}
              <span class="ml-1 rounded-full px-1.5 py-0.5 text-[0.6rem]"
                :class="session.status === 'active' ? 'bg-emerald-400/15 text-emerald-300' : 'bg-white/5 text-slate-500'">
                {{ session.status }}
              </span>
            </p>
          </button>
        </div>
      </nav>

      <!-- Main Content -->
      <div class="relative flex h-full flex-1 flex-col overflow-hidden">
        <div v-if="isLoadingSession" class="absolute inset-0 z-20 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm">
          <div class="flex flex-col items-center gap-3">
            <div class="h-8 w-8 animate-spin rounded-full border-2 border-cyan-300/30 border-t-cyan-300" />
            <p class="text-xs uppercase tracking-[0.3em] text-slate-400">Loading session…</p>
          </div>
        </div>

      <section class="relative mx-auto flex h-full w-full max-w-7xl flex-col overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
        <header class="mb-6 flex flex-col gap-4 rounded-[2rem] border border-white/10 bg-white/5 px-5 py-5 shadow-panel backdrop-blur-xl lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p class="text-xs font-medium uppercase tracking-[0.45em] text-cyan-300/80">Signal Raptor</p>
            <h1 class="mt-2 text-3xl font-semibold tracking-tight text-white">Control Plane Dashboard</h1>
            <p class="mt-2 max-w-2xl text-sm text-slate-300">
              Stream agent responses and inspect every tool invocation in real time.
            </p>
          </div>

          <div class="grid gap-3 sm:grid-cols-[minmax(0,17rem)_auto]">
            <label class="rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-slate-300 shadow-lg shadow-cyan-950/20">
              <span class="mb-2 block text-xs uppercase tracking-[0.3em] text-slate-500">Agent</span>
              <select
                v-model="selectedAgentId"
                class="w-full bg-transparent text-sm font-medium text-white outline-none"
              >
                <option disabled value="">Select an agent</option>
                <option v-for="agent in agents" :key="agent.id" :value="agent.id">
                  {{ agent.name }} · {{ agent.target_model }}
                </option>
              </select>
            </label>

            <button
              class="rounded-2xl border border-cyan-300/30 bg-cyan-300/10 px-5 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-200/60 hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!selectedAgentId || isStreaming"
              @click="handleCreateSession"
            >
              {{ activeSessionId ? 'Reset Session' : 'New Session' }}
            </button>
          </div>
        </header>

        <div class="mb-4 flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.28em] text-slate-400">
          <span class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
            Session {{ sessionLabel }}
          </span>
          <span
            class="rounded-full border px-3 py-1.5 inline-flex items-center gap-1.5"
            :class="isStreaming ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200' : 'border-white/10 bg-white/5 text-slate-300'"
          >
            <template v-if="isStreaming">
              Streaming
              <span class="streaming-dots"><span></span><span></span><span></span></span>
            </template>
            <template v-else>Idle</template>
          </span>
          <span class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
            {{ executionTraces.length }} trace events
          </span>
        </div>

        <div class="grid min-h-0 flex-1 gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(22rem,0.9fr)]">
          <section class="flex min-h-0 flex-col overflow-hidden rounded-[2rem] border border-white/10 bg-slate-900/75 shadow-panel backdrop-blur-xl">
            <div class="border-b border-white/10 px-5 py-4">
              <h2 class="text-lg font-semibold text-white">Operator Console</h2>
              <p class="mt-1 text-sm text-slate-400">Send prompts and watch the assistant stream its final response.</p>
            </div>

            <div ref="chatContainerRef" class="flex-1 space-y-4 overflow-y-auto px-5 py-5">
              <div
                v-if="!chatMessages.length"
                class="flex h-full min-h-[20rem] items-center justify-center rounded-[1.5rem] border border-dashed border-white/10 bg-slate-950/50 px-8 text-center text-sm text-slate-500"
              >
                Create a session, submit a prompt, and the streamed assistant response will appear here.
              </div>

              <article
                v-for="message in chatMessages"
                :key="message.id"
                class="flex"
                :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  class="max-w-[85%] rounded-[1.6rem] px-4 py-3 shadow-lg"
                  :class="message.role === 'user'
                    ? 'border border-cyan-300/20 bg-cyan-300/12 text-cyan-50'
                    : 'border border-white/10 bg-slate-950/80 text-slate-100'"
                >
                  <p class="mb-2 text-[0.68rem] uppercase tracking-[0.28em] text-slate-400">
                    {{ message.role === 'user' ? 'Operator' : 'Assistant' }}
                  </p>
                  <!-- User messages: plain text. Assistant messages: sanitized markdown -->
                  <p v-if="message.role === 'user'" class="whitespace-pre-wrap text-sm leading-7">{{ message.content }}</p>
                  <div
                    v-else-if="message.content"
                    class="prose-chat"
                    v-html="renderMarkdown(message.content)"
                  />
                  <p v-else-if="isStreaming" class="text-sm leading-7 text-slate-400 inline-flex items-center gap-1">
                    Streaming response
                    <span class="streaming-dots"><span></span><span></span><span></span></span>
                  </p>
                </div>
              </article>
              <div ref="chatBottomRef" />
            </div>

            <form class="border-t border-white/10 bg-slate-950/80 px-4 py-4" @submit.prevent="handleSubmitPrompt">
              <div class="rounded-[1.5rem] border border-white/10 bg-slate-900/90 p-2 shadow-xl shadow-slate-950/30">
                <textarea
                  v-model="promptDraft"
                  rows="3"
                  class="w-full resize-none bg-transparent px-3 py-3 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500"
                  placeholder="Ask the agent to inspect a ticket, generate a plan, or invoke a tool..."
                  :disabled="isStreaming"
                  @keydown="handleTextareaKeydown"
                />
                <div class="flex flex-col gap-3 border-t border-white/10 px-3 pb-2 pt-3 sm:flex-row sm:items-center sm:justify-between">
                  <p v-if="formError" class="text-sm text-rose-300">{{ formError }}</p>
                  <p v-else class="text-xs uppercase tracking-[0.28em] text-slate-500">
                    {{ selectedAgentName }}
                    <span class="ml-1 text-slate-600 normal-case tracking-normal">· Enter to send</span>
                  </p>
                  <button
                    type="submit"
                    class="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    :disabled="!promptDraft.trim() || isStreaming"
                  >
                    <template v-if="isStreaming">
                      Streaming
                      <span class="streaming-dots ml-0.5 text-slate-400"><span></span><span></span><span></span></span>
                    </template>
                    <template v-else>Send Prompt</template>
                  </button>
                </div>
              </div>
            </form>
          </section>

          <aside class="flex min-h-0 flex-col overflow-hidden rounded-[2rem] border border-cyan-200/10 bg-[#020816]/90 shadow-panel backdrop-blur-xl">
            <div class="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <h2 class="text-lg font-semibold text-white">Execution Trace</h2>
                <p class="mt-1 text-sm text-slate-400">Live SSE events, tool calls, and serialized tool outputs.</p>
              </div>
              <div class="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[0.68rem] uppercase tracking-[0.28em] text-slate-400">
                terminal
              </div>
            </div>

            <div ref="traceContainerRef" class="flex-1 overflow-y-auto px-4 py-4 font-mono text-sm">
              <div class="space-y-3">
                <div
                  v-if="!executionTraces.length"
                  class="rounded-[1.35rem] border border-dashed border-white/10 bg-slate-950/60 px-4 py-6 text-slate-500"
                >
                  Waiting for the first trace event.
                </div>

                <article
                  v-for="trace in executionTraces"
                  :key="trace.id"
                  class="rounded-[1.35rem] border px-4 py-3"
                  :class="traceToneClass(trace.type)"
                >
                  <div class="mb-3 flex items-center justify-between gap-4 text-[0.68rem] uppercase tracking-[0.3em]">
                    <span>{{ trace.type.replace('_', ' ') }}</span>
                    <span class="text-slate-500">{{ formatTimestamp(trace.createdAt) }}</span>
                  </div>
                  <p class="mb-3 text-sm font-medium tracking-[0.08em] text-white/90">{{ trace.label }}</p>
                  <pre class="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6 text-slate-200">{{ formatPayload(trace.payload) }}</pre>
                </article>
              </div>
              <div ref="traceBottomRef" />
            </div>
          </aside>
        </div>
      </section>
      </div>
    </div>

    <AgentModal v-if="showAgentModal" @close="showAgentModal = false" />
    <ToolModal v-if="showToolModal" @close="showToolModal = false" />
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

import AgentModal from '../components/AgentModal.vue';
import ToolModal from '../components/ToolModal.vue';
import { useSessionStore, type ExecutionTrace, type SessionSummary } from '../stores/sessionStore';

// Enable GitHub-flavoured markdown and auto line-break conversion
marked.setOptions({ breaks: true, gfm: true });

function renderMarkdown(content: string): string {
  const raw = marked.parse(content, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

const sessionStore = useSessionStore();
const { activeSessionId, agents, chatMessages, executionTraces, isStreaming, sessionHistory, isLoadingHistory, isLoadingSession } = storeToRefs(sessionStore);

const showAgentModal = ref(false);
const showToolModal = ref(false);
const promptDraft = ref('');
const formError = ref('');
const selectedAgentId = ref('');
const chatContainerRef = ref<HTMLElement | null>(null);
const chatBottomRef = ref<HTMLElement | null>(null);
const traceContainerRef = ref<HTMLElement | null>(null);
const traceBottomRef = ref<HTMLElement | null>(null);

const selectedAgentName = computed(() => {
  const selectedAgent = agents.value.find((agent) => agent.id === selectedAgentId.value);
  if (!selectedAgent) {
    return 'No agent selected';
  }

  return `${selectedAgent.name} · ${selectedAgent.target_model}`;
});

const sessionLabel = computed(() => {
  if (!activeSessionId.value) {
    return 'not started';
  }

  return activeSessionId.value.slice(0, 8);
});

function scrollChatToBottom() {
  chatBottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function scrollTraceToBottom() {
  traceBottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function formatPayload(payload: unknown): string {
  if (payload == null) {
    return 'null';
  }

  if (typeof payload === 'string') {
    return payload;
  }

  return JSON.stringify(payload, null, 2);
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatSessionDate(value: string): string {
  const d = new Date(value);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function traceToneClass(type: ExecutionTrace['type']): string {
  switch (type) {
    case 'tool_call':
      return 'border-cyan-300/20 bg-cyan-400/8 text-cyan-100';
    case 'tool_result':
      return 'border-emerald-300/20 bg-emerald-400/8 text-emerald-100';
    case 'error':
      return 'border-rose-300/20 bg-rose-400/8 text-rose-100';
    default:
      return 'border-white/10 bg-white/5 text-slate-200';
  }
}

function handleTextareaKeydown(event: KeyboardEvent) {
  // Enter alone submits; Shift+Enter inserts a newline as expected
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    handleSubmitPrompt();
  }
}

function handleNewSession() {
  sessionStore.clearSession();
  promptDraft.value = '';
  formError.value = '';
}

async function handleLoadSession(sessionId: string) {
  formError.value = '';
  const payload = await sessionStore.loadSession(sessionId);
  if (payload) {
    selectedAgentId.value = payload.agent_id;
  }
}

async function handleCreateSession() {
  formError.value = '';

  try {
    await sessionStore.createSession(selectedAgentId.value);
    promptDraft.value = '';
  } catch (error) {
    formError.value = error instanceof Error ? error.message : 'Unable to create a session.';
  }
}

async function handleSubmitPrompt() {
  const trimmedPrompt = promptDraft.value.trim();
  if (!trimmedPrompt) {
    return;
  }

  formError.value = '';

  try {
    if (!activeSessionId.value) {
      await sessionStore.createSession(selectedAgentId.value);
    }

    await sessionStore.runPrompt(trimmedPrompt);
    promptDraft.value = '';
  } catch (error) {
    formError.value = error instanceof Error ? error.message : 'Unable to run the prompt.';
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      sessionStore.fetchAgents(),
      sessionStore.fetchSessions(),
    ]);
    if (agents.value.length > 0) {
      selectedAgentId.value = agents.value[0].id;
    }
  } catch (error) {
    formError.value = error instanceof Error ? error.message : 'Unable to load initial data.';
  }
});

watch(
  () => chatMessages.value,
  async () => {
    await nextTick();
    scrollChatToBottom();
  },
  { deep: true },
);

watch(
  () => executionTraces.value,
  async () => {
    await nextTick();
    scrollTraceToBottom();
  },
  { deep: true },
);
</script>