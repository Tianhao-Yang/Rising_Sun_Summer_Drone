# Rising Sun Summer Drone

Rising Sun is a self-built quadcopter developed as a summer engineering project. It combines mechanical design, flight control, onboard computing, telemetry, data logging, and a custom ground-station system.

This repository contains three main components:

1. Ground station
2. CAD files
3. Raspberry Pi onboard system

## 1. Ground Station

The ground-station system includes a desktop application and an online website.

### Desktop Application

The desktop application was developed using Python and PySide6. It receives MAVLink telemetry from the Pixhawk and live video from the onboard camera through a VTX system.

The application is organized into three pages:

- **Home:** Project overview, interactive 3D drone model, flight-log list, recorded videos, and telemetry-data viewer.
- **Flight Display:** Live camera feed, with a HUD display, flight instruments, motor and battery monitoring, system status, flight-phase checklists, warnings, recording controls and map.
- **HUD:** Enlarged flight interface showing the camera feed and HUD display, also showing flight-phase checklists, warnings, and map.  

The application records the Flight Display, HUD, camera feed, and telemetry data. These files are organized into individual flight logs together synchronized with onboard logs received from the Raspberry Pi through Bluetooth.

### Online Website

The Flask-based website is the public version of the desktop application. It includes:

- A project overview and interactive 3D drone model
- Published flight logs and telemetry data together with recorded flight display, HUD, and camera videos
- Live video views when the desktop application is online

The website is aiming to demonstrates the project and shares flight experiences with the public.
Website: https://red-sun-public-site.onrender.com/

## 2. CAD Files

The drone and its custom components were designed in SolidWorks. This section includes:

- Complete drone assembly
- Structural, motor, and electronics components
- Custom connection and mounting parts for 3D printing
- Exported 3D models used by the application and website

## 3. Onboard System

The onboard system runs on a Raspberry Pi connected to the Pixhawk. It:

- Reads and records MAVLink flight data
- Monitors Raspberry Pi temperature and resource usage
- Manages the **Before Takeoff**, **Cruising**, and **After Landing** phases
- Indicates the current flight phase through onboard LEDs
- Transfers flight logs to the desktop application through Bluetooth

## System Overview

The Pixhawk controls and stabilizes the aircraft. The Raspberry Pi manages onboard monitoring, flight states, and telemetry logging. The desktop application displays and records flight information, while the website publishes selected flight records for public viewing.

## Project Status

The drone, onboard computer, telemetry system, desktop application, and website have been integrated. Flight testing and system improvements are ongoing.
