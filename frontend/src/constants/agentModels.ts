export const providerModels = {
  google_genai: ['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview', 'gemini-2.5-flash', 'gemini-2.5-pro'],
  openai: ['gpt-4o', 'gpt-4o-mini'],
  anthropic: ['claude-sonnet-4-6', 'claude-haiku-4-5'],
} as const;

export type Provider = keyof typeof providerModels;
export type ProviderModel = (typeof providerModels)[Provider][number];

export const providerOptions = Object.keys(providerModels) as Provider[];

export function getDefaultTargetModel(provider: Provider): ProviderModel {
  return providerModels[provider][0];
}