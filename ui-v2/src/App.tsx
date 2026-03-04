import { useEffect, useMemo, useRef, useState } from 'react'
import type { Profile, RunHealthEntry, Sample, StatusMessage } from './types'

const WINDOW_SECONDS = 300
const EVENT_LIMIT = 50

interface UiEvent {
  ts: number
  level: 'info' | 'warn' | 'error'
  text: string
}

interface RunPoint {
  runtimeHours: number
  temperature: number
  target: number
  clockSec: number
}

interface PowerPoint {
  runtimeHours: number
  current: number | null
  voltage: number | null
  clockSec: number
}

interface RunSummary {
  completedAt: number
  profile: string
  durationHours: number
  maxTemp: number
  maxOvershoot: number
  within5Run: number
  switchesPerHour: number
  cost: number
}

interface TrendPoint {
  x: number
  y: number
}

interface BuilderSegment {
  id: number
  target: string
  ramp: string
  hold: string
}

const DEMO_PROFILES: Profile[] = [
  {
    name: 'cone-6-long-glaze',
    data: [[0, 75], [1800, 250], [5400, 1200], [10800, 2232], [12600, 1900], [16200, 1700]]
  },
  {
    name: 'cone-05-fast-bisque',
    data: [[0, 75], [1200, 200], [4800, 1000], [8400, 1888], [10200, 1650]]
  }
]

function getWsUrl(path: string, token?: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const tokenParam = token && token.trim() ? `?token=${encodeURIComponent(token.trim())}` : ''
  return `${protocol}//${window.location.host}${path}${tokenParam}`
}

function round(n: number | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '--'
  return n.toFixed(digits)
}

function pct(n: number | undefined): string {
  if (n == null || Number.isNaN(n)) return '--'
  return `${n.toFixed(1)}%`
}

function polyline(
  samples: Sample[],
  width: number,
  height: number,
  value: (s: Sample) => number,
  minV: number,
  maxV: number
): string {
  if (!samples.length) return ''
  const span = Math.max(1, samples[samples.length - 1].t - samples[0].t)
  const range = Math.max(0.001, maxV - minV)
  return samples
    .map((s) => {
      const x = ((s.t - samples[0].t) / span) * width
      const y = height - ((value(s) - minV) / range) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'builder' | 'health'>('dashboard')
  const [status, setStatus] = useState<StatusMessage>({})
  const [samples, setSamples] = useState<Sample[]>([])
  const [lastMessageAt, setLastMessageAt] = useState<number>(0)
  const [clockTick, setClockTick] = useState<number>(Date.now())
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [selectedProfile, setSelectedProfile] = useState<string>('')
  const [apiState, setApiState] = useState<string>('')
  const [startAtMinutes, setStartAtMinutes] = useState<number>(0)
  const [builderName, setBuilderName] = useState<string>('new-schedule')
  const [builderStartTemp, setBuilderStartTemp] = useState<string>('75')
  const [builderSegments, setBuilderSegments] = useState<BuilderSegment[]>([
    { id: 1, target: '250', ramp: '200', hold: '0' },
    { id: 2, target: '1000', ramp: '350', hold: '20' },
    { id: 3, target: '1830', ramp: '150', hold: '15' }
  ])
  const [builderError, setBuilderError] = useState<string>('')
  const [builderSaving, setBuilderSaving] = useState<boolean>(false)
  const [events, setEvents] = useState<UiEvent[]>([])
  const [monitorToken, setMonitorToken] = useState<string>(() => window.localStorage.getItem('kiln_monitor_token') ?? '')
  const [controlToken, setControlToken] = useState<string>(() => window.localStorage.getItem('kiln_api_token') ?? '')
  const [runPoints, setRunPoints] = useState<RunPoint[]>([])
  const [powerPoints, setPowerPoints] = useState<PowerPoint[]>([])
  const [runSummary, setRunSummary] = useState<RunSummary | null>(null)
  const [healthRows, setHealthRows] = useState<RunHealthEntry[]>([])
  const [healthLimit, setHealthLimit] = useState<number>(40)
  const [healthIncludeExcluded, setHealthIncludeExcluded] = useState<boolean>(false)
  const [healthLoading, setHealthLoading] = useState<boolean>(false)
  const [healthError, setHealthError] = useState<string>('')
  const [viewStartHour, setViewStartHour] = useState<number>(0)
  const [viewEndHour, setViewEndHour] = useState<number>(1)
  const [hoverRuntimeHour, setHoverRuntimeHour] = useState<number | null>(null)
  const prevStatusRef = useRef<StatusMessage | null>(null)
  const lastRuntimeRef = useRef<number>(0)
  const runPointsRef = useRef<RunPoint[]>([])
  const demoMode = useMemo(() => new URLSearchParams(window.location.search).get('demo') === '1', [])

  const addEvent = (level: UiEvent['level'], text: string) => {
    setEvents((prev) => [{ ts: Date.now(), level, text }, ...prev].slice(0, EVENT_LIMIT))
  }

  const addBuilderSegment = () => {
    setBuilderSegments((prev) => {
      const nextId = prev.length ? Math.max(...prev.map((s) => s.id)) + 1 : 1
      return [...prev, { id: nextId, target: '', ramp: '', hold: '0' }]
    })
  }

  const removeBuilderSegment = (id: number) => {
    setBuilderSegments((prev) => prev.filter((s) => s.id !== id))
  }

  const updateBuilderSegment = (id: number, field: keyof Omit<BuilderSegment, 'id'>, value: string) => {
    setBuilderSegments((prev) => prev.map((s) => (s.id === id ? { ...s, [field]: value } : s)))
  }

  const buildPointsFromBuilder = (): { points: Array<[number, number]>; error?: string } => {
    const start = Number(builderStartTemp)
    if (!Number.isFinite(start)) {
      return { points: [], error: 'Start temperature must be a number.' }
    }

    const points: Array<[number, number]> = [[0, Math.round(start)]]
    let currentTemp = start
    let currentSec = 0
    let hasRamp = false

    for (let i = 0; i < builderSegments.length; i += 1) {
      const seg = builderSegments[i]
      const target = Number(seg.target)
      const ramp = Number(seg.ramp)
      const hold = Number(seg.hold || '0')

      if (!Number.isFinite(target)) continue
      if (!Number.isFinite(hold) || hold < 0) {
        return { points: [], error: `Segment ${i + 1}: hold must be >= 0.` }
      }

      if (target !== currentTemp) {
        if (!Number.isFinite(ramp) || ramp <= 0) {
          return { points: [], error: `Segment ${i + 1}: ramp rate must be > 0 when target changes.` }
        }
        const rampSec = (Math.abs(target - currentTemp) / ramp) * 3600
        currentSec += rampSec
        points.push([Math.round(currentSec), Math.round(target)])
        currentTemp = target
        hasRamp = true
      }

      if (hold > 0) {
        currentSec += hold * 60
        points.push([Math.round(currentSec), Math.round(target)])
      }
    }

    if (!hasRamp || points.length < 2) {
      return { points: [], error: 'Add at least one segment with target and ramp rate.' }
    }

    return { points }
  }

  useEffect(() => {
    if (demoMode) {
      const startMs = Date.now()
      const id = window.setInterval(() => {
        const elapsedSec = (Date.now() - startMs) / 1000
        const setpoint = 900 + Math.min(1200, elapsedSec * 0.9)
        const wave = Math.sin(elapsedSec / 12) * 3.5
        const ispoint = setpoint - 2 + wave
        const err = setpoint - ispoint
        const heatOut = Math.max(0, Math.min(1, 0.45 + Math.sin(elapsedSec / 6) * 0.35))
        const heatOn = heatOut > 0.15 ? 1 : 0
        const state = elapsedSec % 300 > 250 ? 'PAUSED' : 'RUNNING'
        const catchingUp = Math.sin(elapsedSec / 30) > 0.85

        const msg: StatusMessage = {
          temperature: ispoint,
          target: setpoint,
          state,
          heat: heatOn,
          runtime: elapsedSec,
          totaltime: 16200,
          catching_up: catchingUp,
          pidstats: {
            time: Date.now() / 1000,
            timeDelta: 2,
            setpoint,
            ispoint,
            err,
            out: heatOut,
            p: err * 10,
            i: err * 65,
            d: Math.cos(elapsedSec / 7) * 2
          } as StatusMessage['pidstats'],
          telemetry: {
            error_avg_1m: err + Math.sin(elapsedSec / 8) * 0.4,
            error_avg_5m: err + Math.sin(elapsedSec / 13) * 0.7,
            error_abs_avg_5m: Math.abs(err) + 1.2,
            within_5deg_pct_5m: 84 + Math.sin(elapsedSec / 15) * 6,
            within_5deg_pct_run: 81 + Math.sin(elapsedSec / 25) * 4,
            switches_5m: 28 + Math.floor((Math.sin(elapsedSec / 10) + 1) * 3),
            switches_per_hour_run: 94 + Math.sin(elapsedSec / 17) * 12,
            duty_cycle_5m: 43 + Math.sin(elapsedSec / 11) * 18,
            overshoot_max_run: 9.3,
            sensor_error_rate_5m: Math.max(0, 2 + Math.sin(elapsedSec / 20) * 2),
            time_catching_up_pct_run: 4 + Math.max(0, Math.sin(elapsedSec / 40) * 7),
            line_current_now: (16 + Math.sin(elapsedSec / 9) * 2.3) * heatOut,
            line_voltage_now: 239 + Math.sin(elapsedSec / 20) * 1.8,
            line_power_now: 7500 * heatOut + Math.sin(elapsedSec / 11) * 120,
            line_energy_wh_now: elapsedSec * 2.2
          }
        }

        setStatus(msg)
        setLastMessageAt(Date.now())
        setSamples((prev) => {
          const now = Date.now() / 1000
          const next = [...prev, { t: now, error: err, heatOn }]
          const cutoff = now - WINDOW_SECONDS
          return next.filter((s) => s.t >= cutoff)
        })
        setRunPoints((prev) => {
          const runtimeHours = elapsedSec / 3600
          const nowSec = Date.now() / 1000
          if (prev.length && Math.abs(prev[prev.length - 1].runtimeHours - runtimeHours) < 0.01) {
            return prev
          }
          return [...prev, { runtimeHours, temperature: ispoint, target: setpoint, clockSec: nowSec }].slice(-50000)
        })
        setPowerPoints((prev) => {
          const runtimeHours = elapsedSec / 3600
          if (prev.length && Math.abs(prev[prev.length - 1].runtimeHours - runtimeHours) < 0.01) {
            return prev
          }
          return [
            ...prev,
            {
              runtimeHours,
              current: msg.telemetry?.line_current_now ?? null,
              voltage: msg.telemetry?.line_voltage_now ?? null,
              clockSec: nowSec
            }
          ].slice(-50000)
        })
      }, 1000)

      addEvent('info', 'Demo mode active (synthetic data)')
      return () => window.clearInterval(id)
    }

    let ws: WebSocket | null = null
    let reconnectTimer: number | null = null

    const connect = () => {
      ws = new WebSocket(getWsUrl('/status', monitorToken))

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data) as StatusMessage
        setStatus(msg)
        setLastMessageAt(Date.now())

        if (msg.pidstats) {
          const now = msg.pidstats.time
          const error = msg.pidstats.setpoint - msg.pidstats.ispoint
          const heatOn = msg.pidstats.out > 0 ? 1 : 0

          setSamples((prev) => {
            const next = [...prev, { t: now, error, heatOn }]
            const cutoff = now - WINDOW_SECONDS
            return next.filter((s) => s.t >= cutoff)
          })
        }

        if (typeof msg.runtime === 'number' && typeof msg.temperature === 'number' && typeof msg.target === 'number') {
          const runtime = msg.runtime
          const nowSec = Date.now() / 1000
          if (runtime < lastRuntimeRef.current - 30) {
            setRunPoints([])
            setPowerPoints([])
            addEvent('info', 'Run timeline reset for new run')
          }
          lastRuntimeRef.current = runtime
          setRunPoints((prev) => {
            const runtimeHours = runtime / 3600
            if (prev.length && Math.abs(prev[prev.length - 1].runtimeHours - runtimeHours) < 0.01) {
              return prev
            }
            const next = [...prev, { runtimeHours, temperature: msg.temperature!, target: msg.target!, clockSec: nowSec }]
            return next.slice(-50000)
          })
          setPowerPoints((prev) => {
            const runtimeHours = runtime / 3600
            if (prev.length && Math.abs(prev[prev.length - 1].runtimeHours - runtimeHours) < 0.01) {
              return prev
            }
            return [
              ...prev,
              {
                runtimeHours,
                current: msg.telemetry?.line_current_now ?? null,
                voltage: msg.telemetry?.line_voltage_now ?? null,
                clockSec: nowSec
              }
            ].slice(-50000)
          })
        }

        const prev = prevStatusRef.current
        if (prev && prev.state !== msg.state && msg.state) {
          addEvent('info', `State changed: ${prev.state ?? 'UNKNOWN'} -> ${msg.state}`)
        }
        if (
          prev &&
          (prev.state === 'RUNNING' || prev.state === 'PAUSED') &&
          msg.state === 'IDLE'
        ) {
          const maxTemp = runPointsRef.current.length
            ? Math.max(...runPointsRef.current.map((p) => p.temperature))
            : (prev.temperature ?? 0)
          setRunSummary({
            completedAt: Date.now(),
            profile: (prev as StatusMessage & { profile?: string }).profile || 'unknown',
            durationHours: (prev.runtime ?? 0) / 3600,
            maxTemp,
            maxOvershoot: prev.telemetry?.overshoot_max_run ?? 0,
            within5Run: prev.telemetry?.within_5deg_pct_run ?? 0,
            switchesPerHour: prev.telemetry?.switches_per_hour_run ?? 0,
            cost: prev.cost ?? 0
          })
          addEvent('info', 'Run summary captured')
        }
        if (prev && prev.catching_up !== msg.catching_up) {
          addEvent(msg.catching_up ? 'warn' : 'info', msg.catching_up ? 'Catch-up active' : 'Catch-up cleared')
        }
        const sensorErr = msg.telemetry?.sensor_error_rate_5m ?? 0
        if (sensorErr > 30) {
          addEvent('error', `High sensor error rate: ${sensorErr.toFixed(1)}%`)
        }
        prevStatusRef.current = msg
      }

      ws.onclose = () => {
        reconnectTimer = window.setTimeout(connect, 1500)
      }
    }

    connect()

    return () => {
      if (ws) ws.close()
      if (reconnectTimer != null) window.clearTimeout(reconnectTimer)
    }
  }, [demoMode, monitorToken])

  useEffect(() => {
    const id = window.setInterval(() => setClockTick(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    runPointsRef.current = runPoints
  }, [runPoints])

  useEffect(() => {
    if (demoMode) {
      setProfiles(DEMO_PROFILES)
      setSelectedProfile((prev) => prev || DEMO_PROFILES[0].name)
      return
    }

    let ws: WebSocket | null = null
    let reconnectTimer: number | null = null

    const connect = () => {
      ws = new WebSocket(getWsUrl('/storage', monitorToken))
      ws.onopen = () => ws?.send('GET')
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as Profile[]
          if (Array.isArray(data)) {
            setProfiles(data)
            if (data.length) {
              setSelectedProfile((prev) => prev || data[0].name)
            }
          }
        } catch {
          // Ignore non-profile storage responses.
        }
      }
      ws.onclose = () => {
        reconnectTimer = window.setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      if (ws) ws.close()
      if (reconnectTimer != null) window.clearTimeout(reconnectTimer)
    }
  }, [demoMode, monitorToken])

  const sendCmd = async (payload: Record<string, unknown>) => {
    if (demoMode) {
      setApiState(`Demo command: ${String(payload.cmd)}`)
      addEvent('info', `Demo command executed: ${String(payload.cmd)}`)
      return
    }
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (controlToken.trim()) {
        headers['X-API-Token'] = controlToken.trim()
      }
      const resp = await fetch('/api', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      })
      const data = (await resp.json()) as { success?: boolean; error?: string }
      if (data.success === false) {
        setApiState(data.error ?? 'Command failed')
        addEvent('error', data.error ?? `Command failed: ${String(payload.cmd)}`)
      } else {
        setApiState('Command sent')
        addEvent('info', `Command sent: ${String(payload.cmd)}`)
      }
    } catch {
      setApiState('API request failed')
      addEvent('error', `API request failed: ${String(payload.cmd)}`)
    }
  }

  const fetchRunHealth = async () => {
    if (demoMode) {
      const demoRows: RunHealthEntry[] = Array.from({ length: 24 }).map((_, i) => ({
        run_id: `demo-${i + 1}`,
        ended_at: new Date(Date.now() - (24 - i) * 86400000).toISOString(),
        profile: i % 2 ? 'cone-6-long-glaze' : 'cone-05-fast-bisque',
        reason: 'schedule_complete',
        runtime_hours: 9 + Math.sin(i / 5) * 0.9,
        max_temp_gap_to_peak_target: 3 + i * 0.3 + Math.sin(i / 2),
        high_temp_duty_pct: 46 + i * 0.5 + Math.sin(i / 3) * 2.5,
        within_5deg_pct: 87 - i * 0.45 + Math.cos(i / 4) * 1.2,
        switches_per_hour: 95 + Math.sin(i / 6) * 14,
        excluded: i % 9 === 0
      }))
      const filtered = healthIncludeExcluded ? demoRows.slice(-healthLimit) : demoRows.filter((r) => !r.excluded).slice(-healthLimit)
      setHealthRows(filtered)
      return
    }
    setHealthLoading(true)
    setHealthError('')
    try {
      const token = monitorToken.trim() || controlToken.trim()
      const params = new URLSearchParams({
        limit: String(healthLimit),
        include_excluded: healthIncludeExcluded ? '1' : '0'
      })
      const resp = await fetch(`/api/run-health?${params.toString()}`, {
        headers: token ? { 'X-API-Token': token } : {}
      })
      const data = (await resp.json()) as { success?: boolean; rows?: RunHealthEntry[]; error?: string }
      if (!data.success) {
        setHealthError(data.error ?? 'Failed to load run health history')
        return
      }
      setHealthRows(data.rows ?? [])
    } catch {
      setHealthError('Failed to load run health history')
    } finally {
      setHealthLoading(false)
    }
  }

  const setRunExcluded = async (runId: string, excluded: boolean) => {
    if (demoMode) {
      setHealthRows((prev) => prev.map((r) => (r.run_id === runId ? { ...r, excluded } : r)))
      return
    }
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (controlToken.trim()) {
        headers['X-API-Token'] = controlToken.trim()
      }
      const resp = await fetch('/api/run-health/exclusions', {
        method: 'POST',
        headers,
        body: JSON.stringify({ run_id: runId, excluded })
      })
      const data = (await resp.json()) as { success?: boolean; error?: string }
      if (!data.success) {
        setHealthError(data.error ?? 'Failed to update exclusion')
        return
      }
      fetchRunHealth()
    } catch {
      setHealthError('Failed to update exclusion')
    }
  }

  const streamState = useMemo(() => {
    if (!lastMessageAt) return 'waiting'
    return clockTick - lastMessageAt <= 5000 ? 'live' : 'stale'
  }, [clockTick, lastMessageAt])

  useEffect(() => {
    fetchRunHealth()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoMode, healthLimit, healthIncludeExcluded, monitorToken, controlToken])

  const stats = useMemo(() => {
    const telemetry = status.telemetry ?? {}

    let fallbackErrorAvg5m = 0
    let fallbackAbsErrorAvg5m = 0
    let fallbackWithin5 = 0
    let fallbackSwitches5m = 0
    let fallbackDuty5m = 0

    if (samples.length > 0) {
      const errs = samples.map((s) => s.error)
      fallbackErrorAvg5m = errs.reduce((a, b) => a + b, 0) / errs.length
      fallbackAbsErrorAvg5m = errs.reduce((a, b) => a + Math.abs(b), 0) / errs.length
      fallbackWithin5 = (errs.filter((x) => Math.abs(x) <= 5).length / errs.length) * 100
      fallbackDuty5m = (samples.reduce((a, b) => a + b.heatOn, 0) / samples.length) * 100

      let switches = 0
      for (let i = 1; i < samples.length; i += 1) {
        if (samples[i].heatOn !== samples[i - 1].heatOn) switches += 1
      }
      fallbackSwitches5m = switches
    }

    return {
      error5m: telemetry.error_avg_5m ?? fallbackErrorAvg5m,
      mae5m: telemetry.error_abs_avg_5m ?? fallbackAbsErrorAvg5m,
      within5m: telemetry.within_5deg_pct_5m ?? fallbackWithin5,
      withinRun: telemetry.within_5deg_pct_run,
      switches5m: telemetry.switches_5m ?? fallbackSwitches5m,
      switchesHr: telemetry.switches_per_hour_run,
      duty5m: telemetry.duty_cycle_5m ?? fallbackDuty5m,
      overshootRun: telemetry.overshoot_max_run,
      sensorErr5m: telemetry.sensor_error_rate_5m,
      catchupRun: telemetry.time_catching_up_pct_run
    }
  }, [samples, status.telemetry])

  const activeProfile = useMemo(
    () => profiles.find((p) => p.name === selectedProfile),
    [profiles, selectedProfile]
  )
  const runProfile = useMemo(() => {
    const activeName = status.profile?.trim()
    if (activeName) {
      return profiles.find((p) => p.name === activeName) ?? activeProfile
    }
    return activeProfile
  }, [activeProfile, profiles, status.profile])
  const runDurationHours = useMemo(() => {
    const runtimeHoursFromState = status.totaltime ? status.totaltime / 3600 : 0
    const runtimeHoursFromSensor = runPoints[runPoints.length - 1]?.runtimeHours ?? 0
    const profileEndSec = runProfile && runProfile.data.length ? runProfile.data[runProfile.data.length - 1][0] : 0
    const runtimeHoursFromProfile = profileEndSec / 3600
    return Math.max(0.1, runtimeHoursFromState, runtimeHoursFromSensor, runtimeHoursFromProfile)
  }, [runPoints, runProfile, status.totaltime])

  const builderResult = useMemo(() => buildPointsFromBuilder(), [builderStartTemp, builderSegments])
  const builderPoints = builderResult.points

  const onApplyBuilderToPreview = () => {
    if (builderResult.error) {
      setBuilderError(builderResult.error)
      setApiState(builderResult.error)
      return
    }
    const previewProfile: Profile = {
      name: builderName.trim() || 'new-schedule',
      data: builderPoints
    }
    setProfiles((prev) => {
      const idx = prev.findIndex((p) => p.name === previewProfile.name)
      if (idx >= 0) {
        const copy = [...prev]
        copy[idx] = previewProfile
        return copy
      }
      return [...prev, previewProfile]
    })
    setSelectedProfile(previewProfile.name)
    setBuilderError('')
    setApiState('Builder points loaded into profile preview')
  }

  const saveProfileOverStorage = async (profile: Profile, force = false): Promise<{ ok: boolean; error?: string }> => {
    return new Promise((resolve) => {
      let closed = false
      const token = controlToken.trim()
      const ws = new WebSocket(getWsUrl('/storage', token))
      const timeout = window.setTimeout(() => {
        if (closed) return
        closed = true
        try {
          ws.close()
        } catch {
          // ignore
        }
        resolve({ ok: false, error: 'Storage save timed out' })
      }, 6000)

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            cmd: 'PUT',
            profile: {
              type: 'profile',
              data: profile.data,
              name: profile.name
            },
            force
          })
        )
      }

      ws.onmessage = (event) => {
        let resp: unknown = null
        try {
          resp = JSON.parse(event.data)
        } catch {
          // ignore plain messages
        }
        if (closed) return

        const parsed = resp as { resp?: string; error?: string } | null
        if (parsed && parsed.resp === 'OK') {
          closed = true
          window.clearTimeout(timeout)
          ws.close()
          resolve({ ok: true })
          return
        }
        if (parsed && parsed.resp === 'FAIL') {
          closed = true
          window.clearTimeout(timeout)
          ws.close()
          resolve({ ok: false, error: parsed.error || 'Profile exists' })
        }
      }

      ws.onerror = () => {
        if (closed) return
        closed = true
        window.clearTimeout(timeout)
        resolve({ ok: false, error: 'Storage websocket error' })
      }
    })
  }

  const onSaveBuilderProfile = async () => {
    const name = builderName.trim()
    if (!name) {
      setBuilderError('Profile name is required.')
      return
    }
    if (builderResult.error) {
      setBuilderError(builderResult.error)
      return
    }
    const profile: Profile = { name, data: builderPoints }
    setBuilderSaving(true)
    try {
      if (demoMode) {
        setProfiles((prev) => {
          const idx = prev.findIndex((p) => p.name === name)
          if (idx >= 0) {
            const copy = [...prev]
            copy[idx] = profile
            return copy
          }
          return [...prev, profile]
        })
        setSelectedProfile(name)
        setBuilderError('')
        setApiState('Demo: builder profile saved locally')
        addEvent('info', `Builder saved profile "${name}" (demo mode)`)
        return
      }

      let result = await saveProfileOverStorage(profile, false)
      if (!result.ok && result.error === 'Profile exists') {
        if (!window.confirm(`Profile "${name}" already exists. Overwrite it?`)) {
          setBuilderError('Save canceled. Choose a different profile name.')
          return
        }
        result = await saveProfileOverStorage(profile, true)
      }

      if (!result.ok) {
        setBuilderError(result.error || 'Failed to save profile')
        setApiState(result.error || 'Failed to save profile')
        addEvent('error', `Builder save failed: ${result.error || 'unknown error'}`)
        return
      }

      setProfiles((prev) => {
        const idx = prev.findIndex((p) => p.name === name)
        if (idx >= 0) {
          const copy = [...prev]
          copy[idx] = profile
          return copy
        }
        return [...prev, profile]
      })
      setSelectedProfile(name)
      setBuilderError('')
      setApiState(`Saved profile "${name}"`)
      addEvent('info', `Builder saved profile "${name}"`)
    } finally {
      setBuilderSaving(false)
    }
  }

  const kilnState = status.state ?? 'IDLE'
  const isRunning = kilnState === 'RUNNING'
  const isPaused = kilnState === 'PAUSED'
  const canStart = kilnState === 'IDLE' || kilnState === 'PAUSED'
  const canPause = isRunning
  const canResume = isPaused
  const canStop = isRunning || isPaused

  const validateProfile = (profile: Profile): string[] => {
    const errs: string[] = []
    if (!profile.data || profile.data.length < 2) {
      errs.push('Profile needs at least 2 points.')
      return errs
    }

    let prevTime = -1
    for (let i = 0; i < profile.data.length; i += 1) {
      const [time, temp] = profile.data[i]
      if (!Number.isFinite(time) || !Number.isFinite(temp)) {
        errs.push(`Point ${i + 1} has invalid numeric values.`)
        continue
      }
      if (time <= prevTime) {
        errs.push(`Point ${i + 1} time must be greater than previous point.`)
      }
      prevTime = time

      if (i > 0) {
        const [prevT, prevTemp] = profile.data[i - 1]
        const dt = time - prevT
        if (dt > 0) {
          const slopePerHour = Math.abs(((temp - prevTemp) / dt) * 3600)
          if (slopePerHour > 1200) {
            errs.push(`Point ${i + 1} has extreme slope (${Math.round(slopePerHour)}°/h).`)
          }
        }
      }
    }
    return errs
  }

  const onStart = async () => {
    if (!activeProfile) {
      setApiState('Select a profile before starting.')
      return
    }
    const validationErrors = validateProfile(activeProfile)
    if (validationErrors.length) {
      setApiState(validationErrors[0])
      addEvent('error', `Start blocked: ${validationErrors[0]}`)
      return
    }
    if (!window.confirm(`Start profile "${activeProfile.name}" at minute ${startAtMinutes}?`)) {
      return
    }
    await sendCmd({ cmd: 'run', profile: selectedProfile, startat: startAtMinutes })
  }

  const onSaveToken = () => {
    window.localStorage.setItem('kiln_monitor_token', monitorToken)
    window.localStorage.setItem('kiln_api_token', controlToken)
    setApiState('Monitor/control tokens saved locally in browser')
  }

  const onPause = async () => {
    if (!window.confirm('Pause run and hold current temperature?')) return
    await sendCmd({ cmd: 'pause' })
  }

  const onResume = async () => {
    if (!window.confirm('Resume paused run?')) return
    await sendCmd({ cmd: 'resume' })
  }

  const onStop = async () => {
    if (!window.confirm('Stop the current run now?')) return
    await sendCmd({ cmd: 'stop' })
  }

  const sensorErr = status.telemetry?.sensor_error_rate_5m ?? 0
  const hasFault = streamState === 'stale' || sensorErr > 30

  const errorPoints = useMemo(() => {
    const min = Math.min(0, ...samples.map((s) => s.error), -5)
    const max = Math.max(0, ...samples.map((s) => s.error), 5)
    return polyline(samples, 560, 140, (s) => s.error, min, max)
  }, [samples])

  const switchPoints = useMemo(
    () => polyline(samples, 560, 100, (s) => s.heatOn, 0, 1),
    [samples]
  )

  const runChart = useMemo(() => {
    const width = 940
    const height = 250
    const plotLeft = 56
    const plotRight = 16
    const plotWidth = width - plotLeft - plotRight
    const xMaxHours = runDurationHours
    const startH = Math.max(0, Math.min(viewStartHour, xMaxHours - 0.01))
    const endH = Math.max(startH + 0.01, Math.min(viewEndHour, xMaxHours))
    const sensorSource = runPoints.filter((p) => p.runtimeHours >= startH && p.runtimeHours <= endH)
    const profileSource = (runProfile?.data ?? []).map(([sec, target]) => ({ runtimeHours: sec / 3600, target }))

    const targetAtRuntime = (runtimeHours: number): number | null => {
      if (!profileSource.length) return null
      if (runtimeHours <= profileSource[0].runtimeHours) return profileSource[0].target
      for (let i = 1; i < profileSource.length; i += 1) {
        const left = profileSource[i - 1]
        const right = profileSource[i]
        if (runtimeHours <= right.runtimeHours) {
          const span = Math.max(0.0001, right.runtimeHours - left.runtimeHours)
          const f = (runtimeHours - left.runtimeHours) / span
          return left.target + (right.target - left.target) * f
        }
      }
      return profileSource[profileSource.length - 1].target
    }

    const targetSeries = profileSource.length
      ? Array.from({ length: Math.max(8, Math.ceil((endH - startH) * 60)) + 1 }).map((_, i, arr) => {
          const h = startH + ((endH - startH) * i) / Math.max(1, arr.length - 1)
          return { runtimeHours: h, target: targetAtRuntime(h) ?? profileSource[profileSource.length - 1].target }
        })
      : sensorSource.map((p) => ({ runtimeHours: p.runtimeHours, target: p.target }))

    const yValues = [
      ...sensorSource.map((p) => p.temperature),
      ...targetSeries.map((p) => p.target)
    ]
    if (!yValues.length) {
      return {
        width,
        height,
        plotLeft,
        plotWidth,
        tempPoints: '',
        targetPoints: '',
        tickData: [] as Array<{ x: number; h: string; clock: string }>,
        yTicks: [] as Array<{ y: number; label: string }>,
        hover: null as null | { x: number; yTemp: number | null; yTarget: number; label: string; temp: number | null; target: number; error: number | null }
      }
    }

    const minTemp = Math.min(...yValues)
    const maxTemp = Math.max(...yValues)
    const range = Math.max(20, maxTemp - minTemp)
    const yMin = minTemp - range * 0.08
    const yMax = maxTemp + range * 0.08

    const mapX = (h: number) => plotLeft + (((h - startH) / (endH - startH)) * plotWidth)
    const mapY = (t: number) => height - ((t - yMin) / (yMax - yMin)) * height

    const tempPoints = sensorSource.map((p) => `${mapX(p.runtimeHours).toFixed(1)},${mapY(p.temperature).toFixed(1)}`).join(' ')
    const targetPoints = targetSeries.map((p) => `${mapX(p.runtimeHours).toFixed(1)},${mapY(p.target).toFixed(1)}`).join(' ')

    const ticks = 6
    const first = runPoints[0]
    const estimatedStart = first ? first.clockSec - first.runtimeHours * 3600 : Date.now() / 1000
    const tickData = Array.from({ length: ticks + 1 }).map((_, idx) => {
      const h = startH + ((endH - startH) / ticks) * idx
      const x = mapX(h)
      const clock = new Date((estimatedStart + h * 3600) * 1000)
      const hh = String(clock.getHours()).padStart(2, '0')
      const mm = String(clock.getMinutes()).padStart(2, '0')
      return {
        x,
        h: `${h.toFixed(1)}h`,
        clock: `${hh}:${mm}`
      }
    })

    const yTicks = Array.from({ length: 5 }).map((_, idx) => {
      const f = idx / 4
      const temp = yMax - (yMax - yMin) * f
      return { y: mapY(temp), label: temp.toFixed(0) }
    })

    let hover = null as null | { x: number; yTemp: number | null; yTarget: number; label: string; temp: number | null; target: number; error: number | null }
    if (hoverRuntimeHour != null) {
      let nearestSensor: RunPoint | null = null
      const latestRuntime = runPoints[runPoints.length - 1]?.runtimeHours ?? -1
      if (runPoints.length && hoverRuntimeHour <= latestRuntime + 0.01) {
        nearestSensor = runPoints[0]
        let best = Math.abs(runPoints[0].runtimeHours - hoverRuntimeHour)
        for (let i = 1; i < runPoints.length; i += 1) {
          const d = Math.abs(runPoints[i].runtimeHours - hoverRuntimeHour)
          if (d < best) {
            best = d
            nearestSensor = runPoints[i]
          }
        }
      }

      const target = targetAtRuntime(hoverRuntimeHour) ?? (nearestSensor?.target ?? 0)
      const clock = new Date((estimatedStart + hoverRuntimeHour * 3600) * 1000)
      const hh = String(clock.getHours()).padStart(2, '0')
      const mm = String(clock.getMinutes()).padStart(2, '0')
      hover = {
        x: mapX(hoverRuntimeHour),
        yTemp: nearestSensor ? mapY(nearestSensor.temperature) : null,
        yTarget: mapY(target),
        label: `${hoverRuntimeHour.toFixed(2)}h | ${hh}:${mm}`,
        temp: nearestSensor ? nearestSensor.temperature : null,
        target,
        error: nearestSensor ? target - nearestSensor.temperature : null
      }
    }

    return { width, height, plotLeft, plotWidth, tempPoints, targetPoints, tickData, yTicks, hover }
  }, [hoverRuntimeHour, runDurationHours, runPoints, runProfile, viewEndHour, viewStartHour])

  const powerChart = useMemo(() => {
    const width = 940
    const height = 150
    const plotLeft = 56
    const plotRight = 16
    const plotWidth = width - plotLeft - plotRight
    const xMaxHours = runDurationHours
    const startH = Math.max(0, Math.min(viewStartHour, xMaxHours - 0.01))
    const endH = Math.max(startH + 0.01, Math.min(viewEndHour, xMaxHours))
    const source = powerPoints.filter((p) => p.runtimeHours >= startH && p.runtimeHours <= endH)

    const mapX = (h: number) => plotLeft + (((h - startH) / (endH - startH)) * plotWidth)
    const buildSeries = (valueOf: (p: PowerPoint) => number | null) =>
      source
        .filter((p) => valueOf(p) != null)
        .map((p) => ({ runtimeHours: p.runtimeHours, value: valueOf(p)! }))

    const currentSeries = buildSeries((p) => p.current)
    const voltageSeries = buildSeries((p) => p.voltage)

    const mapFor = (series: Array<{ runtimeHours: number; value: number }>, minFloor: number) => {
      if (!series.length) {
        return { points: '', ticks: [] as Array<{ y: number; label: string }>, mapY: (_v: number) => height }
      }
      const minV = Math.min(minFloor, ...series.map((p) => p.value))
      const maxV = Math.max(...series.map((p) => p.value))
      const span = Math.max(0.5, maxV - minV)
      const yMin = minV - span * 0.1
      const yMax = maxV + span * 0.1
      const mapY = (v: number) => height - ((v - yMin) / (yMax - yMin)) * height
      const points = series.map((p) => `${mapX(p.runtimeHours).toFixed(1)},${mapY(p.value).toFixed(1)}`).join(' ')
      const ticks = Array.from({ length: 4 }).map((_, idx) => {
        const f = idx / 3
        const value = yMax - (yMax - yMin) * f
        return { y: mapY(value), label: value.toFixed(1) }
      })
      return { points, ticks, mapY }
    }

    const currentPlot = mapFor(currentSeries, 0)
    const voltagePlot = mapFor(voltageSeries, 220)

    const ticks = 6
    const first = powerPoints[0] ?? runPoints[0]
    const estimatedStart = first ? first.clockSec - first.runtimeHours * 3600 : Date.now() / 1000
    const tickData = Array.from({ length: ticks + 1 }).map((_, idx) => {
      const h = startH + ((endH - startH) / ticks) * idx
      const x = mapX(h)
      const clock = new Date((estimatedStart + h * 3600) * 1000)
      const hh = String(clock.getHours()).padStart(2, '0')
      const mm = String(clock.getMinutes()).padStart(2, '0')
      return { x, h: `${h.toFixed(1)}h`, clock: `${hh}:${mm}` }
    })

    let hover = null as null | { x: number; current: number | null; voltage: number | null; label: string }
    if (hoverRuntimeHour != null && source.length) {
      let nearest = source[0]
      let best = Math.abs(source[0].runtimeHours - hoverRuntimeHour)
      for (let i = 1; i < source.length; i += 1) {
        const d = Math.abs(source[i].runtimeHours - hoverRuntimeHour)
        if (d < best) {
          best = d
          nearest = source[i]
        }
      }
      const clock = new Date(nearest.clockSec * 1000)
      const hh = String(clock.getHours()).padStart(2, '0')
      const mm = String(clock.getMinutes()).padStart(2, '0')
      hover = {
        x: mapX(nearest.runtimeHours),
        current: nearest.current,
        voltage: nearest.voltage,
        label: `${nearest.runtimeHours.toFixed(2)}h | ${hh}:${mm}`
      }
    }

    return {
      width,
      height,
      plotLeft,
      plotWidth,
      tickData,
      currentPoints: currentPlot.points,
      voltagePoints: voltagePlot.points,
      currentTicks: currentPlot.ticks,
      voltageTicks: voltagePlot.ticks,
      hover
    }
  }, [hoverRuntimeHour, powerPoints, runDurationHours, runPoints, viewEndHour, viewStartHour])

  const healthTrend = useMemo(() => {
    const width = 940
    const height = 190
    const left = 46
    const right = 10
    const plotWidth = width - left - right
    const plotHeight = height - 20
    const rows = [...healthRows]
    if (rows.length < 2) {
      return {
        width,
        height,
        left,
        plotWidth,
        gapPath: '',
        dutyPath: '',
        withinPath: '',
        switchPath: '',
        currentPath: '',
        noCurrentPath: '',
        xLabels: [] as Array<{ x: number; label: string }>
      }
    }

    const toPoints = (getY: (r: RunHealthEntry) => number): TrendPoint[] =>
      rows.map((r, idx) => ({ x: idx, y: getY(r) }))

    const normPath = (points: TrendPoint[]): string => {
      const ys = points.map((p) => p.y)
      const yMin = Math.min(...ys)
      const yMax = Math.max(...ys)
      const span = Math.max(0.001, yMax - yMin)
      return points
        .map((p, idx) => {
          const x = left + (idx / (points.length - 1)) * plotWidth
          const y = plotHeight - ((p.y - yMin) / span) * (plotHeight - 6)
          return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    }

    const gap = toPoints((r) => r.max_temp_gap_to_peak_target ?? 0)
    const duty = toPoints((r) => r.high_temp_duty_pct ?? 0)
    const within = toPoints((r) => r.within_5deg_pct ?? 0)
    const switches = toPoints((r) => r.switches_per_hour ?? 0)
    const lineCurrent = toPoints((r) => r.line_current_avg_run ?? 0)
    const noCurrent = toPoints((r) => r.no_current_when_heating_pct ?? 0)

    const labelIdx = [0, Math.floor((rows.length - 1) / 2), rows.length - 1]
    const xLabels = labelIdx.map((idx) => {
      const x = left + (idx / Math.max(1, rows.length - 1)) * plotWidth
      const d = rows[idx].ended_at ? new Date(rows[idx].ended_at as string) : null
      const label = d ? `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}` : `#${idx + 1}`
      return { x, label }
    })

    return {
      width,
      height,
      left,
      plotWidth,
      gapPath: normPath(gap),
      dutyPath: normPath(duty),
      withinPath: normPath(within),
      switchPath: normPath(switches),
      currentPath: normPath(lineCurrent),
      noCurrentPath: normPath(noCurrent),
      xLabels
    }
  }, [healthRows])

  useEffect(() => {
    const xMax = runDurationHours
    setViewEndHour((prev) => {
      if (prev <= 0 || prev > xMax) return xMax
      return prev
    })
    setViewStartHour((prev) => Math.max(0, Math.min(prev, xMax - 0.01)))
  }, [runDurationHours])

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Kiln UI v2</h1>
          <p>{demoMode ? 'Demo telemetry dashboard' : 'Live telemetry dashboard'}</p>
        </div>
        <div className={`pill ${streamState}`}>Stream: {streamState}</div>
      </header>

      {hasFault ? (
        <section className="banner">
          {streamState === 'stale' ? 'Telemetry stream is stale. Control with caution.' : null}
          {streamState === 'stale' && sensorErr > 30 ? ' | ' : null}
          {sensorErr > 30 ? `Sensor error rate elevated: ${sensorErr.toFixed(1)}%` : null}
        </section>
      ) : null}

      <nav className="tabbar" aria-label="Dashboard sections">
        <button
          type="button"
          className={`tabbtn ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          Dashboard
        </button>
        <button
          type="button"
          className={`tabbtn ${activeTab === 'builder' ? 'active' : ''}`}
          onClick={() => setActiveTab('builder')}
        >
          Schedule Builder
        </button>
        <button
          type="button"
          className={`tabbtn ${activeTab === 'health' ? 'active' : ''}`}
          onClick={() => setActiveTab('health')}
        >
          Health Trends
        </button>
      </nav>

      {activeTab === 'dashboard' ? (
      <section className="grid stats-grid">
        <article className="card">
          <h3>Temperature</h3>
          <p className="big">{round(status.pidstats?.ispoint ?? status.temperature, 1)}</p>
        </article>
        <article className="card">
          <h3>Target</h3>
          <p className="big">{round(status.pidstats?.setpoint ?? status.target, 1)}</p>
        </article>
        <article className="card">
          <h3>Error Avg 5m</h3>
          <p className="big">{round(stats.error5m, 2)}</p>
        </article>
        <article className="card">
          <h3>MAE 5m</h3>
          <p className="big">{round(stats.mae5m, 2)}</p>
        </article>
        <article className="card">
          <h3>Within ±5° (5m)</h3>
          <p className="big">{pct(stats.within5m)}</p>
        </article>
        <article className="card">
          <h3>Within ±5° (run)</h3>
          <p className="big">{pct(stats.withinRun)}</p>
        </article>
        <article className="card">
          <h3>Switches 5m</h3>
          <p className="big">{round(stats.switches5m, 0)}</p>
        </article>
        <article className="card">
          <h3>Switches/hr</h3>
          <p className="big">{round(stats.switchesHr, 1)}</p>
        </article>
        <article className="card">
          <h3>Duty 5m</h3>
          <p className="big">{pct(stats.duty5m)}</p>
        </article>
        <article className="card">
          <h3>Overshoot Run</h3>
          <p className="big">{round(stats.overshootRun, 2)}</p>
        </article>
        <article className="card">
          <h3>Sensor Err 5m</h3>
          <p className="big">{pct(stats.sensorErr5m)}</p>
        </article>
        <article className="card">
          <h3>Catch-up Run</h3>
          <p className="big">{pct(stats.catchupRun)}</p>
        </article>
      </section>
      ) : null}

      {activeTab === 'dashboard' ? (
      <section className="card controls">
        <h3>Run Controls</h3>
        <p className="state-chip">Kiln state: {kilnState}</p>
        <div className="controls-row token-row">
          <label htmlFor="monitor-token">Monitor Token</label>
          <input
            id="monitor-token"
            type="password"
            value={monitorToken}
            onChange={(e) => setMonitorToken(e.target.value)}
            placeholder="optional"
          />
          <label htmlFor="control-token">Control Token</label>
          <input
            id="control-token"
            type="password"
            value={controlToken}
            onChange={(e) => setControlToken(e.target.value)}
            placeholder="optional"
          />
          <button type="button" onClick={onSaveToken}>
            Save Token
          </button>
        </div>
        <div className="controls-row">
          <label htmlFor="profile-select">Profile</label>
          <select
            id="profile-select"
            value={selectedProfile}
            onChange={(e) => setSelectedProfile(e.target.value)}
          >
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
          <label htmlFor="start-at">Start At (min)</label>
          <input
            id="start-at"
            type="number"
            min={0}
            step={1}
            value={startAtMinutes}
            onChange={(e) => setStartAtMinutes(Math.max(0, Number(e.target.value) || 0))}
          />
          <button
            type="button"
            onClick={onStart}
            disabled={!selectedProfile || !canStart}
          >
            Start
          </button>
          <button type="button" onClick={onPause} disabled={!canPause}>
            Pause
          </button>
          <button type="button" onClick={onResume} disabled={!canResume}>
            Resume
          </button>
          <button type="button" className="danger" onClick={onStop} disabled={!canStop}>
            Stop
          </button>
        </div>
        <p className="api-state">{apiState}</p>
      </section>
      ) : null}

      {activeTab === 'dashboard' ? (
      <section className="grid chart-grid">
        <article className="card chart-card">
          <h3>Full Run Plot (Temp + Target)</h3>
          <div className="chart-tools">
            <label htmlFor="chart-start-hour">Start (h)</label>
            <input
              id="chart-start-hour"
              type="number"
              min={0}
              max={Math.max(0, runDurationHours - 0.01)}
              step={0.25}
              value={viewStartHour}
              onChange={(e) => {
                const requested = Math.max(0, Number(e.target.value) || 0)
                const span = Math.max(0.01, viewEndHour - viewStartHour)
                const nextStart = Math.min(requested, Math.max(0, runDurationHours - 0.01))
                const nextEnd = Math.min(runDurationHours, Math.max(nextStart + 0.01, nextStart + span))
                setViewStartHour(nextStart)
                setViewEndHour(nextEnd)
              }}
            />
            <label htmlFor="chart-end-hour">End (h)</label>
            <input
              id="chart-end-hour"
              type="number"
              min={Math.min(runDurationHours, viewStartHour + 0.01)}
              max={runDurationHours}
              step={0.25}
              value={viewEndHour}
              onChange={(e) => {
                const requested = Number(e.target.value) || runDurationHours
                const nextEnd = Math.max(viewStartHour + 0.01, Math.min(requested, runDurationHours))
                setViewEndHour(nextEnd)
              }}
            />
            <button
              type="button"
              onClick={() => {
                const currentRuntime = runPoints[runPoints.length - 1]?.runtimeHours ?? runDurationHours
                const span = Math.max(0.5, viewEndHour - viewStartHour)
                const nextEnd = Math.min(runDurationHours, currentRuntime + 0.1)
                const nextStart = Math.max(0, nextEnd - span)
                setViewStartHour(nextStart)
                setViewEndHour(nextEnd)
              }}
            >
              Follow Live
            </button>
            <button
              type="button"
              onClick={() => {
                const max = runDurationHours
                setViewStartHour(0)
                setViewEndHour(max)
              }}
            >
              Full Run
            </button>
          </div>
          <svg
            viewBox={`0 0 ${runChart.width} ${runChart.height + 64}`}
            className="chart-svg"
            aria-label="Full run chart"
            onMouseMove={(e) => {
              const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
              const x = e.clientX - rect.left
              const plotX = Math.max(runChart.plotLeft, Math.min(runChart.plotLeft + runChart.plotWidth, (x / rect.width) * runChart.width))
              const h = viewStartHour + ((plotX - runChart.plotLeft) / runChart.plotWidth) * (viewEndHour - viewStartHour)
              setHoverRuntimeHour(h)
            }}
            onMouseLeave={() => setHoverRuntimeHour(null)}
          >
            <polyline points={runChart.targetPoints} className="target-line" fill="none" />
            <polyline points={runChart.tempPoints} className="temp-line" fill="none" />
            {runChart.yTicks.map((t) => (
              <g key={`y-${t.y}-${t.label}`}>
                <line x1={runChart.plotLeft} y1={t.y} x2={runChart.plotLeft + runChart.plotWidth} y2={t.y} className="grid-line-h" />
                <text x={runChart.plotLeft - 8} y={t.y + 3} textAnchor="end" className="axis-text-sub">
                  {t.label}
                </text>
              </g>
            ))}
            {runChart.tickData.map((tick) => (
              <g key={`${tick.x}-${tick.h}`}>
                <line x1={tick.x} y1={0} x2={tick.x} y2={runChart.height} className="grid-line" />
                <text x={tick.x} y={runChart.height + 18} textAnchor="middle" className="axis-text">
                  {tick.h}
                </text>
                <text x={tick.x} y={runChart.height + 36} textAnchor="middle" className="axis-text-sub">
                  {tick.clock}
                </text>
              </g>
            ))}
            {runChart.hover ? (
              <line x1={runChart.hover.x} y1={0} x2={runChart.hover.x} y2={runChart.height} className="cursor-line" />
            ) : null}
          </svg>
          {runChart.hover ? (
            <p className="hover-readout">
              {runChart.hover.label} | Temp {runChart.hover.temp != null ? runChart.hover.temp.toFixed(1) : '--'} | Target {runChart.hover.target.toFixed(1)} | Error {runChart.hover.error != null ? runChart.hover.error.toFixed(1) : '--'}
            </p>
          ) : (
            <p className="hover-readout">Move cursor over chart for exact time/temp readout.</p>
          )}
          <div className="legend">
            <span className="legend-item"><i className="legend-swatch target" /> Target</span>
            <span className="legend-item"><i className="legend-swatch temp" /> Temperature</span>
          </div>
        </article>

        <article className="card chart-card">
          <h3>Line Current / Voltage (Full Run Window)</h3>
          <p className="mini-chart-title">Current (A)</p>
          <svg viewBox={`0 0 ${powerChart.width} ${powerChart.height}`} className="chart-svg" aria-label="Line current chart">
            <polyline points={powerChart.currentPoints} className="current-line" fill="none" />
            {powerChart.currentTicks.map((t) => (
              <g key={`cy-${t.y}-${t.label}`}>
                <line x1={powerChart.plotLeft} y1={t.y} x2={powerChart.plotLeft + powerChart.plotWidth} y2={t.y} className="grid-line-h" />
                <text x={powerChart.plotLeft - 8} y={t.y + 3} textAnchor="end" className="axis-text-sub">{t.label}</text>
              </g>
            ))}
            {powerChart.tickData.map((tick) => (
              <line key={`cx-${tick.x}`} x1={tick.x} y1={0} x2={tick.x} y2={powerChart.height} className="grid-line" />
            ))}
            {powerChart.hover ? (
              <line x1={powerChart.hover.x} y1={0} x2={powerChart.hover.x} y2={powerChart.height} className="cursor-line" />
            ) : null}
          </svg>

          <p className="mini-chart-title">Voltage (V)</p>
          <svg viewBox={`0 0 ${powerChart.width} ${powerChart.height + 36}`} className="chart-svg" aria-label="Line voltage chart">
            <polyline points={powerChart.voltagePoints} className="voltage-line" fill="none" />
            {powerChart.voltageTicks.map((t) => (
              <g key={`vy-${t.y}-${t.label}`}>
                <line x1={powerChart.plotLeft} y1={t.y} x2={powerChart.plotLeft + powerChart.plotWidth} y2={t.y} className="grid-line-h" />
                <text x={powerChart.plotLeft - 8} y={t.y + 3} textAnchor="end" className="axis-text-sub">{t.label}</text>
              </g>
            ))}
            {powerChart.tickData.map((tick) => (
              <g key={`vx-${tick.x}`}>
                <line x1={tick.x} y1={0} x2={tick.x} y2={powerChart.height} className="grid-line" />
                <text x={tick.x} y={powerChart.height + 18} textAnchor="middle" className="axis-text">{tick.h}</text>
                <text x={tick.x} y={powerChart.height + 33} textAnchor="middle" className="axis-text-sub">{tick.clock}</text>
              </g>
            ))}
            {powerChart.hover ? (
              <line x1={powerChart.hover.x} y1={0} x2={powerChart.hover.x} y2={powerChart.height} className="cursor-line" />
            ) : null}
          </svg>
          {powerChart.hover ? (
            <p className="hover-readout">
              {powerChart.hover.label} | Current {powerChart.hover.current != null ? powerChart.hover.current.toFixed(2) : '--'}A | Voltage {powerChart.hover.voltage != null ? powerChart.hover.voltage.toFixed(1) : '--'}V
            </p>
          ) : (
            <p className="hover-readout">Move cursor over chart for current/voltage readout.</p>
          )}
          <div className="legend">
            <span className="legend-item"><i className="legend-swatch current" /> Current</span>
            <span className="legend-item"><i className="legend-swatch voltage" /> Voltage</span>
          </div>
        </article>

        <article className="card chart-card">
          <h3>Error (Last 5 Minutes)</h3>
          <svg viewBox="0 0 560 140" className="chart-svg" aria-label="Error chart">
            <line x1="0" y1="70" x2="560" y2="70" className="zero-line" />
            <polyline points={errorPoints} className="error-line" fill="none" />
          </svg>
        </article>

        <article className="card chart-card">
          <h3>Relay On/Off (Last 5 Minutes)</h3>
          <svg viewBox="0 0 560 100" className="chart-svg" aria-label="Switch chart">
            <polyline points={switchPoints} className="switch-line" fill="none" />
          </svg>
        </article>
      </section>
      ) : null}

      {activeTab === 'dashboard' ? (
      <section className="card summary-card">
        <h3>Run Summary</h3>
        {runSummary ? (
          <div className="summary-grid">
            <div><strong>Completed</strong><span>{new Date(runSummary.completedAt).toLocaleString()}</span></div>
            <div><strong>Profile</strong><span>{runSummary.profile}</span></div>
            <div><strong>Duration</strong><span>{runSummary.durationHours.toFixed(2)} h</span></div>
            <div><strong>Max Temp</strong><span>{runSummary.maxTemp.toFixed(1)}</span></div>
            <div><strong>Max Overshoot</strong><span>{runSummary.maxOvershoot.toFixed(1)}</span></div>
            <div><strong>Within ±5°</strong><span>{runSummary.within5Run.toFixed(1)}%</span></div>
            <div><strong>Switches/hr</strong><span>{runSummary.switchesPerHour.toFixed(1)}</span></div>
            <div><strong>Cost</strong><span>{runSummary.cost.toFixed(2)}</span></div>
          </div>
        ) : (
          <p className="api-state">No completed run summary yet.</p>
        )}
      </section>
      ) : null}

      {activeTab === 'health' ? (
      <section className="card health-card">
        <h3>Run Health Trends</h3>
        <div className="health-controls">
          <label htmlFor="health-limit">Historical runs</label>
          <input
            id="health-limit"
            type="number"
            min={5}
            max={5000}
            value={healthLimit}
            onChange={(e) => setHealthLimit(Math.max(5, Number(e.target.value) || 40))}
          />
          <label className="inline-check" htmlFor="include-excluded">
            <input
              id="include-excluded"
              type="checkbox"
              checked={healthIncludeExcluded}
              onChange={(e) => setHealthIncludeExcluded(e.target.checked)}
            />
            Include excluded
          </label>
          <button type="button" onClick={fetchRunHealth}>Refresh</button>
        </div>
        {healthLoading ? <p className="api-state">Loading run history...</p> : null}
        {healthError ? <p className="api-state">{healthError}</p> : null}

        <svg viewBox={`0 0 ${healthTrend.width} ${healthTrend.height + 34}`} className="chart-svg" aria-label="Health trend chart">
          <polyline points={healthTrend.gapPath} className="trend-gap" fill="none" />
          <polyline points={healthTrend.dutyPath} className="trend-duty" fill="none" />
          <polyline points={healthTrend.withinPath} className="trend-within" fill="none" />
          <polyline points={healthTrend.switchPath} className="trend-switch" fill="none" />
          <polyline points={healthTrend.currentPath} className="trend-current" fill="none" />
          <polyline points={healthTrend.noCurrentPath} className="trend-nocurrent" fill="none" />
          {healthTrend.xLabels.map((x) => (
            <g key={`${x.x}-${x.label}`}>
              <line x1={x.x} y1={0} x2={x.x} y2={healthTrend.height - 20} className="grid-line" />
              <text x={x.x} y={healthTrend.height + 14} textAnchor="middle" className="axis-text-sub">{x.label}</text>
            </g>
          ))}
        </svg>
        <div className="legend">
          <span className="legend-item"><i className="legend-swatch gap" /> Peak Gap</span>
          <span className="legend-item"><i className="legend-swatch duty" /> High-temp Duty</span>
          <span className="legend-item"><i className="legend-swatch within" /> Within ±5°</span>
          <span className="legend-item"><i className="legend-swatch sw" /> Switches/hr</span>
          <span className="legend-item"><i className="legend-swatch hc" /> Avg Current</span>
          <span className="legend-item"><i className="legend-swatch nc" /> No-current %</span>
        </div>

        <div className="profile-table-wrap">
          <table className="profile-table">
            <thead>
              <tr>
                <th>Exclude</th>
                <th>Ended</th>
                <th>Profile</th>
                <th>Reason</th>
                <th>Peak Gap</th>
                <th>High-temp Duty</th>
                <th>Within ±5°</th>
                <th>Switch/hr</th>
                <th>Avg Current</th>
                <th>Avg Power</th>
                <th>No-current %</th>
              </tr>
            </thead>
            <tbody>
              {healthRows.map((row) => (
                <tr key={row.run_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={!!row.excluded}
                      onChange={(e) => setRunExcluded(row.run_id, e.target.checked)}
                    />
                  </td>
                  <td>{row.ended_at ? new Date(row.ended_at).toLocaleString() : '--'}</td>
                  <td>{row.profile ?? '--'}</td>
                  <td>{row.reason ?? '--'}</td>
                  <td>{row.max_temp_gap_to_peak_target?.toFixed(1) ?? '--'}</td>
                  <td>{row.high_temp_duty_pct?.toFixed(1) ?? '--'}%</td>
                  <td>{row.within_5deg_pct?.toFixed(1) ?? '--'}%</td>
                  <td>{row.switches_per_hour?.toFixed(1) ?? '--'}</td>
                  <td>{row.line_current_avg_run?.toFixed(2) ?? '--'}A</td>
                  <td>{row.line_power_avg_run?.toFixed(0) ?? '--'}W</td>
                  <td>{row.no_current_when_heating_pct?.toFixed(1) ?? '--'}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      ) : null}

      {activeTab === 'dashboard' ? (
      <section className="card profile-card">
        <h3>Profile Preview</h3>
        {activeProfile ? (
          <div className="profile-table-wrap">
            <table className="profile-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Time (s)</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {activeProfile.data.slice(0, 18).map((point, idx) => (
                  <tr key={`${activeProfile.name}-${idx}`}>
                    <td>{idx + 1}</td>
                    <td>{Math.round(point[0])}</td>
                    <td>{Math.round(point[1])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="api-state">No profile selected</p>
        )}
      </section>
      ) : null}

      {activeTab === 'dashboard' ? (
      <section className="card events-card">
        <h3>Event Timeline</h3>
        {events.length === 0 ? (
          <p className="api-state">No events yet</p>
        ) : (
          <ul className="event-list">
            {events.map((evt, idx) => (
              <li key={`${evt.ts}-${idx}`} className={`event ${evt.level}`}>
                <span className="ts">{new Date(evt.ts).toLocaleTimeString()}</span>
                <span>{evt.text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      ) : null}

      {activeTab === 'builder' ? (
      <section className="card builder-card">
        <h3>Schedule Builder</h3>
        <p className="api-state">Create a schedule from target/ramp/hold segments, then save as a profile.</p>
        <div className="builder-grid">
          <label htmlFor="builder-name">Profile Name</label>
          <input
            id="builder-name"
            type="text"
            value={builderName}
            onChange={(e) => setBuilderName(e.target.value)}
            placeholder="cone-6-custom"
          />
          <label htmlFor="builder-start">Start Temp</label>
          <input
            id="builder-start"
            type="number"
            value={builderStartTemp}
            onChange={(e) => setBuilderStartTemp(e.target.value)}
          />
        </div>

        <div className="builder-rows">
          <div className="builder-head">
            <span>Target</span>
            <span>Ramp °/h</span>
            <span>Hold min</span>
            <span />
          </div>
          {builderSegments.map((seg, idx) => (
            <div className="builder-row" key={seg.id}>
              <input
                type="number"
                value={seg.target}
                onChange={(e) => updateBuilderSegment(seg.id, 'target', e.target.value)}
                placeholder={idx === 0 ? 'e.g. 250' : ''}
              />
              <input
                type="number"
                min={0}
                value={seg.ramp}
                onChange={(e) => updateBuilderSegment(seg.id, 'ramp', e.target.value)}
                placeholder="e.g. 200"
              />
              <input
                type="number"
                min={0}
                value={seg.hold}
                onChange={(e) => updateBuilderSegment(seg.id, 'hold', e.target.value)}
                placeholder="0"
              />
              <button
                type="button"
                className="danger"
                onClick={() => removeBuilderSegment(seg.id)}
                disabled={builderSegments.length <= 1}
              >
                Remove
              </button>
            </div>
          ))}
        </div>

        <div className="controls-row builder-actions">
          <button type="button" onClick={addBuilderSegment}>Add Segment</button>
          <button type="button" onClick={onApplyBuilderToPreview}>Preview In Profile Table</button>
          <button type="button" onClick={onSaveBuilderProfile} disabled={builderSaving}>
            {builderSaving ? 'Saving…' : 'Save Profile'}
          </button>
        </div>

        {builderResult.error ? <p className="api-state">{builderResult.error}</p> : null}
        {builderError ? <p className="api-state">{builderError}</p> : null}

        <div className="profile-table-wrap">
          <table className="profile-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Time (s)</th>
                <th>Target</th>
              </tr>
            </thead>
            <tbody>
              {builderPoints.slice(0, 40).map((point, idx) => (
                <tr key={`builder-${idx}`}>
                  <td>{idx + 1}</td>
                  <td>{Math.round(point[0])}</td>
                  <td>{Math.round(point[1])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      ) : null}
    </main>
  )
}
