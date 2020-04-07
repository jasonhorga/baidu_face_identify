"""Support for Baidu face recognition."""
import asyncio
import json
import logging

import aiohttp
import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import ATTR_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

# ATTR_GROUP = "group"
# ATTR_PERSON = "person"
# ATTR_CAMERA_ENTITY = "camera_entity"

CONF_API_KEY = "client_id"
CONF_SECRET_KEY = "client_secret"
CONF_GRANT_TYPE = "grant_type"

DEFAULT_TIMEOUT = 10
DOMAIN = "baidu_face_identify"

BAIDU_TOKEN_API_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_FACE_API_URL = "https://aip.baidubce.com/rest/2.0/face/v3/{0}?access_token={1}"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_KEY): cv.string,
                vol.Required(CONF_SECRET_KEY): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up Baidu Face."""

    entities = {}
    face = BaiduFace(
        hass,
        config[DOMAIN].get(CONF_API_KEY),
        config[DOMAIN].get(CONF_SECRET_KEY),
        entities,
    )

    try:
        # get token first
        await face.get_token()
        # read exists group/person from cloud and create entities
        await face.update_store()

    except HomeAssistantError as err:
        _LOGGER.error("Can't load data from face api: %s", err)
        return False

    hass.data[DOMAIN] = face

    return True


class BaiduFaceGroupEntity(Entity):
    """Person-Group state/data Entity."""

    def __init__(self, hass, api, g_id, name):
        """Initialize person/group entity."""
        self.hass = hass
        self._api = api
        self._id = g_id
        self._name = name

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def entity_id(self):
        """Return entity id."""
        return f"{DOMAIN}.{self._id}"

    @property
    def state(self):
        """Return the state of the entity."""
        return len(self._api.store[self._id])

    @property
    def should_poll(self):
        """Return True if entity has to be polled for state."""
        return False

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        attr = {}
        for name, p_id in self._api.store[self._id].items():
            attr[name] = p_id

        return attr


class BaiduFace:
    """Baidu Face api for Home Assistant."""

    def __init__(self, hass, api_key, secret_key, entities):
        """Initialize Baidu Face api."""
        self.hass = hass
        self.websession = async_get_clientsession(hass)
        self._api_key = api_key
        self._secret_key = secret_key
        self._store = {}
        self._entities = entities
        self.timeout = DEFAULT_TIMEOUT
        self._token = ""

    @property
    def store(self):
        """Store group/person data and IDs."""
        return self._store

    async def update_store(self):
        """Load all group/person data into local store."""
        groups = (await self.call_api("post", "faceset/group/getlist"))["result"]
        if groups:
            tasks = []
            for group in groups["group_id_list"]:
                self._store[group] = {}
                self._entities[group] = BaiduFaceGroupEntity(
                    self.hass, self, group, group
                )
                data = {"group_id": group}
                persons = (await self.call_api("get", f"faceset/group/getusers", data))[
                    "result"
                ]
                if persons:
                    for person in persons["user_id_list"]:
                        self._store[group][person] = person
                    tasks.append(self._entities[group].async_update_ha_state())
            if tasks:
                await asyncio.wait(tasks)

    async def get_token(self):
        """Get baidu token."""
        headers = {"Content-Type": "application/json"}
        params = {
            f"{CONF_API_KEY}": self._api_key,
            f"{CONF_SECRET_KEY}": self._secret_key,
            f"{CONF_GRANT_TYPE}": "client_credentials",
        }
        try:
            with async_timeout.timeout(self.timeout):
                response = await getattr(self.websession, "get")(
                    BAIDU_TOKEN_API_URL, data=None, headers=headers, params=params
                )

                answer = await response.json()

            _LOGGER.debug("Read from baidu token api: %s", answer)

            if response.status < 300 and "access_token" in answer:
                self._token = answer["access_token"]
                _LOGGER.debug("Baidu token is %s", self._token)
                return

            _LOGGER.warning(
                "Error %d baidu token api %s", response.status, response.url
            )
            raise HomeAssistantError(answer["error"]["message"])

        except aiohttp.ClientError:
            _LOGGER.warning("Can't connect to baidu token api")

        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout from baidu token api %s", response.url)

        raise HomeAssistantError("Network error on baidu token api.")

    async def call_api(self, method, function, params=None, data=None):
        """Make an api call."""
        headers = {"Content-Type": "application/json"}
        url = BAIDU_FACE_API_URL.format(function, self._token)

        try:
            with async_timeout.timeout(self.timeout):
                response = await getattr(self.websession, method)(
                    url, headers=headers, params=params, data=data
                )

            answer = await response.json()

            _LOGGER.debug("Read from baidu face api: %s\n%s\n%s\n",
                          url, params, answer)

            if response.status < 300:
                return answer

            _LOGGER.warning("Error %d baidu face api %s",
                            response.status, response.url)
            raise HomeAssistantError(answer["error"]["message"])

        except aiohttp.ClientError:
            _LOGGER.warning("Can't connect to baidu face api")

        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout from baidu face api %s", response.url)

        raise HomeAssistantError("Network error on baidu face api.")
