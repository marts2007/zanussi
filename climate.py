import asyncio
import socket
import binascii
import json
import logging
import os.path

import voluptuous as vol

from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL,
    HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_AUTO,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE,
    HVAC_MODES, ATTR_HVAC_MODE)
from homeassistant.const import (
    CONF_NAME, STATE_ON, STATE_UNKNOWN, ATTR_TEMPERATURE,
    PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.restore_state import RestoreEntity


COMPONENT_ABS_DIR = os.path.dirname(
  os.path.abspath(__file__))

_LOGGER = logging.getLogger(__name__)

CONF_UNIQUE_ID = 'unique_id'
CONF_NAME = 'name'
CONF_HOST = 'host'
CONF_TEMPERATURE_SENSOR = 'temperature_sensor'
CONF_DEVICE_CODE = 'device_code'

SUPPORT_FLAGS = (
    SUPPORT_TARGET_TEMPERATURE | 
    SUPPORT_FAN_MODE
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_UNIQUE_ID): cv.string,
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_TEMPERATURE_SENSOR): cv.entity_id,
    vol.Required(CONF_DEVICE_CODE): cv.positive_int
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    host=config.get(CONF_HOST)
    device_code = config.get(CONF_DEVICE_CODE)
    device_files_absdir = os.path.join(COMPONENT_ABS_DIR, 'codes')
    if not os.path.isdir(device_files_absdir):
        os.makedirs(device_files_absdir)    
    device_json_filename = str(device_code) + '.json'
    device_json_path = os.path.join(device_files_absdir, device_json_filename)

    if not os.path.exists(device_json_path):
        _LOGGER.error("Couldn't find the device Json file.")
        return
    with open(device_json_path) as j:
        try:
            device_data = json.load(j)
        except:
            _LOGGER.error("The device Json file is invalid")
            return    
    async_add_entities([ZanussiAC(
        hass, config, device_data
    )])    

class ZanussiAC(ClimateDevice, RestoreEntity):
    def __init__(self, hass, config, device_data):
        self._host=config.get(CONF_HOST)
        self.hass = hass
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._name = config.get(CONF_NAME)
        self._device_code = config.get(CONF_DEVICE_CODE)
        self._temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        self._manufacturer = device_data['manufacturer']
        self._supported_models = device_data['supportedModels']
        self._min_temperature = device_data['minTemperature']
        self._max_temperature = device_data['maxTemperature']
        self._precision = device_data['precision']

        valid_hvac_modes = [x for x in device_data['operationModes'] if x in HVAC_MODES]
        self._operation_modes = [HVAC_MODE_OFF] + valid_hvac_modes
        self._fan_modes = device_data['fanModes']
        self._commands = device_data['commands']
        self._target_temperature = self._min_temperature
        self._hvac_mode = HVAC_MODE_OFF
        self._current_fan_mode = self._fan_modes[0]

        self._last_on_operation = None
        self._current_temperature = None

        self._unit = hass.config.units.temperature_unit
        self._support_flags = SUPPORT_FLAGS

        self._temp_lock = asyncio.Lock()
        self._on_by_remote = False
        _LOGGER.warning('zanussi_init_ok!') 

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._hvac_mode = last_state.state
            self._current_fan_mode = last_state.attributes['fan_mode']
            self._target_temperature = last_state.attributes['temperature']

            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']

        if self._temperature_sensor:
            async_track_state_change(self.hass, self._temperature_sensor, 
                                     self._async_temp_sensor_changed)

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)




    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def state(self):
        """Return the current state."""
        if self._on_by_remote:
            return STATE_ON
        if self.hvac_mode != HVAC_MODE_OFF:
            return self.hvac_mode
        return HVAC_MODE_OFF

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def min_temp(self):
        """Return the polling state."""
        return self._min_temperature
        
    @property
    def max_temp(self):
        """Return the polling state."""
        return self._max_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._precision

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._operation_modes

    @property
    def hvac_mode(self):
        """Return hvac mode ie. heat, cool."""
        return self._hvac_mode

    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation

    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_modes

    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def device_state_attributes(self) -> dict:
        """Platform specific attributes."""
        return {
            'last_on_operation': self._last_on_operation,
            'device_code': self._device_code,
            'manufacturer': self._manufacturer,
            'supported_models': self._supported_models,
        }


        
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)  
        temperature = kwargs.get(ATTR_TEMPERATURE)
        
        if temperature is None:
            return
            
        if temperature < self._min_temperature or temperature > self._max_temperature:
            _LOGGER.warning('The temperature value is out of min/max range') 
            return

        self._target_temperature = round(temperature)
  

        if hvac_mode:
            await self.async_set_hvac_mode(hvac_mode)
            return
        
        if not self._hvac_mode.lower() == HVAC_MODE_OFF:
            await self.send_command()

        await self.async_update_ha_state()

    async def send_command(self):
        async with self._temp_lock:
            self._on_by_remote = False
            operation_mode = self._hvac_mode
            fan_mode = self._current_fan_mode
            target_temperature = '{0:g}'.format(self._target_temperature)

            if operation_mode.lower() == HVAC_MODE_OFF:
                command = self._commands['off']
            else:
                command = self._commands[operation_mode][fan_mode][target_temperature]

            try:
                await self.send(command)
            except Exception as e:
                _LOGGER.exception(e)

    async def send(self, packet):
        #_LOGGER.warning('sending command {}'.format(packet)) 
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        sock.sendto(binascii.unhexlify(self._commands['wake']), (self._host,80))
        sock.close()
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        sock.sendto(binascii.unhexlify(packet), (self._host,80))
        sock.close()

    @callback
    async def async_set_hvac_mode(self, hvac_mode):
        """Set operation mode."""
        self._hvac_mode = hvac_mode
        
        if not hvac_mode == HVAC_MODE_OFF:
            self._last_on_operation = hvac_mode

        await self.send_command()
        await self.async_update_ha_state()


    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._current_fan_mode = fan_mode
        
        if not self._hvac_mode.lower() == HVAC_MODE_OFF:
            await self.send_command()      
        await self.async_update_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVAC_MODE_OFF)
        
    async def async_turn_on(self):
        """Turn on."""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_operation)
        else:
            await self.async_set_hvac_mode(self._operation_modes[1])

    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature sensor changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self.async_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)
            
