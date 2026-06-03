// 采集 worklet：把麦克风 float32 采样转成 16-bit PCM，post 回主线程。
// AudioContext 已按 16000Hz 创建，浏览器会把麦克风重采样到 16k，这里只做格式转换。
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const ch = input[0]
    const pcm = new Int16Array(ch.length)
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    // 转移底层 buffer，零拷贝交给主线程
    this.port.postMessage(pcm.buffer, [pcm.buffer])
    return true
  }
}
registerProcessor('capture-processor', CaptureProcessor)
