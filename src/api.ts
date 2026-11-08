import type { Attempt, CameraFrame, Enrollment, EnrollmentFrame, FrameResult, Observation, Source, Status } from './types'

let token = ''

async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Viso-Token': token },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(30_000)]) : AbortSignal.timeout(30_000),
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('The local service is not responding. Check the Viso terminal, then reconnect.')
  }
  const data = await response.json().catch(() => ({ error: 'Unexpected response from the local service.' }))
  if (!response.ok) throw new Error(`${data.error || 'The local request failed.'} (HTTP ${response.status})`)
  return data as T
}

export const api = {
  async status() {
    const status = await request<Status>('/status')
    if (status.liveness !== 'blink-and-open-eyes' || status.camera_pipeline !== 'buffered-v1') {
      token = ''
      throw new Error('This service needs the camera-pipeline update. Open the updated Viso service, or restart the service with the current code.')
    }
    token = status.token
    return status
  },
  enroll: (name: string, images: string[], source: Source) => request<Status>('/enroll', 'POST', { name, images, source }),
  startEnrollment: (name: string, signal?: AbortSignal) => request<Enrollment>('/enrollments', 'POST', { name }, signal),
  enrollmentFrame: (id: string, image: string, signal?: AbortSignal) => request<EnrollmentFrame>(`/enrollments/${id}/frame`, 'POST', { image }, signal),
  finishEnrollment: (id: string) => request<Status>(`/enrollments/${id}/finish`, 'POST', {}),
  cancelEnrollment: (id: string) => request<{ state: string }>(`/enrollments/${id}`, 'DELETE'),
  remove: () => request<Status>('/profile', 'DELETE'),
  analyze: (image: string) => request<Observation>('/analyze', 'POST', { image }),
  start: (source: Source, threshold: number, signal?: AbortSignal) => request<Attempt>('/attempts', 'POST', { source, threshold }, signal),
  frame: (id: string, image: string, signal?: AbortSignal) => request<FrameResult>(`/attempts/${id}/frame`, 'POST', { image }, signal),
  frames: (id: string, frames: CameraFrame[], signal?: AbortSignal) => request<FrameResult>(`/attempts/${id}/frames`, 'POST', { frames }, signal),
  cancel: (id: string) => request<{ state: string }>(`/attempts/${id}`, 'DELETE'),
}
