export type Source = 'camera' | 'image'

export interface Profile {
  id: string
  name: string
  samples: number
  source: Source
  model_id: string
  created_at: string
  guided?: boolean
}

export interface Status {
  version: string
  mode: 'sandbox'
  token: string
  engine: { ready: boolean; id: string; message: string | null }
  profile: Profile | null
  storage: string
  storage_error: string | null
  threshold: number
  liveness: 'blink-and-open-eyes'
  camera_pipeline: 'buffered-v1'
}

export interface Observation {
  face_count: number
  usable: boolean
  identity_checked: boolean
  message: string
  box: [number, number, number, number] | null
  detection_score: number | null
  latency_ms: number
  similarity: number | null
  attention: {
    eyes: 'open' | 'closed' | 'uncertain' | 'unknown'
    left_blink: number | null
    right_blink: number | null
    left_ear: number | null
    right_ear: number | null
    yaw: number | null
    pitch: number | null
    roll: number | null
    message: string
  }
}

export interface Attempt {
  id: string
  state: 'scanning' | 'unlocked' | 'expired' | 'blocked'
  streak: number
  required: number
  source: Source
  threshold: number
  phase: 'identity' | 'blink' | 'reopen' | 'confirm' | 'complete'
  challenge: number
  message: string
}

export interface Enrollment {
  id: string
  state: 'capturing' | 'ready' | 'expired'
  captured: number
  total: number
  step: 'center' | 'left' | 'right' | 'up' | 'down'
  title: string
  instruction: string
  message: string
  hold_progress: number
  steps: string[]
  returning: boolean
  guidance: {
    yaw: number | null
    pitch: number | null
    target_yaw: number
    target_pitch: number
    tolerance_yaw: number
    tolerance_pitch: number
  }
}

export interface EnrollmentFrame {
  enrollment: Enrollment
  observation: Observation
}

export interface FrameResult {
  attempt: Attempt
  observation: Observation
}

export interface CameraFrame {
  image: string
  offset_ms: number
}

export interface LabImage {
  name: string
  data: string
  aspect: number
}

export interface LogEntry {
  id: number
  time: string
  message: string
  kind: 'info' | 'success' | 'error'
}
