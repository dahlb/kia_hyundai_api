import logging

from pathlib import Path
import sys
path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.kia_hyundai_api.ca import Ca

logger = logging.getLogger("kia_hyundai_api.ca")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing(ca_api: Ca):
    pin = "PIN"
    login_response = await ca_api.login("user", "pass")
    access_token = login_response["access_token"]
    vehicles = await ca_api.get_vehicles(access_token)
    vehicle_id = vehicles["vehicles"][0]["vehicleId"]
    await ca_api.get_cached_vehicle_status(access_token=access_token, vehicle_id=vehicle_id)
    await ca_api.get_next_service_status(access_token=access_token, vehicle_id=vehicle_id)
    pin_token = await ca_api.get_pin_token(access_token=access_token, pin=pin)
    await ca_api.get_location(access_token=access_token, vehicle_id=vehicle_id, pin=pin, pin_token=pin_token)
