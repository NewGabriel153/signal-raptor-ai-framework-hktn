<template>
  <main class="dark min-h-screen overflow-hidden bg-slate-950 text-slate-100">
    <div class="relative isolate min-h-screen">
      <div class="pointer-events-none absolute inset-0 overflow-hidden">
        <div class="absolute left-[-8rem] top-[-6rem] h-72 w-72 rounded-full bg-cyan-400/18 blur-3xl" />
        <div class="absolute bottom-[-10rem] right-[-3rem] h-96 w-96 rounded-full bg-amber-400/14 blur-3xl" />
        <div class="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:64px_64px] opacity-20" />
      </div>

      <section class="relative mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-6 sm:px-6 lg:px-8">
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
            class="rounded-full border px-3 py-1.5"
            :class="isStreaming ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200' : 'border-white/10 bg-white/5 text-slate-300'"
          >
            {{ isStreaming ? 'Streaming' : 'Idle' }}
          </span>
          <span class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
            {{ executionTraces.length }} trace events
          </span>
        </div>

        <div class="grid flex-1 gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(22rem,0.9fr)]">
          <section class="flex min-h-[32rem] flex-col rounded-[2rem] border border-white/10 bg-slate-900/75 shadow-panel backdrop-blur-xl">
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
                  <p class="whitespace-pre-wrap text-sm leading-7">{{ message.content || (isStreaming ? 'Streaming response…' : '') }}</p>
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
                />
                <div class="flex flex-col gap-3 border-t border-white/10 px-3 pb-2 pt-3 sm:flex-row sm:items-center sm:justify-between">
                  <p v-if="formError" class="text-sm text-rose-300">{{ formError }}</p>
                  <p v-else class="text-xs uppercase tracking-[0.28em] text-slate-500">
                    {{ selectedAgentName }}
                  </p>
                  <button
                    type="submit"
                    class="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                    :disabled="!promptDraft.trim() || isStreaming"
                  >
                    {{ isStreaming ? 'Streaming…' : 'Send Prompt' }}
                  </button>
                </div>
              </div>
            </form>
          </section>

          <aside class="flex min-h-[32rem] flex-col overflow-hidden rounded-[2rem] border border-cyan-200/10 bg-[#020816]/90 shadow-panel backdrop-blur-xl">
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
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';

import { useSessionStore, type ExecutionTrace } from '../stores/sessionStore';

const sessionStore = useSessionStore();
const { activeSessionId, agents, chatMessages, executionTraces, isStreaming } = storeToRefs(sessionStore);

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
    await sessionStore.fetchAgents();
    if (agents.value.length > 0) {
      selectedAgentId.value = agents.value[0].id;
    }
  } catch (error) {
    formError.value = error instanceof Error ? error.message : 'Unable to load agents.';
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