import { Preferences } from '@capacitor/preferences'
import type { Settings } from './types'

const SETTINGS_KEY = 'pokemon_damage_agent_settings'

export const defaultSettings: Settings = {
  apiKey: '',
  baseUrl: 'https://api.deepseek.com',
  model: 'deepseek-chat',
}

export async function loadSettings(): Promise<Settings> {
  const { value } = await Preferences.get({ key: SETTINGS_KEY })
  if (!value) return defaultSettings

  try {
    return { ...defaultSettings, ...JSON.parse(value) }
  } catch {
    return defaultSettings
  }
}

export async function saveSettings(settings: Settings) {
  await Preferences.set({
    key: SETTINGS_KEY,
    value: JSON.stringify(settings),
  })
}
