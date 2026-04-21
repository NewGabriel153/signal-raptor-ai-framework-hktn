<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      @mousedown.self="$emit('close')"
    >
      <div class="w-full max-w-lg rounded-2xl border border-white/10 bg-gray-900 shadow-2xl">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-gray-700 px-6 py-4">
          <h2 class="text-lg font-semibold text-white">Register Tool</h2>
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
              placeholder="e.g. calculator_add"
            />
          </div>

          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Description</label>
            <input
              v-model="form.description"
              type="text"
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              placeholder="Adds two numbers together"
            />
          </div>

          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">Python Function Name</label>
            <input
              v-model="form.python_function_name"
              type="text"
              required
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm font-mono text-white outline-none placeholder:text-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              placeholder="calculator_add"
            />
          </div>

          <div>
            <label class="mb-1.5 block text-xs font-medium uppercase tracking-widest text-slate-400">
              JSON Schema
              <span class="ml-1 font-normal normal-case text-slate-500">(OpenAPI format)</span>
            </label>
            <textarea
              v-model="form.json_schema_raw"
              rows="6"
              required
              class="w-full rounded-lg border bg-gray-800 px-3 py-2.5 font-mono text-xs leading-5 text-white outline-none placeholder:text-slate-500 focus:ring-1"
              :class="schemaError
                ? 'border-rose-500 focus:border-rose-500 focus:ring-rose-500'
                : 'border-gray-700 focus:border-cyan-500 focus:ring-cyan-500'"
              placeholder='{ "type": "object", "properties": { "a": { "type": "number" } }, "required": ["a"] }'
            />
            <p v-if="schemaError" class="mt-1.5 text-xs text-rose-400">{{ schemaError }}</p>
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
              {{ isSubmitting ? 'Registering…' : 'Register Tool' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useManagementStore } from '../stores/managementStore';

const emit = defineEmits<{ close: [] }>();
const mgmt = useManagementStore();

const form = reactive({
  name: '',
  description: '',
  python_function_name: '',
  json_schema_raw: '',
});

const schemaError = ref('');
const isSubmitting = ref(false);
const toast = ref<{ type: 'success' | 'error'; message: string } | null>(null);

function validateSchema(): Record<string, unknown> | null {
  schemaError.value = '';
  try {
    const parsed = JSON.parse(form.json_schema_raw) as unknown;
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      schemaError.value = 'Schema must be a JSON object, not an array or primitive.';
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    schemaError.value = 'Invalid JSON — please check your syntax.';
    return null;
  }
}

async function handleSubmit() {
  toast.value = null;
  const schema = validateSchema();
  if (!schema) return;

  isSubmitting.value = true;
  try {
    await mgmt.createTool({
      name: form.name,
      description: form.description,
      python_function_name: form.python_function_name,
      json_schema: schema,
    });
    toast.value = { type: 'success', message: `Tool "${form.name}" registered successfully.` };
    setTimeout(() => emit('close'), 1400);
  } catch (error) {
    toast.value = {
      type: 'error',
      message: error instanceof Error ? error.message : 'Registration failed.',
    };
  } finally {
    isSubmitting.value = false;
  }
}
</script>
