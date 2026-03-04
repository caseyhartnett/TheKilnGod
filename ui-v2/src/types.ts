export interface PidStats {
  time: number
  timeDelta: number
  setpoint: number
  ispoint: number
  err: number
  out: number
  p: number
  i: number
  d: number
}

export interface Telemetry {
  error_avg_1m?: number
  error_avg_5m?: number
  error_abs_avg_5m?: number
  within_5deg_pct_5m?: number
  within_5deg_pct_run?: number
  switches_5m?: number
  switches_per_hour_run?: number
  duty_cycle_5m?: number
  overshoot_max_run?: number
  sensor_error_rate_5m?: number
  time_catching_up_pct_run?: number
  line_voltage_now?: number
  line_current_now?: number
  line_power_now?: number
  line_energy_wh_now?: number
}

export interface StatusMessage {
  temperature?: number
  target?: number
  profile?: string
  state?: string
  heat?: number
  cost?: number
  runtime?: number
  totaltime?: number
  catching_up?: boolean
  pidstats?: PidStats
  telemetry?: Telemetry
}

export interface Sample {
  t: number
  error: number
  heatOn: number
}

export interface Profile {
  name: string
  data: Array<[number, number]>
  temp_units?: string
}

export interface RunHealthEntry {
  run_id: string
  ended_at?: string
  profile?: string
  reason?: string
  runtime_hours?: number
  max_temp_gap_to_peak_target?: number
  high_temp_duty_pct?: number
  within_5deg_pct?: number
  switches_per_hour?: number
  overshoot_max?: number
  line_voltage_avg_run?: number
  line_current_avg_run?: number
  line_power_avg_run?: number
  no_current_when_heating_pct?: number
  power_sensor_stale_pct_run?: number
  excluded?: boolean
}
