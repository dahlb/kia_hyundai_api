import logging
import asyncio

from datetime import datetime
import random
import string
import secrets
import ssl
from collections.abc import Callable
from typing import Any
from collections.abc import Coroutine
import certifi

import pytz
import time

from functools import partial
from aiohttp import ClientSession, ClientResponse

from .errors import AuthError, ActionAlreadyInProgressError
from .const import API_URL_BASE, API_URL_HOST, SeatSettings
from .util_http import request_with_logging, request_with_active_session

_LOGGER = logging.getLogger(__name__)


def _seat_settings(level: SeatSettings | None) -> dict:
    """Derive the seat settings from a seat setting enum."""
    match level:
        case SeatSettings.HeatHigh:
            return {
                "heatVentType": 1,
                "heatVentLevel": 4,
                "heatVentStep": 1,
            }
        case SeatSettings.HeatMedium:
            return {
                "heatVentType": 1,
                "heatVentLevel": 3,
                "heatVentStep": 2,
            }
        case SeatSettings.HeatLow:
            return {
                "heatVentType": 1,
                "heatVentLevel": 2,
                "heatVentStep": 3,
            }
        case SeatSettings.CoolHigh:
            return {
                "heatVentType": 2,
                "heatVentLevel": 4,
                "heatVentStep": 1,
            }
        case SeatSettings.CoolMedium:
            return {
                "heatVentType": 2,
                "heatVentLevel": 3,
                "heatVentStep": 2,
            }
        case SeatSettings.CoolLow:
            return {
                "heatVentType": 2,
                "heatVentLevel": 2,
                "heatVentStep": 3,
            }
        case _:
            return {
                "heatVentType": 0,
                "heatVentLevel": 1,
                "heatVentStep": 0,
            }


class UsKia:
    _ssl_context = None
    session_id: str | None = None
    otp_key: str | None = None
    notify_type: str | None = None
    vehicles: list[dict] | None = None
    last_action = None

    def __init__(
            self,
            username: str,
            password: str,
            otp_callback: Callable[..., Coroutine[Any, Any, Any]],
            device_id: str | None = None,
            refresh_token: str | None = None,
            client_session: ClientSession | None = None
                ):
        """Login into cloud endpoints
        Parameters
        ----------
        username : str
            User email address
        password : str
            User password
        token : Token, optional
            Existing token with stored rmtoken for reuse
        device_id : reused , optional
        otp_callback : Callable[..., Coroutine[Any, Any, Any]]
            Non-interactive OTP handler. Called twice:
            - stage='choose_destination' -> return {'notify_type': 'EMAIL'|'SMS'}
            - stage='input_code' -> return {'otp_code': '<code>'}
        """
        self.username = username
        self.password = password
        self.otp_callback = otp_callback
        # Randomly generate a plausible device id on startup
        self.device_id = device_id or (
            "".join(
                random.choice(string.ascii_letters + string.digits) for _ in range(22)
            )
            + ":"
            + secrets.token_urlsafe(105)
        )
        self.refresh_token = refresh_token
        if client_session is None:
            self.api_session = ClientSession(raise_for_status=True)
        else:
            self.api_session = client_session

    async def get_ssl_context(self):
        if self._ssl_context is None:
            loop = asyncio.get_running_loop()
            new_ssl_context = await loop.run_in_executor(None, partial(ssl.create_default_context, cafile=certifi.where()))
            await loop.run_in_executor(None, partial(new_ssl_context.load_default_certs))
            new_ssl_context.check_hostname = True
            new_ssl_context.verify_mode = ssl.CERT_REQUIRED
            new_ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")
            new_ssl_context.options = (
                    ssl.OP_CIPHER_SERVER_PREFERENCE
            )
            new_ssl_context.options |= 0x4  # OP flag SSL_OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION
            self._ssl_context = new_ssl_context
        return self._ssl_context

    def _api_headers(self, vehicle_key: str | None = None) -> dict:
        headers = {
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "apptype": "L",
            "appversion": "7.12.1",
            "clientid": "MWAMOBILE",
            "from": "SPA",
            "host": API_URL_HOST,
            "language": "0",
            "offset": str(int(time.localtime().tm_gmtoff / 60 / 60)),
            "ostype": "Android",
            "osversion": "11",
            "secretkey": "98er-w34rf-ibf3-3f6h",
            "to": "APIGW",
            "tokentype": "G",
            "user-agent": "okhttp/4.10.0",
            "deviceid": self.device_id,
            "date": datetime.now(tz=pytz.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if self.session_id is not None:
            headers["sid"] = self.session_id
        if self.refresh_token is not None:
            headers["rmtoken"] = self.refresh_token
        if self.otp_key is not None:
            headers["otpkey"] = self.otp_key
            if self.notify_type is not None:
                headers["notifytype"] = self.notify_type
            else:
                raise ValueError("notify_type must be set before sending OTP")
            if self.last_action is not None and "xid" in self.last_action:
                headers["xid"] = self.last_action["xid"]
            else:
                raise ValueError("xid(last_action) must be set before sending OTP")
        if vehicle_key is not None:
            headers["vinkey"] = vehicle_key
        return headers

    @request_with_logging
    async def _post_request_with_logging_and_errors_raised(
            self,
            vehicle_key: str | None,
            url: str,
            json_body: dict,
            authed: bool = True,
    ) -> ClientResponse:
        if authed and self.session_id is None:
            await self.login()
        headers = self._api_headers(vehicle_key=vehicle_key)
        return await self.api_session.post(
            url=url,
            json=json_body,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    @request_with_logging
    async def _get_request_with_logging_and_errors_raised(
            self,
            vehicle_key: str | None,
            url: str,
            authed: bool = True,
    ) -> ClientResponse:
        if authed and self.session_id is None:
            await self.login()
        headers = self._api_headers(vehicle_key=vehicle_key)
        return await self.api_session.get(
            url=url,
            headers=headers,
            ssl=await self.get_ssl_context()
        )

    async def _send_otp(self, notify_type: str) -> dict:
        """
        Send OTP to email or phone

        Parameters
        notify_type = "EMAIL" or "SMS"
        """
        if notify_type not in ("EMAIL", "SMS"):
            raise ValueError(f"Invalid notify_type {notify_type}")
        if self.otp_key is None:
            raise ValueError("OTP key required")
        url = API_URL_BASE + "cmm/sendOTP"
        self.notify_type = notify_type
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body={},
                authed=False,
            )
        )
        _LOGGER.debug(f"Send OTP Response {response.text}")
        return await response.json()

    async def _verify_otp(self, otp_code: str):
        """Verify OTP code and return sid and rmtoken"""
        url = API_URL_BASE + "cmm/verifyOTP"
        data = {"otp": otp_code}
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body=data,
                authed=False,
            )
        )
        self.last_action = None
        self.otp_key = None
        self.notify_type = None
        _LOGGER.debug(f"Verify OTP Response {response.text}")
        response_json = await response.json()
        if response_json["status"]["statusCode"] != 0:
            raise Exception(
                f"OTP verification failed: {response_json['status']['errorMessage']}"
            )
        session_id = response.headers.get("sid")
        rmtoken = response.headers.get("rmtoken")
        if not session_id or not rmtoken:
            raise AuthError(
                f"No session_id or rmtoken in OTP verification response. Headers: {response.headers}"
            )
        self.session_id = session_id
        self.refresh_token = rmtoken

    async def login(self):
        """ Login into cloud endpoints """
        url = API_URL_BASE + "prof/authUser"
        data = {
            "deviceKey": "",
            "deviceType": 2,
            "userCredential": {"userId": self.username, "password": self.password},
        }
        response: ClientResponse = (
            await self._post_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url,
                json_body=data,
                authed=False,
            )
        )
        _LOGGER.debug(f"Complete Login Response {response.text}")
        self.session_id = response.headers.get("sid")
        _LOGGER.debug(f"Session ID {self.session_id}")
        if self.session_id:
            _LOGGER.debug(f"got session id {self.session_id}")
            return
        response_json = await response.json()
        if "payload" in response_json and "otpKey" in response_json["payload"]:
            payload = response_json["payload"]
            if payload.get("rmTokenExpired"):
                _LOGGER.info("Stored rmtoken has expired, need new OTP")
                self.refresh_token = None
            try:
                self.otp_key = payload["otpKey"]
                self.last_action = {
                    "name": "one_time_password",
                    "xid": response.headers.get("xid", None),
                }
                _LOGGER.info("OTP required for login")
                ctx_choice = {
                    "stage": "choose_destination",
                    "hasEmail": bool(payload.get("hasEmail")),
                    "hasPhone": bool(payload.get("hasPhone")),
                    "email": payload.get("email", 'N/A'),
                    "phone": payload.get("phone", 'N/A'),
                }
                _LOGGER.debug(f"OTP callback stage choice args: {ctx_choice}")
                callback_response = await self.otp_callback(ctx_choice)
                _LOGGER.debug(f"OTP callback response {callback_response}")
                notify_type = str(callback_response.get("notify_type", "EMAIL")).upper()
                await self._send_otp(notify_type)
                otp_code = None
                ctx_code = {
                    "stage": "input_code",
                    "notify_type": notify_type,
                    "otpKey": self.otp_key,
                    "xid": self.last_action["xid"],
                }
                _LOGGER.debug(f"OTP callback stage input args: {ctx_code}")
                otp_callback_response = await self.otp_callback(ctx_code)
                otp_code = str(otp_callback_response.get("otp_code", "")).strip()
                if not otp_code:
                    raise AuthError("OTP code required")
                await self._verify_otp(otp_code)
                await self.login()
                return
            finally:
                self.otp_key = None
                self.last_action = None
                self.notify_type = None
        raise AuthError(
                f"No session id returned in login. Response: {response.text} headers {response.headers} cookies {response.cookies}"
                        )


    @request_with_active_session
    async def get_vehicles(self):
        """
        {"status":{"statusCode":0,"errorType":0,"errorCode":0,"errorMessage":"Success with response body"},"payload":{"vehicleSummary":[{"vin":"VIN","vehicleIdentifier":"1234","modelName":"NIRO EV","modelYear":"2019","nickName":"Niro EV","generation":2,"extColorCode":"C3S","trim":"EX PREMIUM","imagePath":{"imageName":"2019-niro_ev-ex_premium-c3s.png","imagePath":"/content/dam/kia/us/owners/image/vehicle/2019/niro_ev/ex_premium/","imageType":"1","imageSize":{"length":"100","width":"100","uom":0}},"enrollmentStatus":1,"fatcAvailable":1,"telematicsUnit":1,"fuelType":4,"colorName":"ALUMINUM SILVER","activationType":2,"mileage":"12844.7","dealerCode":"MD047","mobileStore":[{"osType":0,"downloadURL":"https://itunes.apple.com/us/app/kia-access-with-uvo-link/id1280548773?mt=8","image":{"imageName":"iosImage.png","imagePath":"/content/dam/kia/us/owners/image/common/app/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}},{"osType":1,"downloadURL":"https://play.google.com/store/apps/details?id=com.myuvo.link","image":{"imageName":"androidImage.png","imagePath":"/content/dam/kia/us/owners/image/common/app/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}}],"supportedApp":{"appType":"5","appImage":{"imageName":"uvo-app.png","imagePath":"/content/dam/kia/us/owners/image/common/app/access/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}},"supportAdditionalDriver":0,"customerType":0,"projectCode":"DEEV","headUnitDesc":"AVN5.0","provStatus":"4","enrollmentSuppressionType":0,"vehicleKey":"KEY"}]}}
        """
        url = API_URL_BASE + "ownr/gvl"
        response: ClientResponse = (
            await self._get_request_with_logging_and_errors_raised(
                vehicle_key=None,
                url=url
            )
        )
        response_json = await response.json()
        self.vehicles =  response_json["payload"]["vehicleSummary"]

    async def find_vehicle_key(self, vehicle_id: str):
        if self.vehicles is None:
            await self.get_vehicles()
        if self.vehicles is None:
            raise ValueError("no vehicles found")
        for vehicle in self.vehicles:
            if vehicle["vehicleIdentifier"] == vehicle_id:
                return vehicle["vehicleKey"]
        raise ValueError(f"vehicle key for id:{vehicle_id} not found")

    @request_with_active_session
    async def get_cached_vehicle_status(self, vehicle_id: str):
        """
        {"status":{"statusCode":0,"errorType":0,"errorCode":0,"errorMessage":"Success with response body"},"payload":{"vehicleInfoList":[{"vinKey":"KEY","vehicleConfig":{"vehicleDetail":{"vehicle":{"vin":"VIN","trim":{"modelYear":"2019","salesModelCode":"V1262","optionGroupCode":"015","modelName":"NIRO EV","factoryCode":"DQ","projectCode":"DEEV","trimName":"EX PREMIUM","driveType":"0","transmissionType":"1","ivrCategory":"6","btSeriesCode":"N"},"telematics":1,"mileage":"13228.1","mileageSyncDate":"20211211075445","exteriorColor":"ALUMINUM SILVER","exteriorColorCode":"C3S","fuelType":4,"invDealerCode":"MD047","testVehicle":"0","supportedApps":[{"appType":"0"},{"appType":"5","appImage":{"imageName":"uvo-app.png","imagePath":"/content/dam/kia/us/owners/image/common/app/access/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}}],"activationType":2},"images":[{"imageName":"2019-niro_ev-ex_premium-c3s.png","imagePath":"/content/dam/kia/us/owners/image/vehicle/2019/niro_ev/ex_premium/","imageType":"1","imageSize":{"length":"100","width":"100","uom":0}}],"device":{"launchType":"0","swVersion":"DEEV.USA.SOP.V105.190503.STD_H","telematics":{"generation":"3","platform":"1","tmsCenter":"1","billing":true},"versionNum":"ECO","headUnitType":"0","hdRadio":"X40HA","ampType":"NA","modem":{"meid":"MEID","mdn":"MDN","iccid":"ICCID"},"headUnitName":"avn40ev_np","bluetoothRef":"10","headUnitDesc":"AVN5.0"}},"maintenance":{"nextServiceMile":1771.9004,"maintenanceSchedule":[6500,7500,13000,15000,19500,22500,26000,30000,32500,37500,39000,45000,45500,52000,52500,58500,60000,65000,67500,71500,75000,78000,82500,84500,90000,91000,97500,104000,105000,110500,112500]},"vehicleFeature":{"remoteFeature":{"lock":"1","unlock":"1","start":"3","stop":"1","scheduleCount":"2","inVehicleSchedule":"1","heatedSteeringWheel":"1","heatedSideMirror":"1","heatedRearWindow":"1","heatedSeat":"0","ventSeat":"0","alarm":"1","hornlight":"1","panic":"1","separateHeatedAccessories":"0","windowSafety":"0"},"chargeFeature":{"batteryChargeType":"1","chargeEndPct":"4","immediateCharge":"1","cancelCharge":"1","evRange":"1","scheduleCount":"2","inVehicleSchedule":"1","offPeakType":"2","scheduleType":"2","chargeLevel":"3","scheduleConfig":"1","fatcWithCharge":"1","targetSOC":"1","minTargetSOC":"50","maxTargetSOC":"100","socStep":"10"},"alertFeature":{"geofenceType":{"geofence":"1","entryCount":"5","exitCount":"1","inVehicleConfig":"0","minRadius":"1","maxRadius":"10","minHeight":"1","maxHeight":"10","minWidth":"1","maxWidth":"10","uom":"0"},"curfewType":{"curfew":"1","curfewCount":"21","inVehicleConfig":"0"},"speedType":{"speed":"1","speedCount":"21","inVehicleConfig":"0"},"valetType":{"valet":"1","valetParkingMode":"0","defaultRadius":"1","defaultRadiusUnit":"3","defaultInterval":"5","defaultIntervalUnit":"3","inVehicleConfig":"0"}},"vrmFeature":{"autoDTC":"1","scheduledDTC":"1","backgroundDTC":"1","manualDTC":"1","healthReport":"0","drivingScore":"1","gasRange":"0","evRange":"1","trip":"1"},"locationFeature":{"gpsStreaming":"0","location":"1","poi":"1","poiCount":"25","push2Vehicle":"1","wayPoint":"1","mapType":"1","surroundView":"0","svr":"1"},"userSettingFeature":{"usmType":"0","vehicleOptions":"0","systemOptions":"0","additionalDriver":"0","calendar":"0","valetParkingMode":"0","wifiHotSpot":"0","otaSupport":"0"}},"heatVentSeat":{},"billingPeriod":{"freeTrial":{"value":12,"unit":0},"freeTrialExtension":{"value":12,"unit":1},"servicePeriod":{"value":60,"unit":1}}},"lastVehicleInfo":{"vehicleNickName":"Niro EV","preferredDealer":"MD047","customerType":0,"vehicleStatusRpt":{"statusType":"2","reportDate":{"utc":"20211212004604","offset":-8},"vehicleStatus":{"climate":{"airCtrl":false,"defrost":false,"airTemp":{"value":"72","unit":1},"heatingAccessory":{"steeringWheel":0,"sideMirror":0,"rearWindow":0}},"engine":false,"doorLock":true,"doorStatus":{"frontLeft":0,"frontRight":0,"backLeft":0,"backRight":0,"trunk":0,"hood":0},"lowFuelLight":false,"evStatus":{"batteryCharge":false,"batteryStatus":79,"batteryPlugin":0,"remainChargeTime":[{"remainChargeType":2,"timeInterval":{"value":0,"unit":4}},{"remainChargeType":3,"timeInterval":{"value":0,"unit":4}},{"remainChargeType":1,"timeInterval":{"value":0,"unit":4}}],"drvDistance":[{"type":2,"rangeByFuel":{"evModeRange":{"value":214,"unit":3},"totalAvailableRange":{"value":214,"unit":3}}}],"syncDate":{"utc":"20211211225859","offset":-8},"targetSOC":[{"plugType":0,"targetSOClevel":80,"dte":{"type":2,"rangeByFuel":{"gasModeRange":{"value":0,"unit":3},"evModeRange":{"value":214,"unit":3},"totalAvailableRange":{"value":214,"unit":3}}}},{"plugType":1,"targetSOClevel":90,"dte":{"type":2,"rangeByFuel":{"gasModeRange":{"value":0,"unit":3},"evModeRange":{"value":214,"unit":3},"totalAvailableRange":{"value":214,"unit":3}}}}]},"ign3":true,"transCond":true,"tirePressure":{"all":0},"dateTime":{"utc":"20211212004604","offset":-8},"syncDate":{"utc":"20211211225859","offset":-8},"batteryStatus":{"stateOfCharge":81,"sensorStatus":0},"sleepMode":false,"lampWireStatus":{"headLamp":{},"stopLamp":{},"turnSignalLamp":{}},"windowStatus":{},"engineRuntime":{},"valetParkingMode":0}},"location":{"coord":{"lat":1,"lon":-7,"alt":118,"type":0,"altdo":0},"head":349,"speed":{"value":0,"unit":1},"accuracy":{"hdop":6,"pdop":11},"syncDate":{"utc":"20211211225445","offset":-8}},"financed":true,"financeRegistered":true,"linkStatus":0}}]}}
        {"status":{"statusCode":0,"errorType":0,"errorCode":0,"errorMessage":"Success with response body"},"payload":{"vehicleInfoList":[{"vinKey":"KEY","vehicleConfig":{"vehicleDetail":{"vehicle":{"vin":"VIN","trim":{"modelYear":"2021","salesModelCode":"45482","optionGroupCode":"010","modelName":"SPORTAGE","factoryCode":"D9","projectCode":"QL","trimName":"SX-P","driveType":"2","transmissionType":"1","ivrCategory":"5","btSeriesCode":"4"},"telematics":1,"mileage":"11665.9","mileageSyncDate":"20211216143655","exteriorColor":"STEEL GRAY","exteriorColorCode":"KLG","fuelType":1,"invDealerCode":"NJ074","testVehicle":"0","supportedApps":[{"appType":"0"},{"appType":"5","appImage":{"imageName":"uvo-app.png","imagePath":"/content/dam/kia/us/owners/image/common/app/access/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}}],"activationType":2},"images":[{"imageName":"2021-sportage-sx-p-klg.png","imagePath":"/content/dam/kia/us/owners/image/vehicle-app/2021/sportage/sx-p/","imageType":"1","imageSize":{"length":"100","width":"100","uom":0}}],"device":{"launchType":"0","swVersion":"QL21.USA.SOP.V115.200325.STD_H","telematics":{"generation":"3","platform":"1","tmsCenter":"1","billing":true},"versionNum":"GASOLINE","headUnitType":"0","hdRadio":"X40HA","ampType":"NA","modem":{"meid":"MEID","mdn":"MDN","iccid":"ICCID"},"headUnitName":"avn5em","bluetoothRef":"10","headUnitDesc":"AVN5.0"}},"billingPeriod":{"freeTrial":{"value":12,"unit":0},"freeTrialExtension":{"value":12,"unit":1},"servicePeriod":{"value":60,"unit":1}}},"lastVehicleInfo":{"vehicleNickName":"Kia","preferredDealer":"NJ074","customerType":0,"enrollment":{"provStatus":"4","enrollmentStatus":"1","enrollmentType":"0","registrationDate":"20200829","expirationDate":"20210829","expirationMileage":"100000","freeServiceDate":{"startDate":"20200829","endDate":"20210829"}},"activeDTC":{"dtcActiveCount":"0"},"vehicleStatusRpt":{"statusType":"2","reportDate":{"utc":"20211217151540","offset":-8},"vehicleStatus":{"climate":{"airCtrl":false,"defrost":false,"airTemp":{"value":"LOW","unit":1},"heatingAccessory":{"steeringWheel":0,"sideMirror":0,"rearWindow":0}},"engine":false,"doorLock":true,"doorStatus":{"frontLeft":0,"frontRight":0,"backLeft":0,"backRight":0,"trunk":0,"hood":0},"lowFuelLight":false,"ign3":false,"transCond":true,"dateTime":{"utc":"20211217151540","offset":-8},"syncDate":{"utc":"20211217053655","offset":-8},"batteryStatus":{},"sleepMode":true,"lampWireStatus":{"headLamp":{},"stopLamp":{},"turnSignalLamp":{}},"windowStatus":{},"vehicleMovementHis":true,"engineRuntime":{"value":1509,"unit":3},"valetParkingMode":0}},"location":{"coord":{"lat":40.62193333,"lon":-74.4951805556,"alt":113,"type":0,"altdo":0},"head":22,"speed":{"value":0,"unit":1},"accuracy":{"hdop":7,"pdop":13},"syncDate":{"utc":"20211217053655","offset":-8}},"financed":true,"financeRegistered":true,"linkStatus":0}}]}}
        {"status":{"statusCode":0,"errorType":0,"errorCode":0,"errorMessage":"Success with response body"},"payload":{"vehicleInfoList":[{"vinKey":"KEY","vehicleConfig":{"vehicleDetail":{"vehicle":{"vin":"VIN","trim":{"modelYear":"2020","salesModelCode":"G4262","optionGroupCode":"010","modelName":"NIRO","factoryCode":"G5","projectCode":"DEHEV","trimName":"TOURING","driveType":"0","transmissionType":"1","ivrCategory":"5","btSeriesCode":"G"},"telematics":1,"mileage":"0","mileageSyncDate":"20211228211444","exteriorColor":"DEEP CERULEAN","exteriorColorCode":"C3U","fuelType":3,"invDealerCode":"PA004","testVehicle":"0","supportedApps":[{"appType":"0"},{"appType":"5","appImage":{"imageName":"uvo-app.png","imagePath":"/content/dam/kia/us/owners/image/common/app/access/","imageType":"2","imageSize":{"length":"100","width":"100","uom":0}}}],"activationType":2},"images":[{"imageName":"2020-niro-touring-c3u.png","imagePath":"/content/dam/kia/us/owners/image/vehicle-app/2020/niro/touring/","imageType":"1","imageSize":{"length":"100","width":"100","uom":0}}],"device":{"launchType":"0","swVersion":"DEPE_HEV.USA.D2V.002.001.191207","telematics":{"generation":"3","platform":"1","tmsCenter":"1","billing":true},"versionNum":"GASOLINE","headUnitType":"2","hdRadio":"X40HAF","ampType":"NA","modem":{"meid":"352756079211901","mdn":"6574342729","iccid":"89148000005952739845"},"headUnitName":"daudio1","bluetoothRef":"19","headUnitDesc":"DAV2"}},"maintenance":{"nextServiceMile":5823.7197,"maintenanceSchedule":[7500,15000,22500,30000,37500,45000,52500,60000,67500,75000,82500,90000,97500,105000,112500]},"vehicleFeature":{"remoteFeature":{"lock":"1","unlock":"1","start":"3","stop":"1","scheduleCount":"2","inVehicleSchedule":"1","heatedSteeringWheel":"1","heatedSideMirror":"1","heatedRearWindow":"1","heatedSeat":"0","ventSeat":"0","alarm":"1","hornlight":"1","panic":"1","doorSecurity":"1","engineIdleTime":"1","separateHeatedAccessories":"0","windowSafety":"0"},"chargeFeature":{"batteryChargeType":"0","chargeEndPct":"0","immediateCharge":"0","cancelCharge":"0","evRange":"0","scheduleCount":"0","inVehicleSchedule":"0","offPeakType":"0","scheduleType":"0","chargeLevel":"0","scheduleConfig":"0","fatcWithCharge":"0"},"alertFeature":{"geofenceType":{"geofence":"1","entryCount":"5","exitCount":"1","inVehicleConfig":"0","minRadius":"1","maxRadius":"10","minHeight":"1","maxHeight":"10","minWidth":"1","maxWidth":"10","uom":"0"},"curfewType":{"curfew":"1","curfewCount":"21","inVehicleConfig":"0"},"speedType":{"speed":"1","speedCount":"21","inVehicleConfig":"0"},"valetType":{"valet":"1","valetParkingMode":"0","defaultRadius":"1","defaultRadiusUnit":"3","defaultInterval":"5","defaultIntervalUnit":"3","inVehicleConfig":"0"}},"vrmFeature":{"autoDTC":"1","scheduledDTC":"1","backgroundDTC":"1","manualDTC":"1","healthReport":"0","drivingScore":"1","gasRange":"1","evRange":"0","trip":"1"},"locationFeature":{"gpsStreaming":"0","location":"1","poi":"1","poiCount":"25","push2Vehicle":"1","wayPoint":"1","mapType":"1","surroundView":"0","svr":"1"},"userSettingFeature":{"usmType":"0","calendar":"0","valetParkingMode":"0","wifiHotSpot":"0","otaSupport":"0","digitalKeyOption":"0"}},"heatVentSeat":{},"billingPeriod":{"freeTrial":{"value":12,"unit":0},"freeTrialExtension":{"value":12,"unit":1},"servicePeriod":{"value":60,"unit":1}}},"lastVehicleInfo":{"vehicleNickName":"Niro","preferredDealer":"PA004","licensePlate":"","psi":"","customerType":1,"vehicleStatusRpt":{"statusType":"2","reportDate":{"utc":"20211229124008","offset":-8},"vehicleStatus":{"climate":{"airCtrl":false,"defrost":false,"airTemp":{"value":"75","unit":1},"heatingAccessory":{"steeringWheel":0,"sideMirror":0,"rearWindow":0}},"engine":false,"doorLock":true,"doorStatus":{"frontLeft":0,"frontRight":0,"backLeft":0,"backRight":0,"trunk":0,"hood":0},"lowFuelLight":false,"ign3":false,"transCond":true,"distanceToEmpty":{"value":438,"unit":3},"tirePressure":{"all":0,"frontLeft":0,"frontRight":0,"rearLeft":0,"rearRight":0},"dateTime":{"utc":"20211229124008","offset":-8},"syncDate":{"utc":"20211229121444","offset":-8},"batteryStatus":{"stateOfCharge":100,"sensorStatus":0,"deliveryMode":0},"sleepMode":true,"lampWireStatus":{"headLamp":{},"stopLamp":{},"turnSignalLamp":{}},"windowStatus":{},"engineOilStatus":false,"vehicleMovementHis":false,"engineRuntime":{"value":8,"unit":1},"valetParkingMode":0}},"location":{"coord":{"lat":4,"lon":-7,"alt":61.2,"type":0,"altdo":0},"head":179,"speed":{"value":0,"unit":1},"accuracy":{"hdop":0,"pdop":1},"syncDate":{"utc":"20211229121444","offset":-8}},"financed":true,"financeRegistered":false,"linkStatus":0}}]}}
        {'status': {'statusCode': 0, 'errorType': 0, 'errorCode': 0, 'errorMessage': 'Success with response body'}, 'payload': {'vehicleInfoList': [{'vinKey': '***', 'vehicleConfig': {'vehicleDetail': {'vehicle': {'vin': '***', 'trim': {'modelYear': '2023', 'salesModelCode': 'U4462', 'optionGroupCode': '010', 'modelName': 'SORENTO HYBRID', 'factoryCode': 'HC', 'projectCode': 'MQ4HEV', 'trimName': 'SX-P', 'driveType': '2', 'transmissionType': '1', 'ivrCategory': '5', 'btSeriesCode': 'U'}, 'telematics': 1, 'mileage': '19865', 'mileageSyncDate': '20250308071606', 'exteriorColor': 'AURORA BLACK', 'exteriorColorCode': 'ABP', 'fuelType': 3, 'invDealerCode': 'MI008', 'testVehicle': '0', 'supportedApps': [{'appType': '0'}, {'appType': '5', 'appImage': {'imageName': 'uvo-app.png', 'imagePath': '/content/dam/kia/us/owners/image/common/app/access/', 'imageType': '2', 'imageSize': {'length': '100', 'width': '100', 'uom': 0}}}], 'activationType': 2, 'headUnitType': 'N', 'displayType': 'AVN5.0W', 'headUnitName': 'AVN5W'}, 'images': [{'imageName': '2023-sorento_hybrid-sx-p-abp.png', 'imagePath': '/content/dam/kia/us/owners/image/vehicle/2023/sorento_hybrid/sx-p/', 'imageType': '1', 'imageSize': {'length': '100', 'width': '100', 'uom': 0}}], 'device': {'launchType': '0', 'swVersion': 'MQ422HEV.USA.S5W_M.V009.001.230203', 'telematics': {'generation': '3', 'platform': '1', 'tmsCenter': '1', 'billing': True, 'genType': '2'}, 'versionNum': 'GASOLINE', 'headUnitType': '0', 'hdRadio': 'X40HA', 'ampType': 'NA', 'headUnitName': 'AVN5W', 'bluetoothRef': '20', 'headUnitDesc': 'AVN5.0W'}}, 'maintenance': {'nextServiceMile': 4134.5, 'maintenanceSchedule': [8000, 16000, 24000, 32000, 40000, 48000, 56000, 64000, 72000, 80000, 88000, 96000]}, 'vehicleFeature': {'remoteFeature': {'lock': '1', 'unlock': '1', 'start': '3', 'stop': '1', 'scheduleCount': '2', 'inVehicleSchedule': '1', 'heatedSteeringWheel': '1', 'heatedSideMirror': '1', 'heatedRearWindow': '1', 'heatedSeat': '1', 'ventSeat': '1', 'alarm': '1', 'hornlight': '1', 'panic': '1', 'doorSecurity': '1', 'rearOccupancyAlert': '1', 'lowFuel': '1', 'headLightTailLight': '1', 'engineIdleTime': '1', 'engineIdleStop': '1', 'softwareUpdate': '1', 'batteryDischarge': '1', 'separateHeatedAccessories': '1', 'surroundViewMonitor': '0', 'windowSafety': '1', 'comboCommand': '1', 'isHeatedAccessoriesSupported': '1', 'steeringWheelStepLevel': '1', 'frunkOption': '0'}, 'chargeFeature': {'batteryChargeType': '0', 'chargeEndPct': '0', 'immediateCharge': '0', 'cancelCharge': '0', 'evRange': '0', 'scheduleCount': '0', 'inVehicleSchedule': '0', 'offPeakType': '0', 'scheduleType': '0', 'chargeLevel': '0', 'scheduleConfig': '0', 'fatcWithCharge': '0', 'evAlarmOption': '0', 'chargePortDoorOption': '0', 'v2LSocSetServiceOption': '0', 'v2LRemainTimeOption': '0', 'chargePassSupport': '0', 'v2hSubscribed': '0', 'evrpSupport': '0'}, 'alertFeature': {'geofenceType': {'geofence': '1', 'entryCount': '5', 'exitCount': '1', 'inVehicleConfig': '0', 'minRadius': '1', 'maxRadius': '10', 'minHeight': '1', 'maxHeight': '10', 'minWidth': '1', 'maxWidth': '10', 'uom': '0'}, 'curfewType': {'curfew': '1', 'curfewCount': '21', 'inVehicleConfig': '0'}, 'speedType': {'speed': '1', 'speedCount': '21', 'inVehicleConfig': '0'}, 'valetType': {'valet': '1', 'valetParkingMode': '1', 'defaultRadius': '1', 'defaultRadiusUnit': '3', 'defaultInterval': '5', 'defaultIntervalUnit': '3', 'inVehicleConfig': '0'}}, 'vrmFeature': {'autoDTC': '1', 'scheduledDTC': '1', 'backgroundDTC': '1', 'manualDTC': '1', 'healthReport': '0', 'drivingScore': '1', 'gasRange': '1', 'evRange': '0', 'trip': '1'}, 'locationFeature': {'gpsStreaming': '0', 'location': '1', 'poi': '1', 'poiCount': '25', 'push2Vehicle': '1', 'wayPoint': '0', 'lastMile': '1', 'mapType': '1', 'surroundView': '1', 'svr': '1'}, 'userSettingFeature': {'usmType': '2', 'vehicleOptions': '0', 'systemOptions': '1', 'additionalDriver': '1', 'calendar': '1', 'valetParkingMode': '1', 'wifiHotSpot': '0', 'otaSupport': '0', 'digitalKeyOption': '0', 'digitalStoreSupport': '0', 'idleSpeedValetAlert': '0', 'ecuOtaHistory': '0'}}, 'heatVentSeat': {'driverSeat': {'heatVentType': 3, 'heatVentStep': 3}, 'passengerSeat': {'heatVentType': 3, 'heatVentStep': 3}, 'rearLeftSeat': {'heatVentType': 1, 'heatVentStep': 2}, 'rearRightSeat': {'heatVentType': 1, 'heatVentStep': 2}}, 'billingPeriod': {'freeTrial': {'value': 12, 'unit': 0}, 'freeTrialExtension': {'value': 12, 'unit': 1}, 'servicePeriod': {'value': 60, 'unit': 1}}}, 'lastVehicleInfo': {'vehicleNickName': 'My SORENTO HYBRID', 'preferredDealer': 'MI008', 'licensePlate': '', 'psi': '', 'customerType': 0, 'enrollment': {'provStatus': '4', 'enrollmentStatus': '1', 'enrollmentType': '0', 'registrationDate': '20230918', 'expirationDate': '20240918', 'expirationMileage': '100000', 'freeServiceDate': {'startDate': '20230918', 'endDate': '20240918'}, 'endOfLife': 0}, 'vehicleStatusRpt': {'statusType': '2', 'reportDate': {'utc': '20250311143718', 'offset': -7}, 'vehicleStatus': {'climate': {'airCtrl': False, 'defrost': False, 'airTemp': {'value': '72', 'unit': 1}, 'heatingAccessory': {'steeringWheel': 0, 'sideMirror': 0, 'rearWindow': 0}, 'heatVentSeat': {'driverSeat': {'heatVentType': 0, 'heatVentLevel': 1}, 'passengerSeat': {'heatVentType': 0, 'heatVentLevel': 1}, 'rearLeftSeat': {'heatVentType': 0, 'heatVentLevel': 1}, 'rearRightSeat': {'heatVentType': 0, 'heatVentLevel': 1}}}, 'engine': False, 'doorLock': False, 'doorStatus': {'frontLeft': 0, 'frontRight': 0, 'backLeft': 0, 'backRight': 0, 'trunk': 0, 'hood': 0}, 'lowFuelLight': False, 'ign3': False, 'transCond': True, 'distanceToEmpty': {'value': 155, 'unit': 3}, 'tirePressure': {'all': 0}, 'dateTime': {'utc': '20250311143718', 'offset': -7}, 'syncDate': {'utc': '20250308221606', 'offset': -8}, 'batteryStatus': {'stateOfCharge': 72, 'deliveryMode': 1, 'powerAutoCutMode': 2}, 'sleepMode': True, 'lampWireStatus': {'headLamp': {'headLampStatus': False, 'lampLL': False, 'lampRL': False, 'lampLH': False, 'lampRH': False, 'lampLB': False, 'lampRB': False}, 'stopLamp': {'leftLamp': False, 'rightLamp': False}, 'turnSignalLamp': {'lampLF': False, 'lampRF': False, 'lampLR': False, 'lampRR': False}}, 'windowStatus': {'windowFL': 1, 'windowFR': 1, 'windowRL': 1, 'windowRR': 1}, 'smartKeyBatteryWarning': False, 'fuelLevel': 31, 'washerFluidStatus': False, 'brakeOilStatus': False, 'engineOilStatus': False, 'vehicleMovementHis': False, 'engineRuntime': {'value': 0, 'unit': 3}, 'remoteControlAvailable': 1, 'valetParkingMode': 0, 'rsaStatus': 0}}, 'location': {'coord': {'lat': '***', 'lon': '***', 'alt': 202, 'type': 0, 'altdo': 0}, 'head': 87, 'speed': {'value': 0, 'unit': 1}, 'accuracy': {'hdop': 7, 'pdop': 12}, 'syncDate': {'utc': '20250308221606', 'offset': -8}}, 'financed': True, 'financeRegistered': False, 'linkStatus': 0}}]}}
        """
        url = API_URL_BASE + "cmm/gvi"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "vehicleConfigReq": {
                "airTempRange": "0",
                "maintenance": "1",
                "seatHeatCoolOption": "1",
                "vehicle": "1",
                "vehicleFeature": "1",
            },
            "vehicleInfoReq": {
                "drivingActivty": "0",
                "dtc": "0",
                "enrollment": "1",
                "functionalCards": "0",
                "location": "1",
                "vehicleStatus": "1",
                "weather": "0",
            },
            "vinKey": [vehicle_key],
        }
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        response_json = await response.json()
        return response_json["payload"]["vehicleInfoList"][0]

    @request_with_active_session
    async def request_vehicle_data_sync(self, vehicle_id: str):
        """
        {"status":{"statusCode":0,"errorType":0,"errorCode":0,"errorMessage":"Success with response body"},"payload":{"vehicleStatusRpt":{"statusType":"1","reportDate":{"utc":"20211130173341","offset":-8},"vehicleStatus":{"climate":{"airCtrl":false,"defrost":false,"airTemp":{"value":"72","unit":1},"heatingAccessory":{"steeringWheel":0,"sideMirror":0,"rearWindow":0}},"engine":false,"doorLock":true,"doorStatus":{"frontLeft":0,"frontRight":0,"backLeft":0,"backRight":0,"trunk":0,"hood":0},"lowFuelLight":false,"evStatus":{"batteryCharge":false,"batteryStatus":79,"batteryPlugin":0,"remainChargeTime":[{"remainChargeType":1,"timeInterval":{"value":0,"unit":4}},{"remainChargeType":2,"timeInterval":{"value":0,"unit":4}},{"remainChargeType":3,"timeInterval":{"value":0,"unit":4}}],"drvDistance":[{"type":2,"rangeByFuel":{"evModeRange":{"value":213,"unit":3},"totalAvailableRange":{"value":213,"unit":3}}}],"syncDate":{"utc":"20211130165836","offset":-8},"targetSOC":[{"plugType":0,"targetSOClevel":80,"dte":{"type":2,"rangeByFuel":{"gasModeRange":{"value":0,"unit":3},"evModeRange":{"value":213,"unit":3},"totalAvailableRange":{"value":213,"unit":3}}}},{"plugType":1,"targetSOClevel":90,"dte":{"type":2,"rangeByFuel":{"gasModeRange":{"value":0,"unit":3},"evModeRange":{"value":213,"unit":3},"totalAvailableRange":{"value":213,"unit":3}}}}]},"ign3":true,"transCond":true,"tirePressure":{"all":0},"dateTime":{"utc":"20211130173341","offset":-8},"syncDate":{"utc":"20211130165836","offset":-8},"batteryStatus":{"stateOfCharge":87,"sensorStatus":0},"sleepMode":false,"lampWireStatus":{"headLamp":{},"stopLamp":{},"turnSignalLamp":{}},"windowStatus":{},"engineRuntime":{},"valetParkingMode":0}}}}
        """
        url = API_URL_BASE + "rems/rvs"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "requestType": 0  # value of 1 would return cached results instead of forcing update
        }
        await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )

    @request_with_active_session
    async def check_last_action_finished(
            self,
            vehicle_id: str,
    ) -> bool:
        url = API_URL_BASE + "cmm/gts"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        if self.last_action is None:
            _LOGGER.debug("no last action to check")
            return True
        body = {"xid": self.last_action["xid"]}
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        response_json = await response.json()
        finished = all(v == 0 for v in response_json["payload"].values())
        if finished:
            _LOGGER.debug("last action is finished")
            self.last_action = None
        return finished

    @request_with_active_session
    async def lock(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/door/lock"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "lock",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def unlock(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/door/unlock"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "unlock",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def start_climate(
            self,
            vehicle_id: str,
            set_temp: int,
            defrost: bool,
            climate: bool,
            heating: bool,
            driver_seat: SeatSettings | None = None,
            passenger_seat: SeatSettings | None = None,
            left_rear_seat: SeatSettings | None = None,
            right_rear_seat: SeatSettings | None = None,
    ):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/start"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "remoteClimate": {
                "airCtrl": climate,
                "airTemp": {
                    "unit": 1,
                    "value": str(set_temp),
                },
                "defrost": defrost,
                "heatingAccessory": {
                    "rearWindow": int(heating),
                    "sideMirror": int(heating),
                    "steeringWheel": int(heating),
                },
                "ignitionOnDuration": {
                    "unit": 4,
                    "value": 9,
                },
            }
        }
        if (
            driver_seat is not None
            or passenger_seat is not None
            or left_rear_seat is not None
            or right_rear_seat is not None
        ):
            body["remoteClimate"]["heatVentSeat"] = {
                "driverSeat": _seat_settings(driver_seat),
                "passengerSeat": _seat_settings(passenger_seat),
                "rearLeftSeat": _seat_settings(left_rear_seat),
                "rearRightSeat": _seat_settings(right_rear_seat),
                }
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "start_climate",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def stop_climate(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "rems/stop"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "stop_climate",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def start_charge(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/charge"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {"chargeRatio": 100}
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "start_charge",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def stop_charge(self, vehicle_id: str):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/cancel"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        response = await self._get_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
        )
        self.last_action = {
            "name": "stop_charge",
            "xid": response.headers["Xid"]
        }

    @request_with_active_session
    async def set_charge_limits(
            self,
            vehicle_id: str,
            ac_limit: int,
            dc_limit: int,
    ):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("{} still pending".format(self.last_action["name"]))
        url = API_URL_BASE + "evc/sts"
        vehicle_key = await self.find_vehicle_key(vehicle_id=vehicle_id)
        body = {
            "targetSOClist": [
                {
                    "plugType": 0,
                    "targetSOClevel": dc_limit,
                },
                {
                    "plugType": 1,
                    "targetSOClevel": ac_limit,
                },
            ]
        }
        response = await self._post_request_with_logging_and_errors_raised(
            vehicle_key=vehicle_key,
            url=url,
            json_body=body,
        )
        self.last_action = {
            "name": "set_charge_limits",
            "xid": response.headers["Xid"]
        }
