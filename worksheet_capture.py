#!/usr/bin/env python3
"""
Worksheet Capture & AI Analysis System
Captures burst photos on button hold, sends to Claude API
"""

import base64
import logging
import os
import time
from pathlib import Path

import adafruit_drv2605
import board
import busio
from anthropic import Anthropic
from gpiozero import Button
from picamera2 import Picamera2

# =====================================================
# CONFIGURATION
# =====================================================
BUTTON_PIN = 27
CAPTURE_DIR = Path.home() / "worksheet_capture" / "images"
BURST_DELAY = 0.20  # seconds between captures
API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# =====================================================
# INITIALIZATION
# =====================================================
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

# Button
button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.1)
logger.info("Button initialized on GPIO 27")

# Haptics
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    drv = adafruit_drv2605.DRV2605(i2c)
    HAPTICS_ENABLED = True
    logger.info("Haptics initialized")
except Exception as exc:
    logger.warning(f"Haptics unavailable: {exc}")
    HAPTICS_ENABLED = False

# Camera
picam = Picamera2()
config = picam.create_still_configuration(
    main={"size": (2304, 1296)},
    buffer_count=4,
)
picam.configure(config)
picam.start()
logger.info("Camera initialized")

# Anthropic API
if not API_KEY:
    logger.error("ANTHROPIC_API_KEY not set!")
    raise SystemExit(1)

client = Anthropic(api_key=API_KEY)
logger.info("Claude API client initialized")

# =====================================================
# HAPTIC FEEDBACK
# =====================================================

def _play_haptic_sequence(effects, pause_after=0.0):
    if not HAPTICS_ENABLED:
        return
    try:
        for idx, effect in enumerate(effects):
            drv.sequence[idx] = adafruit_drv2605.Effect(effect)
        drv.play()
        if pause_after:
            time.sleep(pause_after)
            drv.stop()
    except Exception:
        pass


def haptic_click():
    """Single click - capture feedback"""
    _play_haptic_sequence([11, 0])


def haptic_double_click():
    """Double click - API response received"""
    _play_haptic_sequence([11, 11, 0], pause_after=0.25)

# =====================================================
# CAMERA FUNCTIONS
# =====================================================

def autofocus_once():
    """Perform autofocus"""
    try:
        picam.autofocus_cycle()
        time.sleep(0.2)
        logger.debug("Autofocus complete")
    except Exception:
        pass


def capture_burst():
    """Capture images while button is held"""
    logger.info("=== BURST STARTED ===")
    captured_files = []

    # Focus once at start
    autofocus_once()

    # Capture while button held
    while button.is_pressed:
        try:
            timestamp = int(time.time() * 1000)
            filepath = CAPTURE_DIR / f"{timestamp}.jpg"

            picam.capture_file(str(filepath))
            captured_files.append(filepath)

            haptic_click()  # Shutter click feedback
            logger.info(f"Captured: {filepath.name}")

            time.sleep(BURST_DELAY)

        except Exception as exc:
            logger.error(f"Capture failed: {exc}")

    logger.info(f"=== BURST ENDED: {len(captured_files)} images ===")
    return captured_files

# =====================================================
# IMAGE PROCESSING
# =====================================================

def image_to_base64(filepath):
    """Convert image to base64 for API"""
    try:
        with open(filepath, "rb") as file_handle:
            return base64.standard_b64encode(file_handle.read()).decode("utf-8")
    except Exception as exc:
        logger.error(f"Failed to encode {filepath}: {exc}")
        return None

# =====================================================
# CLAUDE API
# =====================================================

def analyze_images(image_files):
    """Send images to Claude API for analysis"""
    if not image_files:
        logger.warning("No images to analyze")
        return None

    logger.info(f"Analyzing {len(image_files)} images with Claude...")

    try:
        # Prepare message content with all images
        content = []

        # Add all images
        for idx, img_path in enumerate(image_files, 1):
            base64_image = image_to_base64(img_path)
            if base64_image:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64_image,
                        },
                    }
                )
                logger.debug(f"Added image {idx} to request")

        # Add text prompt
        content.append(
            {
                "type": "text",
                "text": (
                    "You are analyzing "
                    f"{len(image_files)} burst photos of the same scene.\n\n"
                    "TASK: Describe what you see in these images. Be specific about:\n"
                    "1. The overall scene/subject\n"
                    "2. Image quality (sharpness, lighting, focus)\n"
                    "3. Which image number appears clearest (if applicable)\n"
                    "4. Any text, objects, or details visible\n\n"
                    "Provide a clear, concise analysis."
                ),
            }
        )

        # Make API call
        logger.info("Sending request to Claude API...")
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )

        # Extract response
        response_text = response.content[0].text
        logger.info("API response received")

        return response_text

    except Exception as exc:
        logger.error(f"API call failed: {exc}")
        return None

# =====================================================
# MAIN LOOP
# =====================================================

def main():
    logger.info("=" * 60)
    logger.info("WORKSHEET CAPTURE & ANALYSIS SYSTEM")
    logger.info("Hold button to capture burst, release to analyze")
    logger.info("Images saved to: " + str(CAPTURE_DIR))
    logger.info("=" * 60)

    try:
        while True:
            # Wait for button press
            logger.info("\n[READY] Waiting for button press...")
            button.wait_for_press()

            # Capture burst
            captured_files = capture_burst()

            if not captured_files:
                logger.warning("No images captured")
                continue

            # Analyze with Claude
            logger.info("\n[ANALYZING] Sending to Claude API...")
            response = analyze_images(captured_files)

            if response:
                # Success feedback
                haptic_double_click()

                # Display response
                logger.info("\n" + "=" * 60)
                logger.info("CLAUDE'S ANALYSIS:")
                logger.info("=" * 60)
                print(f"\n{response}\n")
                logger.info("=" * 60)
            else:
                logger.error("Analysis failed")

            # Brief pause before next capture
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("\n\nShutting down...")
        picam.stop()
        picam.close()
        logger.info("Goodbye!")


if __name__ == "__main__":
    main()
