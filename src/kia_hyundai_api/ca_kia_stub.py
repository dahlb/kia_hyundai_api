# run with "python3 src/kia_hyundai_api/ca_kia_stub.py"
import asyncio

from pathlib import Path
import sys
path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
from src.kia_hyundai_api.ca_stub import testing
from src.kia_hyundai_api import CaKia

asyncio.run(testing(CaKia()))
