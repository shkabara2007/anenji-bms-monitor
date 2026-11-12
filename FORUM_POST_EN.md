# ANENJI SH12100-H: Windows BLE BMS monitor and PowMR charging field notes

Sharing read-only source code and test notes for two ANENJI 12.8V/100Ah LiFePO4 battery packs over BLE. Windows GUI (Python 3.13, Bleak 3.0.2, aiobmsble 0.30.0) shows cell voltages, pack voltage/current, BMS SOC, temperatures and fault states; appends CSV on manual refresh.

The two tested devices exposed GATT channels `FFFB` (request) and `FFFC` (notification). On Windows we observed intermittent `Could not start notify ... Unreachable` / `Characteristic fffc was not found!` errors, followed by successful two-pack readings in both library-managed and direct-Bleak implementations. The root cause remains unknown.

In a PowMR POW-HVM1K-12V setup with two packs in parallel, BMS charge current reached 0 A near 13.61 V at several tested Bulk setpoints (14.2–14.4 V; Float 13.7 V). One pack's cell-voltage spread reached ~46–50 mV near end of charge and dropped to ~4–7 mV during discharge. The actual charger stage, peak charge voltage and capacity were not verified. Not a device fault diagnosis.

Source and documentation prepared for a public repository named `anenji-bms-monitor` (add URL once published). Research/monitoring only; no safety-critical control. Private identifiers and owner logs removed.
