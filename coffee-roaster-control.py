# main.py
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict
import asyncio
import json
from datetime import datetime
import csv
import os
import numpy as np
from scipy.interpolate import CubicSpline
import math
import time

app = FastAPI()

# Placeholder for actual hardware integration
class RoasterHardware:
    def read_temperature(self):
        pass

    def set_fan_speed(self, speed):
        pass

    def set_heating_element(self, power):
        pass

# Simulated roaster
class SimulatedRoaster:
    def __init__(self, heating_lag=5.0, speed_up_factor=5):
        self.bean_temperature = 25.0
        self.env_temperature = 25.0
        self.fan_speed = 0.0
        self.heating_power = 0.0
        self.current_heating_power = 0.0
        self.ambient_temperature = 25.0
        self.max_cooling_rate = 5.0
        self.heating_efficiency = 10.0
        self.heating_lag = heating_lag
        self.speed_up_factor = speed_up_factor
        self.last_update_time = time.time()

    def read_temperatures(self):
        current_time = time.time()
        elapsed_time = (current_time - self.last_update_time) * self.speed_up_factor
        self.last_update_time = current_time

        # Update current heating power based on lag
        heating_power_difference = self.heating_power - self.current_heating_power
        self.current_heating_power += heating_power_difference * elapsed_time / self.heating_lag

        # Calculate heating effect
        heating_effect = self.current_heating_power * self.heating_efficiency * elapsed_time
        
        # Calculate cooling effect
        env_temperature_difference = self.env_temperature - self.ambient_temperature
        env_cooling_factor = math.exp(env_temperature_difference / 100) - 1
        env_cooling_effect = min(self.max_cooling_rate, env_cooling_factor * (1 + self.fan_speed)) * elapsed_time
        
        # Update environment temperature
        self.env_temperature += heating_effect - env_cooling_effect
        
        # Update bean temperature (lags behind environment temperature)
        bean_temperature_difference = self.env_temperature - self.bean_temperature
        bean_heating_effect = bean_temperature_difference * 0.1 * elapsed_time
        self.bean_temperature += bean_heating_effect
        
        # Ensure temperatures don't go below ambient
        self.env_temperature = max(self.env_temperature, self.ambient_temperature)
        self.bean_temperature = max(self.bean_temperature, self.ambient_temperature)
        
        return self.bean_temperature, self.env_temperature

    def set_fan_speed(self, speed):
        self.fan_speed = max(0, min(1, speed))

    def set_heating_element(self, power):
        self.heating_power = max(0, min(1, power))

# Choose between simulated and real hardware
USE_SIMULATION = True
SPEED_UP_FACTOR = 5  # Simulation runs 5x faster than real time

roaster = SimulatedRoaster(heating_lag=3.0, speed_up_factor=SPEED_UP_FACTOR) if USE_SIMULATION else RoasterHardware()

class SetPoint(BaseModel):
    time: float
    temperature: float

class RoastSettings(BaseModel):
    setpoints: List[SetPoint]

    def get_target_temperature(self, current_time):
        if not self.setpoints:
            raise ValueError("No setpoints defined. Cannot calculate target temperature.")
        
        times = [sp.time for sp in self.setpoints]
        temperatures = [sp.temperature for sp in self.setpoints]
        
        if len(self.setpoints) == 1:
            # If there's only one setpoint, return its temperature
            return float(temperatures[0])
        
        cs = CubicSpline(times, temperatures)
        return float(cs(current_time))

roast_settings = RoastSettings(setpoints=[SetPoint(time=0.0, temperature=200.0)])
is_roasting = False
roast_data = []

roast_logs_dir = "roast_logs"
os.makedirs(roast_logs_dir, exist_ok=True)

# New: Path for storing roast profiles
PROFILES_FILE = "roast_profiles.json"

# New: Load profiles from file
def load_profiles():
    if os.path.exists(PROFILES_FILE):
        with open(PROFILES_FILE, 'r') as f:
            return json.load(f)
    return {}

# New: Save profiles to file
def save_profiles(profiles):
    with open(PROFILES_FILE, 'w') as f:
        json.dump(profiles, f, indent=2)

@app.get("/")
async def get():
    with open("coffee-roaster-interface.html", "r") as file:
        return HTMLResponse(content=file.read())

# Add these new global variables
is_preheating = False
preheat_target_temperature = 0
is_roast_completed = False

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global is_roasting, is_preheating, roast_start_time, preheat_target_temperature, is_roast_completed
    await websocket.accept()
    try:
        while True:
            if is_roasting or is_preheating:
                current_time = (datetime.now() - roast_start_time).total_seconds() if is_roasting else 0
                if USE_SIMULATION:
                    current_time *= SPEED_UP_FACTOR
                bean_temperature, env_temperature = roaster.read_temperatures()
                
                if is_roasting:
                    target_temperature = roast_settings.get_target_temperature(current_time)
                else:  # is_preheating
                    target_temperature = preheat_target_temperature
                
                # Simple PID-like control (you might want to adjust this for two temperatures)
                error = target_temperature - bean_temperature
                fan_speed = max(0, min(1, 0.5 - error * 0.02))
                heating_power = max(0, min(1, error * 0.05))
                
                roaster.set_fan_speed(fan_speed)
                roaster.set_heating_element(heating_power)
                
                if is_roasting:
                    roast_data.append([datetime.now().isoformat(), bean_temperature, env_temperature, fan_speed, heating_power])
                
                await websocket.send_json({
                    "time": current_time,
                    "bean_temperature": bean_temperature,
                    "env_temperature": env_temperature,
                    "target_temperature": target_temperature,
                    "fan_speed": fan_speed,
                    "heating_power": heating_power,
                    "is_preheating": is_preheating,
                    "is_roasting": is_roasting,
                    "is_roast_completed": is_roast_completed
                })
                
                # Check if the roast should end (only if we're actually roasting)
                if is_roasting and current_time >= roast_settings.setpoints[-1].time and bean_temperature >= target_temperature:
                    is_roasting = False
                    is_roast_completed = True
                    save_roast_data()
                    await websocket.send_json({"roast_finished": True})
            
            await asyncio.sleep(1 / SPEED_UP_FACTOR if USE_SIMULATION else 1)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

@app.post("/start_preheat")
async def start_preheat():
    global is_preheating, preheat_target_temperature, roast_settings, is_roast_completed
    if is_roasting:
        return {"message": "Cannot start preheating while roasting"}
    
    # Get the first setpoint temperature
    first_setpoint = roast_settings.setpoints[0] if roast_settings.setpoints else None
    if not first_setpoint:
        return {"message": "No setpoints defined"}
    
    preheat_target_temperature = first_setpoint.temperature
    is_preheating = True
    is_roast_completed = False
    return {"message": f"Preheating started to {preheat_target_temperature}°C"}

@app.post("/start_roast")
async def start_roast(settings: RoastSettings):
    global roast_settings, is_roasting, is_preheating, roast_data, roast_start_time
    if is_roasting:
        return {"message": "A roast is already in progress"}
    if not is_preheating:
        return {"message": "Please preheat before starting the roast"}
    roast_settings = settings
    is_roasting = True
    is_preheating = False
    roast_data = []
    roast_start_time = datetime.now()
    
    # Generate the entire roast profile
    total_time = settings.setpoints[-1].time
    time_points = np.linspace(0, total_time, num=int(total_time)+1)
    target_temperatures = [settings.get_target_temperature(t) for t in time_points]
    
    return {
        "message": "Roast started",
        "profile": {
            "time": time_points.tolist(),
            "target_temperature": target_temperatures
        }
    }

@app.get("/stop_roast")
async def stop_roast():
    global is_roasting, is_roast_completed
    if not is_roasting:
        return {"message": "No roast in progress"}
    is_roasting = False
    is_roast_completed = True
    save_roast_data()
    return {"message": "Roast stopped"}

@app.get("/reset_roast")
async def reset_roast():
    global is_roasting, is_preheating, is_roast_completed
    is_roasting = False
    is_preheating = False
    is_roast_completed = False
    return {"message": "Roast reset, ready for preheating"}

def save_roast_data():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"roast_log_{timestamp}.csv"
    
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Time', 'Bean_Temperature', 'Environment_Temperature', 'Fan_Speed', 'Heating_Power', 'Target_Temperature'])
        
        for row in roast_data:
            time = (datetime.fromisoformat(row[0]) - roast_start_time).total_seconds()
            if USE_SIMULATION:
                time *= SPEED_UP_FACTOR
            target_temp = get_target_temperature(time, roast_settings.setpoints)
            writer.writerow(row + [target_temp])
    
    print(f"Roast data saved to {filename}")

def get_target_temperature(time, setpoints):
    for i in range(len(setpoints) - 1):
        if setpoints[i].time <= time < setpoints[i+1].time:
            t1, t2 = setpoints[i].time, setpoints[i+1].time
            temp1, temp2 = setpoints[i].temperature, setpoints[i+1].temperature
            return temp1 + (temp2 - temp1) * (time - t1) / (t2 - t1)
    return setpoints[-1].temperature  # Return last setpoint temperature if time is beyond all setpoints

@app.get("/roast_logs")
async def get_roast_logs():
    logs = [f for f in os.listdir(roast_logs_dir) if f.endswith('.csv')]
    return {"logs": logs}

@app.get("/roast_log/{filename}")
async def get_roast_log(filename: str):
    filepath = os.path.join(roast_logs_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Log file not found")
    with open(filepath, "r") as file:
        reader = csv.DictReader(file)
        data = list(reader)
    return {"data": data}

# New: Route to save a roast profile
@app.post("/save_profile")
async def save_profile(profile: Dict):
    profiles = load_profiles()
    profile_name = profile.get('name')
    if not profile_name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    profiles[profile_name] = profile
    save_profiles(profiles)
    return {"message": f"Profile '{profile_name}' saved successfully"}

# New: Route to get all saved profiles
@app.get("/get_profiles")
async def get_profiles():
    profiles = load_profiles()
    return {"profiles": profiles}

# New: Route to load a specific profile
@app.get("/load_profile/{profile_name}")
async def load_profile(profile_name: str):
    profiles = load_profiles()
    if profile_name not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profiles[profile_name]

# New: Route to delete a profile
@app.delete("/delete_profile/{profile_name}")
async def delete_profile(profile_name: str):
    profiles = load_profiles()
    if profile_name not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    del profiles[profile_name]
    save_profiles(profiles)
    return {"message": f"Profile '{profile_name}' deleted successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
