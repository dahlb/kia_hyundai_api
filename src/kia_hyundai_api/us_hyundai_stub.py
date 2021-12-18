# run with "python3 src/kia_hyundai_api/us_hyundai_stub.py"
import logging
import asyncio

from pathlib import Path
import sys
path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.kia_hyundai_api import UsHyundai

logger = logging.getLogger("kia_hyundai_api.us_hyundai")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing():
    api = UsHyundai()
    username = "USER"
    pin = "PIN"
    access_token, = await api.login(username=username, password="pass", pin=pin)
    vehicles = await api.get_vehicles(username=username, pin=pin, access_token=access_token)
    vin = vehicles["enrolledVehicleDetails"][0]["vin"]
    # regid = vehicles["enrolledVehicleDetails"][0]["regid"]
    await api.get_cached_vehicle_status(username=username, pin=pin, access_token=access_token, vehicle_vin=vin)
    await api.get_location(username=username, pin=pin, access_token=access_token, vehicle_vin=vin)

asyncio.run(testing())
