// 播放 worklet：环形缓冲。主线程把后端回流的 16-bit PCM(24k) post 进来，
// 这里转 float32 连续输出，实现无缝播放（= 桌面端 GaplessPlayer 的浏览器版）。
class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buf = new Float32Array(24000 * 30) // 30s 环形缓冲，足够长
    this.read = 0
    this.write = 0
    this.size = 0
    this.port.onmessage = (e) => {
      if (e.data === 'flush') { // 打断/清空（预留给免提阶段的 barge-in）
        this.read = this.write = this.size = 0
        return
      }
      const pcm = new Int16Array(e.data)
      for (let i = 0; i < pcm.length; i++) {
        if (this.size >= this.buf.length) break // 满则丢，正常不会发生
        this.buf[this.write] = pcm[i] / 32768
        this.write = (this.write + 1) % this.buf.length
        this.size++
      }
    }
  }

  process(_inputs, outputs) {
    const out = outputs[0][0]
    for (let i = 0; i < out.length; i++) {
      if (this.size > 0) {
        out[i] = this.buf[this.read]
        this.read = (this.read + 1) % this.buf.length
        this.size--
      } else {
        out[i] = 0 // 欠载输出静音
      }
    }
    return true
  }
}
registerProcessor('playback-processor', PlaybackProcessor)
