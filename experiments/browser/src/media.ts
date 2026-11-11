import type { CameraFrame, LabImage } from './types'

const captureCanvases = new WeakMap<HTMLVideoElement, HTMLCanvasElement>()

export function capture(video: HTMLVideoElement | null): string {
  if (!video || video.readyState < 2 || !video.videoWidth) throw new Error('Wait for the camera preview to appear.')
  let canvas = captureCanvases.get(video)
  if (!canvas) { canvas = document.createElement('canvas'); captureCanvases.set(video, canvas) }
  const scale = Math.min(1, 960 / Math.max(video.videoWidth, video.videoHeight))
  const width = Math.round(video.videoWidth * scale), height = Math.round(video.videoHeight * scale)
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height }
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas capture is unavailable in this browser.')
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.85)
}

/** Sample independently of HTTP/inference, retaining short blinks in a bounded queue. */
export class CameraSampler {
  private frames: CameraFrame[] = []
  private callback = 0
  private stopped = false
  private nextCapture = 0
  private lastMediaTime = -1
  private wake: (() => void) | null = null
  private failure: unknown
  private readonly useVideoCallback: boolean

  constructor(private video: HTMLVideoElement, private startedAt: number, private signal: AbortSignal) {
    this.useVideoCallback = typeof video.requestVideoFrameCallback === 'function'
    signal.addEventListener('abort', this.stop, { once: true })
    if (signal.aborted) this.stop()
    else this.schedule()
  }

  private schedule() {
    if (this.stopped) return
    this.callback = this.useVideoCallback
      ? this.video.requestVideoFrameCallback((now, metadata) => this.sample(now, metadata.mediaTime))
      : requestAnimationFrame((now) => this.sample(now, this.video.currentTime))
  }

  private sample(now: number, mediaTime: number) {
    if (this.stopped) return
    try {
      if (now >= this.nextCapture && mediaTime > this.lastMediaTime) {
        this.lastMediaTime = mediaTime
        this.nextCapture = Math.max(this.nextCapture + 50, now) // ~20 samples/s, never a duplicate video frame
        this.frames.push({ image: capture(this.video), offset_ms: performance.now() - this.startedAt })
        this.frames = this.frames.slice(-6)
        this.wake?.()
      }
      this.schedule()
    } catch (error) { this.failure = error; this.stop() }
  }

  discard() { this.frames = [] }

  async take(): Promise<CameraFrame[]> {
    while (!this.stopped) {
      const now = performance.now() - this.startedAt
      this.frames = this.frames.filter((frame) => now - frame.offset_ms <= 450)
      if (this.frames.length) return this.frames.splice(0)
      await new Promise<void>((resolve) => { this.wake = resolve })
      this.wake = null
    }
    throw this.failure || new DOMException('Camera sampling stopped.', 'AbortError')
  }

  stop = () => {
    this.stopped = true
    if (this.useVideoCallback) this.video.cancelVideoFrameCallback(this.callback)
    else cancelAnimationFrame(this.callback)
    this.signal.removeEventListener('abort', this.stop)
    this.frames = []
    this.wake?.()
  }
}

export async function loadImage(file: File): Promise<LabImage> {
  if (!['image/jpeg', 'image/png'].includes(file.type)) throw new Error('Choose JPEG or PNG images.')
  if (file.size > 15_000_000) throw new Error('Choose an image under 15 MB.')
  const bitmap = await createImageBitmap(file)
  try {
    if (Math.min(bitmap.width, bitmap.height) < 80 || bitmap.width * bitmap.height > 25_000_000) {
      throw new Error('Choose an image at least 80 pixels wide and under 25 megapixels.')
    }
    const scale = Math.min(1, 960 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Image processing is unavailable in this browser.')
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    return { name: file.name, data: canvas.toDataURL('image/jpeg', 0.9), aspect: bitmap.width / bitmap.height }
  } finally {
    bitmap.close()
  }
}
