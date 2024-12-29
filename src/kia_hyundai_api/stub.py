# run with "python3 src/kia_hyundai_api/stub.py"
import logging
import asyncio

from getpass import getpass
from pathlib import Path
import sys

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.kia_hyundai_api import UsKia

logger = logging.getLogger("src.kia_hyundai_api")
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


async def testing():
    username = input("Username: ")
    password = getpass()
    api: UsKia = UsKia(username=username, password=password)
    try:
        await api.get_vehicles()
        vehicle_id = api.vehicles[0]["vehicleIdentifier"]
        await api.lock(vehicle_id=vehicle_id)
        while await api.check_last_action_finished(vehicle_id=vehicle_id) is False:
            await asyncio.sleep(1)
        await api.unlock(vehicle_id=vehicle_id)
    finally:
        await api.api_session.close()


asyncio.run(testing(), debug=True)
