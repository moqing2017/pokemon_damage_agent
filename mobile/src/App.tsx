import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertCircle, Calculator, KeyRound, RotateCcw, Send, Settings as SettingsIcon, X } from 'lucide-react'
import './App.css'
import { defaultSettings, loadSettings, saveSettings } from './storage'
import { formatBattleConfig, formatCalcResult, handleUserMessage } from './agent'
import type { SessionState, Settings } from './types'

interface Message {
  role: 'user' | 'assistant' | 'system'
  lines: string[]
}

function App() {
  const [settings, setSettings] = useState<Settings>(defaultSettings)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [session, setSession] = useState<SessionState>({ assumptions: [] })
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      lines: ['输入一句对战问题，我会抽取战况、追问必要信息，然后用本地计算器给出中文伤害结果。'],
    },
  ])

  useEffect(() => {
    loadSettings().then(setSettings)
  }, [])

  const canSubmit = useMemo(() => input.trim().length > 0 && !busy, [input, busy])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || busy) return

    if (text.toLowerCase() === 'reset') {
      resetSession()
      setInput('')
      return
    }

    if (text.toLowerCase() === 'status') {
      showStatus()
      setInput('')
      return
    }

    setInput('')
    setBusy(true)
    setProgress('准备中')
    setMessages((old) => [...old, { role: 'user', lines: [text] }])

    try {
      const response = await handleUserMessage(text, settings, session, setProgress)
      if (response.kind === 'questions') {
        const defaultLine = response.defaultable.length
          ? `其余信息可以默认：${response.defaultable.join('；')}`
          : '其余信息暂时不需要默认。'
        setMessages((old) => [
          ...old,
          {
            role: 'assistant',
            lines: ['还需要确认：', ...response.questions.map((item, index) => `${index + 1}. ${item}`), defaultLine],
          },
        ])
      } else {
        setSession(response.session)
        const corrections = response.normalization.corrections ?? []
        const lines = [
          ...(corrections.length ? [`术语标准化：${response.normalization.normalized_text}`, ...corrections.map((item) => `${item.original} -> ${item.normalized}`)] : []),
          '计算使用配置：',
          ...formatBattleConfig(response.enriched.battle).map((line) => `- ${line}`),
          ...(response.enriched.assumptions?.length ? ['采用的假设：', ...response.enriched.assumptions.map((line) => `- ${line}`)] : []),
          ...(response.enriched.warnings?.length ? ['提醒：', ...response.enriched.warnings.map((line) => `- ${line}`)] : []),
          '计算结果：',
          ...formatCalcResult(response.result).map((line) => `- ${line}`),
        ]
        setMessages((old) => [...old, { role: 'assistant', lines }])
      }
    } catch (error) {
      setMessages((old) => [
        ...old,
        {
          role: 'system',
          lines: [error instanceof Error ? error.message : '处理失败'],
        },
      ])
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  function resetSession() {
    setSession({ assumptions: [] })
    setMessages((old) => [...old, { role: 'assistant', lines: ['上下文已清空。'] }])
  }

  function showStatus() {
    if (!session.battle) {
      setMessages((old) => [...old, { role: 'assistant', lines: ['当前还没有战况上下文。'] }])
      return
    }
    const battle = session.battle
    if (!battle) return
    setMessages((old) => [...old, { role: 'assistant', lines: ['当前战况：', ...formatBattleConfig(battle).map((line) => `- ${line}`)] }])
  }

  async function persistSettings(next: Settings) {
    setSettings(next)
    await saveSettings(next)
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <Calculator size={22} />
          <div>
            <h1>宝可梦伤害 Agent</h1>
            <span>{settings.apiKey ? 'API Key 已设置' : '请先设置 API Key'}</span>
          </div>
        </div>
        <div className="top-actions">
          <button type="button" className="icon-button" onClick={resetSession} aria-label="清空上下文">
            <RotateCcw size={19} />
          </button>
          <button type="button" className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="设置">
            <SettingsIcon size={20} />
          </button>
        </div>
      </header>

      <section className="chat-list" aria-live="polite">
        {messages.map((message, index) => (
          <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
            {message.role === 'system' && <AlertCircle size={18} />}
            <div>
              {message.lines.map((line, lineIndex) => (
                <p key={`${index}-${lineIndex}`}>{line}</p>
              ))}
            </div>
          </article>
        ))}
        {busy && (
          <article className="message assistant">
            <div className="progress-dot" />
            <p>{progress || '处理中'}</p>
          </article>
        )}
      </section>

      <form className="composer" onSubmit={submit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="例如：晴天下幽尾玄鱼波动冲能确一喷火龙Y吗"
          autoComplete="off"
        />
        <button type="submit" disabled={!canSubmit} aria-label="发送">
          <Send size={20} />
        </button>
      </form>

      {settingsOpen && (
        <section className="settings-panel" role="dialog" aria-modal="true" aria-label="设置">
          <div className="settings-card">
            <div className="settings-title">
              <KeyRound size={20} />
              <h2>DeepSeek 设置</h2>
              <button type="button" className="icon-button" onClick={() => setSettingsOpen(false)} aria-label="关闭">
                <X size={18} />
              </button>
            </div>
            <label>
              API Key
              <input
                type="password"
                value={settings.apiKey}
                onChange={(event) => persistSettings({ ...settings, apiKey: event.target.value })}
                placeholder="sk-..."
              />
            </label>
            <label>
              Base URL
              <input
                value={settings.baseUrl}
                onChange={(event) => persistSettings({ ...settings, baseUrl: event.target.value })}
              />
            </label>
            <label>
              Model
              <input
                value={settings.model}
                onChange={(event) => persistSettings({ ...settings, model: event.target.value })}
              />
            </label>
            <p className="settings-note">Key 只保存到本机应用存储中。打包 APK 时不会内置你的 key。</p>
          </div>
        </section>
      )}
    </main>
  )
}

export default App
