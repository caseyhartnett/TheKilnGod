import time
import logging
import sys
import os
sys.path.insert(0, 'lib')
import config
import paho.mqtt.client as mqtt
import paho.mqtt

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("test_mqtt")

try:
    print(f"Paho MQTT version: {paho.mqtt.__version__}")
except AttributeError:
    print("Could not determine Paho MQTT version")

broker = config.ha_mqtt_broker
port = config.ha_mqtt_port
username = config.ha_mqtt_username
password = config.ha_mqtt_password
client_id = config.ha_mqtt_client_id

print(f"Connecting to {broker}:{port} as {client_id}")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected to MQTT broker!")
    else:
        print(f"Failed to connect, return code: {rc}")

# Create client with explicit API version (required for paho-mqtt 2.x)
client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION1)

if username and password:
    client.username_pw_set(username, password)

client.on_connect = on_connect

try:
    client.connect(broker, port, 60)
    client.loop_start()
    
    # Give it a moment to connect
    time.sleep(2)
    
    topic = f"{config.ha_mqtt_topic_prefix}/test"
    payload = "hello world"
    print(f"Publishing to {topic}: {payload}")
    
    info = client.publish(topic, payload)
    info.wait_for_publish()
    print("Message published successfully")
    
    time.sleep(2)
    client.loop_stop()
    client.disconnect()
    print("Disconnected")
except Exception as e:
    print(f"An error occurred: {e}")
