# run with "python3 src/kia_hyundai_api/us_kia_stub.py"
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
    api: UsKia = UsKia()
    username = input("Username: ")
    password = getpass()
    try:
        session_id = await api.login(username=username, password=password)
        vehicles = await api.get_vehicles(session_id=session_id)
        identifier = vehicles["vehicleSummary"][0]["vehicleIdentifier"]
        key = vehicles["vehicleSummary"][0]["vehicleKey"]
        await api.get_cached_vehicle_status(session_id=session_id, vehicle_key=key)
        await api.lock(session_id=session_id, vehicle_key=key)
    finally:
        await api.cleanup_client_session()


asyncio.run(testing())
