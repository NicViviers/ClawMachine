from machine import Pin, ADC
from utime import sleep_ms
from random import randint

class Relay:
    """
    A wrapper class to control an active-LOW relay.
    - .on() turns the relay ON (sends a LOW signal).
    - .off() turns the relay OFF (sends a HIGH signal).
    """
    pin: Pin

    def __init__(self, pin: int):
        """Initializes the relay on a specific GPIO pin."""
        self.pin = Pin(pin, Pin.OUT)

    def on(self):
        """Turns the relay ON by setting the pin LOW (0)."""
        self.pin.value(0)
        sleep_ms(15)

    def off(self):
        """Turns the relay OFF by setting the pin HIGH (1)."""
        self.pin.value(1)
        sleep_ms(15)

    def value(self, value: int):
        """Sets the relay to the provided value"""
        self.pin.value(value)
        sleep_ms(15)


class Motor:
    pole1: Relay
    pole2: Relay
    DIR_OFF = (False, False)

    def __init__(self, pole1: int, pole2: int):
        self.pole1 = Relay(pole1)
        self.pole2 = Relay(pole2)
        self.off()

    def set_dir(self, dir: tuple[bool, bool]):
        self.pole1.value(dir[0])
        self.pole2.value(dir[1])

    def off(self):
        # Changes both polarities to break the circuit
        self.pole1.off()
        self.pole2.off()
        sleep_ms(15)


class YMotor(Motor):
    DIR_FORWARD = (False, True)
    DIR_BACKWARD = (True, False)

    limit_back = Pin(16, Pin.IN, Pin.PULL_UP)
    limit_front = Pin(17, Pin.IN, Pin.PULL_UP)

    def __init__(self):
        super().__init__(6, 5)

    def home(self):
        super().set_dir(self.DIR_FORWARD)

        while self.limit_front.value():
            sleep_ms(25)

        # Move back slightly to release pressure off limit switch
        self.set_dir(self.DIR_BACKWARD)
        sleep_ms(15)
        self.off()

    
class XMotor(Motor):
    DIR_RIGHT = (True, False)
    DIR_LEFT = (False, True)

    limit_right = Pin(18, Pin.IN, Pin.PULL_UP)
    TOTAL_TRAVEL_TIME_MS = 1300
    position = 0

    def __init__(self):
        super().__init__(4, 3)

    def off(self):
        super().off()
        self.last_dir = self.DIR_OFF

    def home(self):
        super().set_dir(self.DIR_RIGHT)

        while self.limit_right.value():
            sleep_ms(25)

        self.off()
        self.position = self.TOTAL_TRAVEL_TIME_MS # Re-calibrate the position

        # Move back slightly to release pressure off limit switch
        super().set_dir(self.DIR_LEFT)
        sleep_ms(30)
        self.off()


class Claw(Motor):
    DIR_UP = (False, True)
    DIR_DOWN = (True, False)
    limit_up = Pin(19, Pin.IN, Pin.PULL_UP)
    claw = Relay(0)

    def __init__(self):
        super().__init__(2, 1)
        self.claw.off()

    def rise(self):
        self.set_dir(self.DIR_UP)

        while self.limit_up.value():
            sleep_ms(50)

        self.off()

        # Move back slightly to release pressure off limit switch
        self.set_dir(self.DIR_DOWN)
        sleep_ms(30)
        self.off()

    def drop(self):
        self.set_dir(self.DIR_DOWN)
        sleep_ms(1120)
        self.off()

    def grab(self):
        self.claw.on()

    def release(self):
        self.claw.off()


class Keyboard:
    CENTER_VOLTAGE = 1.65
    DEAD_ZONE = 0.35
    DEBOUNCE_THRESHOLD = 2

    btn = Pin(22, Pin.IN, Pin.PULL_UP)
    SW = Pin(28, Pin.IN, Pin.PULL_UP)
    VRx = ADC(0)
    VRy = ADC(1)

    def __init__(self):
        self._x_state = "IDLE"
        self._y_state = "IDLE"
        self._x_counter = 0
        self._y_counter = 0

    def _get_raw_x(self) -> float:
        return round(self.VRx.read_u16() * 3.3 / 65536, 2)

    def _get_raw_y(self) -> float:
        return round(self.VRy.read_u16() * 3.3 / 65536, 2)

    def update(self):
        """Call this once per loop to process debouncing."""
        raw_x = self._get_raw_x()
        raw_y = self._get_raw_y()

        # Logic for X Axis
        new_x_dir = "IDLE"
        if raw_x > self.CENTER_VOLTAGE + self.DEAD_ZONE:
            new_x_dir = "LEFT"
        elif raw_x < self.CENTER_VOLTAGE - self.DEAD_ZONE:
            new_x_dir = "RIGHT"

        if new_x_dir == self._x_state:
            self._x_counter = min(self._x_counter + 1, self.DEBOUNCE_THRESHOLD)
        else:
            self._x_counter = 0
            self._x_state = new_x_dir

        # Logic for Y Axis
        new_y_dir = "IDLE"
        if raw_y > self.CENTER_VOLTAGE + self.DEAD_ZONE:
            new_y_dir = "UP"
        elif raw_y < self.CENTER_VOLTAGE - self.DEAD_ZONE:
            new_y_dir = "DOWN"

        if new_y_dir == self._y_state:
            self._y_counter = min(self._y_counter + 1, self.DEBOUNCE_THRESHOLD)
        else:
            self._y_counter = 0
            self._y_state = new_y_dir

    @property
    def LEFT(self) -> bool:
        return self._x_state == "LEFT" and self._x_counter >= self.DEBOUNCE_THRESHOLD
    
    @property
    def RIGHT(self) -> bool:
        return self._x_state == "RIGHT" and self._x_counter >= self.DEBOUNCE_THRESHOLD
    
    @property
    def UP(self) -> bool:
        return self._y_state == "UP" and self._y_counter >= self.DEBOUNCE_THRESHOLD
    
    @property
    def DOWN(self) -> bool:
        return self._y_state == "DOWN" and self._y_counter >= self.DEBOUNCE_THRESHOLD

    @property
    def CLAW(self) -> bool:
        return not bool(self.btn.value())
    
    @property
    def AUTO_MODE(self) -> bool:
        return not bool(self.SW.value())


class Machine:
    # Relay bank
    power = Relay(7)
    y_motor = YMotor()
    x_motor = XMotor()
    claw = Claw()
    keyboard = Keyboard()
    auto_play = Pin(11, Pin.IN, Pin.PULL_UP)

    def __init__(self):
        self.claw.off()
        self.power.on()

        self.x_motor_current_dir = self.x_motor.DIR_OFF
        self.y_motor_current_dir = (False, False)
        self.x_motor.position = self.x_motor.TOTAL_TRAVEL_TIME_MS

        self.x_motor.home()
        self.y_motor.home()
        self.claw.rise()

        while True:
            self.keyboard.update()
            
            # Auto play mode
            if self.auto_play.value():
                self.x_motor.set_dir(self.x_motor.DIR_OFF)
                self.y_motor.set_dir(self.y_motor.DIR_OFF)

                counter = 3
                while self.auto_play.value() and counter != 0:
                    sleep_ms(800)
                    counter -=1

                if counter == 0:
                    print("Auto-mode enabled!")
                    self.auto_mode()

            # Handle claw button inputs
            if self.keyboard.CLAW:
                self.x_motor.set_dir(self.x_motor.DIR_OFF)
                self.y_motor.set_dir(self.y_motor.DIR_OFF)
                self.claw_sequence()
                continue

            # Determine the desired state from the joystick
            desired_x_dir = self.x_motor_current_dir
            desired_y_dir = self.y_motor_current_dir

            if self.keyboard.LEFT:
                desired_x_dir = self.x_motor.DIR_LEFT
            elif self.keyboard.RIGHT:
                desired_x_dir = self.x_motor.DIR_RIGHT
            else:
                desired_x_dir = self.x_motor.DIR_OFF

            if self.keyboard.UP:
                desired_y_dir = self.y_motor.DIR_BACKWARD
            elif self.keyboard.DOWN:
                desired_y_dir = self.y_motor.DIR_FORWARD
            else:
                desired_y_dir = self.y_motor.DIR_OFF

            # Update X-Motor position and state if necessary
            # Check for software and hardware limits
            if desired_x_dir == self.x_motor.DIR_RIGHT and self.x_motor.limit_right.value() == 0:
                desired_x_dir = self.x_motor.DIR_OFF # Force stop
                self.x_motor.position = self.x_motor.TOTAL_TRAVEL_TIME_MS # Re-calibrate!
            elif desired_x_dir == self.x_motor.DIR_LEFT and self.x_motor.position <= 0:
                desired_x_dir = self.x_motor.DIR_OFF # Force stop

            if desired_x_dir != self.x_motor_current_dir:
                if desired_x_dir == self.x_motor.DIR_OFF:
                    self.x_motor.off()
                else:
                    self.x_motor.set_dir(desired_x_dir)
                self.x_motor_current_dir = desired_x_dir

            # Y-Axis hardware limits
            if (desired_y_dir == self.y_motor.DIR_FORWARD and self.y_motor.limit_front.value() == 0) or \
               (desired_y_dir == self.y_motor.DIR_BACKWARD and self.y_motor.limit_back.value() == 0):
                desired_y_dir = (False, False) # Force stop
            
            # Update Y-Motor state if necessary
            if desired_y_dir != self.y_motor_current_dir:
                if desired_y_dir == (False, False):
                    self.y_motor.off()
                else:
                    self.y_motor.set_dir(desired_y_dir)
                self.y_motor_current_dir = desired_y_dir

            # Incrementally update X position based on how long the loop takes
            loop_delay = 10 # This must match your sleep_ms value
            if self.x_motor_current_dir == self.x_motor.DIR_LEFT:
                self.x_motor.position -= loop_delay
            elif self.x_motor_current_dir == self.x_motor.DIR_RIGHT:
                self.x_motor.position += loop_delay

            # Clamp position to stay within valid range
            self.x_motor.position = max(0, min(self.x_motor.position, self.x_motor.TOTAL_TRAVEL_TIME_MS))

            sleep_ms(loop_delay)

    def claw_sequence(self):
        self.claw.drop()
        self.claw.grab()
        sleep_ms(500)

        self.claw.rise()
        sleep_ms(250)

        self.x_motor.home()
        self.y_motor.home()
        sleep_ms(500)
        self.claw.release()
    
    def auto_mode(self):
        while True:
            self.x_motor.set_dir(self.x_motor.DIR_LEFT)
            sleep_ms(randint(300, 1290))
            self.x_motor.off()

            self.y_motor.set_dir(self.y_motor.DIR_BACKWARD)
            sleep_ms(randint(300, 1290))
            self.y_motor.off()

            self.claw_sequence()

            counter = 0
            while counter != 40:
                if self.keyboard.AUTO_MODE:
                    print("Auto-mode disabled!")
                    return

                counter += 1
                sleep_ms(500)
        

Machine()
