import time
from machine import PWM
from machine import RTC
from machine import Pin
from machine import Timer
import _thread
from webserver import WebServer
from network import WLAN

HOURS_SETUP_CYCLE = 790/1000
MINUTES_SETUP_CYCLE = 880/1000
SECONDS_SETUP_CYCLE = 860/1000

HOURS_UPPER_CYCLE = 765/1000
MINUTES_UPPER_CYCLE = 795/1000
SECONDS_UPPER_CYCLE = 770/1000

MIN_BUTTON_PRESS_TIME = 0.05
MAX_BUTTON_PRESS_TIME = 0.40

HOURS_PANEL_METER_PIN = 'P12'
MINUTES_PANEL_METER_PIN = 'P11'
SECONDS_PANEL_METER_PIN = 'P10'
PUSH_BUTTON_PIN = 'P13'
ROTARY_ENCODER_A_SIGNAL_PIN = 'P21'
ROTARY_ENCODER_B_SIGNAL_PIN = 'P22'

class State(object):
    DEAD = -1
    CLOCK = 0
    SET_HOUR = 1
    SET_MINUTE = 2
    SET_SECOND = 3
    SET_RTC_TIME = 4
    START = CLOCK
    END = SET_RTC_TIME

class App(object):
    # clock mode state
    currentState = State.CLOCK

    # real time clock
    rtc = RTC()

    # Pulse width Modulation and Channels
    pwmHours = None
    pwmMinutes = None
    pwmSeconds = None
    pwmChHours = None
    pwmChMinutes = None
    pwmChSeconds = None

    currentHoursDutyCycle = -1
    currentMinutesDutyCycle = -1
    currentSecondsDutyCycle = -1
    updateClockFaceAlive = False

    # user interface controls and helpers
    buttonPressChrono = None
    pushButton = None
    encoderASignal = None
    encoderBSignal = None

    # state helpers for A and B encoder
    lastEncoderAState = 1
    lastEncoderBState = 1

    stepTimeCallback = None
    currentHour = 1
    currentMinute = 0
    currentSecond = 0
    timeIsDirty = False

    webServer = None

def move_to_next_state():
    newState = App.currentState + 1
    if newState > State.END:
        newState = State.START
    App.currentState = newState

def set_rtc_time():
    print("set_rtc_time, isDirty: ", App.timeIsDirty)
    if App.timeIsDirty is True:
        print("settime time to, hour: ", App.currentHour, ":",
            App.currentMinute, ":", App.currentSecond)
        App.timeIsDirty = False
        year, month, day, hour, minute, second, microsecond, tzinfo = App.rtc.now()
        App.rtc.init((year, month, day, App.currentHour-1, App.currentMinute,
            App.currentSecond, 0, tzinfo))

def step_hour_callback(step):
    hour = App.currentHour + step
    if hour > 12:
        hour = 1
    if hour < 1:
        hour = 12
    if App.currentHour != hour:
        App.timeIsDirty = True
        App.currentHour = hour
    update_clock_face(App.currentHour, -1, -1)

def step_minute_callback(step):
    minute = App.currentMinute + step
    if minute > 59:
        minute = 0
    if minute < 0:
        minute = 59
    if App.currentMinute != minute:
        App.timeIsDirty = True
        App.currentMinute = minute
    update_clock_face(-1, App.currentMinute, -1)

def step_second_callback(step):
    second = App.currentSecond + step
    if second > 59:
        second = 0
    if second < 0:
        second = 59
    if App.currentSecond != second:
        App.timeIsDirty = True
        App.currentSecond = second
    update_clock_face(-1, -1, App.currentSecond)

def update_current_time_from_rtc():
    year, month, day, hour, minute, second, microsecond, tzinfo = App.rtc.now()
    #print("time from rtc: ", hour, ":", minute, ":", second)

    # we only track 1-12, we don't care about AM/PM
    if hour > 12:
        hour = hour - 12
    if hour == 0:
        hour = 12

    App.currentHour = hour
    App.currentMinute = minute
    App.currentSecond = second

# Rotary Encoder: https://www.adafruit.com/product/377
# State Transition Diagram
#              A  |  B
# ==========|=====+=====
# Resting   |  1  |  1
# ----------+-----+-----
# CCW       |     |
#    Step 1 |  1  |  0  - B goes low
#    Step 2 |  0  |  0  - A goes low
#    Step 3 |  0  |  1  - B goes high
#    Step 4 |  1  |  1  - A goes high
# ----------+-----+-----
# CW        |     |
#    Step 1 |  0  |  1 - A goes low
#    Step 2 |  0  |  0 - B goes low
#    Step 3 |  1  |  0 - A goes high
#    Step 4 |  1  |  1 - B goes high

def dump_encoder_state(tag, aValue, bValue):
    #print(tag, ", a: ", aValue, ", b: ", bValue)
    pass

def get_encoder_value():
    return App.encoderASignal.value(), App.encoderBSignal.value()

def update_encoder_state(stateA, stateB):
    App.lastEncoderAState = stateA
    App.lastEncoderBState = stateB

def encoder_a_callback(p):
    encoderAValue, encoderBValue = get_encoder_value()
    dump_encoder_state("encoder_a_callback", encoderAValue, encoderBValue)
    # if we got called in the resting spot because A went from 0 -> 1, we will
    # assume the user turned the knob to the left.
    # No need to check for all of the other state transitions.
    if encoderAValue == 1 and encoderBValue == 1:
        if App.lastEncoderAState == 0 and App.lastEncoderBState == 1:
            # print("<---- left turn detected")
            callback = App.stepTimeCallback
            if callback:
                callback(-1)

    update_encoder_state(encoderAValue, encoderBValue)

def encoder_b_callback(p):
    encoderAValue, encoderBValue = get_encoder_value()
    dump_encoder_state("encoder_b_callback", encoderAValue, encoderBValue)
    # if we got called in the resting spot because B went from 1 -> 0, we will
    # assume the user turned the knob to the right
    # No need to check for all of the other state transitions.
    if encoderAValue == 1 and encoderBValue == 1:
        if App.lastEncoderAState == 1 and App.lastEncoderBState == 0:
            # print("right turn detected ---->")
            callback = App.stepTimeCallback
            if callback:
                callback(1)

    update_encoder_state(encoderAValue, encoderBValue)

def push_button_callback(p):
    val = p.value()
    if p.value() == 0 and App.buttonPressChrono is not None:
        App.buttonPressChrono.stop()
        elapsedTime = App.buttonPressChrono.read()
        if elapsedTime > MIN_BUTTON_PRESS_TIME and elapsedTime < MAX_BUTTON_PRESS_TIME:
            move_to_next_state()
        App.buttonPressChrono = None
    elif p.value() == 1 and App.buttonPressChrono is None:
        App.buttonPressChrono = Timer.Chrono()
        App.buttonPressChrono.start()

def update_clock_face(hour, minute, second):
    hoursCycle = HOURS_SETUP_CYCLE if hour == -1 else HOURS_UPPER_CYCLE/12 * (hour-1)
    if hoursCycle != App.currentHoursDutyCycle:
        App.currentHoursDutyCycle = hoursCycle
        App.pwmChHours.duty_cycle(App.currentHoursDutyCycle)
        #print("updating clock face hours to: ", hour, "(", App.currentHoursDutyCycle, ")")
    minutesCycle = MINUTES_SETUP_CYCLE if minute == -1 else MINUTES_UPPER_CYCLE/60 * minute
    if minutesCycle != App.currentMinutesDutyCycle:
        App.currentMinutesDutyCycle = minutesCycle
        App.pwmChMinutes.duty_cycle(App.currentMinutesDutyCycle)
        #print("updating clock face minutes to: ", minute, "(", App.currentMinutesDutyCycle, ")")
    secondsCycle = SECONDS_SETUP_CYCLE if second == -1 else SECONDS_UPPER_CYCLE/60 * second
    if secondsCycle != App.currentSecondsDutyCycle:
        App.currentSecondsDutyCycle = secondsCycle
        App.pwmChSeconds.duty_cycle(App.currentSecondsDutyCycle)
        #print("updating clock face seconds to: ", second, "(", App.currentSecondsDutyCycle, ")")

def update_clock_face_loop(delay):
    while App.currentState == State.CLOCK:
        update_current_time_from_rtc()
        update_clock_face(App.currentHour, App.currentMinute, App.currentSecond)
        time.sleep(delay)

def awesome_reset_panel_sequence():
    # this is only for visual coolness
    for cycle in range(0, HOURS_UPPER_CYCLE*1000):
        App.pwmChHours.duty_cycle(cycle/1000)
        App.pwmChMinutes.duty_cycle(cycle/1000)
        App.pwmChSeconds.duty_cycle(cycle/1000)
        time.sleep(.0015)
    # hold for a moment
    time.sleep(.5)
    # drop back to zero
    App.pwmChHours.duty_cycle(0)
    App.pwmChMinutes.duty_cycle(0)
    App.pwmChSeconds.duty_cycle(0)
    # give time for the arms to return and rest
    time.sleep(1.5)

def set_pin_callback(p, cb):
    p.callback(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=cb)

def webserver_request_callback(params):
    print('webserver_request_callback:', params)
    try:
        hourValue = None
        minuteValue = None
        secondValue = None
        if 'hour' in params:
            val = int(params['hour'])
            val = val if val >= 0 and val <= 23 else None
            if val is not None:
                if val > 12:
                    val = val - 12
                if val == 0:
                    val = 12
            hourValue = val
        if 'minute' in params:
            val = int(params['minute'])
            print('minute a', val)
            minuteValue = val if val >= 0 and val <= 59 else None
            print('minute b', minuteValue)
        if 'second' in params:
            val = int(params['second'])
            secondValue = val if val >= 0 and val <= 59 else None
        if hourValue or minuteValue or secondValue:
            year, month, day, hour, minute, second, microsecond, tzinfo = App.rtc.now()
            hour = hourValue if hourValue is not None else hour
            minute = minuteValue if minuteValue is not None else minute
            second = secondValue if secondValue is not None else second
            print('setting time to: %d:%d:%d' % (hour, minute, second))
            App.rtc.init((year, month, day, hour, minute, second, 0, tzinfo))

    except ValueError as e:
        print('webserver_request_callback error: ', str(e))
        return False

    return True

def deinit():
    App.currentState = State.DEAD

    # TODO - ensure any thread running is shutdown/killed
    # when available in Micropython, would be nice to have a way to join
    # on a _thread the thread-id returned from _thread.start_new_thread is
    # always 'None'

    if App.webServer:
        App.webServer.stop()
        App.webServer = None

    # stop all callbacks
    if App.encoderASignal:
        set_pin_callback(App.encoderASignal, None)
        App.encoderASignal = None
    if App.encoderBSignal:
        set_pin_callback(App.encoderBSignal, None)
        App.encoderBSignal = None
    if App.pushButton:
        set_pin_callback(App.pushButton, None)
        App.pushButton = None

    # stop button pressed timer
    if App.buttonPressChrono:
        App.buttonPressChrono.stop()
        App.buttonPressChrono = None

    # stop all pwm by setting their duty cycle to 0
    # !! there is no 'deinit' on PWM or PWM.channel. !!
    if App.pwmChHours:
        App.pwmChHours.duty_cycle(0)
        App.pwmChHours = None
    if App.pwmChMinutes:
        App.pwmChMinutes.duty_cycle(0)
        App.pwmChMinutes = None
    if App.pwmChSeconds:
        App.pwmChSeconds.duty_cycle(0)
        App.pwmChSeconds = None
    if App.pwmHours:
        PWM(0, frequency=0)
        App.pwmHours = None
    if App.pwmMinutes:
        PWM(1, frequency=0)
        App.pwmMinutes = None
    if App.pwmSeconds:
        PWM(2, frequency=0)
        App.pwmSeconds = None

def init():
    WLAN(mode=WLAN.AP, ssid='Panel Meter Clock', auth=(None))

    # setup the PWM channels
    App.pwmHours = PWM(0, frequency=5000)
    App.pwmMinutes = PWM(1, frequency=5000)
    App.pwmSeconds = PWM(2, frequency=5000)
    App.pwmChHours = App.pwmHours.channel(0, pin=HOURS_PANEL_METER_PIN, duty_cycle=0)
    App.pwmChMinutes = App.pwmMinutes.channel(1, pin=MINUTES_PANEL_METER_PIN, duty_cycle=0)
    App.pwmChSeconds = App.pwmSeconds.channel(2, pin=SECONDS_PANEL_METER_PIN, duty_cycle=0)

    # push button callback (active HIGH)
    App.pushButton = Pin(PUSH_BUTTON_PIN, Pin.IN)
    set_pin_callback(App.pushButton, push_button_callback)

    # rotary encoder callback
    App.encoderASignal = Pin(ROTARY_ENCODER_A_SIGNAL_PIN, Pin.IN, pull=Pin.PULL_UP)
    set_pin_callback(App.encoderASignal, encoder_a_callback)
    App.encoderBSignal = Pin(ROTARY_ENCODER_B_SIGNAL_PIN, Pin.IN, pull=Pin.PULL_UP)
    set_pin_callback(App.encoderBSignal, encoder_b_callback)

    # initialize the Real Time Clock to the date/time this project was started
    App.rtc.init((2017, 11, 24, 3, 22, 0, 0, 0))

    # create and start the webServer
    App.webServer = WebServer(80, 'index.htm', webserver_request_callback, True)
    App.webServer.start()


if __name__ == '__main__':
    init()
    awesome_reset_panel_sequence()
    try:
        prevState = -1
        while True:
            workingState = App.currentState
            if prevState != workingState:
                App.stepTimeCallback = None
                if workingState == State.CLOCK:
                    print("CLOCK")
                    _thread.start_new_thread(update_clock_face_loop, (.3,))
                if workingState == State.SET_HOUR:
                    print("SET_HOUR")
                    App.stepTimeCallback = step_hour_callback
                if workingState == State.SET_MINUTE:
                    print("SET_MINUTE")
                    App.stepTimeCallback = step_minute_callback
                if workingState == State.SET_SECOND:
                    print("SET_SECOND")
                    App.stepTimeCallback = step_second_callback
                if workingState == State.SET_RTC_TIME:
                    set_rtc_time()
                    move_to_next_state()

                # if in setup mode, force update the clock face
                if App.stepTimeCallback:
                    App.stepTimeCallback(0)
                prevState = workingState
            time.sleep(.1)
    except KeyboardInterrupt:
        pass
    finally:
        deinit()
