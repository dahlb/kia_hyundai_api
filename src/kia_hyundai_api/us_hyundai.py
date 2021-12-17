import logging

import time
from aiohttp import ClientSession, ClientResponse, ClientError

from .rate_error import RateError

_LOGGER = logging.getLogger(__name__)

BASE_URL: str = "api.telematics.hyundaiusa.com"
LOGIN_API: str = "https://" + BASE_URL + "/v2/ac/"
API_URL: str = "https://" + BASE_URL + "/ac/v2/"


def request_with_logging(func):
    async def request_with_logging_wrapper(*args, **kwargs):
        url = kwargs["url"]
        json_body = kwargs.get("json_body")
        if json_body is not None:
            _LOGGER.debug(f"sending {url} request with {json_body}")
        else:
            _LOGGER.debug(f"sending {url} request")
        response = await func(*args, **kwargs)
        _LOGGER.debug(f"response headers:{response.headers}")
        response_text = await response.text()
        _LOGGER.debug(f"response text:{response_text}")
        response_json = await response.json()
        if "errorCode" in response_json:
            if (
                response_json["errorCode"] == 502
                and response_json.get("errorSubCode", "") == "HT_534"
            ):
                raise RateError
            raise ClientError(f"api error:{response_json}")

    return request_with_logging_wrapper


def _api_headers(
    username: str,
    pin: str,
    access_token: str = None,
    vehicle_vin: str = None,
    vehicle_regid: str = None,
    extra_headers: dict[str, str] = None,
) -> dict[str, str]:
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
        "host": BASE_URL,
        "origin": "https://" + BASE_URL,
        "referer": "https://" + BASE_URL + "/login",
        "from": "SPA",
        "to": "ISS",
        "language": "0",
        "offset": str(int(time.localtime().tm_gmtoff / 60 / 60)),
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "refresh": "false",
        "encryptFlag": "false",
        "brandIndicator": "H",
        "gen": "2",
        "username": username,
        "blueLinkServicePin": pin,
        "client_id": "m66129Bb-em93-SPAHYN-bZ91-am4540zp19920",
        "clientSecret": "v558o935-6nne-423i-baa8",
    }
    if extra_headers is not None:
        headers.update(extra_headers)
    if vehicle_regid is not None:
        headers["registrationId"] = vehicle_regid
    if access_token is not None:
        headers["accessToken"] = access_token
    if vehicle_vin is not None:
        headers["vin"] = vehicle_vin
    return headers


class UsHyundai:
    def __init__(self, client_session: ClientSession = None):
        if client_session is None:
            self.api_session = ClientSession(raise_for_status=True)
        else:
            self.api_session = client_session

    async def cleanup_client_session(self):
        await self.api_session.close()

    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
        self,
        username: str,
        pin: str,
        url: str,
        json_body: dict,
        access_token: str = None,
        vehicle_vin: str = None,
        vehicle_regid: str = None,
        extra_headers: dict[str, str] = None,
    ) -> ClientResponse:
        headers = _api_headers(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            vehicle_regid=vehicle_regid,
            extra_headers=extra_headers,
        )
        return await self.api_session.post(url=url, json=json_body, headers=headers)

    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
        self,
        username: str,
        pin: str,
        url: str,
        access_token: str = None,
        vehicle_vin: str = None,
        vehicle_regid: str = None,
        extra_headers: dict[str, str] = None,
    ) -> ClientResponse:
        headers = _api_headers(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            vehicle_regid=vehicle_regid,
            extra_headers=extra_headers,
        )
        return await self.api_session.get(url=url, headers=headers)

    async def login(
        self, username: str, password: str, pin: str
    ) -> tuple[str, str, float]:
        url = LOGIN_API + "oauth/token"
        json_body = {"username": username, "password": password}
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                username=username, pin=pin, url=url, json_body=json_body
            )
        )
        response_json = await response.json()
        access_token: str = response_json["access_token"]
        refresh_token: str = response_json["refresh_token"]
        expires_in = float(response["expires_in"])
        return access_token, refresh_token, expires_in

    async def get_vehicles(self, username: str, pin: str, access_token: str):
        url = API_URL + "enrollment/details/" + username
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                username=username, pin=pin, access_token=access_token, url=url
            )
        )
        response_json = await response.json()
        return response_json

    async def get_cached_vehicle_status(
        self, username: str, pin: str, access_token: str, vehicle_vin: str
    ):
        url = API_URL + "rcs/rvs/vehicleStatus"
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                username=username,
                pin=pin,
                access_token=access_token,
                vehicle_vin=vehicle_vin,
                url=url,
            )
        )
        response_json = await response.json()
        return response_json["vehicleStatus"]

    def get_location(
        self, username: str, pin: str, access_token: str, vehicle_vin: str
    ):
        url = API_URL + "rcs/rfc/findMyCar"
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                username=username,
                pin=pin,
                access_token=access_token,
                vehicle_vin=vehicle_vin,
                url=url,
            )
        )
        response_json = await response.json()
        return response_json

    async def lock(
        self,
        username: str,
        pin: str,
        access_token: str,
        vehicle_vin: str,
        vehicle_regid: str,
    ):
        url = API_URL + "rcs/rdo/off"
        extra_headers = {"registrationId": vehicle_regid, "APPCLOUD-VIN": vehicle_vin}
        json_body = {"userName": self.username, "vin": vehicle_vin}
        response = await self._post_request_with_logging_and_errors_raised(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            url=url,
            json_body=json_body,
            extra_headers=extra_headers,
        )
        response_json = await response.json()
        return response_json

    async def unlock(
        self,
        username: str,
        pin: str,
        access_token: str,
        vehicle_vin: str,
        vehicle_regid: str,
    ):
        url = API_URL + "rcs/rdo/on"
        extra_headers = {"APPCLOUD-VIN": vehicle_vin}
        json_body = {"userName": self.username, "vin": vehicle_vin}
        response = await self._post_request_with_logging_and_errors_raised(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            vehicle_regid=vehicle_regid,
            url=url,
            json_body=json_body,
            extra_headers=extra_headers,
        )
        response_json = await response.json()
        return response_json

    async def start_climate(
        self,
        username: str,
        pin: str,
        access_token: str,
        vehicle_vin: str,
        vehicle_regid: str,
        set_temp,
        defrost,
        climate,
        heating,
        duration,
    ):
        url = API_URL + "rcs/rsc/start"
        json_body = {
            "Ims": 0,
            "airCtrl": int(climate),
            "airTemp": {"unit": 1, "value": set_temp},
            "defrost": defrost,
            "heating1": int(heating),
            "igniOnDuration": duration,
            "username": self.username,
            "vin": vehicle_vin,
        }
        response = await self._post_request_with_logging_and_errors_raised(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            vehicle_regid=vehicle_regid,
            url=url,
            json_body=json_body,
        )
        response_json = await response.json()
        return response_json

    async def stop_climate(
        self,
        username: str,
        pin: str,
        access_token: str,
        vehicle_vin: str,
        vehicle_regid: str,
    ):
        url = API_URL + "rcs/rsc/stop"
        response = await self._post_request_with_logging_and_errors_raised(
            username=username,
            pin=pin,
            access_token=access_token,
            vehicle_vin=vehicle_vin,
            vehicle_regid=vehicle_regid,
            url=url,
            json_body={},
        )
        response_json = await response.json()
        return response_json
