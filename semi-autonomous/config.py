import os
from openai import OpenAI

# Load .env without requiring python-dotenv
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
#


MODEL = "meta/llama-3.1-8b-instruct"
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ.get("NVIDIA_API_KEY", ""),
)

"""
MODEL = "gpt-4.1-mini"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
)
"""
# Factory layout (mm)
TRAVEL_Y = 200   # safe horizontal travel height
PICK_Y   = 82    # pick / place height

POSITIONS = {
    "source1":  55,
    "source2":  158,
    "process1": 450,
    "process2": 650,
    "output":   945,
}
HOME_X = POSITIONS["process1"]

# Modbus
MODBUS_HOST = "127.0.0.1"
MOVE_DELAY  = 3 # seconds per move segment; use 3.0 for real hardware
