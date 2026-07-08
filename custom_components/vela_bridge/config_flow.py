from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN, CONF_BROKER_HOST, CONF_BROKER_PORT, CONF_USERNAME, CONF_PASSWORD, CONF_TOPIC_PREFIX

class VelaBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_BROKER_HOST, default="mqtt.velacomfort.com"): str,
            vol.Required(CONF_BROKER_PORT, default=8883): int,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_TOPIC_PREFIX): str,
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
