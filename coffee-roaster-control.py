# main.py
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List
import asyncio
import json
from datetime import datetime
import csv
import os
import numpy as np
from scipy.interpolate import CubicSpline

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
    def __init__(self):
        self.temperature = 25.0
        self.fan_speed = 0.0
        self.heating_power = 0.0

    def read_temperature(self):
        # Simple simulation of temperature change
        self.temperature += (self.heating_power * 10) - (self.fan_speed * 0.05)
        return self.temperature

    def set_fan_speed(self, speed):
        self.fan_speed = speed

    def set_heating_element(self, power):
        self.heating_power = power

# Choose between simulated and real hardware
USE_SIMULATION = True
roaster = SimulatedRoaster() if USE_SIMULATION else RoasterHardware()

class SetPoint(BaseModel):
    time: float
    temperature: float

class RoastSettings(BaseModel):
    setpoints: List[SetPoint]

    def get_target_temperature(self, current_time):
        times = [sp.time for sp in self.setpoints]
        temperatures = [sp.temperature for sp in self.setpoints]
        cs = CubicSpline(times, temperatures)
        return float(cs(current_time))

roast_settings = RoastSettings(setpoints=[SetPoint(time=0.0, temperature=200.0)])
is_roasting = False
roast_data = []

roast_logs_dir = "roast_logs"
os.makedirs(roast_logs_dir, exist_ok=True)

@app.get("/")
async def get():
    with open("coffee-roaster-interface.html", "r") as file:
        return HTMLResponse(content=file.read())

@app.post("/start_roast")
async def start_roast(settings: RoastSettings):
    global roast_settings, is_roasting, roast_data, roast_start_time
    if is_roasting:
        return {"message": "A roast is already in progress"}
    roast_settings = settings
    is_roasting = True
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
    global is_roasting
    is_roasting = False
    save_roast_data()
    return {"message": "Roast stopped"}

def save_roast_data():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"roast_log_{timestamp}.csv"
    filepath = os.path.join(roast_logs_dir, filename)
    with open(filepath, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Time", "Temperature", "Target Temperature", "Fan Speed", "Heating Power"])
        for row in roast_data:
            writer.writerow(row + [roast_settings.target_temperature])  # Add target temperature to each row

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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global is_roasting, roast_start_time
    await websocket.accept()
    try:
        while True:
            if is_roasting:
                current_time = (datetime.now() - roast_start_time).total_seconds()
                temperature = roaster.read_temperature()
                target_temperature = roast_settings.get_target_temperature(current_time)
                
                # Simple PID-like control
                error = target_temperature - temperature
                fan_speed = max(0, min(1, 0.5 - error * 0.02))
                heating_power = max(0, min(1, error * 0.05))
                
                roaster.set_fan_speed(fan_speed)
                roaster.set_heating_element(heating_power)
                
                roast_data.append([datetime.now().isoformat(), temperature, target_temperature, fan_speed, heating_power])
                
                await websocket.send_json({
                    "time": current_time,
                    "temperature": temperature,
                    "target_temperature": target_temperature,
                    "fan_speed": fan_speed,
                    "heating_power": heating_power
                })
                
                # Check if the roast should end
                if current_time >= roast_settings.setpoints[-1].time and temperature >= target_temperature:
                    is_roasting = False
                    save_roast_data()
                    await websocket.send_json({"roast_finished": True})
            
            await asyncio.sleep(1)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
