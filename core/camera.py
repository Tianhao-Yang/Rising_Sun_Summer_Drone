import cv2
import numpy as np

from config import CAMERA_INDEX

def create_no_camera_screen():
    # Keep the fallback black frame when the USB camera is disconnected,
    # but do not draw any "No USB Camera Detected" text.
    screen = np.zeros((480, 640, 3), dtype=np.uint8)
    return screen

def open_usb_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

    if not cap.isOpened():
        cap.release()
        return None

    return cap

