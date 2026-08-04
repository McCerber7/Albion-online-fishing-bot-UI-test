import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "water_region": {"top": 220, "left": 500, "width": 900, "height": 400},
    "bar_region": {"top": 830, "left": 597, "width": 250, "height": 30},
    "cast_power_time": 0.55,
    "auto_cast_power": True,
    "cast_point": {"x": 0, "y": 0, "use_custom": False},
    "hsv": {
        "lower_float": [0, 100, 100],
        "upper_float": [10, 255, 255],
        "lower_zone": [35, 100, 100],
        "upper_zone": [85, 255, 255]
    },
    "auto_hsv": {
        "h_tol": 12,
        "s_tol": 60,
        "v_tol": 60,
        "adaptive_float": False,
        "adaptive_zone": False
    },
    "minigame": {
        "target_pct": 56,
        "danger_left_pct": 25,
        "danger_right_pct": 70
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                if "auto_hsv" not in cfg:
                    cfg["auto_hsv"] = DEFAULT_CONFIG["auto_hsv"]
                if "minigame" not in cfg:
                    cfg["minigame"] = DEFAULT_CONFIG["minigame"]
                if "cast_point" not in cfg:
                    cfg["cast_point"] = DEFAULT_CONFIG["cast_point"]
                if "auto_cast_power" not in cfg:
                    cfg["auto_cast_power"] = DEFAULT_CONFIG["auto_cast_power"]
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)