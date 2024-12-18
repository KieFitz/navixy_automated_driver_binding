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

# Memory to track last assigned drivers
last_assigned_drivers = {}

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
        "trackers": tracker_ids,
        "sensor_type": "state"
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
        sensors = tracker_data.get("virtual_sensors", [])
        driver_id = parse_driver_id_from_sensors(sensors)

        if driver_id:
            driver = driver_map.get(driver_id)
            if driver:
                employee_id = driver["id"]  # Renamed for clarity
                # Check if already assigned
                if last_assigned_drivers.get(tracker_id) == employee_id:
                    print(f"Tracker {tracker_id} is already assigned to employee_id {employee_id}. Skipping.")
                    continue

                print(f"Matching employee_id {employee_id} for driver_id {driver_id}.")
                assign_driver_to_tracker(tracker_id, driver, driver_id)
                last_assigned_drivers[tracker_id] = employee_id
            else:
                print(f"No matching driver found in driver_map for driver_id {driver_id}. Attempting to parse driver name and add new driver.")
                driver_name, driver_surname = parse_driver_name_from_sensors(sensors)
                if driver_name and driver_surname:
                    add_driver_to_navixy(driver_name, driver_surname, driver_id)
                    fetch_drivers()  # Refresh driver list after adding new driver
        else:
            # Unassign driver if no valid Driver ID is found
            if tracker_id in last_assigned_drivers:
                print(f"No valid Driver ID found for tracker {tracker_id}. Unassigning driver.")
                unassign_driver_from_tracker(tracker_id)
                last_assigned_drivers.pop(tracker_id, None)

# Parse driver ID from sensors (explicitly parsing Driver_ID_MSB and Driver_ID_LSB as using Teltonika device and tachograph data)
def parse_driver_id_from_sensors(sensors):
    msb = None
    lsb = None
    for sensor in sensors:
        if sensor["label"] == "Driver_ID_MSB":
            try:
                msb = int(sensor["value"])  # Directly parse as integer
            except (ValueError, TypeError):
                print(f"Invalid MSB value: {sensor['value']}")
                return None
        elif sensor["label"] == "Driver_ID_LSB":
            try:
                lsb = int(sensor["value"])  # Directly parse as integer
            except (ValueError, TypeError):
                print(f"Invalid LSB value: {sensor['value']}")
                return None

    if msb is not None and lsb is not None:
        # Convert MSB and LSB to hex
        msb_hex = f"{msb:08x}"
        lsb_hex = f"{lsb:08x}"

        # Convert hex to ASCII characters
        msb_ascii = "".join(chr(int(msb_hex[i:i + 2], 16)) for i in range(0, len(msb_hex), 2))
        lsb_ascii = "".join(chr(int(lsb_hex[i:i + 2], 16)) for i in range(0, len(lsb_hex), 2))

        # Combine ASCII strings
        driver_id = msb_ascii + lsb_ascii
        print(f"Processed Driver ID: {driver_id} (MSB: {msb}, LSB: {lsb})")
        return driver_id

    print("Driver_ID_MSB or Driver_ID_LSB missing or invalid in sensors.")
    return None

# Parse driver name from sensors
# Parse driver name and surname from sensors
def parse_driver_name_from_sensors(sensors):
    driver_name = ""
    driver_surname = ""
    for sensor in sensors:
        if sensor["label"] == "dn":
            try:
                driver_name = sensor["value"]  # Extract driver name directly
                if driver_name in ["", "Off", None]:
                    print(f"Invalid or missing driver name: {driver_name}")
                    return None, None
            except (KeyError, TypeError):
                print(f"Error parsing driver name from sensor: {sensor}")
                return None, None
        elif sensor["label"] == "ds":
            try:
                driver_surname = sensor["value"]  # Extract driver surname directly
                if driver_surname in ["", "Off", None]:
                    print(f"Invalid or missing driver surname: {driver_surname}")
                    return None, None
            except (KeyError, TypeError):
                print(f"Error parsing driver surname from sensor: {sensor}")
                return None, None

    if driver_name and driver_surname:
        print(f"Parsed driver name: {driver_name}, surname: {driver_surname}")
    else:
        print("Driver name or surname not found in sensors.")
    return driver_name, driver_surname

# Add new driver to Navixy
def add_driver_to_navixy(driver_name, driver_surname, driver_id):
    url = f"{API_BASE_URL}/employee/create"
    payload = {
        "hash": API_KEY,
        "force_reassign": True,
        "employee": {
            "id": None,
            "files": [],
            "first_name": driver_name,
            "middle_name": "",
            "last_name": driver_surname,
            "email": "",
            "phone": "",
            "driver_license_number": "",
            "driver_license_cats": "",
            "driver_license_issue_date": None,
            "driver_license_valid_till": None,
            "hardware_key": driver_id,
            "ssn": "",
            "personnel_number": "",
            "location": None,
            "tags": [],
            "fields": {}
        }
    }

    print(f"Adding new driver to Navixy: {payload}")
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        print(f"Driver {driver_name} added successfully.")
    else:
        print(f"Error adding driver: {response.status_code}, {response.text}")


# Assign driver to tracker
def assign_driver_to_tracker(tracker_id, driver, driver_id):
    url = f"{API_BASE_URL}/tracker/employee/assign"
    payload = {
        "hash": API_KEY,
        "tracker_id": tracker_id,
        "new_employee_id": driver["id"]
    }

    print(f"Attempting to assign employee_id {driver['id']} ({driver['first_name']} {driver['last_name']}) to tracker {tracker_id} using driver_id {driver_id}.")
    print(f"Payload: {payload}")
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        print(f"Assigned employee_id {driver['id']} to tracker {tracker_id} successfully.")
    elif response.status_code == 400:
        # Handle specific "no change needed" error
        response_json = response.json()
        if response_json.get("status", {}).get("code") == 263:
            print(f"No change needed for tracker {tracker_id}. Skipping assignment.")
        else:
            print(f"Unexpected error while assigning employee_id: {response.text}")
    else:
        print(f"Error assigning employee_id: {response.status_code}, {response.text}")

# Unassign driver from tracker
def unassign_driver_from_tracker(tracker_id):
    url = f"{API_BASE_URL}/tracker/employee/assign"
    payload = {
        "hash": API_KEY,
        "tracker_id": tracker_id,
        "new_employee_id": None
    }

    print(f"Unassigning driver from tracker {tracker_id}. Making API call.")
    print(f"Payload: {payload}")
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        print(f"Driver unassigned from tracker {tracker_id} successfully.")
    else:
        print(f"Error unassigning driver: {response.status_code}, {response.text}")

# Schedule tasks
schedule.every().day.at("00:00").do(fetch_drivers)
schedule.every().day.at("00:10").do(fetch_trackers)
schedule.every(2).minutes.do(fetch_sensor_data)

if __name__ == "__main__":
    # Run daily tasks immediately on start
    fetch_drivers()
    fetch_trackers()

    # Run the scheduler
    while True:
        schedule.run_pending()
        time.sleep(1)
