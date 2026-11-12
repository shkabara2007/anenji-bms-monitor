# Public release and privacy

This repository intentionally omits the original owner's BLE MAC addresses, exact pack names, personal Windows username/home path, raw Bluetooth logs, CSV history, screenshots, conversation transcripts, and locally configured Windows executables. Public documentation uses Pack A / Pack B and rounded numerical observations only.

To use the source, create your own `batteries.json` from `batteries.example.json`. That file and generated data files are gitignored. Do **not** submit them or system logs without sanitization.

No remote access or phone command code is included. Runtime BLE communication is designed for read-only telemetry using the `aiobmsble` Saihang parser, not BMS configuration. This is not a safety system.
