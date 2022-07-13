import logging

from datetime import datetime
import random
import string
import secrets
import json

import pytz
import time

from aiohttp import ClientSession, ClientResponse, ClientError

from .errors import AuthError
from .util_http import request_with_logging

_LOGGER = logging.getLogger(__name__)


class UsKiaWeb:
    def __init__(self, client_session: ClientSession = None):
        # Randomly generate a plausible device id on startup
        self.device_id = (
            "".join(
                random.choice(string.ascii_letters + string.digits) for _ in range(22)
            )
            + ":"
            + secrets.token_urlsafe(105)
        )

        self.BASE_URL: str = "https://owners.kia.com"
        self.API_URL: str = self.BASE_URL + "/apps/services/owners/"

        if client_session is None:
            self.api_session = ClientSession(raise_for_status=True)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self):
        await self.api_session.close()

    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self, headers: dict, url: str, data: dict, json_body: dict
    ) -> ClientResponse:
        return await self.api_session.post(url=url, data=data, json=json_body, headers=headers)

    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self, session_id: str, vehicle_key: str, url: str
    ) -> ClientResponse:
        headers = self._api_headers(session_id, vehicle_key)
        return await self.api_session.get(url=url, headers=headers)

    async def login(self, username, password):
        url = self.API_URL + "apiGateway"
        json_body = {
            "userId": username,
            "password": password,
            "userType": "1",
            "vin": "",
            "action": "authenticateUser"
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = await self._post_request_with_logging_and_errors_raised(
            url=url,
            json_body=None,
            data=json.dumps(json_body),
            headers=headers
        )
        return response.cookies["JSESSIONID"], await response.json(content_type="utf-8;charset=iso-8859-1")
