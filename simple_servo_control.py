import maestro
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import threading
import time
import uvicorn
import numpy as np
import asyncio
import json

app = FastAPI()

# Serve static files (for the plot)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Servo Configuration
WIND_UP_SERVO = 0
POWER_SERVO = 1
FAN_SERVO = 2
SERVO_ACCELERATION = 4
SERVO_SPEED = 10
MIN_PULSE = 4000
MAX_PULSE = 8000

servo = maestro.Controller()

# Set acceleration and speed for all servos
for channel in [WIND_UP_SERVO, POWER_SERVO, FAN_SERVO]:
    servo.setAccel(channel, SERVO_ACCELERATION)
    servo.setSpeed(channel, SERVO_SPEED)

# Hardcoded curves for power and fan
def power_curve(t):
    return int(MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (np.sin(t / 30) + 1) / 2)

def fan_curve(t):
    return int(MIN_PULSE + (MAX_PULSE - MIN_PULSE) * (np.cos(t / 20) + 1) / 2)

# Generate the entire profile
def generate_profile():
    total_time = 600  # 10 minutes
    time_points = np.linspace(0, total_time, num=int(total_time)+1)
    power_profile = [power_curve(t) for t in time_points]
    fan_profile = [fan_curve(t) for t in time_points]
    return {
        "time": time_points.tolist(),
        "power": power_profile,
        "fan": fan_profile
    }

profile = generate_profile()

def wind_up_action():
    while True:
        # Move from min to max
        for pulse in range(MIN_PULSE, MAX_PULSE, 100):
            servo.setTarget(WIND_UP_SERVO, pulse)
            time.sleep(0.01)
        # Move from max to min
        for pulse in range(MAX_PULSE, MIN_PULSE, -100):
            servo.setTarget(WIND_UP_SERVO, pulse)
            time.sleep(0.01)
        time.sleep(60)  # Wait for 1 minute before next wind-up action

def control_servo(servo_id, curve_func):
    start_time = time.time()
    while True:
        elapsed_time = time.time() - start_time
        if elapsed_time > 600:  # Reset after 10 minutes
            start_time = time.time()
            elapsed_time = 0
        
        desired_position = curve_func(elapsed_time)
        desired_position = max(MIN_PULSE, min(MAX_PULSE, desired_position))
        servo.setTarget(servo_id, desired_position)
        
        time.sleep(0.1)

@app.get("/")
async def index():
    return FileResponse("simple-servo-control.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"profile": profile})
    
    try:
        start_time = time.time()
        while True:
            current_time = time.time() - start_time
            if current_time > 600:
                start_time = time.time()
                current_time = 0
            
            wind_up_position = servo.getPosition(WIND_UP_SERVO)
            power_position = servo.getPosition(POWER_SERVO)
            fan_position = servo.getPosition(FAN_SERVO)
            
            await websocket.send_json({
                "time": current_time,
                "wind_up": wind_up_position,
                "power": power_position,
                "fan": fan_position
            })
            
            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == '__main__':
    threading.Thread(target=wind_up_action, daemon=True).start()
    threading.Thread(target=control_servo, args=(POWER_SERVO, power_curve), daemon=True).start()
    threading.Thread(target=control_servo, args=(FAN_SERVO, fan_curve), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)