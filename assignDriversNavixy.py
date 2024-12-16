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
# writes driver list and trackers list to json once a day to update if new employees/trackers are added.
DRIVERS_FILE = "drivers.json"
TRACKERS_FILE = "trackers.json"

# Fetch drivers
def fetch_drivers():
    url = f"{API_BASE_URL}/employee/list"
    response = requests.post(url, headers=HEADERS, json={"hash": API_KEY})
    if response.status_code == 200:
        drivers = response.json().get("list", [])
        with open(DRIVERS_FILE, "w") as f:
            json.dump(drivers, f)
        print("Drivers list updated.")
    else:
        print(f"Error fetching drivers: {response.status_code}, {response.text}")

# Fetch trackers ID list
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
    url = f"{API_BASE_URL}/tracker/readings/batch_list"
    payload = {
        "hash": API_KEY,
        "trackers": tracker_ids
    }
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        print("Sensor data fetched.")
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

    for tracker_id, tracker_data in data.get("result", {}).items():
        sensors = tracker_data.get("inputs", [])
        driver_id = parse_driver_id_from_sensors(sensors)

        if driver_id and driver_id in driver_map:
            assign_driver_to_tracker(tracker_id, driver_map[driver_id])

# Parse driver ID from sensors (explicitly parsing Driver_ID_MSB and Driver_ID_LSB as using Teltonika device and tachograph data)
def parse_driver_id_from_sensors(sensors):
    msb = None
    lsb = None
    for sensor in sensors:
        if sensor["label"] == "Driver_ID_MSB":
            msb = int(sensor["value"])
        elif sensor["label"] == "Driver_ID_LSB":
            lsb = int(sensor["value"])

    if msb is not None and lsb is not None:
        return (msb << 32) | lsb
    return None

# Assign driver to tracker
def assign_driver_to_tracker(tracker_id, driver):
    url = f"{API_BASE_URL}/tracker/employee/assign"
    payload = {
        "hash": API_KEY,
        "tracker_id": tracker_id,
        "driver_id": driver["id"]
    }

    print(f"Attempting to assign driver {driver['id']} ({driver['first_name']} {driver['last_name']}) to tracker {tracker_id}.")
    print(f"Payload: {payload}")
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
