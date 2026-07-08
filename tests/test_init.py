import pytest
from unittest.mock import patch, MagicMock
from homeassistant.core import HomeAssistant
from custom_components.vela_bridge import async_setup_entry, async_unload_entry
from custom_components.vela_bridge.const import DOMAIN

async def test_async_setup_entry(hass: HomeAssistant):
    """Test setting up and unloading the VELA Bridge integration config entry."""
    entry_data = {
        "broker_host": "mqtt.velacomfort.com",
        "broker_port": 8883,
        "username": "acct_test_user",
        "password": "test_password",
        "topic_prefix": "tc/test_tenant/",
    }
    
    # Create a mock ConfigEntry
    entry = MagicMock()
    entry.data = entry_data
    entry.entry_id = "test_entry_id"

    # Mock the paho mqtt client connection and thread
    with patch("paho.mqtt.client.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Invoke setup
        result = await async_setup_entry(hass, entry)
        
        assert result is True
        assert entry.entry_id in hass.data[DOMAIN]
        
        # Verify paho client initialization & LWT configuration
        mock_client_class.assert_called_once()
        mock_client.username_pw_set.assert_called_once_with("acct_test_user", "test_password")
        mock_client.will_set.assert_called_once_with(
            "tc/test_tenant/bridge/acct_test_user/availability",
            payload="offline",
            qos=1,
            retain=True
        )

        # Test unloading the entry
        unload_result = await async_unload_entry(hass, entry)
        assert unload_result is True
        assert entry.entry_id not in hass.data[DOMAIN]
        mock_client.disconnect.assert_called_once()
