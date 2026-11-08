import type { LabImage } from './types'

export function capture(video: HTMLVideoElement | null): string {
  if (!video || video.readyState < 2 || !video.videoWidth) throw new Error('Wait for the camera preview to appear.')
  const canvas = document.createElement('canvas')
  const scale = Math.min(1, 960 / Math.max(video.videoWidth, video.videoHeight))
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas capture is unavailable in this browser.')
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.9)
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

export const delay = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))
