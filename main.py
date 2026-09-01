import time
import threading
import cv2

from config import (WINDOW_NAME,CAMERA_RECONNECT_INTERVAL,)
from core.camera import (create_no_camera_screen,open_usb_camera,)
from core.state import TelemetryState
from core.telemetry import telemetry_worker
from hud.renderer import (draw_telemetry,draw_disconnect_messages,)


def main():

    cv2.namedWindow(WINDOW_NAME,cv2.WINDOW_NORMAL,) # Create the OpenCV window.

    no_camera_screen = create_no_camera_screen() # Create the fallback black screen used when the USB camera is disconnected.

    telemetry_state = TelemetryState() # Contains all current flight / telemetry data.

    stop_event = threading.Event() # Used to tell the telemetry thread to stop when the program closes.




    telemetry_thread = threading.Thread(target=telemetry_worker,args=(telemetry_state, stop_event),daemon=True,) # Define telemetry thread

    telemetry_thread.start() #Start telemetry thread

    cap = None # Initialize USB Camera Connection 

    last_camera_connection_attempt = 0.0


    try:          

        while True:  # Main loop: check camera->get image->draw HUD->check telemetry/RC connection

            current_time = time.monotonic() # Get time



            # Check USB Connection 
            if cap is None: #No USB Connection

                display_frame = no_camera_screen.copy() #Display no camera screen

                camera_connected = False 


                if (current_time - last_camera_connection_attempt >= CAMERA_RECONNECT_INTERVAL): #If 2 second interval between camera connection

                    last_camera_connection_attempt = current_time

                    print("Checking for USB camera...")


                    cap = open_usb_camera() # Try again connection


                    if cap is not None:

                        print("USB camera detected.")

                        camera_connected = True


            else: # USB connected

                ret, frame = cap.read()


                if ret and frame is not None: #USB still connected

                    display_frame = frame # Display the camera frame

                    camera_connected = True


                else: #USB disconnected

                    print("USB camera disconnected.")


                    cap.release()

                    cap = None

                    camera_connected = False

                    display_frame = no_camera_screen.copy()


            draw_telemetry(display_frame,telemetry_state,) # Draw HUD based on any of the frame(black frame or camera frame)

            with telemetry_state.lock: #Determine telemetry connection

                telemetry_connected = telemetry_state.connected

                rc_failsafe = telemetry_state.rc_failsafe

                rc_percent_available = (telemetry_state.rc_rssi_percent is not None and telemetry_state.rc_rssi_percent > 0)# No telemetry means we cannot know the RC state.
                if not telemetry_connected: #Check fro RC connection
                    rc_connected = False

                elif rc_failsafe is True:# ArduPilot reports Radio Failsafe.
                    rc_connected = False


                elif rc_failsafe is False: # ArduPilot reports receiver healthy.
                    rc_connected = True

                else:

                    rc_connected = rc_percent_available

            draw_disconnect_messages(display_frame,camera_connected=camera_connected,telemetry_connected=telemetry_connected,rc_connected=rc_connected,) # Draw disconnect warning

            cv2.imshow(WINDOW_NAME,display_frame,) # Display frame


            key = cv2.waitKeyEx(20)

            key_low = key & 0xFF


            # Press Q or Esc to close the program.
            if key_low == ord("q") or key_low == 27:

                break


            # Close the program if the OpenCV window is closed.
            if (cv2.getWindowProperty(WINDOW_NAME,cv2.WND_PROP_VISIBLE,)< 1):
                break


    except KeyboardInterrupt:

        print("\nProgram stopped by user.")


    finally:
        stop_event.set()  # Tell the telemetry thread to stop.


        # Release USB camera.
        if cap is not None:

            cap.release()


        # Wait briefly for telemetry thread to exit.
        telemetry_thread.join(timeout=2.0)


        # Close all OpenCV windows.
        cv2.destroyAllWindows()


if __name__ == "__main__":

    main()