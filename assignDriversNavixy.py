import requests
import json
import time
import schedule
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configurations
API_BASE_URL = "https://api.navixy.com/v2"
API_KEY = os.getenv("API_KEY")
HEADERS = {"Content-Type": "application/json"}
DRIVERS_FILE = "drivers.json"
TRACKERS_FILE = "trackers.json"

# Fetch drivers
def fetch_drivers():
    url = f"{API_BASE_URL}/driver/list"
    response = requests.post(url, headers=HEADERS, json={"hash": API_KEY})
    if response.status_code == 200:
        drivers = response.json().get("list", [])
        with open(DRIVERS_FILE, "w") as f:
            json.dump(drivers, f)
        print("Drivers list updated.")
    else:
        print(f"Error fetching drivers: {response.status_code}, {response.text}")

# Fetch trackers
def fetch_trackers():
    url = f"{API_BASE_URL}/tracker/list"
    response = requests.post(url, headers=HEADERS, json={"hash": API_KEY})
    if response.status_code == 200:
        trackers = response.json().get("list", [])
        with open(TRACKERS_FILE, "w") as f:
            json.dump(trackers, f)
        print("Trackers list updated.")
    else:
        print(f"Error fetching trackers: {response.status_code}, {response.text}")

# Fetch sensor data
def fetch_sensor_data():
    try:
        with open(TRACKERS_FILE, "r") as f:
            trackers = json.load(f)
    except FileNotFoundError:
        print("Trackers file not found. Run daily tasks first.")
        return

    tracker_ids = [tracker["id"] for tracker in trackers]
    url = f"{API_BASE_URL}/tracker/batch_read"
    payload = {
        "hash": API_KEY,
        "trackers": tracker_ids,
        "fields": ["sensors"]
    }
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        process_sensor_data(response.json())
    else:
        print(f"Error fetching sensor data: {response.status_code}, {response.text}")

# Process sensor data and assign drivers
def process_sensor_data(data):
    try:
        with open(DRIVERS_FILE, "r") as f:
            drivers = json.load(f)
    except FileNotFoundError:
        print("Drivers file not found. Run daily tasks first.")
        return

    driver_map = {driver["hardware_key"]: driver for driver in drivers}

    for tracker in data.get("trackers", []):
        tracker_id = tracker["id"]
        sensors = tracker.get("sensors", [])
        driver_id = parse_driver_id_from_sensors(sensors)

        if driver_id and driver_id in driver_map:
            assign_driver_to_tracker(tracker_id, driver_map[driver_id])

# Parse driver ID from sensors (explicitly parsing Driver_ID_MSB and Driver_ID_LSB)
def parse_driver_id_from_sensors(sensors):
    msb = None
    lsb = None
    for sensor in sensors:
        if sensor["type"] == "Driver_ID_MSB":
            msb = sensor["value"]
        elif sensor["type"] == "Driver_ID_LSB":
            lsb = sensor["value"]
    
    if msb is not None and lsb is not None:
        return (msb << 8) | lsb
    return None

# Assign driver to tracker
def assign_driver_to_tracker(tracker_id, driver):
    url = f"{API_BASE_URL}/tracker/assign_driver"
    payload = {
        "hash": API_KEY,
        "tracker_id": tracker_id,
        "driver_id": driver["id"]
    }
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        print(f"Assigned driver {driver['name']} to tracker {tracker_id}.")
    else:
        print(f"Error assigning driver: {response.status_code}, {response.text}")

# Schedule tasks
schedule.every().day.at("00:00").do(fetch_drivers)
schedule.every().day.at("00:10").do(fetch_trackers)
schedule.every(1).minutes.do(fetch_sensor_data)

if __name__ == "__main__":
    # Run daily tasks immediately on start
    fetch_drivers()
    fetch_trackers()

    # Run the scheduler
    while True:
        schedule.run_pending()
        time.sleep(1)
