import { defineStore } from 'pinia';
import type { Provider, ProviderModel } from '../constants/agentModels';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export interface ToolItem {
  id: string;
  name: string;
  description: string | null;
  json_schema: Record<string, unknown>;
  python_function_name: string;
  created_at: string;
}

interface ToolListResponse {
  items: ToolItem[];
  count: number;
}

interface ToolCreatePayload {
  name: string;
  description: string;
  python_function_name: string;
  json_schema: Record<string, unknown>;
}

interface AgentCreatePayload {
  name: string;
  description: string;
  model_provider: Provider;
  target_model: ProviderModel;
  tool_ids: string[];
}

export const useManagementStore = defineStore('management', {
  state: () => ({
    tools: [] as ToolItem[],
    isLoadingTools: false,
  }),

  actions: {
    async fetchTools() {
      this.isLoadingTools = true;
      try {
        const response = await fetch(`${API_BASE_URL}/tools/`);
        if (!response.ok) throw new Error(`Failed to load tools (${response.status}).`);
        const payload = (await response.json()) as ToolListResponse;
        this.tools = payload.items;
      } finally {
        this.isLoadingTools = false;
      }
    },

    async createTool(payload: ToolCreatePayload): Promise<ToolItem> {
      const response = await fetch(`${API_BASE_URL}/tools/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const err = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(err?.detail ?? `Failed to create tool (${response.status}).`);
      }
      const tool = (await response.json()) as ToolItem;
      this.tools.unshift(tool);
      return tool;
    },

    async createAgent(payload: AgentCreatePayload): Promise<{ id: string }> {
      const { tool_ids, ...agentBody } = payload;

      const response = await fetch(`${API_BASE_URL}/agents/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentBody),
      });
      if (!response.ok) {
        const err = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(err?.detail ?? `Failed to create agent (${response.status}).`);
      }
      const agent = (await response.json()) as { id: string };

      for (const toolId of tool_ids) {
        const assignRes = await fetch(`${API_BASE_URL}/agents/${agent.id}/tools/${toolId}`, {
          method: 'POST',
        });
        if (!assignRes.ok && assignRes.status !== 409) {
          throw new Error(`Failed to assign tool ${toolId} to agent.`);
        }
      }

      return agent;
    },
  },
});
