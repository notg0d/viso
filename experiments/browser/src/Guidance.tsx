import { ArrowRight, Check, Eye, FlaskConical, LoaderCircle, LockKeyhole, Monitor, Pause, Play, ScanFace, UnlockKeyhole } from 'lucide-react'
import type { Attempt, Observation, Source } from './types'

export function EyeReadout({ observation }: { observation: Observation }) {
  const attention = observation.attention
  const angle = (value: number | null) => value === null ? '—' : `${Math.round(value)}°`
  return <div className="eye-readout">
    <span className={attention.eyes === 'open' ? 'eyes-open' : 'eyes-blocked'} title={attention.message}><Eye size={14} />{attention.eyes === 'open' ? 'Both eyes open' : attention.eyes === 'closed' ? 'Eyes closed' : 'Eyes not confirmed open'}</span>
    <span title="Positive yaw is your left; positive pitch is down.">{attention.eye_method === 'pose-calibrated' ? 'Tilt adjusted · ' : ''}Yaw {angle(attention.yaw)} · Pitch {angle(attention.pitch)}</span>
  </div>
}

interface UnlockProps {
  state: 'locked' | 'scanning' | 'unlocked' | 'rejected' | 'expired' | 'blocked'
  attempt: Attempt | null
  source: Source
  name?: string
  ready: boolean
  working: boolean
  inspecting: boolean
  onTest: () => void
  onStop: () => void
  onInspect: () => void
}

export function UnlockCard({ state, attempt, source, name, ready, working, inspecting, onTest, onStop, onInspect }: UnlockProps) {
  const scanning = state === 'scanning'
  const progress = !attempt ? 0 : attempt.phase === 'complete' ? 3 : ['confirm', 'reopen'].includes(attempt.phase) ? 2 : attempt.phase === 'blink' ? 1 : 0
  const title = state === 'unlocked' ? `Hello, ${name || 'you'}.` : scanning ? attempt?.recovering ? 'Following your movement…' : { identity: 'Looking for you…', blink: 'Give us a blink.', reopen: 'Open your eyes.', confirm: 'Almost there…', complete: 'Verified.' }[attempt?.phase || 'identity'] : state === 'blocked' ? 'Photo stays locked.' : state === 'rejected' ? 'Not a match.' : state === 'expired' ? 'Let’s try again.' : 'A glance away.'
  return <section className="card unlock-card" aria-labelledby="unlock-title">
    <div className="card-heading"><div><span className="section-number">02</span><h2 id="unlock-title">You open the door.</h2></div><Monitor size={17} /></div>
    <div className={`lock-simulation ${state}`}>
      <span className="simulation-label">SIMULATED LOCK SCREEN</span>
      <div className="lock-orbit"><div className="lock-symbol">{state === 'unlocked' ? <UnlockKeyhole size={28} /> : scanning && attempt?.phase !== 'identity' ? <Eye size={29} /> : scanning ? <ScanFace size={29} /> : <LockKeyhole size={27} />}</div></div>
      <h3>{title}</h3>
      <p aria-live="polite">{state === 'unlocked' ? 'Your test workspace is unlocked.' : scanning || state === 'blocked' || state === 'expired' ? attempt?.message || 'Look at the camera with both eyes open.' : state === 'rejected' ? 'The test workspace stayed locked.' : name ? 'Face the camera, then blink when prompted.' : 'Enroll your face to try an unlock.'}</p>
      <div className="challenge-steps" aria-label={`${progress} of 3 verification steps complete`}>{['Match', 'Blink', 'Eyes open'].map((label, index) => <span key={label} className={index < progress ? 'complete' : ''}><i>{index < progress ? <Check size={10} /> : index + 1}</i>{label}</span>)}</div>
      <span className="simulation-footnote">{source === 'camera' ? 'Fresh blink required for every unlock' : 'Photo tests always keep the simulator locked'}</span>
    </div>
    <div className="unlock-actions">
      {scanning ? <button className="button primary full" onClick={onStop}><Pause size={16} />Stop test<span className="key-hint">ESC</span></button> : state === 'unlocked' ? <button className="button primary full" onClick={onStop}><LockKeyhole size={16} />Lock again</button> : <button className="button primary full" disabled={!ready || !name || working} onClick={onTest}><Play size={15} />{source === 'image' ? 'Test photo rejection' : 'Test face unlock'}<ArrowRight size={16} /></button>}
      <button className="text-button inspect-button" disabled={!ready || working} onClick={onInspect}>{inspecting ? <LoaderCircle size={14} className="spin" /> : <ScanFace size={14} />}Inspect frame only</button>
    </div>
    <div className="test-note"><FlaskConical size={15} /><span>Blink + open-eye checks enabled. Video-replay resistance is not established.</span></div>
  </section>
}
