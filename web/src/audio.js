// 浏览器音频引擎：采集（麦克风 -> 16k PCM 帧）与播放（24k PCM -> 无缝输出）。
// 两个独立 AudioContext：采集 16k、播放 24k。必须在用户手势内创建/resume（iOS 要求）。

const REC_RATE = 16000
const TTS_RATE = 24000

export async function createPlayer() {
  const ctx = new AudioContext({ sampleRate: TTS_RATE })
  await ctx.audioWorklet.addModule('/playback-worklet.js')
  const node = new AudioWorkletNode(ctx, 'playback-processor', { outputChannelCount: [1] })
  node.connect(ctx.destination)
  return {
    async resume() { if (ctx.state !== 'running') await ctx.resume() },
    enqueue(arrayBuffer) { node.port.postMessage(arrayBuffer, [arrayBuffer]) },
    flush() { node.port.postMessage('flush') },
  }
}

export async function createCapture(onFrame) {
  const ctx = new AudioContext({ sampleRate: REC_RATE })
  await ctx.audioWorklet.addModule('/capture-worklet.js')
  if (ctx.sampleRate !== REC_RATE) {
    // 个别设备（部分 iOS）可能不 honor sampleRate；届时需在 worklet 里重采样到 16k。
    console.warn(`采集 AudioContext 实际采样率=${ctx.sampleRate}，非 ${REC_RATE}，ASR 可能不准。`)
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  const src = ctx.createMediaStreamSource(stream)
  const node = new AudioWorkletNode(ctx, 'capture-processor')
  let sending = false
  node.port.onmessage = (e) => { if (sending) onFrame(e.data) }
  src.connect(node) // 不接 destination，避免把自己的声音播出来

  return {
    async resume() { if (ctx.state !== 'running') await ctx.resume() },
    start() { sending = true },
    stop() { sending = false },
  }
}
