import logging
import json
import asyncio
import threading
import ssl
import paho.mqtt.client as mqtt_client
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN, 
    CONF_BROKER_HOST, 
    CONF_BROKER_PORT, 
    CONF_USERNAME, 
    CONF_PASSWORD, 
    CONF_TOPIC_PREFIX
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up VELA Bridge from a config entry with a dedicated MQTT client."""
    config = entry.data
    broker_host = config[CONF_BROKER_HOST]
    broker_port = config[CONF_BROKER_PORT]
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]
    topic_prefix = config[CONF_TOPIC_PREFIX]

    # Construction of isolated bridge namespace: tc/{account_ulid}/bridge/{username}/
    bridge_namespace = f"{topic_prefix}bridge/{username}/"
    availability_topic = f"{bridge_namespace}availability"

    # Instantiate dedicated MQTT client
    client = mqtt_client.Client(client_id=f"vela_{username}_{entry.entry_id}")
    client.username_pw_set(username, password)

    # Enable SSL/TLS for secure connections
    if broker_port == 8883 or broker_port == 443:
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)

    # Set broker-registered Last Will & Testament (LWT)
    client.will_set(availability_topic, payload="offline", qos=1, retain=True)

    loop = asyncio.get_running_loop()

    # Callback when connected to EMQX broker
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            _LOGGER.info("VELA Bridge successfully connected to broker %s", broker_host)
            # Publish online status
            client.publish(availability_topic, "online", qos=1, retain=True)
            # Subscribe to commands for all devices under this bridge namespace
            command_topic = f"{bridge_namespace}devices/+/command"
            client.subscribe(command_topic, qos=1)
            _LOGGER.info("VELA Bridge subscribed to commands on %s", command_topic)
        else:
            _LOGGER.error("VELA Bridge connection failed with result code %s", rc)

    # Callback when command message is received from VELA
    def on_message(client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            _LOGGER.info("VELA Bridge received command on %s: %s", topic, payload)

            # Extract entity_id from topic: tc/{acct}/bridge/{username}/devices/{entity_id}/command
            parts = topic.split('/')
            entity_id = parts[-2]

            # Execute commands inside Home Assistant's event loop
            asyncio.run_coroutine_threadsafe(
                execute_vela_command(entity_id, payload),
                hass.loop
            )
        except Exception as e:
            _LOGGER.error("Failed to process VELA command message: %s", e)

    client.on_connect = on_connect
    client.on_message = on_message

    # Helper to publish states
    async def publish_device_state(entity_id, state_obj):
        if state_obj is None:
            return

        temp_current = state_obj.attributes.get("current_temperature")
        temp_set = state_obj.attributes.get("temperature")
        temp_high = state_obj.attributes.get("target_temp_high")
        temp_low = state_obj.attributes.get("target_temp_low")
        mode = state_obj.state  # heat, cool, off, auto, heat_cool
        fan_mode = state_obj.attributes.get("fan_mode")

        # Map to standard VELA keys used by unmodified ingest (DeviceMapper)
        payload = {
            "online": True,
            "temp_current": float(temp_current) if temp_current is not None else None,
            "current_temperature": float(temp_current) if temp_current is not None else None,
            "temp_set": float(temp_set) if temp_set is not None else None,
            "temperature_set": float(temp_set) if temp_set is not None else None,
            "upper_temp": float(temp_high) if temp_high is not None else None,
            "lower_temp": float(temp_low) if temp_low is not None else None,
            "mode": mode,
            "fan_mode": fan_mode,
        }

        state_topic = f"{bridge_namespace}devices/{entity_id}/state"
        
        # Publish asynchronously in threadpool to keep HA loop responsive
        await loop.run_in_executor(
            None,
            lambda: client.publish(state_topic, json.dumps(payload), qos=1, retain=True)
        )

    # Helper to execute commands in HA
    async def execute_vela_command(entity_id: str, cmd: dict):
        # 1. Temperature setpoint (Single or Dual)
        temp_target = cmd.get("temp_set", cmd.get("temperature_set"))
        if temp_target is not None:
            await hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": entity_id, "temperature": float(temp_target)},
                blocking=True
            )
        elif ("upper_temp" in cmd and cmd["upper_temp"] is not None) or ("lower_temp" in cmd and cmd["lower_temp"] is not None):
            # Dual setpoint support for heat_cool / auto mode (using upper_temp and lower_temp)
            service_data = {"entity_id": entity_id}
            if "upper_temp" in cmd and cmd["upper_temp"] is not None:
                service_data["target_temp_high"] = float(cmd["upper_temp"])
            if "lower_temp" in cmd and cmd["lower_temp"] is not None:
                service_data["target_temp_low"] = float(cmd["lower_temp"])
            await hass.services.async_call(
                "climate", "set_temperature",
                service_data,
                blocking=True
            )

        # 2. HVAC Mode
        if "mode" in cmd and cmd["mode"] is not None:
            await hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": cmd["mode"]},
                blocking=True
            )

        # 3. Fan Mode
        if "fan_mode" in cmd and cmd["fan_mode"] is not None:
            await hass.services.async_call(
                "climate", "set_fan_mode",
                {"entity_id": entity_id, "fan_mode": cmd["fan_mode"]},
                blocking=True
            )

    # State listener for HA entity changes
    async def state_listener(event):
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        await publish_device_state(entity_id, new_state)

    # Async registration loop
    async def register_and_announce_entities():
        await asyncio.sleep(2)
        
        ent_reg = er.async_get(hass)
        climate_entities = [
            entity_id for entity_id, entry in ent_reg.entities.items()
            if entity_id.startswith("climate.")
        ]

        for entity_id in climate_entities:
            discovery_topic = f"{bridge_namespace}discovery/climate/{entity_id}"
            state_topic = f"{bridge_namespace}devices/{entity_id}/state"
            availability_topic = f"{bridge_namespace}devices/{entity_id}/availability"
            
            state_obj = hass.states.get(entity_id)
            name = state_obj.name if state_obj else entity_id
            
            discovery_payload = {
                "public_id": entity_id,
                "name_alias": name,
                "source_convention": "ha",
                "capabilities_json": {
                    "source_convention": "ha",
                    "last_state_topic": state_topic,
                    "manufacturer": state_obj.attributes.get("manufacturer", "Home Assistant"),
                    "model": state_obj.attributes.get("model", "Climate Entity"),
                    "min_temp": state_obj.attributes.get("min_temp", 7.0),
                    "max_temp": state_obj.attributes.get("max_temp", 35.0),
                    "modes": state_obj.attributes.get("hvac_modes", ["heat", "cool", "off", "auto", "heat_cool"]),
                    "fan_modes": state_obj.attributes.get("fan_modes", ["auto", "low", "medium", "high"]),
                }
            }
            
            # Publish discovery & online status
            await loop.run_in_executor(
                None,
                lambda: client.publish(discovery_topic, json.dumps(discovery_payload), qos=1, retain=True)
            )
            await loop.run_in_executor(
                None,
                lambda: client.publish(availability_topic, "online", qos=1, retain=True)
            )
            
            # Publish initial state
            if state_obj:
                await publish_device_state(entity_id, state_obj)

            # Track state changes for this entity
            async_track_state_change_event(hass, [entity_id], state_listener)

    # Establish TCP connection to broker in a separate background loop thread
    def run_client_loop():
        try:
            client.connect(broker_host, broker_port, keepalive=60)
            client.loop_forever()
        except Exception as e:
            _LOGGER.error("VELA Bridge MQTT loop exception: %s", e)

    loop_thread = threading.Thread(target=run_client_loop, daemon=True)
    loop_thread.start()

    # Save client reference for unload lifecycle
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "thread": loop_thread,
        "bridge_namespace": bridge_namespace
    }

    # Announce existing entities
    hass.async_create_task(register_and_announce_entities())

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a VELA Bridge config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    if entry_data:
        client = entry_data["client"]
        bridge_namespace = entry_data["bridge_namespace"]
        availability_topic = f"{bridge_namespace}availability"

        # Publish offline availability
        await hass.async_add_executor_job(
            lambda: client.publish(availability_topic, "offline", qos=1, retain=True)
        )
        
        # Stop loop and disconnect
        client.disconnect()
        
        hass.data[DOMAIN].pop(entry.entry_id)

    return True
