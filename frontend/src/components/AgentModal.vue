<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      @mousedown.self="$emit('close')"
    >
      <div class="w-full max-w-lg rounded-2xl border border-white/10 bg-gray-900 shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-gray-700 px-6 py-4">
          <h2 class="text-lg font-semibold text-white">Create Agent</h2>
          <button class="text-slate-400 transition hover:text-white" @click="$emit('close')">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>

        <!-- Form -->
        <form class="space-y-4 px-6 py-5" @submit.prevent="handleSubmit">
          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Name</label>
            <input
              v-model="form.name"
              type="text"
              required
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              placeholder="e.g. Research Assistant"
            />
          </div>

          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Description</label>
            <input
              v-model="form.description"
              type="text"
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              placeholder="An agent that researches and summarizes topics"
            />
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Model Provider</label>
              <select
                v-model="form.model_provider"
                @change="onProviderChange"
                class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              >
                <option
                  v-for="provider in providerOptions"
                  :key="provider"
                  :value="provider"
                >
                  {{ provider }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Target Model</label>
              <select
                v-model="form.target_model"
                class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              >
                <option
                  v-for="model in providerModels[selectedProvider]"
                  :key="model"
                  :value="model"
                >
                  {{ model }}
                </option>
              </select>
            </div>
          </div>

          <!-- Tool Selection -->
          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">
              Assign Tools
              <span class="ml-1 font-normal normal-case text-slate-500">(optional)</span>
            </label>
            <div class="max-h-44 overflow-y-auto rounded-lg border border-gray-700 bg-gray-800 p-3">
              <div v-if="mgmt.isLoadingTools" class="flex items-center justify-center py-4">
                <div class="h-4 w-4 animate-spin rounded-full border-2 border-cyan-300/30 border-t-cyan-300" />
              </div>
              <p v-else-if="!mgmt.tools.length" class="py-2 text-center text-xs text-slate-500">
                No tools registered yet.
              </p>
              <label
                v-for="tool in mgmt.tools"
                :key="tool.id"
                class="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2 transition hover:bg-white/5"
              >
                <input
                  type="checkbox"
                  :value="tool.id"
                  v-model="selectedToolIds"
                  class="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-gray-600 bg-gray-700 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                />
                <span class="min-w-0 flex-1">
                  <span class="block text-sm text-slate-200">{{ tool.name }}</span>
                  <span v-if="tool.description" class="block truncate text-xs text-slate-500">{{ tool.description }}</span>
                </span>
              </label>
            </div>
          </div>

          <!-- Toast notification -->
          <Transition enter-from-class="opacity-0 -translate-y-1" enter-active-class="transition duration-200" leave-to-class="opacity-0" leave-active-class="transition duration-150">
            <div
              v-if="toast"
              class="rounded-lg px-3 py-2.5 text-sm"
              :class="toast.type === 'success' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'"
            >
              {{ toast.message }}
            </div>
          </Transition>

          <!-- Actions -->
          <div class="flex items-center justify-end gap-3 border-t border-gray-700 pt-4">
            <button
              type="button"
              class="rounded-lg px-4 py-2 text-sm text-slate-400 transition hover:text-white"
              @click="$emit('close')"
            >
              Cancel
            </button>
            <button
              type="submit"
              :disabled="isSubmitting"
              class="rounded-lg bg-cyan-600 px-5 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {{ isSubmitting ? 'Creating…' : 'Create Agent' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { getDefaultTargetModel, providerModels, providerOptions } from '../constants/agentModels';
import type { Provider } from '../constants/agentModels';
import { useManagementStore } from '../stores/managementStore';
import { useSessionStore } from '../stores/sessionStore';

const emit = defineEmits<{ close: [] }>();
const mgmt = useManagementStore();
const sessionStore = useSessionStore();

const form = reactive({
  name: '',
  description: '',
  model_provider: 'google_genai' as Provider,
  target_model: getDefaultTargetModel('google_genai'),
});

const selectedToolIds = ref<string[]>([]);
const isSubmitting = ref(false);
const toast = ref<{ type: 'success' | 'error'; message: string } | null>(null);
const selectedProvider = computed(() => form.model_provider);

function onProviderChange() {
  form.target_model = getDefaultTargetModel(selectedProvider.value);
}

onMounted(() => {
  mgmt.fetchTools();
});

async function handleSubmit() {
  toast.value = null;
  isSubmitting.value = true;
  try {
    await mgmt.createAgent({
      name: form.name,
      description: form.description,
      model_provider: form.model_provider,
      target_model: form.target_model,
      tool_ids: selectedToolIds.value,
    });
    toast.value = { type: 'success', message: `Agent "${form.name}" created successfully.` };
    void sessionStore.fetchAgents();
    setTimeout(() => emit('close'), 1400);
  } catch (error) {
    toast.value = {
      type: 'error',
      message: error instanceof Error ? error.message : 'Creation failed.',
    };
  } finally {
    isSubmitting.value = false;
  }
}
</script>
