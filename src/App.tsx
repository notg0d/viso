import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, ArrowDownToLine, ArrowRight, Camera, Check, ChevronRight, CircleHelp,
  Cpu, Fingerprint, FlaskConical, FolderLock, Image as ImageIcon, LoaderCircle,
  Monitor, Plus, RefreshCw, ScanFace, Settings2,
  ShieldCheck, Sparkles, Square, Trash2, Upload, UserRound, X,
} from 'lucide-react'
import { api } from './api'
import { capture, delay, loadImage } from './media'
import type { Attempt, Enrollment, LabImage, LogEntry, Observation, Source, Status } from './types'
import { EnrollmentGuide, EyeReadout, UnlockCard } from './Guidance'

type Page = 'bench' | 'identity' | 'activity'
type TestState = 'locked' | 'scanning' | 'unlocked' | 'rejected' | 'expired' | 'blocked'

function App() {
  const [page, setPage] = useState<Page>('bench')
  const [status, setStatus] = useState<Status | null>(null)
  const [connecting, setConnecting] = useState(true)
  const [source, setSource] = useState<Source>('camera')
  const [images, setImages] = useState<LabImage[]>([])
  const [selectedImage, setSelectedImage] = useState(0)
  const [cameraState, setCameraState] = useState<'off' | 'starting' | 'on'>('off')
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [cameraAspect, setCameraAspect] = useState(4 / 3)
  const [busy, setBusy] = useState<string | null>(null)
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [observation, setObservation] = useState<Observation | null>(null)
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [testState, setTestState] = useState<TestState>('locked')
  const [threshold, setThreshold] = useState(0.55)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const video = useRef<HTMLVideoElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const cameraGeneration = useRef(0)
  const scanGeneration = useRef(0)
  const scanController = useRef<AbortController | null>(null)
  const attemptId = useRef<string | null>(null)
  const nextLogId = useRef(0)
  const enrollmentId = useRef<string | null>(null)
  const enrollmentGeneration = useRef(0)
  const enrollmentController = useRef<AbortController | null>(null)
  const savingEnrollment = useRef(false)

  const log = useCallback((message: string, kind: LogEntry['kind'] = 'info') => {
    const entry = { id: ++nextLogId.current, time: new Date().toISOString(), message, kind }
    setLogs((previous) => [entry, ...previous].slice(0, 100))
  }, [])

  const fail = useCallback((cause: unknown) => {
    const message = cause instanceof Error ? cause.message : 'Something went wrong. Please try again.'
    setError(message)
    log(message, 'error')
  }, [log])

  const reconnect = useCallback(async () => {
    setConnecting(true)
    setError(null)
    try {
      const next = await api.status()
      setStatus(next)
      log(next.engine.ready ? 'Local recognition engine connected.' : 'Service connected; recognition models need attention.', next.engine.ready ? 'success' : 'error')
    } catch (cause) {
      setStatus(null)
      fail(cause)
    } finally {
      setConnecting(false)
    }
  }, [fail, log])

  useEffect(() => { void reconnect() }, [reconnect])

  const cancelScan = useCallback(() => {
    scanGeneration.current += 1
    scanController.current?.abort()
    scanController.current = null
    const id = attemptId.current
    attemptId.current = null
    if (id) void api.cancel(id).catch(() => {})
    setAttempt(null)
    setTestState('locked')
  }, [])

  const cancelEnrollment = useCallback(() => {
    if (savingEnrollment.current) return
    enrollmentGeneration.current += 1
    enrollmentController.current?.abort()
    enrollmentController.current = null
    const id = enrollmentId.current
    enrollmentId.current = null
    if (id) void api.cancelEnrollment(id).catch(() => {})
    setEnrollment(null)
    setBusy((current) => current === 'enroll' ? null : current)
  }, [])

  const stopCamera = useCallback(() => {
    cancelEnrollment()
    cameraGeneration.current += 1
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
    if (video.current) video.current.srcObject = null
    setCameraState('off')
  }, [cancelEnrollment])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { cancelScan(); cancelEnrollment() } }
    const onHidden = () => {
      if (document.hidden) { cancelScan(); stopCamera() }
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('visibilitychange', onHidden)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('visibilitychange', onHidden)
      scanGeneration.current += 1
      scanController.current?.abort()
      enrollmentGeneration.current += 1
      enrollmentController.current?.abort()
      if (enrollmentId.current) void api.cancelEnrollment(enrollmentId.current).catch(() => {})
      stream.current?.getTracks().forEach((track) => track.stop())
    }
  }, [cancelScan, cancelEnrollment, stopCamera])

  async function startCamera(chosenDevice = deviceId) {
    stopCamera()
    const generation = ++cameraGeneration.current
    setCameraState('starting')
    setError(null)
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost and a supported browser. Use Image lab to test without a camera.')
      const next = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 960 }, height: { ideal: 720 }, ...(chosenDevice ? { deviceId: { exact: chosenDevice } } : { facingMode: 'user' }) },
      })
      if (generation !== cameraGeneration.current || !video.current) {
        next.getTracks().forEach((track) => track.stop())
        return
      }
      stream.current = next
      const track = next.getVideoTracks()[0]
      track.addEventListener('ended', () => { cancelScan(); stopCamera(); log('Camera disconnected.', 'error') })
      const settings = track.getSettings()
      setCameraAspect((settings.width || 640) / (settings.height || 480))
      setDeviceId(settings.deviceId || '')
      video.current.srcObject = next
      await video.current.play()
      if (generation !== cameraGeneration.current) return
      setCameraState('on')
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === 'videoinput'))
      log('Camera started. Frames stay on this computer.')
    } catch (cause) {
      if (generation !== cameraGeneration.current) return
      stopCamera()
      const code = cause instanceof DOMException ? cause.name : ''
      fail(new Error(code === 'NotAllowedError' ? 'Camera access was declined. Allow it in your browser, or use Image lab.' : code === 'NotFoundError' ? 'No camera found. Connect a webcam, or use Image lab.' : code === 'NotReadableError' ? 'The camera is busy. Close other camera apps and try again.' : cause instanceof Error ? cause.message : 'Could not start the camera.'))
    }
  }

  function changeSource(next: Source) {
    cancelScan()
    stopCamera()
    setSource(next)
    setObservation(null)
    setError(null)
  }

  function navigate(next: Page) {
    cancelScan()
    stopCamera()
    setPage(next)
  }

  async function chooseImages(files: FileList | null) {
    if (!files?.length) return
    setBusy('images')
    setError(null)
    cancelScan()
    setObservation(null)
    try {
      if (files.length > 5) throw new Error('Choose up to five photos of the same person.')
      const loaded = await Promise.all(Array.from(files).map(loadImage))
      setImages(loaded)
      setSelectedImage(0)
      log(`${loaded.length} image${loaded.length > 1 ? 's' : ''} loaded into memory.`)
    } catch (cause) { fail(cause) } finally {
      setBusy(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  function currentFrame() {
    if (source === 'camera') return capture(video.current)
    if (!images[selectedImage]) throw new Error('Choose a reference or test image first.')
    return images[selectedImage].data
  }

  async function analyze() {
    setBusy('analyze')
    setError(null)
    try {
      const result = await api.analyze(currentFrame())
      setObservation(result)
      log(result.usable ? `Frame inspected: one usable face${result.similarity === null ? '' : `, similarity ${result.similarity.toFixed(3)}`}.` : result.message, result.usable ? 'success' : 'info')
    } catch (cause) { fail(cause) } finally { setBusy(null) }
  }

  async function enroll() {
    cancelEnrollment()
    const generation = enrollmentGeneration.current
    const controller = new AbortController()
    enrollmentController.current = controller
    setBusy('enroll')
    setError(null)
    setObservation(null)
    cancelScan()
    try {
      let next: Status
      if (source === 'camera') {
        const started = await api.startEnrollment(name, controller.signal)
        if (generation !== enrollmentGeneration.current) { void api.cancelEnrollment(started.id).catch(() => {}); return }
        enrollmentId.current = started.id
        setEnrollment(started)
        while (generation === enrollmentGeneration.current) {
          if (!stream.current?.active) throw new Error('Camera stopped during enrollment. Start it and try again.')
          const result = await api.enrollmentFrame(started.id, capture(video.current), controller.signal)
          if (generation !== enrollmentGeneration.current) return
          setEnrollment(result.enrollment)
          setObservation(result.observation)
          if (result.enrollment.state === 'expired') throw new Error(result.enrollment.message)
          if (result.enrollment.state === 'ready') break
          await delay(60)
        }
        if (generation !== enrollmentGeneration.current) return
        savingEnrollment.current = true
        setBusy('saving')
        next = await api.finishEnrollment(started.id)
        enrollmentId.current = null
      } else {
        savingEnrollment.current = true
        next = await api.enroll(name, images.map((image) => image.data), source)
      }
      setStatus(next)
      setObservation(null)
      log(`Enrolled ${next.profile!.name} with ${next.profile!.samples} ${source === 'camera' ? 'guided angles' : 'image samples'}.`, 'success')
    } catch (cause) {
      if (generation === enrollmentGeneration.current) fail(cause)
    } finally {
      savingEnrollment.current = false
      if (generation === enrollmentGeneration.current) { cancelEnrollment(); setBusy(null) }
    }
  }

  async function removeProfile() {
    setBusy('remove')
    setError(null)
    cancelScan()
    try {
      setStatus(await api.remove())
      setObservation(null)
      log('Enrollment deleted. Active tests were reset.')
    } catch (cause) { fail(cause) } finally { setBusy(null) }
  }

  async function runTest() {
    cancelScan()
    const generation = scanGeneration.current
    const controller = new AbortController()
    scanController.current = controller
    setError(null)
    setObservation(null)
    setTestState('scanning')
    try {
      const started = await api.start(source, threshold, controller.signal)
      if (generation !== scanGeneration.current) { void api.cancel(started.id).catch(() => {}); return }
      attemptId.current = started.id
      setAttempt(started)
      log(`Started ${source === 'camera' ? 'live camera' : 'still-image'} test at threshold ${threshold.toFixed(2)}.`)
      while (generation === scanGeneration.current) {
        const result = await api.frame(started.id, currentFrame(), controller.signal)
        if (generation !== scanGeneration.current) return
        setAttempt(result.attempt)
        setObservation(result.observation)
        if (result.attempt.state !== 'scanning') {
          setTestState(result.attempt.state)
          log(result.attempt.state === 'unlocked' ? `Face matched (${result.observation.similarity?.toFixed(3)}), blink verified, eyes open. Sandbox unlocked.` : result.attempt.message, result.attempt.state === 'unlocked' ? 'success' : 'info')
          return
        }
        if (source === 'image') {
          setTestState('rejected')
          log(result.observation.usable ? 'Face did not meet the threshold. Sandbox remains locked.' : result.observation.message, 'info')
          await api.cancel(started.id)
          attemptId.current = null
          return
        }
        // Inference requests are serialized; a short interval avoids missing a blink.
        await delay(30)
      }
    } catch (cause) {
      if (generation !== scanGeneration.current) return
      cancelScan()
      fail(cause)
    }
  }

  function exportLogs() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ app: 'Viso', mode: 'sandbox', exported_at: new Date().toISOString(), events: logs }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `viso-session-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const scanning = testState === 'scanning'
  const working = !!busy || scanning
  const mediaReady = source === 'camera' ? cameraState === 'on' : images.length > 0
  const ready = !!status?.engine.ready && mediaReady
  const profile = status?.profile
  const image = images[selectedImage]
  const aspect = source === 'camera' ? cameraAspect : image?.aspect || 4 / 3
  const score = observation?.similarity
  const title = page === 'bench' ? "Look. You're in." : page === 'identity' ? 'A face to remember.' : 'Every little signal.'
  const subtitle = page === 'bench' ? 'Your face is the key. Give it a test drive.' : page === 'identity' ? 'A small mathematical signature. Stored right here.' : 'A clear view of what happened in this session.'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); if (!working) navigate('bench') }} aria-label="Viso home">
          <span className="brand-icon"><ScanFace size={24} strokeWidth={1.7} /></span><span>viso<span className="brand-dot">.</span></span>
        </a>
        <div className="workspace-label">DEVELOPMENT WORKSPACE</div>
        <nav aria-label="Main navigation">
          <button disabled={!!busy} className={`nav-item ${page === 'bench' ? 'active' : ''}`} onClick={() => navigate('bench')}><FlaskConical size={18} />Test bench<span className="nav-dot" /></button>
          <button disabled={!!busy} className={`nav-item ${page === 'identity' ? 'active' : ''}`} onClick={() => navigate('identity')}><Fingerprint size={18} />Identity vault</button>
          <button disabled={!!busy} className={`nav-item ${page === 'activity' ? 'active' : ''}`} onClick={() => navigate('activity')}><Activity size={18} />Session activity{logs.length > 0 && <span className="nav-count">{logs.length}</span>}</button>
        </nav>
        <div className="sidebar-note"><span className="tiny-tag">MILESTONE 01</span><h3>Meet your camera.</h3><p>Real face recognition.<br />A simulated unlock.</p><div className="milestone-track"><span /><span /><span /></div><p className="muted-small">Next up: Windows sign-in</p></div>
        <div className="sidebar-bottom"><div className="device-icon"><Monitor size={18} /></div><div><strong>Windows sandbox</strong><span>Local development · v0.2.0</span></div></div>
      </aside>

      <main>
        <div className="topbar"><div className="breadcrumbs">Workspace<ChevronRight size={13} /><span>{page === 'bench' ? 'Test bench' : page === 'identity' ? 'Identity vault' : 'Session activity'}</span></div><span className="environment-badge"><FlaskConical size={13} />TEST ENVIRONMENT</span></div>
        <div className="main-content">
          <header className="page-heading"><div><div className="eyebrow">FACE UNLOCK, REIMAGINED</div><h1>{title}</h1><p>{subtitle}</p></div><button className={`connection ${status?.engine.ready ? 'online' : ''}`} onClick={() => void reconnect()} disabled={working || connecting} title="Reconnect to the local service">{connecting ? <LoaderCircle size={14} className="spin" /> : <span className="status-dot" />} {connecting ? 'Connecting' : status?.engine.ready ? 'Engine connected' : 'Service unavailable'}<RefreshCw size={12} /></button></header>

          {error && <div className="notice error" role="alert"><CircleHelp size={18} /><span>{error}</span><button className="icon-button" aria-label="Dismiss error" onClick={() => setError(null)}><X size={16} /></button></div>}
          {status?.engine.message && <div className="notice error" role="alert"><Cpu size={18} /><span>{status.engine.message}</span></div>}
          {status?.storage_error && <div className="notice error" role="alert"><FolderLock size={18} /><span>{status.storage_error}</span><button className="button compact" disabled={working} onClick={() => void removeProfile()}>Reset profile</button></div>}

          {page === 'bench' && <>
            <div className="bench-grid">
              <section className="card capture-card" aria-labelledby="capture-title">
                <div className="card-heading"><div><span className="section-number">01</span><h2 id="capture-title">The camera sees you.</h2></div><span className="subtle-tag">INPUT</span></div>
                <div className="source-toolbar"><div className="segmented" aria-label="Input source"><button className={source === 'camera' ? 'selected' : ''} disabled={working} onClick={() => changeSource('camera')}><Camera size={15} />Live camera</button><button className={source === 'image' ? 'selected' : ''} disabled={working} onClick={() => changeSource('image')}><ImageIcon size={15} />Image lab</button></div><span className="local-caption"><span className="status-dot" />LOCAL ONLY</span></div>
                <div className={`camera-stage ${mediaReady ? 'has-media' : ''}`}>
                  <div className={`media-surface ${source === 'camera' ? 'mirrored' : ''}`} style={{ aspectRatio: aspect, maxWidth: `${aspect * 350}px`, display: mediaReady || cameraState === 'starting' ? undefined : 'none' }}>
                    {source === 'camera' ? <video ref={video} autoPlay muted playsInline aria-label="Live camera preview" /> : image && <img src={image.data} alt="Selected test input" />}
                    {observation?.box && <div className={`face-box ${observation.usable ? 'usable' : ''}`} style={{ left: `${observation.box[0] * 100}%`, top: `${observation.box[1] * 100}%`, width: `${observation.box[2] * 100}%`, height: `${observation.box[3] * 100}%` }}><span /><span /><span /><span /></div>}
                  </div>
                  {!mediaReady && <div className="camera-placeholder"><div className="viewfinder"><ScanFace size={58} strokeWidth={1} /><i /><i /><i /><i /></div><h3>{source === 'camera' ? 'A little face time?' : 'Start with a familiar face.'}</h3><p>{source === 'camera' ? 'Turn on your camera to get acquainted.' : 'Choose up to five photos of the same person.'}</p><button className="button stage-button" disabled={working || cameraState === 'starting'} onClick={() => source === 'camera' ? void startCamera() : fileInput.current?.click()}>{cameraState === 'starting' ? <LoaderCircle size={16} className="spin" /> : source === 'camera' ? <Camera size={16} /> : <Upload size={16} />}{cameraState === 'starting' ? 'Opening camera…' : source === 'camera' ? 'Enable camera' : 'Choose images'}</button></div>}
                  {mediaReady && <>
                    <span className="stage-badge"><span className={`status-dot ${source === 'camera' ? 'pulsing' : ''}`} />{source === 'camera' ? 'LIVE PREVIEW' : 'STILL IMAGE'}</span>
                    {enrollment ? <EnrollmentGuide enrollment={enrollment} /> : <div className={`stage-caption ${scanning ? 'scanning' : ''}`}><ScanFace size={15} />{scanning ? attempt?.message || 'Looking for your face…' : busy === 'enroll' ? 'Building your face profile…' : observation?.message || (source === 'camera' ? 'Center your face in the frame' : image?.name)}</div>}
                  </>}
                </div>
                {enrollment && <div className="enrollment-feedback" aria-live="polite"><span>{enrollment.message}</span><button className="text-button" disabled={busy === 'saving'} onClick={() => { cancelEnrollment(); log('Guided enrollment canceled.') }}>Cancel enrollment</button></div>}
                {observation && <EyeReadout observation={observation} />}
                <input ref={fileInput} type="file" accept="image/jpeg,image/png" multiple className="sr-only" aria-label="Choose test images" onChange={(event) => void chooseImages(event.target.files)} />
                {source === 'image' && images.length > 0 && <div className="image-strip">{images.map((item, index) => <button className={selectedImage === index ? 'selected' : ''} key={`${item.name}-${index}`} disabled={working} aria-label={`Select image ${index + 1}: ${item.name}`} onClick={() => { cancelScan(); setSelectedImage(index); setObservation(null) }}><img src={item.data} alt="" /><span>{index + 1}</span></button>)}<button className="add-image" aria-label="Choose different images" disabled={working} onClick={() => fileInput.current?.click()}><Plus size={18} /></button><span>{images.length} / 5 samples</span></div>}
                <div className="capture-toolbar">{source === 'camera' ? <><div className="camera-picker"><Camera size={15} /><select aria-label="Camera device" value={deviceId} disabled={working || cameraState === 'starting' || !devices.length} onChange={(event) => { setDeviceId(event.target.value); setObservation(null); void startCamera(event.target.value) }}>{!devices.length && <option value="">Default webcam</option>}{devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}</select></div>{cameraState === 'on' && <button className="text-button" disabled={!!busy} onClick={() => { cancelScan(); stopCamera(); log('Camera stopped.') }}><Square size={12} />Stop camera</button>}</> : <><span className="muted-small">JPEG or PNG · processed in memory</span>{images.length > 0 && <button className="text-button" disabled={working} onClick={() => { setImages([]); setObservation(null); cancelScan() }}>Clear images</button>}</>}</div>
                <div className="enrollment-area">
                  {profile ? <div className="enrolled-summary"><span className="avatar"><UserRound size={22} /></span><div><strong>{profile.name}<span className="small-check"><Check size={11} /></span></strong><span>{profile.samples} samples · {profile.guided ? 'Guided camera enrollment' : profile.source === 'camera' ? 'Camera enrollment' : 'Image lab enrollment'}</span></div><button className="button secondary compact" disabled={working} onClick={() => navigate('identity')}>Manage<ArrowRight size={14} /></button></div> : <>
                    <label htmlFor="profile-name">MAKE IT PERSONAL</label>
                    <div className="enroll-controls"><input id="profile-name" maxLength={40} value={name} disabled={working} onChange={(event) => setName(event.target.value)} placeholder="Your profile name" /><button className="button primary" disabled={!ready || working || !name.trim() || !!status?.storage_error} onClick={() => void enroll()}>{busy === 'enroll' || busy === 'saving' ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />}{busy === 'saving' ? 'Saving…' : busy === 'enroll' ? 'Enrolling…' : 'Enroll face'}</button></div>
                    <p>{source === 'camera' ? 'Follow five directions: center, left, right, up, down. Keep both eyes open.' : 'Enroll a reference photo with both eyes open. Use the camera for blink verification.'}</p>
                  </>}
                </div>
              </section>

              <div className="right-column">
                <UnlockCard state={testState} attempt={attempt} source={source} name={profile?.name} ready={ready} working={working} inspecting={busy === 'analyze'} onTest={() => void runTest()} onStop={() => { cancelScan(); log('Sandbox locked. Blink challenge reset.') }} onInspect={() => void analyze()} />
                <section className="card sensitivity-card"><div className="setting-heading"><div><Settings2 size={16} /><h2>Match threshold</h2></div><output htmlFor="threshold">{threshold.toFixed(2)}</output></div><input id="threshold" aria-label="Match threshold" type="range" min="0.35" max="0.9" step="0.01" value={threshold} disabled={working} onChange={(event) => { setThreshold(Number(event.target.value)); cancelScan() }} /><div className="range-labels"><span>More permissive</span><span>More selective</span></div><p>Cosine similarity, not a confidence percentage.</p></section>
              </div>
            </div>
            <div className="metrics-grid"><Metric icon={<Fingerprint size={18} />} label="SIMILARITY" value={score === null || score === undefined ? '—' : score.toFixed(3)} detail={score === null || score === undefined ? 'Run a test to compare' : score >= threshold ? 'Above your threshold' : 'Below your threshold'} good={score !== null && score !== undefined && score >= threshold} /><Metric icon={<Activity size={18} />} label="INFERENCE TIME" value={observation ? `${Math.round(observation.latency_ms)}` : '—'} unit={observation ? 'ms' : ''} detail="Local CPU · detection + embedding" /><Metric icon={<Cpu size={18} />} label="RECOGNITION ENGINE" value="SFace" detail="YuNet detection · ONNX models" /><Metric icon={<FolderLock size={18} />} label="PROFILE STORAGE" value={status?.storage || '—'} detail={status?.storage === 'Windows DPAPI' ? 'Encrypted for this Windows user' : 'Enrollment lasts for this process'} /></div>
            <section className="card activity-preview"><div className="card-heading"><div><Activity size={17} /><h2>Recent activity</h2></div><button className="text-button" disabled={!!busy} onClick={() => navigate('activity')}>View session<ArrowRight size={14} /></button></div><EventList entries={logs.slice(0, 3)} /></section>
          </>}

          {page === 'identity' && <div className="identity-grid">
            <section className="card identity-card"><span className="large-avatar"><Fingerprint size={42} strokeWidth={1.3} /></span><span className="eyebrow">YOUR ENROLLED IDENTITY</span><h2>{profile?.name || 'An empty canvas.'}</h2><p>{profile ? 'One face profile, ready for the test bench.' : 'Your first enrollment will appear here.'}</p>
              {profile ? <><dl className="profile-details"><div><dt>Source</dt><dd>{profile.guided ? 'Guided camera' : profile.source === 'camera' ? 'Live camera' : 'Image lab'}</dd></div><div><dt>Samples</dt><dd>{profile.samples}</dd></div><div><dt>Enrolled</dt><dd>{new Date(profile.created_at).toLocaleString()}</dd></div><div><dt>Storage</dt><dd>{status?.storage}</dd></div><div><dt>Representation</dt><dd>128-dimensional SFace embedding</dd></div></dl><button className="button danger" disabled={working} onClick={() => void removeProfile()}>{busy === 'remove' ? <LoaderCircle size={16} className="spin" /> : <Trash2 size={16} />}Delete enrollment</button></> : <button className="button primary" disabled={working} onClick={() => navigate('bench')}><Plus size={16} />Enroll your face</button>}
            </section>
            <div className="identity-info">
              <section className="card info-card"><ShieldCheck size={24} /><h2>At home on your device.</h2><p>Recognition runs on your CPU. Frames travel only to the local service on this computer and are processed in memory.</p><p>Windows DPAPI encrypts the face profile for your current Windows user. In ephemeral mode, the profile lives in memory until the service closes.</p><span className="subtle-tag">NO ACCOUNT OR CLOUD REQUIRED</span></section>
              <section className="card info-card"><FlaskConical size={24} /><h2>A test bench, by design.</h2><p>This build changes a simulated lock screen. It does not authenticate a Windows session or collect a Windows password.</p><p>Every unlock requires a recognized face, a fresh blink, and both eyes open again. Uncertain eye tracking blocks unlocking. A blink challenge is not validated protection against replayed or generated video.</p><div className="roadmap"><span className="done"><Check size={13} />Local recognition</span><span className="done"><Check size={13} />Guided enrollment + blink challenge</span><span><span className="roadmap-dot" />Credential Provider in a Windows VM</span></div></section>
            </div>
          </div>}

          {page === 'activity' && <section className="card activity-page"><div className="card-heading"><div><Activity size={18} /><h2>Session events</h2><span className="subtle-tag">{logs.length} EVENTS</span></div><div className="row-actions"><button className="button secondary compact" disabled={!logs.length} onClick={exportLogs}><ArrowDownToLine size={15} />Export JSON</button><button className="icon-button" aria-label="Clear session activity" disabled={!logs.length} onClick={() => setLogs([])}><Trash2 size={16} /></button></div></div><EventList entries={logs} /><div className="activity-footer">Last 100 events in this tab. The log contains no camera images or face embeddings.</div></section>}

          <footer className="page-footer"><span><ShieldCheck size={14} />On-device. On your terms.</span><span>Viso Sandbox<span className="footer-dot">·</span>Built for a familiar face<Sparkles size={13} /></span></footer>
        </div>
      </main>
    </div>
  )
}

function Metric({ icon, label, value, unit, detail, good }: { icon: React.ReactNode; label: string; value: string; unit?: string; detail: string; good?: boolean }) {
  return <div className="metric"><div className="metric-heading">{icon}<span>{label}</span></div><div className={`metric-value ${good ? 'good' : ''}`}>{value}<small>{unit}</small></div><p>{detail}</p></div>
}

function EventList({ entries }: { entries: LogEntry[] }) {
  return <div className="event-list" aria-live="polite">{entries.length === 0 ? <div className="empty-events"><Activity size={20} /><span>A fresh session. Events will appear as you test.</span></div> : entries.map((entry) => <div className={`event ${entry.kind}`} key={entry.id}><span className="event-dot">{entry.kind === 'success' ? <Check size={12} /> : entry.kind === 'error' ? <X size={12} /> : <span />}</span><span className="event-message">{entry.message}</span><time dateTime={entry.time}>{new Date(entry.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time></div>)}</div>
}

export default App
