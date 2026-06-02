import { Capacitor, CapacitorHttp } from '@capacitor/core'
import type { Settings } from './types'

interface ChatResponse {
  choices?: Array<{
    finish_reason?: string
    message?: {
      content?: string
    }
  }>
}

export async function deepseekJson<T>(
  settings: Settings,
  systemPrompt: string,
  payload: unknown,
  maxTokens = 2500,
): Promise<T> {
  if (!settings.apiKey.trim()) {
    throw new Error('请先在右上角设置里填写 DeepSeek API Key')
  }

  let lastError: unknown

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const body = {
        model: settings.model.trim() || 'deepseek-chat',
        messages: [
          {
            role: 'system',
            content: `${systemPrompt}\n\n最终回答必须是一个合法 JSON object，不要输出解释文字。`,
          },
          {
            role: 'user',
            content: JSON.stringify(payload, null, 2),
          },
        ],
        temperature: 0,
        max_tokens: maxTokens,
        response_format: { type: 'json_object' },
      }
      const data = await postJson<ChatResponse>(
        `${settings.baseUrl.replace(/\/$/, '')}/chat/completions`,
        {
          Authorization: `Bearer ${settings.apiKey.trim()}`,
          'Content-Type': 'application/json',
        },
        body,
      )
      const choice = data.choices?.[0]
      const content = choice?.message?.content
      if (!content) {
        throw new Error(`DeepSeek 返回空内容，finish_reason=${choice?.finish_reason ?? 'unknown'}`)
      }

      return parseJsonContent(content) as T
    } catch (error) {
      lastError = error
      if (attempt < 3) {
        await new Promise((resolve) => window.setTimeout(resolve, attempt * 1200))
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error('DeepSeek 调用失败')
}

async function postJson<T>(url: string, headers: Record<string, string>, data: unknown): Promise<T> {
  if (Capacitor.isNativePlatform()) {
    const response = await CapacitorHttp.post({
      url,
      headers,
      data,
      responseType: 'json',
    })
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`DeepSeek HTTP ${response.status}: ${JSON.stringify(response.data)}`)
    }
    return response.data as T
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    throw new Error(`DeepSeek HTTP ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

function parseJsonContent(content: string) {
  let text = content.trim()
  if (text.startsWith('```')) {
    text = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim()
  }

  try {
    return JSON.parse(text)
  } catch {
    const start = text.indexOf('{')
    const end = text.lastIndexOf('}')
    if (start >= 0 && end > start) {
      return JSON.parse(repairJsonLikeText(text.slice(start, end + 1)))
    }
    throw new Error('DeepSeek 响应中没有 JSON 对象')
  }
}

function repairJsonLikeText(text: string) {
  return text
    .replace(/\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)/g, '$1"$2"$3')
    .replace(/,\s*([}\]])/g, '$1')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
    .replace(/\bNone\b/g, 'null')
}
