import logging

DOMAIN = "broadair"
LOGGER = logging.getLogger(__package__)

# fan speed ladder (ordered) and airflow mapping from the status dump
SPEEDS = ["sleep", "1", "2", "3"]
LEVEL = {"sleep": 0, "1": 1, "2": 2, "3": 3}
M3H_TO_SPEED = {50: "sleep", 80: "1", 120: "2", 180: "3"}
PRESET_AUTO = "Auto"
