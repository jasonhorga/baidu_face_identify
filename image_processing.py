"""Component that will help set the Baidu face for verify processing."""
import base64
import logging
import os
from datetime import datetime

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.image_processing import (
    ATTR_CONFIDENCE, CONF_CONFIDENCE, CONF_ENTITY_ID, CONF_NAME, CONF_SOURCE,
    DEFAULT_CONFIDENCE, PLATFORM_SCHEMA, ImageProcessingFaceEntity)
from homeassistant.const import ATTR_NAME
from homeassistant.core import split_entity_id
from homeassistant.exceptions import HomeAssistantError

from . import DOMAIN as BAIDU_FACE_DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_GROUP = "group"
CONF_LOCAL_PATH = "local_path"

ATTR_GROUP_ID = "group_id"
ATTR_SCORE = "score"
ATTR_UID = "user_id"
ATTR_USER_INFO = "user_info"

ATTR_LIST = {
    ATTR_GROUP_ID: "null",
    ATTR_SCORE: "null",
    ATTR_UID: "null",
    ATTR_USER_INFO: "null",
}

DEFAULT_LOCAL_PATH = "/local/face"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_GROUP): cv.slugify,
        vol.Optional(CONF_LOCAL_PATH, default=DEFAULT_LOCAL_PATH): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Baidu Face identify platform."""

    api = hass.data[BAIDU_FACE_DOMAIN]
    face_group = config[CONF_GROUP]
    confidence = config[CONF_CONFIDENCE]
    local_path = config.get(CONF_LOCAL_PATH)
    if not local_path.endswith("/"):
        local_path = f"{local_path}/"

    entities = []
    for camera in config[CONF_SOURCE]:
        entities.append(
            BaiduFaceIdentifyEntity(
                camera[CONF_ENTITY_ID],
                api,
                face_group,
                local_path,
                confidence,
                camera.get(CONF_NAME),
            )
        )

    async_add_entities(entities)


class BaiduFaceIdentifyEntity(ImageProcessingFaceEntity):
    """Representation of the Baidu Face API entity for identify."""

    def __init__(
        self, camera_entity, api, face_group, local_path, confidence, name=None
    ):
        """Initialize the Baidu Face API."""
        super().__init__()

        self._api = api
        self._camera = camera_entity
        self._confidence = confidence
        self._face_group = face_group
        self._save_path = (
            f'{self._api.hass.config.config_dir}{local_path.replace("local","www")}'
        )
        if not (os.path.exists(self._save_path)):
            os.makedirs(self._save_path)

        if name:
            self._name = name
        else:
            self._name = f"Baidu Face {split_entity_id(camera_entity)[1]}"

    @property
    def confidence(self):
        """Return minimum confidence for send events."""
        return self._confidence

    @property
    def camera_entity(self):
        """Return camera entity id from process pictures."""
        return self._camera

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    async def async_process_image(self, image):
        """Process image.

        This method is a coroutine.
        """

        try:
            params = {
                "image_type": "BASE64",
                "group_id_list": self._face_group,
            }

            data = {"image": str(base64.b64encode(image), "utf-8")}

            ret_json = (await self._api.call_api("post", "search", params, data))[
                "result"
            ]

        except HomeAssistantError as err:
            _LOGGER.error("Can't process image on Baidu face: %s", err)
            return

        # Parse data
        known_faces = []

        for key in ATTR_LIST:
            ATTR_LIST[key] = "null"

        if ret_json:
            confidence = ret_json["user_list"][0]["score"]
            for key in ATTR_LIST:
                ATTR_LIST[key] = ret_json["user_list"][0][key]

            # save all recognized person
            if confidence > self._confidence:
                save_path = f'{self._save_path}{ATTR_LIST[ATTR_UID]}_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{confidence}.jpg'
                with open(save_path, "wb") as fp:
                    fp.write(image)

            known_faces.append(
                {ATTR_NAME: ATTR_LIST[ATTR_UID], ATTR_CONFIDENCE: confidence})

        self.async_process_faces(known_faces, len(known_faces))
