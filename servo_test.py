import maestro
import time
import matplotlib.pyplot as plt

servo = maestro.Controller()
servo_channel = 0  # Assuming we're using the first servo channel

# Set acceleration and speed
servo.setAccel(servo_channel, 4)  # Set servo acceleration to 4
servo.setSpeed(servo_channel, 10)  # Set servo speed to 10

# Servo Configuration
SERVO_CHANNEL = 0
SERVO_ACCELERATION = 4
SERVO_SPEED = 10
MIN_PULSE = 4000
MAX_PULSE = 8000
STEP_SIZE = 100

servo = maestro.Controller()

# Set acceleration and speed
servo.setAccel(SERVO_CHANNEL, SERVO_ACCELERATION)
servo.setSpeed(SERVO_CHANNEL, SERVO_SPEED)

# Lists to store data for plotting
desired_positions = []
actual_positions = []
timestamps = []
start_time = time.time()

# Move servo from min to max
for pulse in range(MIN_PULSE, MAX_PULSE + 1, STEP_SIZE):
    servo.setTarget(servo_channel, pulse)
    print(f"Setting servo position to: {pulse}")
    
    # Wait for the servo to reach the position
    while abs(servo.getPosition(servo_channel) - pulse) > 10:  # Tolerance of 10
        current_position = servo.getPosition(servo_channel)
        print(f"Current position: {current_position}")
        
        # Store data for plotting
        desired_positions.append(pulse)
        actual_positions.append(current_position)
        timestamps.append(time.time() - start_time)
        
        time.sleep(0.01)
    
    # Record final position for this step
    current_position = servo.getPosition(servo_channel)
    print(f"Reached position: {current_position}")
    
    desired_positions.append(pulse)
    actual_positions.append(current_position)
    timestamps.append(time.time() - start_time)

# Return to center position
center_pulse = 6000
servo.setTarget(servo_channel, center_pulse)
print("Returning to center position")

# Wait for the servo to reach the center position
while abs(servo.getPosition(servo_channel) - center_pulse) > 10:
    current_position = servo.getPosition(servo_channel)
    
    desired_positions.append(center_pulse)
    actual_positions.append(current_position)
    timestamps.append(time.time() - start_time)
    
    time.sleep(0.01)

# Get final position
final_position = servo.getPosition(servo_channel)
print(f"Final position: {final_position}")

# Store final data point for plotting
desired_positions.append(center_pulse)
actual_positions.append(final_position)
timestamps.append(time.time() - start_time)

servo.close()

# Plot the results
plt.figure(figsize=(10, 6))
plt.plot(timestamps, desired_positions, label='Desired Position')
plt.plot(timestamps, actual_positions, label='Actual Position')
plt.xlabel('Time (seconds)')
plt.ylabel('Servo Position')
plt.title('Servo Position vs Time')
plt.legend()
plt.grid(True)
plt.show()