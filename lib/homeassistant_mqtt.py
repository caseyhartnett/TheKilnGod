import time
import threading
import logging
import json
import paho.mqtt.client as mqtt
import config

log = logging.getLogger(__name__)

class HomeAssistantMQTT(threading.Thread):
    """Background thread that publishes kiln state to Home Assistant via MQTT"""
    
    def __init__(self, oven):
        """
        Initialize the Home Assistant MQTT updater
        
        Args:
            oven: The oven object (RealOven or SimulatedOven)
        """
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.update_interval = config.sensor_time_wait
        self.connected = False
        self.client = None
        
        # MQTT Setup
        self.broker = config.ha_mqtt_broker
        self.port = config.ha_mqtt_port
        self.username = config.ha_mqtt_username
        self.password = config.ha_mqtt_password
        self.client_id = config.ha_mqtt_client_id
        self.topic_prefix = config.ha_mqtt_topic_prefix
        
        if config.ha_mqtt_enabled:
            self.setup_mqtt()
        else:
            log.info("Home Assistant MQTT integration disabled")
            
    def setup_mqtt(self):
        try:
            self.client = mqtt.Client(client_id=self.client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
            
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
                
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            
            log.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
            self.client.connect_async(self.broker, self.port, 60)
            self.client.loop_start()
            
        except Exception as e:
            log.error(f"Failed to initialize MQTT client: {e}")
            self.connected = False
            
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("Connected to MQTT broker")
            self.connected = True
        else:
            log.error(f"Failed to connect to MQTT broker, return code: {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc):
        log.warning(f"Disconnected from MQTT broker, return code: {rc}")
        self.connected = False

    def publish(self, subtopic, payload, retain=False):
        if not self.connected or not self.client:
            return
            
        topic = f"{self.topic_prefix}/{subtopic}"
        try:
            self.client.publish(topic, payload, retain=retain)
        except Exception as e:
            log.error(f"Error publishing to {topic}: {e}")

    def run(self):
        """Main loop that updates Home Assistant"""
        if not config.ha_mqtt_enabled:
            return
            
        log.info("Home Assistant MQTT updater started")
        
        while True:
            try:
                if self.connected:
                    # Get current state from oven
                    state = self.oven.get_state()
                    
                    # Extract values
                    temperature = state.get('temperature', 0)
                    target = state.get('target', 0)
                    oven_state = state.get('state', 'IDLE')
                    heat = state.get('heat', 0)
                    heat_rate = state.get('heat_rate', 0)
                    runtime = state.get('runtime', 0)
                    totaltime = state.get('totaltime', 0)
                    profile_name = state.get('profile', 'None')
                    if profile_name is None:
                        profile_name = "None"

                    # Derived values
                    heat_on = "ON" if heat > 0 else "OFF"
                    time_remaining = totaltime - runtime if totaltime > 0 else 0
                    if time_remaining < 0:
                        time_remaining = 0
                    
                    # Publish data to MQTT
                    # log.debug(f"Publishing MQTT data: Temp={temperature}, State={oven_state}")
                    log.info(f"Publishing to {self.topic_prefix}: Temp={temperature}, State={oven_state}")
                    self.publish("sensor/temperature/state", str(round(temperature, 2)))
                    self.publish("sensor/target_temperature/state", str(round(target, 2)))
                    self.publish("sensor/status/state", oven_state)
                    self.publish("binary_sensor/heat/state", heat_on)
                    self.publish("sensor/time_remaining/state", str(int(time_remaining)))
                    self.publish("sensor/profile_name/state", profile_name)
                    self.publish("sensor/runtime/state", str(int(runtime)))
                    self.publish("sensor/heat_rate/state", str(round(heat_rate, 2)))
                else:
                    log.warning("MQTT not connected, skipping publish")
                
                # Sleep until next update
                time.sleep(self.update_interval)
                
            except Exception as e:
                log.error(f"Error in Home Assistant MQTT updater: {e}")
                time.sleep(self.update_interval)

