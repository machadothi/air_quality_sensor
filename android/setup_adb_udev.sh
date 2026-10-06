#!/bin/sh
# Lets adb talk to Google Pixel phones (USB vendor 18d1) without root.
# Run once: sudo sh setup_adb_udev.sh   then unplug and replug the phone.
set -e
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0660", GROUP="plugdev", TAG+="uaccess"' > /etc/udev/rules.d/51-android.rules
udevadm control --reload-rules
echo "Android udev rule installed. Unplug and replug the phone."
