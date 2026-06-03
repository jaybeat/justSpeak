import { useRef, useState, useEffect } from 'react'
import { createSession } from './session.js'
import './App.css'

const STATUS_TEXT = {
  idle: '按住按钮说中文',
  listening: '正在聆听…… 松手翻译',
  processing: '翻译中……',
}

export default function App() {
  const [lang, setLang] = useState('en')
  const [status, setStatus] = useState('idle')
  const [zh, setZh] = useState('')
  const [translation, setTranslation] = useState('')
  const [error, setError] = useState('')
  const sessionRef = useRef(null)
  const holdingRef = useRef(false)

  // 创建一次 session，绑定回调
  if (!sessionRef.current) {
    sessionRef.current = createSession({
      onAsr: (t) => setZh(t),
      onTransDelta: (t) => setTranslation((prev) => prev + t),
      onTranslation: (t) => setTranslation(t),
      onError: (t) => { setError(t); setStatus('idle') },
      onStatus: (s) => setStatus(s),
      onDone: () => setStatus('idle'),
    })
  }

  useEffect(() => {
    sessionRef.current.setLang(lang)
  }, [lang])

  async function beginHold(e) {
    e.preventDefault()
    if (holdingRef.current) return
    holdingRef.current = true
    setError('')
    setZh('')
    setTranslation('')
    try {
      await sessionRef.current.start()
    } catch (err) {
      holdingRef.current = false
      setError(err?.message || '无法开始录音（麦克风权限？）')
      setStatus('idle')
    }
  }

  function endHold(e) {
    e.preventDefault()
    if (!holdingRef.current) return
    holdingRef.current = false
    sessionRef.current.end()
  }

  return (
    <div className="app">
      <h1>justSpeak · 语音翻译</h1>

      <div className="lang-toggle">
        {[['en', '中 → 英'], ['ja', '中 → 日']].map(([code, label]) => (
          <button
            key={code}
            className={lang === code ? 'active' : ''}
            onClick={() => setLang(code)}
            disabled={status !== 'idle'}
          >
            {label}
          </button>
        ))}
      </div>

      <button
        className={`talk ${status}`}
        onPointerDown={beginHold}
        onPointerUp={endHold}
        onPointerLeave={endHold}
        onPointerCancel={endHold}
      >
        {status === 'listening' ? '🎙️ 松手翻译' : '🎤 按住说话'}
      </button>

      <p className="status">{STATUS_TEXT[status]}</p>

      {error && <p className="error">⚠ {error}</p>}

      <div className="result">
        <div className="line">
          <span className="tag">中文</span>
          <span className="text">{zh || '—'}</span>
        </div>
        <div className="line">
          <span className="tag">{lang === 'en' ? '英文' : '日文'}</span>
          <span className="text big">{translation || '—'}</span>
        </div>
      </div>
    </div>
  )
}
