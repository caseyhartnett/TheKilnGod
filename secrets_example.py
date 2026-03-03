# Secrets and Local Configuration
#
# COPY THIS FILE to 'secrets.py' and update with your local settings.
# The 'secrets.py' file is git-ignored and will not be committed.
#
# Any variable defined in config.py can be overridden here.

# MQTT Credentials
ha_mqtt_username = "your_mqtt_username"
ha_mqtt_password = "your_mqtt_password"

# Optional API tokens
# api_monitor_token = "set_a_long_random_monitor_token"
# api_control_token = "set_a_long_random_control_token"

# Optional ntfy notifications
# notifications_enabled = True
# notification_provider = "ntfy"
# ntfy_server = "https://ntfy.sh"
# ntfy_topic = "your-unique-kiln-topic"
# ntfy_access_token = None  # set for private/protected topics

# Optional alert tuning overrides
# notifications_temp_milestone_interval = 500
# notifications_deviation_drop_window_seconds = 45
# notifications_deviation_drop_threshold = 20
# notifications_deviation_min_error = 35
# notifications_deviation_min_target_temp = 300
# notifications_deviation_cooldown_seconds = 300
