import threading
import time
import datetime
import logging
import json
import uuid
import math
from collections import deque
import config
import os
import digitalio
import busio
import adafruit_bitbangio as bitbangio
import statistics
from telemetry_math import avg, bool_pct

log = logging.getLogger(__name__)

class DupFilter(object):
    def __init__(self):
        self.msgs = set()

    def filter(self, record):
        rv = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return rv

class Duplogger():
    def __init__(self):
        self.log = logging.getLogger("%s.dupfree" % (__name__))
        dup_filter = DupFilter()
        self.log.addFilter(dup_filter)
    def logref(self):
        return self.log

duplog = Duplogger().logref()

class Output(object):
    '''This represents a GPIO output that controls a solid
    state relay to turn the kiln elements on and off.
    inputs
        config.gpio_heat
        config.gpio_heat_invert
    '''
    def __init__(self):
        self.active = False
        self.heater = digitalio.DigitalInOut(config.gpio_heat) 
        self.heater.direction = digitalio.Direction.OUTPUT 
        self.off = config.gpio_heat_invert
        self.on = not self.off

    def heat(self,sleepfor):
        self.heater.value = self.on
        time.sleep(sleepfor)

    def cool(self,sleepfor):
        '''no active cooling, so sleep'''
        self.heater.value = self.off
        time.sleep(sleepfor)

# wrapper for blinka board
class Board(object):
    '''This represents a blinka board where this code
    runs.
    '''
    def __init__(self):
        log.info("board: %s" % (self.name))
        self.temp_sensor.start()

class RealBoard(Board):
    '''Each board has a thermocouple board attached to it.
    Any blinka board that supports SPI can be used. The
    board is automatically detected by blinka.
    '''
    def __init__(self):
        self.name = None
        self.load_libs()
        self.temp_sensor = self.choose_tempsensor()
        Board.__init__(self) 

    def load_libs(self):
        import board
        self.name = board.board_id

    def choose_tempsensor(self):
        if config.max31855:
            return Max31855()
        if config.max31856:
            return Max31856()

class SimulatedBoard(Board):
    '''Simulated board used during simulations.
    See config.simulate
    '''
    def __init__(self):
        self.name = "simulated"
        self.temp_sensor = TempSensorSimulated()
        Board.__init__(self) 

class TempSensor(threading.Thread):
    '''Used by the Board class. Each Board must have
    a TempSensor.
    '''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.time_step = config.sensor_time_wait
        self.status = ThermocoupleTracker()

class TempSensorSimulated(TempSensor):
    '''Simulates a temperature sensor '''
    def __init__(self):
        TempSensor.__init__(self)
        self.simulated_temperature = config.sim_t_env
    def temperature(self):
        return self.simulated_temperature

class TempSensorReal(TempSensor):
    '''real temperature sensor that takes many measurements
       during the time_step
       inputs
           config.temperature_average_samples 
    '''
    def __init__(self):
        TempSensor.__init__(self)
        self.sleeptime = self.time_step / float(config.temperature_average_samples)
        self.temptracker = TempTracker() 
        self.spi_setup()
        self.cs = digitalio.DigitalInOut(config.spi_cs)

    def spi_setup(self):
        if(hasattr(config,'spi_sclk') and
           hasattr(config,'spi_mosi') and
           hasattr(config,'spi_miso')):
            self.spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
            log.info("Software SPI selected for reading thermocouple")
        else:
            import board
            self.spi = board.SPI();
            log.info("Hardware SPI selected for reading thermocouple")

    def get_temperature(self):
        '''read temp from tc and convert if needed'''
        try:
            temp = self.raw_temp() # raw_temp provided by subclasses
            if config.temp_scale.lower() == "f":
                temp = (temp*9/5)+32
            self.status.good()
            return temp
        except ThermocoupleError as tce:
            if tce.ignore:
                log.error("Problem reading temp (ignored) %s" % (tce.message))
                self.status.good()
            else:
                log.error("Problem reading temp %s" % (tce.message))
                self.status.bad()
        return None

    def temperature(self):
        '''average temp over a duty cycle'''
        return self.temptracker.get_avg_temp()

    def run(self):
        while True:
            temp = self.get_temperature()
            if temp is not None:  # Fixed: Changed from 'if temp:' to handle 0° as valid temperature
                self.temptracker.add(temp)
            time.sleep(self.sleeptime)

class TempTracker(object):
    '''creates a sliding window of N temperatures per
       config.sensor_time_wait
    '''
    def __init__(self):
        self.size = config.temperature_average_samples
        self.temps = [0 for i in range(self.size)]
  
    def add(self,temp):
        self.temps.append(temp)
        while(len(self.temps) > self.size):
            del self.temps[0]

    def get_avg_temp(self, chop=25):
        '''
        take the median of the given values. this used to take an avg
        after getting rid of outliers. median works better.
        '''
        return statistics.median(self.temps)

class ThermocoupleTracker(object):
    '''Keeps sliding window to track successful/failed calls to get temp
       over the last two duty cycles.
    '''
    def __init__(self):
        self.size = config.temperature_average_samples * 2 
        self.status = [True for i in range(self.size)]
        self.limit = 30

    def good(self):
        '''True is good!'''
        self.status.append(True)
        del self.status[0]

    def bad(self):
        '''False is bad!'''
        self.status.append(False)
        del self.status[0]

    def error_percent(self):
        errors = sum(i == False for i in self.status) 
        return (errors/self.size)*100

    def over_error_limit(self):
        if self.error_percent() > self.limit:
            return True
        return False

class Max31855(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31855")
        import adafruit_max31855
        self.thermocouple = adafruit_max31855.MAX31855(self.spi, self.cs)

    def raw_temp(self):
        try:
            return self.thermocouple.temperature_NIST
        except RuntimeError as rte:
            if rte.args and rte.args[0]:
                raise Max31855_Error(rte.args[0])
            raise Max31855_Error('unknown')

class ThermocoupleError(Exception):
    '''
    thermocouple exception parent class to handle mapping of error messages
    and make them consistent across adafruit libraries. Also set whether
    each exception should be ignored based on settings in config.py.
    '''
    def __init__(self, message):
        self.ignore = False
        self.message = message
        self.map_message()
        self.set_ignore()
        super().__init__(self.message)

    def set_ignore(self):
        if self.message == "not connected" and config.ignore_tc_lost_connection == True:
            self.ignore = True
        if self.message == "short circuit" and config.ignore_tc_short_errors == True:
            self.ignore = True
        if self.message == "unknown" and config.ignore_tc_unknown_error == True:
            self.ignore = True
        if self.message == "cold junction range fault" and config.ignore_tc_cold_junction_range_error == True:
            self.ignore = True
        if self.message == "thermocouple range fault" and config.ignore_tc_range_error == True:
            self.ignore = True
        if self.message == "cold junction temp too high" and config.ignore_tc_cold_junction_temp_high == True:
            self.ignore = True
        if self.message == "cold junction temp too low" and config.ignore_tc_cold_junction_temp_low == True:
            self.ignore = True
        if self.message == "thermocouple temp too high" and config.ignore_tc_temp_high == True:
            self.ignore = True
        if self.message == "thermocouple temp too low" and config.ignore_tc_temp_low == True:
            self.ignore = True
        if self.message == "voltage too high or low" and config.ignore_tc_voltage_error == True:
            self.ignore = True

    def map_message(self):
        try:
            self.message = self.map[self.orig_message]
        except KeyError:
            self.message = "unknown"

class Max31855_Error(ThermocoupleError):
    '''
    All children must set self.orig_message and self.map
    '''
    def __init__(self, message):
        self.orig_message = message
        # this purposefully makes "fault reading" and
        # "Total thermoelectric voltage out of range..." unknown errors
        self.map = {
            "thermocouple not connected" : "not connected",
            "short circuit to ground" : "short circuit",
            "short circuit to power" : "short circuit",
            }
        super().__init__(message)

class Max31856_Error(ThermocoupleError):
    def __init__(self, message):
        self.orig_message = message
        self.map = {
            "cj_range" : "cold junction range fault",
            "tc_range" : "thermocouple range fault",
            "cj_high"  : "cold junction temp too high",
            "cj_low"   : "cold junction temp too low",
            "tc_high"  : "thermocouple temp too high",
            "tc_low"   : "thermocouple temp too low",
            "voltage"  : "voltage too high or low", 
            "open_tc"  : "not connected"
            }
        super().__init__(message)

class Max31856(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31856")
        import adafruit_max31856
        self.thermocouple = adafruit_max31856.MAX31856(self.spi,self.cs,
                                        thermocouple_type=config.thermocouple_type)
        if (config.ac_freq_50hz == True):
            self.thermocouple.noise_rejection = 50
        else:
            self.thermocouple.noise_rejection = 60

    def raw_temp(self):
        # The underlying adafruit library does not throw exceptions
        # for thermocouple errors. Instead, they are stored in 
        # dict named self.thermocouple.fault. Here we check that
        # dict for errors and raise an exception.
        # and raise Max31856_Error(message)
        temp = self.thermocouple.temperature
        for k,v in self.thermocouple.fault.items():
            if v:
                raise Max31856_Error(k)
        return temp

class Oven(threading.Thread):
    '''parent oven class. this has all the common code
       for either a real or simulated oven'''
    def __init__(self, buzzer=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.temperature = 0
        self.time_step = config.sensor_time_wait
        self.buzzer = buzzer
        self.notifier = None
        self.reset()

    def reset(self):
        self.cost = 0
        self.state = "IDLE"
        self.profile = None
        self.start_time = 0
        self.runtime = 0
        self.totaltime = 0
        self.target = 0
        self.heat = 0
        self.heat_rate = 0
        self.heat_rate_temps = []
        self.pid = PID(ki=config.pid_ki, kd=config.pid_kd, kp=config.pid_kp)
        self.catching_up = False
        self._init_telemetry()

    def _init_telemetry(self):
        self.telemetry_window_seconds = 300
        self.telemetry_samples = deque()
        self.telemetry_switches_5m = deque()
        self.telemetry_last_heat_state = None
        self.telemetry_last_sample_runtime = None
        self.telemetry_last_runtime = 0
        self.telemetry_last_catching_up = False
        self.telemetry_run_samples = 0
        self.telemetry_run_within_5deg = 0
        self.telemetry_run_error_sum = 0.0
        self.telemetry_run_error_abs_sum = 0.0
        self.telemetry_run_switches = 0
        self.telemetry_run_overshoot_max = 0.0
        self.telemetry_run_catching_up_seconds = 0.0
        self.telemetry_run_heat_on_seconds = 0.0
        self.telemetry_run_high_temp_seconds = 0.0
        self.telemetry_run_high_temp_heat_on_seconds = 0.0
        self.telemetry_run_high_temp_error_abs_sum = 0.0
        self.telemetry_run_high_temp_samples = 0
        self.telemetry_run_max_temp = 0.0
        self.telemetry_run_max_target = 0.0
        self.current_run_id = None
        self.current_run_started_ts = None
        self.current_run_peak_target = None
        self.alert_last_sent_at = {}
        self.alert_sent_once = set()
        self.next_profile_checkpoint_index = None
        self.next_temp_milestone = None
        if not hasattr(self, 'last_run_summary'):
            self.last_run_summary = None

    def _record_telemetry_sample(self, temp):
        # Record telemetry only once per control-cycle-ish runtime progression
        if self.state not in ("RUNNING", "PAUSED"):
            return
        if self.telemetry_last_sample_runtime is not None:
            if abs(self.runtime - self.telemetry_last_sample_runtime) < 0.5:
                return
        self.telemetry_last_sample_runtime = self.runtime

        now = time.time()
        error = self.target - temp
        abs_error = abs(error)
        within_5deg = abs_error <= 5
        heat_on = 1 if self.heat > 0 else 0
        overshoot = max(0.0, temp - self.target)

        if self.telemetry_last_heat_state is not None and heat_on != self.telemetry_last_heat_state:
            self.telemetry_run_switches += 1
            self.telemetry_switches_5m.append(now)
        self.telemetry_last_heat_state = heat_on

        runtime_delta = max(0.0, self.runtime - self.telemetry_last_runtime)
        prev_runtime = self.telemetry_last_runtime
        if self.telemetry_last_runtime > 0 and self.telemetry_last_catching_up:
            self.telemetry_run_catching_up_seconds += runtime_delta
        if prev_runtime > 0 and heat_on:
            self.telemetry_run_heat_on_seconds += runtime_delta
        self.telemetry_last_runtime = self.runtime
        self.telemetry_last_catching_up = self.catching_up

        self.telemetry_run_samples += 1
        self.telemetry_run_error_sum += error
        self.telemetry_run_error_abs_sum += abs_error
        if within_5deg:
            self.telemetry_run_within_5deg += 1
        if overshoot > self.telemetry_run_overshoot_max:
            self.telemetry_run_overshoot_max = overshoot
        if temp > self.telemetry_run_max_temp:
            self.telemetry_run_max_temp = temp
        if self.target > self.telemetry_run_max_target:
            self.telemetry_run_max_target = self.target

        if self.current_run_peak_target and self.current_run_peak_target > 0:
            high_temp_threshold = self.current_run_peak_target * 0.9
            if self.target >= high_temp_threshold:
                self.telemetry_run_high_temp_seconds += runtime_delta
                if heat_on:
                    self.telemetry_run_high_temp_heat_on_seconds += runtime_delta
                self.telemetry_run_high_temp_error_abs_sum += abs_error
                self.telemetry_run_high_temp_samples += 1

        self.telemetry_samples.append({
            'time': now,
            'runtime': self.runtime,
            'error': error,
            'abs_error': abs_error,
            'heat_on': heat_on,
            'within_5deg': within_5deg,
            'temperature': temp,
            'target': self.target,
            'catching_up': self.catching_up,
            'sensor_error_percent': self.board.temp_sensor.status.error_percent(),
        })

        cutoff = now - self.telemetry_window_seconds
        while self.telemetry_samples and self.telemetry_samples[0]['time'] < cutoff:
            self.telemetry_samples.popleft()
        while self.telemetry_switches_5m and self.telemetry_switches_5m[0] < cutoff:
            self.telemetry_switches_5m.popleft()
        self._check_runtime_alerts(now, temp, error)

    def _notify_with_cooldown(self, key, event, payload, cooldown_seconds=None):
        if cooldown_seconds is None:
            cooldown_seconds = float(getattr(config, 'notifications_alert_cooldown_seconds', 300))
        now = time.time()
        last_ts = self.alert_last_sent_at.get(key)
        if last_ts is not None and (now - last_ts) < cooldown_seconds:
            return False
        self.alert_last_sent_at[key] = now
        self._notify_event(event, payload)
        return True

    def _notify_once_per_run(self, key, event, payload):
        if key in self.alert_sent_once:
            return False
        self.alert_sent_once.add(key)
        self._notify_event(event, payload)
        return True

    def _check_runtime_alerts(self, now, temp, error):
        if self.state != "RUNNING" or not self.profile:
            return
        self._check_profile_rate_change_alert()
        self._check_temp_milestone_alert(temp)
        self._check_abnormal_deviation_alert(now, temp, error)

    def _check_profile_rate_change_alert(self):
        points = self.profile.data if self.profile else []
        if len(points) < 3:
            return
        if self.next_profile_checkpoint_index is None:
            for idx in range(1, len(points) - 1):
                if points[idx][0] > self.runtime:
                    self.next_profile_checkpoint_index = idx
                    break
            if self.next_profile_checkpoint_index is None:
                self.next_profile_checkpoint_index = len(points) - 1

        while self.next_profile_checkpoint_index is not None and self.next_profile_checkpoint_index < len(points) - 1:
            idx = self.next_profile_checkpoint_index
            checkpoint_time = points[idx][0]
            if self.runtime < checkpoint_time:
                break

            prev_point = points[idx - 1]
            curr_point = points[idx]
            next_point = points[idx + 1]
            prev_slope = 0.0
            next_slope = 0.0
            if curr_point[0] > prev_point[0]:
                prev_slope = (curr_point[1] - prev_point[1]) / float(curr_point[0] - prev_point[0]) * 3600.0
            if next_point[0] > curr_point[0]:
                next_slope = (next_point[1] - curr_point[1]) / float(next_point[0] - curr_point[0]) * 3600.0

            self._notify_once_per_run(
                key="rate_change_%d" % idx,
                event="profile_rate_change",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "checkpoint_seconds": checkpoint_time,
                    "checkpoint_hours": checkpoint_time / 3600.0,
                    "temperature_target": curr_point[1],
                    "previous_rate_deg_per_hour": prev_slope,
                    "new_rate_deg_per_hour": next_slope,
                },
            )
            self.next_profile_checkpoint_index = idx + 1

    def _check_temp_milestone_alert(self, temp):
        interval = float(getattr(config, 'notifications_temp_milestone_interval', 500))
        if interval <= 0:
            return
        if self.next_temp_milestone is None:
            self.next_temp_milestone = math.floor(max(0.0, temp) / interval) * interval + interval

        while self.next_temp_milestone is not None and temp >= self.next_temp_milestone:
            milestone = self.next_temp_milestone
            self._notify_once_per_run(
                key="temp_milestone_%d" % int(milestone),
                event="temp_milestone_reached",
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "milestone_temp": milestone,
                    "temperature": temp,
                    "target": self.target,
                    "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
                },
            )
            self.next_temp_milestone += interval

    def _check_abnormal_deviation_alert(self, now, temp, error):
        drop_window = float(getattr(config, 'notifications_deviation_drop_window_seconds', 45))
        drop_threshold = float(getattr(config, 'notifications_deviation_drop_threshold', 20))
        min_error = float(getattr(config, 'notifications_deviation_min_error', 35))
        min_target = float(getattr(config, 'notifications_deviation_min_target_temp', 300))

        if self.target < min_target or error < min_error or self.heat <= 0:
            return

        sample = None
        cutoff = now - drop_window
        for item in self.telemetry_samples:
            if item['time'] >= cutoff:
                sample = item
                break
        if not sample:
            return

        temp_drop = temp - sample['temperature']
        if temp_drop <= -abs(drop_threshold):
            self._notify_with_cooldown(
                key='abnormal_deviation',
                event='abnormal_deviation',
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "temperature": temp,
                    "target": self.target,
                    "error": error,
                    "drop_window_seconds": drop_window,
                    "temperature_drop": temp_drop,
                    "runtime_hours": self.runtime / 3600.0 if self.runtime else 0.0,
                },
                cooldown_seconds=float(getattr(config, 'notifications_deviation_cooldown_seconds', 300)),
            )

    def get_telemetry(self):
        recent = list(self.telemetry_samples)
        errors = [sample['error'] for sample in recent]
        abs_errors = [sample['abs_error'] for sample in recent]
        heat = [sample['heat_on'] for sample in recent]
        within = [sample['within_5deg'] for sample in recent]
        sensor_errors = [sample['sensor_error_percent'] for sample in recent]

        one_minute_cutoff = time.time() - 60
        recent_1m_errors = [sample['error'] for sample in recent if sample['time'] >= one_minute_cutoff]

        runtime_hours = self.runtime / 3600 if self.runtime > 0 else 0
        switches_per_hour = self.telemetry_run_switches / runtime_hours if runtime_hours > 0 else 0.0
        within_5deg_run = (
            (self.telemetry_run_within_5deg / float(self.telemetry_run_samples)) * 100
            if self.telemetry_run_samples
            else 0.0
        )
        catching_up_pct_run = (
            (self.telemetry_run_catching_up_seconds / self.runtime) * 100
            if self.runtime > 0
            else 0.0
        )

        return {
            'window_seconds': self.telemetry_window_seconds,
            'error_now': self.target - self.temperature,
            'error_avg_1m': avg(recent_1m_errors),
            'error_avg_5m': avg(errors),
            'error_abs_avg_5m': avg(abs_errors),
            'within_5deg_pct_5m': bool_pct(within),
            'within_5deg_pct_run': within_5deg_run,
            'switches_5m': len(self.telemetry_switches_5m),
            'switches_per_hour_run': switches_per_hour,
            'duty_cycle_5m': avg(heat) * 100,
            'overshoot_max_run': self.telemetry_run_overshoot_max,
            'time_catching_up_pct_run': catching_up_pct_run,
            'sensor_error_rate_5m': avg(sensor_errors),
        }

    @staticmethod
    def get_start_from_temperature(profile, temp):
        target_temp = profile.get_target_temperature(0)
        if temp > target_temp + 5:
            startat = profile.find_next_time_from_temperature(temp)
            log.info("seek_start is in effect, starting at: {} s, {} deg".format(round(startat), round(temp)))
        else:
            startat = 0
        return startat

    def set_heat_rate(self,runtime,temp):
        '''heat rate is the heating rate in degrees/hour
        '''
        # arbitrary number of samples
        # the time this covers changes based on a few things
        numtemps = 60
        self.heat_rate_temps.append((runtime,temp))
         
        # drop old temps off the list
        if len(self.heat_rate_temps) > numtemps:
            self.heat_rate_temps = self.heat_rate_temps[-1*numtemps:]
        time2 = self.heat_rate_temps[-1][0]
        time1 = self.heat_rate_temps[0][0]
        temp2 = self.heat_rate_temps[-1][1]
        temp1 = self.heat_rate_temps[0][1]
        if time2 > time1:
            self.heat_rate = ((temp2 - temp1) / (time2 - time1))*3600

    def run_profile(self, profile, startat=0, allow_seek=True):
        log.debug('run_profile run on thread' + threading.current_thread().name)
        
        # Play start sound
        if self.buzzer:
            # Run in separate thread to not block
            threading.Thread(target=self.buzzer.start_firing).start()

        runtime = startat * 60
        if allow_seek:
            if self.state == 'IDLE':
                if config.seek_start:
                    temp = self.board.temp_sensor.temperature()  # Defined in a subclass
                    runtime += self.get_start_from_temperature(profile, temp)

        self.reset()
        self.startat = startat * 60
        self.runtime = runtime
        self.start_time = datetime.datetime.now() - datetime.timedelta(seconds=self.startat)
        self.profile = profile
        self.totaltime = profile.get_duration()
        self.current_run_id = str(uuid.uuid4())
        self.current_run_started_ts = time.time()
        self.current_run_peak_target = max((temp for (_, temp) in profile.data), default=0)
        self.next_profile_checkpoint_index = None
        self.next_temp_milestone = None
        self.current_run_summary = None
        self.state = "RUNNING"
        log.info("Running schedule %s starting at %d minutes" % (profile.name,startat))
        log.info("Starting")
        self._notify_event("run_started", {
            "profile": profile.name,
            "startat_minutes": startat,
            "run_id": self.current_run_id,
        })

    def get_run_health_summary(self, reason):
        runtime_hours = self.runtime / 3600 if self.runtime > 0 else 0.0
        switches_per_hour = self.telemetry_run_switches / runtime_hours if runtime_hours > 0 else 0.0
        within_5deg_run = (
            (self.telemetry_run_within_5deg / float(self.telemetry_run_samples)) * 100
            if self.telemetry_run_samples
            else 0.0
        )
        heat_duty_run = (self.telemetry_run_heat_on_seconds / self.runtime) * 100 if self.runtime > 0 else 0.0
        high_temp_duty = (
            (self.telemetry_run_high_temp_heat_on_seconds / self.telemetry_run_high_temp_seconds) * 100
            if self.telemetry_run_high_temp_seconds > 0
            else 0.0
        )
        high_temp_mae = (
            self.telemetry_run_high_temp_error_abs_sum / float(self.telemetry_run_high_temp_samples)
            if self.telemetry_run_high_temp_samples
            else 0.0
        )
        peak_target = self.current_run_peak_target if self.current_run_peak_target else self.telemetry_run_max_target
        max_temp_gap_to_peak = peak_target - self.telemetry_run_max_temp if peak_target else 0.0

        return {
            'run_id': self.current_run_id,
            'started_at': datetime.datetime.utcfromtimestamp(self.current_run_started_ts).isoformat() + 'Z'
                if self.current_run_started_ts else None,
            'ended_at': datetime.datetime.utcnow().isoformat() + 'Z',
            'reason': reason,
            'profile': self.profile.name if self.profile else None,
            'runtime_seconds': self.runtime,
            'runtime_hours': runtime_hours,
            'cost': self.cost,
            'max_temp': self.telemetry_run_max_temp,
            'max_target': self.telemetry_run_max_target,
            'peak_profile_target': peak_target,
            'max_temp_gap_to_peak_target': max_temp_gap_to_peak,
            'overshoot_max': self.telemetry_run_overshoot_max,
            'within_5deg_pct': within_5deg_run,
            'switch_count': self.telemetry_run_switches,
            'switches_per_hour': switches_per_hour,
            'heat_duty_pct': heat_duty_run,
            'high_temp_seconds': self.telemetry_run_high_temp_seconds,
            'high_temp_duty_pct': high_temp_duty,
            'high_temp_mae': high_temp_mae,
            'catching_up_seconds': self.telemetry_run_catching_up_seconds,
            'catching_up_pct': (self.telemetry_run_catching_up_seconds / self.runtime) * 100 if self.runtime > 0 else 0.0,
            'sensor_error_rate_5m': avg([sample['sensor_error_percent'] for sample in self.telemetry_samples]),
            'completed': reason == 'schedule_complete',
        }

    def save_run_health_summary(self, summary):
        if not getattr(config, 'run_health_history_enabled', True):
            return
        try:
            with open(config.run_health_history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(summary) + '\n')
        except Exception as error:
            log.error("failed writing run health history: %s", error)

    def finalize_run(self, reason='abort'):
        if self.state in ('RUNNING', 'PAUSED') and self.profile:
            summary = self.get_run_health_summary(reason)
            self.last_run_summary = summary
            self.save_run_health_summary(summary)
            log.info("run health summary saved for profile=%s reason=%s", summary.get('profile'), reason)
            self._notify_event("run_finished", summary)

    def abort_run(self, reason='abort'):
        if self.buzzer:
            if reason == 'schedule_complete':
                self.buzzer.firing_complete()
            elif str(reason).startswith('manual_stop'):
                self.buzzer.manual_stop()
            elif str(reason).startswith('emergency'):
                self.buzzer.error()
        self.finalize_run(reason=reason)
        self.reset()
        self.save_automatic_restart_state()

    def get_start_time(self):
        return datetime.datetime.now() - datetime.timedelta(milliseconds = self.runtime * 1000)

    def kiln_must_catch_up(self):
        '''shift the whole schedule forward in time by one time_step
        to wait for the kiln to catch up'''
        if config.kiln_must_catch_up == True:
            temp = self.board.temp_sensor.temperature() + \
                config.thermocouple_offset
            # kiln too cold, wait for it to heat up
            if self.target - temp > config.pid_control_window:
                log.info("kiln must catch up, too cold, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            # kiln too hot, wait for it to cool down
            if temp - self.target > config.pid_control_window:
                log.info("kiln must catch up, too hot, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            self.catching_up = False;

    def update_runtime(self):

        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds()

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def reset_if_emergency(self):
        '''reset if the temperature is way TOO HOT, or other critical errors detected'''
        if (self.board.temp_sensor.temperature() + config.thermocouple_offset >=
            config.emergency_shutoff_temp):
            log.info("emergency!!! temperature too high")
            self._notify_with_cooldown(
                key='temp_too_high',
                event='issue_detected',
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "temperature_too_high",
                    "temperature": self.board.temp_sensor.temperature() + config.thermocouple_offset,
                    "limit": config.emergency_shutoff_temp,
                },
                cooldown_seconds=60,
            )
            if config.ignore_temp_too_high == False:
                self.abort_run(reason='emergency_temp_too_high')
        
        if self.board.temp_sensor.status.over_error_limit():
            log.info("emergency!!! too many errors in a short period")
            self._notify_with_cooldown(
                key='tc_error_rate',
                event='issue_detected',
                payload={
                    "profile": self.profile.name if self.profile else None,
                    "run_id": self.current_run_id,
                    "issue": "thermocouple_error_rate_high",
                    "error_rate_pct": self.board.temp_sensor.status.error_percent(),
                },
                cooldown_seconds=60,
            )
            if config.ignore_tc_too_many_errors == False:
                self._notify_event("sensor_fault", {
                    "error_rate_pct": self.board.temp_sensor.status.error_percent(),
                    "run_id": self.current_run_id,
                    "profile": self.profile.name if self.profile else None,
                })
                self.abort_run(reason='emergency_tc_error_rate')

    def reset_if_schedule_ended(self):
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            log.info("total cost = %s%.2f" % (config.currency_type,self.cost))
            self.abort_run(reason='schedule_complete')

    def update_cost(self):
        if self.heat:
            cost = (config.kwh_rate * config.kw_elements) * ((self.heat)/3600)
        else:
            cost = 0
        self.cost = self.cost + cost

    def get_state(self):
        temp = 0
        try:
            temp = self.board.temp_sensor.temperature() + config.thermocouple_offset
        except AttributeError as error:
            # this happens at start-up with a simulated oven
            temp = 0
            pass
        except Exception as e:
            # Catch all other exceptions that might occur when reading temperature
            # This prevents temp from staying at 0 when other errors occur
            log.error(f"Error reading temperature in get_state(): {e}")
            temp = 0

        self.set_heat_rate(self.runtime,temp)
        self.temperature = temp
        self._record_telemetry_sample(temp)

        state = {
            'cost': self.cost,
            'runtime': self.runtime,
            'temperature': temp,
            'target': self.target,
            'state': self.state,
            'heat': self.heat,
            'heat_rate': self.heat_rate,
            'totaltime': self.totaltime,
            'kwh_rate': config.kwh_rate,
            'currency_type': config.currency_type,
            'profile': self.profile.name if self.profile else None,
            'pidstats': self.pid.pidstats,
            'catching_up': self.catching_up,
            'telemetry': self.get_telemetry(),
            'last_run_summary': self.last_run_summary,
        }
        return state

    def save_state(self):
        with open(config.automatic_restart_state_file, 'w', encoding='utf-8') as f:
            json.dump(self.get_state(), f, ensure_ascii=False, indent=4)

    def state_file_is_old(self):
        '''returns True is state files is older than 15 mins default
                   False if younger
                   True if state file cannot be opened or does not exist
        '''
        if os.path.isfile(config.automatic_restart_state_file):
            state_age = os.path.getmtime(config.automatic_restart_state_file)
            now = time.time()
            minutes = (now - state_age)/60
            if(minutes <= config.automatic_restart_window):
                return False
        return True

    def save_automatic_restart_state(self):
        # only save state if the feature is enabled
        if not config.automatic_restarts == True:
            return False
        self.save_state()

    def should_i_automatic_restart(self):
        # only automatic restart if the feature is enabled
        if not config.automatic_restarts == True:
            return False
        if self.state_file_is_old():
            duplog.info("automatic restart not possible. state file does not exist or is too old.")
            return False

        with open(config.automatic_restart_state_file) as infile:
            d = json.load(infile)
        if d["state"] != "RUNNING":
            duplog.info("automatic restart not possible. state = %s" % (d["state"]))
            return False
        return True

    def automatic_restart(self):
        with open(config.automatic_restart_state_file) as infile: d = json.load(infile)
        startat = d["runtime"]/60
        filename = "%s.json" % (d["profile"])
        profile_path = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', 'storage','profiles',filename))

        log.info("automatically restarting profile = %s at minute = %d" % (profile_path,startat))
        with open(profile_path) as infile:
            profile_json = json.dumps(json.load(infile))
        profile = Profile(profile_json)
        self.run_profile(profile, startat=startat, allow_seek=False)  # We don't want a seek on an auto restart.
        self.cost = d["cost"]
        time.sleep(1)
        self.ovenwatcher.record(profile)

    def set_ovenwatcher(self,watcher):
        log.info("ovenwatcher set in oven class")
        self.ovenwatcher = watcher

    def set_notifier(self, notifier):
        self.notifier = notifier

    def emit_notification(self, event, payload=None):
        self._notify_event(event, payload)

    def _notify_event(self, event, payload=None):
        if not self.notifier:
            return
        try:
            self.notifier.emit_event(event, payload or {})
        except Exception as exc:
            log.error("failed to queue notification event=%s: %s", event, exc)

    def run(self):
        while True:
            log.debug('Oven running on ' + threading.current_thread().name)
            if self.state == "IDLE":
                if self.should_i_automatic_restart() == True:
                    self.automatic_restart()
                time.sleep(1)
                continue
            if self.state == "PAUSED":
                self.start_time = self.get_start_time()
                self.update_runtime()
                self.update_target_temp()
                self.heat_then_cool()
                self.reset_if_emergency()
                self.reset_if_schedule_ended()
                continue
            if self.state == "RUNNING":
                self.update_cost()
                self.save_automatic_restart_state()
                self.kiln_must_catch_up()
                self.update_runtime()
                self.update_target_temp()
                self.heat_then_cool()
                self.reset_if_emergency()
                self.reset_if_schedule_ended()

class SimulatedOven(Oven):

    def __init__(self):
        self.board = SimulatedBoard()
        self.t_env = config.sim_t_env
        self.c_heat = config.sim_c_heat
        self.c_oven = config.sim_c_oven
        self.p_heat = config.sim_p_heat
        self.R_o_nocool = config.sim_R_o_nocool
        self.R_ho_noair = config.sim_R_ho_noair
        self.R_ho = self.R_ho_noair
        self.speedup_factor = config.sim_speedup_factor

        # set temps to the temp of the surrounding environment
        self.t = config.sim_t_env  # deg C or F temp of oven
        self.t_h = self.t_env #deg C temp of heating element

        super().__init__()

        self.start_time = self.get_start_time();

        # start thread
        self.start()
        log.info("SimulatedOven started")

    # runtime is in sped up time, start_time is actual time of day
    def get_start_time(self):
        return datetime.datetime.now() - datetime.timedelta(milliseconds = self.runtime * 1000 / self.speedup_factor)

    def update_runtime(self):
        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds() * self.speedup_factor

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def heating_energy(self,pid):
        # using pid here simulates the element being on for
        # only part of the time_step
        self.Q_h = self.p_heat * self.time_step * pid

    def temp_changes(self):
        #temperature change of heat element by heating
        self.t_h += self.Q_h / self.c_heat

        #energy flux heat_el -> oven
        self.p_ho = (self.t_h - self.t) / self.R_ho

        #temperature change of oven and heating element
        self.t += self.p_ho * self.time_step / self.c_oven
        self.t_h -= self.p_ho * self.time_step / self.c_heat

        #temperature change of oven by cooling to environment
        self.p_env = (self.t - self.t_env) / self.R_o_nocool
        self.t -= self.p_env * self.time_step / self.c_oven
        self.temperature = self.t
        self.board.temp_sensor.simulated_temperature = self.t

    def heat_then_cool(self):
        now_simulator = self.start_time + datetime.timedelta(milliseconds = self.runtime * 1000)
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature() +
                               config.thermocouple_offset, now_simulator)

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        self.heating_energy(pid)
        self.temp_changes()

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = heat_on

        log.info("simulation: -> %dW heater: %.0f -> %dW oven: %.0f -> %dW env" % (int(self.p_heat * pid),
            self.t_h,
            int(self.p_ho),
            self.t,
            int(self.p_env)))

        time_left = self.totaltime - self.runtime

        try:
            log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                (self.pid.pidstats['ispoint'],
                self.pid.pidstats['setpoint'],
                self.pid.pidstats['err'],
                self.pid.pidstats['pid'],
                self.pid.pidstats['p'],
                self.pid.pidstats['i'],
                self.pid.pidstats['d'],
                heat_on,
                heat_off,
                self.runtime,
                self.totaltime,
                time_left))
        except KeyError:
            pass

        # we don't actually spend time heating & cooling during
        # a simulation, so sleep.
        time.sleep(self.time_step / self.speedup_factor)


class RealOven(Oven):

    def __init__(self, buzzer=None):
        self.board = RealBoard()
        self.output = Output()
        self.reset()

        # call parent init
        Oven.__init__(self, buzzer)

        # start thread
        self.start()

    def reset(self):
        super().reset()
        self.output.cool(0)

    def heat_then_cool(self):
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature() +
                               config.thermocouple_offset, datetime.datetime.now())

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        # Minimum on-time protection: if heat_on is less than minimum,
        # round it down to 0 to prevent rapid cycling.
        # Exception: Allow throttled heating (intentional low power operation)
        # to bypass the minimum to prevent blocking legitimate throttling.
        # Throttling occurs when: target <= throttle_below_temp, error is large (outside PID window),
        # and PID output matches throttle percentage.
        current_temp = self.board.temp_sensor.temperature() + config.thermocouple_offset
        error = self.target - current_temp
        is_throttled = (config.throttle_below_temp and config.throttle_percent and 
                       self.target <= config.throttle_below_temp and
                       error > config.pid_control_window and
                       abs(pid - (config.throttle_percent/100.0)) < 0.01)
        
        if config.min_on_time > 0 and 0 < heat_on < config.min_on_time and not is_throttled:
            log.debug(f"heat_on ({heat_on:.3f}s) below minimum ({config.min_on_time}s), setting to 0")
            heat_off = self.time_step  # entire cycle is off
            heat_on = 0.0

        # self.heat is for the front end to display if the heat is on
        self.heat = 0.0
        if heat_on > 0:
            self.heat = 1.0

        if heat_on:
            self.output.heat(heat_on)
        if heat_off:
            self.output.cool(heat_off)
        time_left = self.totaltime - self.runtime
        try:
            log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                (self.pid.pidstats['ispoint'],
                self.pid.pidstats['setpoint'],
                self.pid.pidstats['err'],
                self.pid.pidstats['pid'],
                self.pid.pidstats['p'],
                self.pid.pidstats['i'],
                self.pid.pidstats['d'],
                heat_on,
                heat_off,
                self.runtime,
                self.totaltime,
                time_left))
        except KeyError:
            pass

class Profile():
    def __init__(self, json_data):
        obj = json.loads(json_data)
        self.name = obj["name"]
        self.data = sorted(obj["data"])

    def get_duration(self):
        return max([t for (t, x) in self.data])

    #  x = (y-y1)(x2-x1)/(y2-y1) + x1
    @staticmethod
    def find_x_given_y_on_line_from_two_points(y, point1, point2):
        if point1[0] > point2[0]: return 0  # time2 before time1 makes no sense in kiln segment
        if point1[1] >= point2[1]: return 0 # Zero will crach. Negative temeporature slope, we don't want to seek a time.
        x = (y - point1[1]) * (point2[0] -point1[0] ) / (point2[1] - point1[1]) + point1[0]
        return x

    def find_next_time_from_temperature(self, temperature):
        time = 0 # The seek function will not do anything if this returns zero, no useful intersection was found
        for index, point2 in enumerate(self.data):
            if point2[1] >= temperature:
                if index > 0: #  Zero here would be before the first segment
                    if self.data[index - 1][1] <= temperature: # We have an intersection
                        time = self.find_x_given_y_on_line_from_two_points(temperature, self.data[index - 1], point2)
                        if time == 0:
                            if self.data[index - 1][1] == point2[1]: # It's a flat segment that matches the temperature
                                time = self.data[index - 1][0]
                                break

        return time

    def get_surrounding_points(self, time):
        if time > self.get_duration():
            return (None, None)

        prev_point = None
        next_point = None

        for i in range(len(self.data)):
            if time < self.data[i][0]:
                prev_point = self.data[i-1]
                next_point = self.data[i]
                break

        return (prev_point, next_point)

    def get_target_temperature(self, time):
        if time > self.get_duration():
            return 0

        (prev_point, next_point) = self.get_surrounding_points(time)

        incl = float(next_point[1] - prev_point[1]) / float(next_point[0] - prev_point[0])
        temp = prev_point[1] + (time - prev_point[0]) * incl
        return temp


class PID():

    def __init__(self, ki=1, kp=1, kd=1):
        self.ki = ki
        self.kp = kp
        self.kd = kd
        self.lastNow = datetime.datetime.now()
        self.iterm = 0
        self.lastErr = 0
        self.pidstats = {}

    # FIX - this was using a really small window where the PID control
    # takes effect from -1 to 1. I changed this to various numbers and
    # settled on -50 to 50 and then divide by 50 at the end. This results
    # in a larger PID control window and much more accurate control...
    # instead of what used to be binary on/off control.
    def compute(self, setpoint, ispoint, now):
        timeDelta = (now - self.lastNow).total_seconds()

        window_size = 100

        error = float(setpoint - ispoint)

        # this removes the need for config.stop_integral_windup
        # it turns the controller into a binary on/off switch
        # any time it's outside the window defined by
        # config.pid_control_window
        icomp = 0
        output = 0
        out4logs = 0
        dErr = 0
        if error < (-1 * config.pid_control_window):
            log.info("kiln outside pid control window, max cooling")
            output = 0
            # it is possible to set self.iterm=0 here and also below
            # but I dont think its needed
        elif error > (1 * config.pid_control_window):
            log.info("kiln outside pid control window, max heating")
            output = 1
            if config.throttle_below_temp and config.throttle_percent:
                if setpoint <= config.throttle_below_temp:
                    output = config.throttle_percent/100
                    log.info("max heating throttled at %d percent below %d degrees to prevent overshoot" % (config.throttle_percent,config.throttle_below_temp))
        else:
            icomp = (error * timeDelta * (1/self.ki))
            self.iterm += (error * timeDelta * (1/self.ki))
            dErr = (error - self.lastErr) / timeDelta
            output = self.kp * error + self.iterm + self.kd * dErr
            output = sorted([-1 * window_size, output, window_size])[1]
            out4logs = output
            output = float(output / window_size)
            
        self.lastErr = error
        self.lastNow = now

        # no active cooling
        if output < 0:
            output = 0

        self.pidstats = {
            'time': time.mktime(now.timetuple()),
            'timeDelta': timeDelta,
            'setpoint': setpoint,
            'ispoint': ispoint,
            'err': error,
            'errDelta': dErr,
            'p': self.kp * error,
            'i': self.iterm,
            'd': self.kd * dErr,
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'pid': out4logs,
            'out': output,
        }

        return output
