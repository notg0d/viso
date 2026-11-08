import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, Eye, FlaskConical, LoaderCircle, LockKeyhole, Monitor, Pause, Play, ScanFace, UnlockKeyhole } from 'lucide-react'
import type { Attempt, Enrollment, Observation, Source } from './types'

export function EnrollmentGuide({ enrollment }: { enrollment: Enrollment }) {
  const Direction = enrollment.returning ? ScanFace : { center: ScanFace, left: ArrowLeft, right: ArrowRight, up: ArrowUp, down: ArrowDown }[enrollment.step]
  const guide = enrollment.guidance
  const left = (yaw: number) => Math.max(3, Math.min(97, 50 - yaw / 60 * 100))
  const top = (pitch: number) => Math.max(3, Math.min(97, 50 + pitch / 50 * 100))
  return <div className="enrollment-guide" aria-live="polite">
    <div className="guide-steps" aria-label={`${enrollment.captured} of ${enrollment.total} angles captured`}>
      {enrollment.steps.map((step, index) => <span key={step} className={index < enrollment.captured ? 'complete' : step === enrollment.step ? 'current' : ''}>{index < enrollment.captured ? <Check size={11} /> : index + 1}<small>{step}</small></span>)}
    </div>
    <div className="pose-target" role="img" aria-label="Move the white dot into the green target with a small head movement">
      <span className="pose-cross horizontal" /><span className="pose-cross vertical" />
      <span className="pose-zone" style={{ left: `${left(guide.target_yaw)}%`, top: `${top(guide.target_pitch)}%`, width: `${guide.tolerance_yaw / 30 * 100}%`, height: `${guide.tolerance_pitch / 25 * 100}%` }} />
      {guide.yaw !== null && guide.pitch !== null && <span className={`pose-dot ${enrollment.hold_progress > 0 ? 'aligned' : ''}`} style={{ left: `${left(guide.yaw)}%`, top: `${top(guide.pitch)}%` }} />}
      <Direction className="pose-direction" size={19} />
    </div>
    <span className="pose-target-label">Move the dot into the green target</span>
    <h3>{enrollment.state === 'ready' ? 'All angles captured' : enrollment.title}</h3>
    <p>{enrollment.instruction}</p>
    <div className="pose-hold" role="progressbar" aria-label="Hold this angle" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(enrollment.hold_progress * 100)}><span style={{ width: `${enrollment.hold_progress * 100}%` }} /></div>
  </div>
}

export function EyeReadout({ observation }: { observation: Observation }) {
  const attention = observation.attention
  const angle = (value: number | null) => value === null ? '—' : `${Math.round(value)}°`
  return <div className="eye-readout">
    <span className={attention.eyes === 'open' ? 'eyes-open' : 'eyes-blocked'} title={attention.message}><Eye size={14} />{attention.eyes === 'open' ? 'Both eyes open' : attention.eyes === 'closed' ? 'Eyes closed' : 'Eyes not confirmed open'}</span>
    <span title="Positive yaw is your left; positive pitch is down.">Yaw {angle(attention.yaw)} · Pitch {angle(attention.pitch)}</span>
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
