// Ring and light-sweep adaptation of jonnyoo/glance (MIT, Jonathan Zhou).
// See THIRD_PARTY_NOTICES.md. Viso uses four directional sectors plus center.
import type { CSSProperties } from 'react'
import { Check } from 'lucide-react'
import type { Enrollment } from './types'

const tickCount = 80
const compass = ['up', 'right', 'down', 'left'] as const
const distance = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180)
const ribbons = Array.from({ length: 42 }, (_, index) => {
  const lane = index % 7
  return {
    '--lane': `${7 + index / 41 * 86}%`,
    '--thickness': `${[31, 19, 10.5, 15.5, 7.2, 23, 8.8][lane]}px`,
    '--length': `${[58, 47, 36, 43, 27, 52, 31][lane]}%`,
    '--blur': `${[13.5, 11.6, 9.6, 12.2, 8.2, 13.2, 10.2][lane]}px`,
    '--duration': `${[1.22, 1.08, .98, 1.16, .94, 1.28, 1.04][lane]}s`,
    '--delay': `${.36 + [0, .03, .06, .015, .08, .04, .065][lane] + index % 4 * .008}s`,
    '--bow': `${[18, -14, 10, -22, 26, 8, -12][lane]}px`,
  } as CSSProperties
})

export function EnrollmentGuide({ enrollment }: { enrollment: Enrollment }) {
  const complete = enrollment.state === 'ready'
  const direction = enrollment.returning ? 'center' : enrollment.step
  const guide = enrollment.guidance
  const tracked = guide.yaw !== null && guide.pitch !== null
  // Screen-space direction matches the mirrored preview: subject's left is left.
  const x = -(guide.yaw ?? 0) / 16
  const y = (guide.pitch ?? 0) / 12
  const magnitude = Math.hypot(x, y)
  const turnAngle = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360
  const captured = new Set(enrollment.steps.slice(0, enrollment.captured))
  const centering = direction === 'center' && !complete

  return <div className={`enrollment-guide ${complete ? 'complete' : ''}`}>
    {!complete && direction !== 'center' && <div key={direction} className={`direction-sweep sweep-${direction}`} aria-hidden="true">
      {ribbons.map((style, index) => <span className={`sweep-ribbon ${index % 6 === 1 || index % 6 === 4 ? 'vivid' : ''}`} style={style} key={index}><i /><i /><i /></span>)}
    </div>}
    <div className="guide-steps" aria-label={`${enrollment.captured} of ${enrollment.total} angles captured`}>
      {enrollment.steps.map((step, index) => <span key={step} title={step} className={index < enrollment.captured ? 'complete' : step === enrollment.step ? 'current' : ''}>
        {index < enrollment.captured ? <Check size={10} /> : index + 1}<span className="sr-only">{step}</span>
      </span>)}
    </div>
    <svg className={`enrollment-ring ${centering ? 'centering' : ''}`} viewBox="0 0 256 256" role="img" aria-label={complete ? 'All five angles captured' : 'Ring follows your head movement; green sectors are captured angles'}>
      <circle className="ring-guide" cx="128" cy="128" r="101" />
      <g key={enrollment.captured} className={enrollment.captured === 1 ? 'center-captured' : ''}>
        {Array.from({ length: tickCount }, (_, index) => {
          const angle = index * 360 / tickCount
          const sector = compass[Math.floor(((angle + 45) % 360) / 90)]
          const lit = captured.has(sector)
          const target = sector === direction
          const intensity = tracked && magnitude > .15 ? Math.min(1, magnitude) * Math.max(0, 1 - distance(angle, turnAngle) / 13.5) : 0
          const length = lit ? 13 : 6 + 9 * intensity
          return <line key={index} className={`ring-tick ${lit ? 'captured' : ''} ${target ? 'target' : ''} ${intensity > 0 ? 'tracking' : ''}`}
            x1="128" y1="25" x2="128" y2={25 - length} transform={`rotate(${angle} 128 128)`}
            style={{ '--tick-delay': `${index * .004}s`, '--turn': intensity } as CSSProperties} />
        })}
      </g>
      <circle className="ring-hold" cx="128" cy="128" r="98" pathLength="100" strokeDasharray={`${enrollment.hold_progress * 100} 100`} transform="rotate(-90 128 128)" />
      <circle className="ring-completion" cx="128" cy="128" r="112" />
      {complete && <path className="ring-check" d="m109 128 13 13 27-28" />}
    </svg>
    <div className="guide-copy">
      <h3 aria-live="polite">{complete ? 'All angles captured' : enrollment.title}</h3>
      <p>{complete ? 'Your face profile is ready.' : enrollment.instruction}</p>
      <div className="pose-hold" role="progressbar" aria-label="Hold this angle" aria-valuemin={0} aria-valuemax={100} aria-valuenow={complete ? 100 : Math.round(enrollment.hold_progress * 100)}><span style={{ width: `${complete ? 100 : enrollment.hold_progress * 100}%` }} /></div>
    </div>
  </div>
}
