// 会话层：管理 WebSocket 连接 + 一个翻译 turn 的起止。
//
// ★ VAD 接缝：start() / end() 现在由「按住说话」按钮调用。将来做免提模式时，
//   Silero VAD 的 onSpeechStart / onSpeechEnd 调用同样这两个方法即可，其余代码零改动。

import { createPlayer, createCapture } from './audio.js'

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/translate` // 经 Vite/反代到后端
}

export function createSession(handlers = {}) {
  let ws = null
  let player = null
  let capture = null
  let ready = false
  let lang = 'en'

  async function ensureAudio() {
    if (ready) return
    player = await createPlayer()
    capture = await createCapture((frame) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(frame)
    })
    ready = true
  }

  function connectWs() {
    return new Promise((resolve, reject) => {
      if (ws && ws.readyState === WebSocket.OPEN) return resolve()
      ws = new WebSocket(wsUrl())
      ws.binaryType = 'arraybuffer'
      ws.onopen = () => resolve()
      ws.onerror = () => reject(new Error('WebSocket 连接失败'))
      ws.onmessage = (e) => {
        if (typeof e.data === 'string') {
          const d = JSON.parse(e.data)
          if (d.type === 'asr') handlers.onAsr?.(d.text)
          else if (d.type === 'translation_delta') handlers.onTransDelta?.(d.text)
          else if (d.type === 'translation') handlers.onTranslation?.(d.text)
          else if (d.type === 'error') handlers.onError?.(d.text)
          else if (d.type === 'turn_done') handlers.onDone?.()
        } else {
          player.enqueue(e.data) // 二进制 = TTS PCM(24k)
        }
      }
      ws.onclose = () => { ws = null } // 下次 start 重连
    })
  }

  return {
    setLang(l) { lang = l },

    async start() {
      await ensureAudio()
      await player.resume()
      await capture.resume()
      await connectWs()
      ws.send(JSON.stringify({ type: 'start', lang }))
      capture.start()
      handlers.onStatus?.('listening')
    },

    end() {
      if (!ready) return
      capture.stop()
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'end' }))
      }
      handlers.onStatus?.('processing')
    },
  }
}
