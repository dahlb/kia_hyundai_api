import logging

import time
import ssl
import certifi
from aiohttp import ClientSession, ClientResponse, ClientError

from .errors import AuthError, RateError
from .util import clean_dictionary_for_logging

_LOGGER = logging.getLogger(__name__)

BASE_URL: str = "api.telematics.hyundaiusa.com"
LOGIN_API: str = "https://" + BASE_URL + "/v2/ac/"
API_URL: str = "https://" + BASE_URL + "/ac/v2/"


def request_with_logging(func):
    """
    {'errorSubCode': 'IDM_401_4', 'functionName': 'remoteVehicleStatus', 'errorSubMessage': 'Feature disabled as it is not part of subscription.', 'errorMessage': 'Feature disabled as it is not part of subscription.', 'errorCode': 401}
    {'errorSubCode': 'HT_504', 'systemName': 'HATA', 'functionName': 'findMyCar', 'errorSubMessage': 'HATA findMyCar service failed while performing the operation FindMyCar', 'errorMessage': "We're sorry, but we could not complete your request. Please try again later.", 'errorCode': 504, 'serviceName': 'FindMyCar'}
    """

    async def request_with_logging_wrapper(*args, **kwargs) -> ClientResponse:
        url = kwargs["url"]
        json_body = kwargs.get("json_body")
        if json_body is not None:
            _LOGGER.debug(
                f"sending {url} request with {clean_dictionary_for_logging(json_body)}"
            )
        else:
            _LOGGER.debug(f"sending {url} request")
        response = await func(*args, **kwargs)
        _LOGGER.debug(
            f"response headers:{clean_dictionary_for_logging(response.headers)}"
        )
        try:
            response_json = await response.json()
            _LOGGER.debug(
                f"response json:{clean_dictionary_for_logging(response_json)}"
            )
        except RuntimeError:
            response_text = await response.text()
            _LOGGER.debug(f"response text:{response_text}")
        if "errorCode" in response_json:
            if (
                response_json["errorCode"] == 502
                and response_json.get("errorSubCode", "") == "HT_534"
            ):
                raise RateError
            if (
                response_json["errorCode"] == 502
                and response_json.get("errorSubCode", "") == "IDM_401_1"
            ):
                raise AuthError
            raise ClientError(f"api error:{response_json}")
        return response

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
            self.api_session = ClientSession(raise_for_status=False)
        else:
            self.api_session = client_session

        new_ssl_context = ssl.create_default_context(cafile=certifi.where())
        new_ssl_context.load_default_certs()
        new_ssl_context.check_hostname = True
        new_ssl_context.verify_mode = ssl.CERT_REQUIRED
        new_ssl_context.set_ciphers("ALL:@SECLEVEL=1")
        new_ssl_context.options = (
                ssl.OP_CIPHER_SERVER_PREFERENCE
        )
        self.ssl_context = new_ssl_context

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
        return await self.api_session.post(
            url=url,
            json=json_body,
            headers=headers,
            ssl=self.ssl_context
        )

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
        return await self.api_session.get(
            url=url,
            headers=headers,
            ssl=self.ssl_context
        )

    async def login(
        self, username: str, password: str, pin: str
    ) -> tuple[str, str, float]:
        """
        {"access_token":"","refresh_token":"","expires_in":"1799","username":"example@example.net"}
        """
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
        expires_in: float = float(response_json["expires_in"])
        return access_token, refresh_token, expires_in

    async def get_vehicles(
        self, username: str, pin: str, access_token: str
    ) -> dict[str, any]:
        """
        { "enrolledVehicleDetails": [ { "packageDetails": [ { "assetNumber": "1-229*******75", "displayCategory": "Connected Care", "packageId": "1-5MAJBS", "term": "36", "renewalDate": "20241014000000", "packageType": "Connected Care", "startDate": "20211014000000" }, { "assetNumber": "1-229*******35", "displayCategory": "Remote", "packageId": "1-5MAJLE", "term": "36", "renewalDate": "20241014000000", "packageType": "Remote", "startDate": "20211014000000" } ], "vehicleDetails": { "svrStatus": "NONE", "dynamicBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/sel/exterior/base/twilight-black/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "remoteStartWakeupDays": "seven", "enrollmentDate": "20211014", "trim": "SEL", "modelCode": "SANTA FE HYBRID", "ubiCapabilityInd": "Y", "vin": "VIN", "enrollmentId": "NUM", "sideMirrorHeatCapable": "YES", "ownersuccession": "1", "odometer": "63", "nickName": "2022 SANTA FE HYBRID", "defaultBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/sel/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "evStatus": "N", "modelYear": "2022", "steeringWheelHeatCapable": "YES", "defaultDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/sel/exterior/base/default/Dashboard-01.png", "vehicleGeneration": "2", "starttype": "BUTTON", "sapColorCode": "S3B", "bluelinkEnabled": true, "odometerUpdateDate": "20211016155605", "fatcAvailable": "Y", "color": "BLACK", "maintSyncCapable": "NO", "brandIndicator": "H", "deviceStatus": "ENROLLED", "mapProvider": "HERE", "generalBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/general/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "interiorColor": "NNB", "accessoryCode": "D-AUDIO2", "nadid": "nadid", "mit": "mit", "regid": "H00003854255VKM8S*******8299", "blueLink": "Y", "waypointInd": "NO", "billingInd": "YEARLY", "dynamicDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/sel/exterior/base/twilight-black/Dashboard-01.png", "imat": "7500", "additionalVehicleDetails": { "combinedHeatSettingsEnable": "Y", "temperatureRange": "false", "tmuSleepMode": "No", "enableHCAModule": "Y", "remoteLockConsentForRemoteStart": "No", "calendarVehicleSyncEnable": "No", "dkEnrolled": "N", "icpAvntCapable": "N", "icpAACapable": "N", "evAlarmOptionInfo": "No", "remoteLockConsentForRemoteStartCapable": "No", "mapOtaAccepted": "N", "icpCPCapable": "N", "dkCapable": "N", "enableValetActivate": "N" }, "transmissiontype": "AUTO", "bluelinkEnrolled": true, "rearWindowHeatCapable": "YES", "preferredDealerCode": "NJ045", "hmaModel": "TMHE", "series": "SANTA FE HYBRID", "enrollmentStatus": "ACTIVE", "generalDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2021/santa-fe-hybrid/general/exterior/base/default/Dashboard-01.png", "userprofilestatus": "NA" }, "roleDetails": [ { "roleCode": "SD", "roleName": "Secondary Driver" } ], "responseHeaderMap": {} } ], "addressDetails": [ { "city": "R****", "postalCode": "07***6", "type": "PRIMARY", "region": "NJ" } ], "user": { "accountId": "47***9", "firstName": "B*****", "lastName": "******", "loginId": "b*****@*****.com", "prefix": "Mr.", "additionalUserDetails": { "userProfileUpdate": "N", "timezoneOffset": -4, "appRating": "N", "timezoneAbbr": "EDT", "otaAcceptance": "N" }, "tncFlag": "Y", "idmId": "U0***SE", "userId": "b*****@*****.com", "notificationEmail": "b*****@*****.com", "email": "b*****@*****.com" } }
        {"enrolledVehicleDetails":[{"packageDetails":[{"assetNumber":"1-*","displayCategory":"Connected Care","packageId":"1-NZ1IOB","term":"1","renewalDate":"20211215000000","packageType":"Connected Care","startDate":"20210315000000"},{"assetNumber":"1-21339595491","displayCategory":"Remote","packageId":"1-NZ1ISZ","term":"1","renewalDate":"20211215000000","packageType":"Remote","startDate":"20210315000000"}],"driverDetails":[{"driverAddressDetails":[{"city":"CITY","postalCode":"ZIP","type":"PRIMARY","region":"NC"}],"driver":{"accountId":"NUM","firstName":"NAME","lastName":"NAME","phonesOptIn":[],"tncId":"20","loginId":"EMAIL,"preferredDealerCode":"NC072","driverUserProfile":"N","phones":[],"idmId":"idmId","userId":"EMAIL","email":"lysawinstonmines1@gmail.com"}}],"vehicleDetails":{"svrStatus":"NONE","dynamicBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/3.8/exterior/base/parisian-gray/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","remoteStartWakeupDays":"four","enrollmentDate":"20190207","svdDay":"06","trim":"3.8","modelCode":"GENESIS","ubiCapabilityInd":"Y","vin":"VIN","enrollmentId":"NUM","sideMirrorHeatCapable":"NO","ownersuccession":"1","odometer":"105088","nickName":"Phat boy","defaultBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/3.8/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","evStatus":"N","modelYear":"2015","steeringWheelHeatCapable":"NO","defaultDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/3.8/exterior/base/default/Dashboard-01.png","vehicleGeneration":"2","starttype":"BUTTON","silhouette":"https://owners.genesis.com/content/dam/genesis/us/mygenesis/image/Not_Avaliable.png","sapColorCode":"V6S","bluelinkEnabled":true,"odometerUpdateDate":"20211130052616","fatcAvailable":"Y","color":"GRAY","maintSyncCapable":"NO","brandIndicator":"H","deviceStatus":"ENROLLED","setOffPeak":"0","mapProvider":"HERE","generalBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/general/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","interiorColor":"RRY","accessoryCode":"AVN 4.5","nadid":"2343180194","mit":"3750","regid":"regid","blueLink":"Y","waypointInd":"NO","billingInd":"MONTHLY","dynamicDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/3.8/exterior/base/parisian-gray/Dashboard-01.png","imat":"imat","additionalVehicleDetails":{"combinedHeatSettingsEnable":"Y","temperatureRange":"false","tmuSleepMode":"No","enableHCAModule":"Y","remoteLockConsentForRemoteStart":"No","calendarVehicleSyncEnable":"No","tmuSleepInMin":140.28333333333333,"dkEnrolled":"N","icpAvntCapable":"N","icpAACapable":"N","enableRoadSideAssitanceAAAModule":"Y","evAlarmOptionInfo":"No","remoteLockConsentForRemoteStartCapable":"No","mapOtaAccepted":"N","icpCPCapable":"N","dkCapable":"N","enableValetActivate":"N","energyConsoleCapable":"No"},"transmissiontype":"AUTO","bluelinkEnrolled":true,"setChargeSchedule":"0","rearWindowHeatCapable":"NO","preferredDealerCode":"NC072","hmaModel":"DH","series":"GENESIS","enrollmentStatus":"ACTIVE","generalDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2015/genesis/general/exterior/base/default/Dashboard-01.png","userprofilestatus":"NA"},"roleDetails":[{"roleCode":"OWN","roleName":"OWNER"},{"roleCode":"SUB","roleName":"SUBSCRIBER"}],"responseHeaderMap":{}}],"addressDetails":[{"city":"CITY","street":"LOC","postalCode":"ZIP","type":"PRIMARY","region":"NC"}],"emergencyContacts":[{"firstName":"NAME","lastName":"NAME","contactId":"NUM","phones":[{"number":"PHONE","type":"mobile","order":1}],"relationship":"spouse","email":"EMAIL"}],"user":{"lastName":"NAME","phonesOptIn":[{"number":"NUM","primaryPhoneIndicator":"YES","fccOptIn":"YES","type":"MOBILE"}],"loginId":"EMAIL","prefix":"Mr.","tncFlag":"N","phones":[{"number":"PHONE","type":"cell","order":1}],"userId":"EMAIL","notificationEmail":"EMAIL","accountId":"NUM","firstName":"NAME","additionalUserDetails":{"userProfileUpdate":"N","timezoneOffset":-5,"appRating":"N","timezoneAbbr":"EST","otaAcceptance":"N","telematicsPhoneNumber":"PHONE"},"idmId":"AD7BDED7","email":"EMAIL"}}
        {"enrolledVehicleDetails":[{"packageDetails":[{"assetNumber":"1-12729429635","displayCategory":"Connected Care","packageId":"1-5MAJBS","term":"35","renewalDate":"20220815000000","packageType":"Connected Care","startDate":"20190816000000"},{"assetNumber":"1-12729429695","displayCategory":"Remote","packageId":"1-5MAJLE","term":"35","renewalDate":"20220815000000","packageType":"Remote","startDate":"20190816000000"}],"vehicleDetails":{"svrStatus":"NONE","dynamicBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/quartz-white/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","remoteStartWakeupDays":"four","enrollmentDate":"20190816","svdDay":"15","trim":"SEL","modelCode":"SONATA","ubiCapabilityInd":"Y","vin":"xxxxxx","enrollmentId":"xxxxx","sideMirrorHeatCapable":"YES","ownersuccession":"1","odometer":"8001","nickName":"2019 SONATA","defaultBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","evStatus":"N","modelYear":"2019","steeringWheelHeatCapable":"YES","defaultDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/default/Dashboard-01.png","vehicleGeneration":"2","starttype":"BUTTON","silhouette":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/sedan/Dashboard-01.svg","sapColorCode":"W8","bluelinkEnabled":true,"odometerUpdateDate":"20211216131200","fatcAvailable":"Y","color":"WHITE","maintSyncCapable":"NO","brandIndicator":"H","deviceStatus":"ENROLLED","setOffPeak":"0","mapProvider":"GOOGLE","generalBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/general/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","interiorColor":"BB","accessoryCode":"D-AUDIO","nadid":"xxxxx","mit":"7500","regid":"xxxxxxx","blueLink":"Y","waypointInd":"NO","billingInd":"YEARLY","dynamicDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/quartz-white/Dashboard-01.png","imat":"7500","additionalVehicleDetails":{"combinedHeatSettingsEnable":"Y","temperatureRange":"false","tmuSleepMode":"Yes","enableHCAModule":"Y","hyundaiHome":"N","remoteLockConsentForRemoteStart":"No","calendarVehicleSyncEnable":"No","dkEnrolled":"N","icpAvntCapable":"N","icpAACapable":"N","enableRoadSideAssitanceAAAModule":"Y","evAlarmOptionInfo":"No","remoteLockConsentForRemoteStartCapable":"No","mapOtaAccepted":"N","icpCPCapable":"N","dkCapable":"N","enableValetActivate":"N","energyConsoleCapable":"No"},"transmissiontype":"AUTO","bluelinkEnrolled":true,"setChargeSchedule":"0","rearWindowHeatCapable":"YES","preferredDealerCode":"NY120","hmaModel":"LF","series":"SONATA","enrollmentStatus":"ACTIVE","generalDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/general/exterior/base/default/Dashboard-01.png","userprofilestatus":"NA"},"roleDetails":[{"roleCode":"OWN","roleName":"OWNER"},{"roleCode":"SUB","roleName":"SUBSCRIBER"}],"responseHeaderMap":{}}],"addressDetails":[{"city":"XXXXXXXXXX","street":"XXXXXX","postalCode":"XXXXX","type":"PRIMARY","region":"NY"}],"user":{"accountId":"XXXXXX","firstName":"FirstName","lastName":"LastName","phonesOptIn":[{"number":"XXXXXXXXXXX","primaryPhoneIndicator":"YES","fccOptIn":"YES","type":"MOBILE"}],"loginId":"example@example.net","additionalUserDetails":{"userProfileUpdate":"Y","timezoneOffset":-5,"appRating":"N","timezoneAbbr":"EST","otaAcceptance":"N","telematicsPhoneNumber":"xxxxxxxxxxxx"},"tncFlag":"N","phones":[{"number":"XXXXXXXXXX","type":"cell","order":1}],"idmId": ”XXXXXXXX","userId":"example@example.net","notificationEmail":"example@example.net","email":"example@example.net"}}
        { "addressDetails": [ { "city": "Some City", "postalCode": "55555", "region": "GT", "street": "1 Main St", "type": "PRIMARY" } ], "enrolledVehicleDetails": [ { "packageDetails": [ { "assetNumber": "1-12345678901", "displayCategory": "Connected Care", "packageId": "1-5OOOOS", "packageType": "Connected Care", "renewalDate": "20991231000000", "startDate": "20991231000000", "term": "36" }, { "assetNumber": "1-23456789012", "displayCategory": "Guidance", "packageId": "1-5OOOOH", "packageType": "Guidance", "renewalDate": "20991231000000", "startDate": "20991231000000", "term": "36" }, { "assetNumber": "1-34567890123", "displayCategory": "Remote", "packageId": "1-5OOOOE", "packageType": "Remote", "renewalDate": "20991231000000", "startDate": "20991231000000", "term": "99" } ], "responseHeaderMap": {}, "roleDetails": [ { "roleCode": "OWN", "roleName": "OWNER" }, { "roleCode": "SUB", "roleName": "SUBSCRIBER" } ], "vehicleDetails": { "accessoryCode": "WAVN 5.0", "additionalVehicleDetails": { "calendarVehicleSyncEnable": "No", "combinedHeatSettingsEnable": "Y", "dkCapable": "N", "dkEnrolled": "N", "dynamicSOCText": "Use the slider above to set a charge limit. Charging will stop when this battery level is reached. The limit cannot be set lower than 50% This setting will override all other charge settings if set.", "enableHCAModule": "Y", "enableRoadSideAssitanceAAAModule": "Y", "enableValetActivate": "N", "energyConsoleCapable": "No", "evAlarmOptionInfo": "No", "hyundaiHome": "N", "icpAACapable": "N", "icpAvntCapable": "N", "icpCPCapable": "N", "mapOtaAccepted": "N", "maxTemp": 92, "minTemp": 62, "remoteLockConsentForRemoteStart": "No", "remoteLockConsentForRemoteStartCapable": "No", "targetSOCLevelMax": 100, "temperatureRange": "true", "tmuSleepInMin": 150.5, "tmuSleepMode": "No" }, "billingInd": "YEARLY", "blueLink": "Y", "bluelinkEnabled": true, "bluelinkEnrolled": true, "brandIndicator": "H", "color": "GRAY", "defaultBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/ev-limited/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "defaultDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/ev-limited/exterior/base/default/Dashboard-01.png", "deviceStatus": "ENROLLED", "dynamicBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/ev-limited/exterior/base/electric-shadow/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "dynamicDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/ev-limited/exterior/base/electric-shadow/Dashboard-01.png", "enrollmentDate": "20990101", "enrollmentId": "1234567", "enrollmentStatus": "ACTIVE", "enrollmentType": "INDIVIDUAL", "evStatus": "E", "fatcAvailable": "Y", "generalBurgerMenu": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/general/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png", "generalDashboard": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2020/ioniq-electric/general/exterior/base/default/Dashboard-01.png", "hmaModel": "AEEV", "imat": "5000", "interiorColor": "T9Y", "maintSyncCapable": "NO", "mapProvider": "HERE", "mit": "5000", "modelCode": "IONIQ ELECTRIC", "modelYear": "2020", "nadid": "1234567890", "nickName": "2020 IONIQ ELECTRIC", "odometer": "20", "odometerUpdateDate": "20211223080848", "ownersuccession": "1", "preferredDealerCode": "GR100", "rearWindowHeatCapable": "NO", "regid": "H00001234567ABCDE89DE0FG123456", "remoteStartWakeupDays": "seven", "sapColorCode": "USS", "series": "IONIQ ELECTRIC", "setOffPeak": "1", "sideMirrorHeatCapable": "NO", "silhouette": "https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/sedan/Dashboard-01.svg", "starttype": "KEY", "steeringWheelHeatCapable": "NO", "svdDay": "27", "svrStatus": "NONE", "targetSOCLevel": "50", "transmissiontype": "AUTO", "trim": "EV LIMITED", "ubiCapabilityInd": "Y", "userprofilestatus": "NA", "vehicleGeneration": "2", "vin": "ABCD12EF3GH456789", "waypointInd": "NO" } } ], "user": { "accountId": "1234567", "additionalUserDetails": { "appRating": "N", "otaAcceptance": "N", "telematicsPhoneNumber": "8005551212", "timezoneAbbr": "EST", "timezoneOffset": -5, "userProfileUpdate": "N" }, "email": "someone@example.com", "firstName": "Someone", "idmId": "A1BCD2EF", "lastName": "Somesurname", "loginId": "someone@example.com", "notificationEmail": "someone@example.com", "phones": [ { "number": "8005551212", "order": 1, "type": "cell" } ], "phonesOptIn": [ { "fccOptIn": "NO", "number": "8005551212", "primaryPhoneIndicator": "YES", "type": "MOBILE" } ], "tncFlag": "N", "userId": "someone@example.com" } }
        """
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
    ) -> dict[str, any]:
        """
        {'hataTID': 'xxxxxxxxxxxx', 'vehicleStatus': {'dateTime': '2021-12-19T15:42:13Z', 'acc': False, 'trunkOpen': False, 'doorLock': True, 'defrostStatus': 'false', 'transCond': True, 'doorLockStatus': 'true', 'doorOpen': {'frontRight': 0, 'frontLeft': 0, 'backLeft': 0, 'backRight': 0}, 'airCtrlOn': False, 'airTemp': {'unit': 0, 'hvacTempType': 0, 'value': '01H'}, 'battery': {'batSoc': 70, 'batState': 0, 'sjbDeliveryMode': 0}, 'vehicleLocation': {'coord': {'lon': -xxxxxx, 'type': 0, 'lat': xxxxxxx}}, 'ign3': False, 'ignitionStatus': 'false', 'lowFuelLight': False, 'sideBackWindowHeat': 0, 'dte': {'unit': 3, 'value': 263.0}, 'engine': False, 'defrost': False, 'hoodOpen': False, 'airConditionStatus': 'false', 'steerWheelHeat': 0, 'tirePressureLamp': {'tirePressureWarningLampRearLeft': 0, 'tirePressureWarningLampFrontLeft': 0, 'tirePressureWarningLampFrontRight': 0, 'tirePressureWarningLampAll': 0, 'tirePressureWarningLampRearRight': 0}, 'trunkOpenStatus': 'false'}} 2021-12-21 21:43:19 DEBUG (SyncWorker_5) [custom_components.kia_uvo.HyundaiBlueLinkAPIUSA] kia_uvo - Get Vehicles Response {"enrolledVehicleDetails":[{"packageDetails":[{"assetNumber":"1-XXXXX","displayCategory":"Connected Care","packageId":"1-XXXXXX","term":"35","renewalDate":"20220815000000","packageType":"Connected Care","startDate":"20190816000000"},{"assetNumber":"1-XXXXXX","displayCategory":"Remote","packageId":"1-XXXXXX","term":"35","renewalDate":"20220815000000","packageType":"Remote","startDate":"20190816000000"}],"vehicleDetails":{"svrStatus":"NONE","dynamicBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/quartz-white/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","remoteStartWakeupDays":"four","enrollmentDate":"20190816","svdDay":"15","trim":"SEL","modelCode":"SONATA","ubiCapabilityInd":"Y","vin":"XXXXXXXXXX","enrollmentId":"XXXXXX","sideMirrorHeatCapable":"YES","ownersuccession":"1","odometer":"8001","nickName":"2019 SONATA","defaultBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","evStatus":"N","modelYear":"2019","steeringWheelHeatCapable":"YES","defaultDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/default/Dashboard-01.png","vehicleGeneration":"2","starttype":"BUTTON","silhouette":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/sedan/Dashboard-01.svg","sapColorCode":"W8","bluelinkEnabled":true,"odometerUpdateDate":"20211216131200","fatcAvailable":"Y","color":"WHITE","maintSyncCapable":"NO","brandIndicator":"H","deviceStatus":"ENROLLED","setOffPeak":"0","mapProvider":"GOOGLE","generalBurgerMenu":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/general/exterior/base/default/Dashboard-01.png/jcr:content/renditions/cq5dam.thumbnail.105.68.png","interiorColor":"BB","accessoryCode":"D-AUDIO","nadid":"XXXXXXXXX","mit":"7500","regid":"XXXXXXXX","blueLink":"Y","waypointInd":"NO","billingInd":"YEARLY","dynamicDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/sel/exterior/base/quartz-white/Dashboard-01.png","imat":"7500","additionalVehicleDetails":{"combinedHeatSettingsEnable":"Y","temperatureRange":"false","tmuSleepMode":"Yes","enableHCAModule":"Y","hyundaiHome":"N","remoteLockConsentForRemoteStart":"No","calendarVehicleSyncEnable":"No","dkEnrolled":"N","icpAvntCapable":"N","icpAACapable":"N","enableRoadSideAssitanceAAAModule":"Y","evAlarmOptionInfo":"No","remoteLockConsentForRemoteStartCapable":"No","mapOtaAccepted":"N","icpCPCapable":"N","dkCapable":"N","enableValetActivate":"N","energyConsoleCapable":"No"},"transmissiontype":"AUTO","bluelinkEnrolled":true,"setChargeSchedule":"0","rearWindowHeatCapable":"YES","preferredDealerCode":"XXXXXX","hmaModel":"LF","series":"SONATA","enrollmentStatus":"ACTIVE","generalDashboard":"https://owners.hyundaiusa.com/content/dam/hyundai/us/myhyundai/image/2019/sonata/general/exterior/base/default/Dashboard-01.png","userprofilestatus":"NA"},"roleDetails":[{"roleCode":"OWN","roleName":"OWNER"},{"roleCode":"SUB","roleName":"SUBSCRIBER"}],"responseHeaderMap":{}}],"addressDetails":[{"city":"XXXXXXXXXXXX","street":"XXXXXXXXX","postalCode":"XXXXX","type":"PRIMARY","region":"NY"}],"user":{"accountId":"XXXXXXX","firstName":"FirstName","lastName":"LastName","phonesOptIn":[{"number":"XXXXXXXXXX","primaryPhoneIndicator":"YES","fccOptIn":"YES","type":"MOBILE"}],"loginId":"example@example.net","additionalUserDetails":{"userProfileUpdate":"Y","timezoneOffset":-5,"appRating":"N","timezoneAbbr":"EST","otaAcceptance":"N","telematicsPhoneNumber":"XXXXXXX"},"tncFlag":"N","phones":[{"number":"XXXXXXX","type":"cell","order":1}],"idmId":"XXXXXXX","userId":"example@example.net","notificationEmail":"example@example.net","email":"example@example.net"}}
        """
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
        return response_json

    async def get_location(
        self, username: str, pin: str, access_token: str, vehicle_vin: str
    ) -> dict[str, any]:
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
    ) -> dict[str, any]:
        url = API_URL + "rcs/rdo/off"
        extra_headers = {"registrationId": vehicle_regid, "APPCLOUD-VIN": vehicle_vin}
        json_body = {"userName": username, "vin": vehicle_vin}
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
    ) -> dict[str, any]:
        url = API_URL + "rcs/rdo/on"
        extra_headers = {"APPCLOUD-VIN": vehicle_vin}
        json_body = {"userName": username, "vin": vehicle_vin}
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
    ) -> dict[str, any]:
        url = API_URL + "rcs/rsc/start"
        json_body = {
            "Ims": 0,
            "airCtrl": int(climate),
            "airTemp": {"unit": 1, "value": set_temp},
            "defrost": defrost,
            "heating1": int(heating),
            "igniOnDuration": duration,
            "username": username,
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
    ) -> dict[str, any]:
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
