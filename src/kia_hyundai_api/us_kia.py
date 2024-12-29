import logging
import asyncio

from datetime import datetime
import random
import string
import secrets
import ssl
import certifi

import pytz
import time

from functools import partial
from aiohttp import ClientSession, ClientResponse

from .errors import AuthError, ActionAlreadyInProgressError
from .const import API_URL_BASE, API_URL_HOST
from .util_http import request_with_logging, request_with_active_session

_LOGGER = logging.getLogger(__name__)


class UsKia:
    _ssl_context = None
    session_id: str | None = None
    vehicles: list[dict] | None = None
    last_action = None

    def __init__(self, username: str, password: str, client_session: ClientSession = None):
        # Randomly generate a plausible device id on startup
        self.device_id = (
            "".join(
                random.choice(string.ascii_letters + string.digits) for _ in range(22)
            )
            + ":"
            + secrets.token_urlsafe(105)
        )
        self.username = username
        self.password = password
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

    def _api_headers(self, vehicle_key: str = None) -> dict:
        headers = {
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US,en;q=0.9",
            "apptype": "L",
            "appversion": "6.0.1",
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
            "user-agent": "okhttp/3.12.1",
            "deviceid": self.device_id,
            "date": datetime.now(tz=pytz.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if self.session_id is not None:
            headers["sid"] = self.session_id
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

    async def login(self):
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
        self.session_id = response.headers.get("sid")
        if not self.session_id:
            response_text = await response.text()
            raise AuthError(
                f"no session id returned in login. Response: {response_text} headers {response.headers} cookies {response.cookies}"
            )
        _LOGGER.debug(f"got session id {self.session_id}")

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
        return response_json["payload"]

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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
    ):
        if await self.check_last_action_finished(vehicle_id=vehicle_id) is False:
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
            raise ActionAlreadyInProgressError("%s still pending" % self.last_action["name"])
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
