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
  window_seconds?: number
  error_now?: number
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
  line_voltage_avg_5m?: number
  line_current_avg_5m?: number
  line_power_avg_5m?: number
  line_energy_wh_last_5m?: number
  power_sensor_available?: boolean
  power_sensor_ok?: boolean
  power_sensor_stale_5m?: number
  power_sensor_error_rate_5m?: number
  no_current_when_heating_pct_run?: number
  catchup_supervisor_enabled?: boolean
  catchup_supervisor_mode?: string
  catchup_shadow_state?: string
  catchup_shadow_avg_error_confidence?: number
  catchup_shadow_rise_rate_trend_deg_per_hour?: number
  catchup_shadow_duty_cycle_confidence_pct?: number
  catchup_shadow_lagging_seconds?: number
  catchup_shadow_cusum_deg_seconds?: number
  catchup_shadow_holdoff_active?: boolean
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
  last_run_summary?: RunSummaryMessage
  status_reason?: string
  status_reason_text?: string
  status_reason_kind?: string
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

export interface BacklogMessage {
  type: 'backlog'
  profile?: Profile | null
  log?: StatusMessage[]
}

export interface RunHealthEntry {
  run_id: string
  ended_at?: string
  profile?: string
  reason?: string
  reason_text?: string
  reason_kind?: string
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

export interface RunSummaryMessage {
  run_id?: string
  started_at?: string
  ended_at?: string
  reason?: string
  reason_text?: string
  reason_kind?: string
  profile?: string
  runtime_seconds?: number
  runtime_hours?: number
  cost?: number
  max_temp?: number
  overshoot_max?: number
  within_5deg_pct?: number
  switches_per_hour?: number
}

export interface ConfigMessage {
  temp_scale?: string
  time_scale_slope?: string
  time_scale_profile?: string
  kwh_rate?: number
  currency_type?: string
  hardware?: {
    simulate?: boolean
    relay?: {
      gpio_heat?: string | number | boolean | null
      gpio_heat_invert?: boolean
    }
    buzzer?: {
      gpio_buzzer?: string | number | boolean | null
    }
    spi?: {
      mode?: string
      spi_sclk?: string | number | boolean | null
      spi_mosi?: string | number | boolean | null
      spi_miso?: string | number | boolean | null
      spi_cs?: string | number | boolean | null
    }
    thermocouple?: {
      board?: string
      type?: string | number | boolean | null
      offset?: number
      samples_per_cycle?: number
      sensor_time_wait?: number
    }
    display?: {
      enabled?: boolean
      width?: number
      height?: number
      i2c_address?: string | number | boolean | null
      i2c_port?: number
    }
    power_sensor?: {
      enabled?: boolean
      type?: string | number | boolean | null
      port?: string | number | boolean | null
      baudrate?: number
      address?: number
      poll_interval?: number
      timeout?: number
      stale_seconds?: number
    }
  }
}
