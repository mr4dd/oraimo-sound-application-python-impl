# OpenBuds Python Testbed

-----

A functional CLI tool for managing earbud settings over RFCOMM. This testbed bypasses the official OEM app to provide a direct interface for remapping controls, toggling low-latency modes, and monitoring battery health.

## Features

RFCOMM Connectivity: Direct serial communication over Bluetooth (Channel 1).

Pairing Sequence: Implements a 3-step handshake (PAIR_0 through PAIR_2) to authenticate with the hardware.

Battery Telemetry: Visual ASCII status bars for Left bud, Right bud, and the Charging Case.

Feature Toggling:

    Game Mode: Low-latency audio switching.

    Spatial Audio: Toggle immersive sound processing.

Gesture Mapping: Preset-based remapping for single, double, and triple-tap functions.

## Command Reference

Once connected, use the following commands in the CLI:

|Command  | Arguments       |  Description                                            |
|---------|------------     |--------------                                           |
|pair     | N/A             | Initiates the handshake and retrieves device metadata.  |
|GM       | ON / OFF        | Toggles Game Mode (Low Latency).                        |
|Spatial  | ON / OFF        | Toggles Spatial Audio processing.                       |
|FN       | [side] [preset] | Sets bud functions (Side: left/right).                  |
|SP       | [preset]        | Sets EQ presets (standard, heavybass, rock, jazz, vocal)|
|exit     | N/A             | Closes the socket and exits.                            |

Available Presets (FN)

    control: Sets default track navigation (Play/Pause, Prev/Next).

    volume: Maps taps to Volume Up/Down.

    none: Disables all touch interactions.

## Packet Structure

The implementation uses a standard frame for all outgoing commands:

    Sequence (1 byte): Incremental counter (0–15).

    Command (1 byte): The opcode for the specific feature (e.g., 0x27 for pairing).

    Client ID (2 bytes): Hardcoded to 0100.

    Payload Length (1 byte): Size of the subsequent data.

    Payload: Variable hex data (e.g., 01 for ON, 00 for OFF).

## Getting Started

Dependencies:

    Requires pybluez.

Run:

```bash
python main.py
```

Connect: Enter your device's MAC address when prompted.

Pair: You must run the pair command first to unlock further functionality.
