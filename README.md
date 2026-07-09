# VELA Home Assistant Custom Integration

This custom component integrates VELA commercial/residential thermostats with Home Assistant using a dedicated client connection over MQTT (without reusing Home Assistant's global MQTT connection).

## Features
- **Dedicated MQTT Client**: Connects directly to VELA's broker. Does not conflict with local brokers or Zigbee2MQTT/Tasmota setups.
- **Auto-Discovery & State Synchronization**: Publishes states (temperature, fan, HVAC mode) to the VELA central ingest.
- **Command Subscription**: Listens for target temperature and HVAC mode commands from the VELA dashboard.
- **Dual Setpoint Support**: Handles auto-mode heating/cooling ranges (`target_temp_high`/`target_temp_low`).
- **Last Will and Testament (LWT)**: Automatically propagates bridge availability to VELA when connection is dropped.

## Installation via HACS
1. Open Home Assistant, go to **HACS** -> **Integrations**.
2. Click the three dots in the top right, select **Custom repositories**.
3. Add this repository URL and select **Integration** as the category.
4. Click **Install**.
5. Restart Home Assistant.
6. Go to **Settings** -> **Devices & Services** -> **Add Integration**, search for **VELA Climate**, and enter your credentials.
