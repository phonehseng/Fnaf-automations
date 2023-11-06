import os
import sys
import pyautogui
from fnaf_framework import MyBot
from fnafobjects.fnaf import Fnafobj
import time
import keyboard


fnafbot = MyBot()
fnafbot.start_app(Fnafobj.start_fnaf, Fnafobj.kill_fnaf)
time.sleep(5)
while True:  # making a loop
    if keyboard.is_pressed('enter'):  # if key 'enter' is pressed 
        print('Starting bot')
        break
print("Am I")
time.sleep(10)
fnafbot.left_light()
time.sleep(1)
fnafbot.left_door()
time.sleep(1)
fnafbot.check_stage()
time.sleep(1)
fnafbot.right_light()
time.sleep(1)
fnafbot.right_door()

