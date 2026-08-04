import time
import ctypes
import math
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from vision import Vision
from input_handler import InputHandler

try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass


class BotWorker(QThread):
    water_frame_ready = pyqtSignal(np.ndarray)
    bar_frame_ready = pyqtSignal(np.ndarray)
    mask_float_ready = pyqtSignal(np.ndarray)
    mask_zone_ready = pyqtSignal(np.ndarray)
    log_ready = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    hsv_updated = pyqtSignal()

    STATE_PAUSED = -1
    STATE_CASTING = 0
    STATE_FISHING = 1
    STATE_MINIGAME = 2

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.vision = Vision()
        self.running = True
        self.current_state = self.STATE_PAUSED

    def toggle_active(self):
        if self.current_state == self.STATE_PAUSED:
            self.current_state = self.STATE_CASTING
            self.status_changed.emit("АКТИВЕН (Заброс)")
            self.log_ready.emit("[⚡ СТАРТ] Бот запущен!")
        else:
            self.current_state = self.STATE_PAUSED
            InputHandler.hold_mouse_end()
            self.status_changed.emit("ПАУЗА")
            self.log_ready.emit("[💤 ПАУЗА] Бот остановлен!")

    def adapt_hsv_range(self, hsv_crop, current_lower, current_upper):
        mean_hsv = cv2.mean(hsv_crop)[:3]
        mean_s, mean_v = mean_hsv[1], mean_hsv[2]

        s_tol = self.config.get("auto_hsv", {}).get("s_tol", 60)
        v_tol = self.config.get("auto_hsv", {}).get("v_tol", 60)

        new_s_min = max(0, int(mean_s - s_tol))
        new_s_max = min(255, int(mean_s + s_tol))
        new_v_min = max(0, int(mean_v - v_tol))
        new_v_max = min(255, int(mean_v + v_tol))

        lower = np.copy(current_lower)
        upper = np.copy(current_upper)

        lower[1] = int(0.85 * lower[1] + 0.15 * new_s_min)
        upper[1] = int(0.85 * upper[1] + 0.15 * new_s_max)
        lower[2] = int(0.85 * lower[2] + 0.15 * new_v_min)
        upper[2] = int(0.85 * upper[2] + 0.15 * new_v_max)

        return lower, upper

    def run(self):
        is_float_tracked = False
        lost_frames_counter = 0
        REQUIRED_LOST_FRAMES = 3
        minigame_lost_frames = 0
        fishing_start_time = time.time()

        ui_frame_counter = 0
        current_lmb_state = False

        while self.running:
            water_region = self.config["water_region"]
            bar_region = self.config["bar_region"]
            cast_power_time = self.config.get("cast_power_time", 0.55)
            auto_cast_power = self.config.get("auto_cast_power", True)
            hsv_cfg = self.config["hsv"]
            auto_cfg = self.config.get("auto_hsv", {})
            mg_cfg = self.config.get("minigame", {"target_pct": 58, "danger_left_pct": 25, "danger_right_pct": 75})

            lower_float = np.array(hsv_cfg["lower_float"])
            upper_float = np.array(hsv_cfg["upper_float"])
            lower_zone = np.array(hsv_cfg["lower_zone"])
            upper_zone = np.array(hsv_cfg["upper_zone"])

            cast_cfg = self.config.get("cast_point", {})
            if cast_cfg.get("use_custom", False) and cast_cfg.get("x", 0) > 0:
                water_center_x = cast_cfg["x"]
                water_center_y = cast_cfg["y"]
            else:
                water_center_x = water_region["left"] + water_region["width"] // 2
                water_center_y = water_region["top"] + water_region["height"] // 2

            # 📏 АВТО-РАСЧЕТ СИЛЫ (ВРЕМЕНИ ЗАЖАТИЯ ЛКМ) ПО РАССРОЯНИЮ
            if auto_cast_power:
                # В Albion персонаж находится примерно в нижней центральной части зоны воды
                player_base_x = water_region["left"] + water_region["width"] // 2
                player_base_y = water_region["top"] + water_region["height"] + 50

                dist_px = math.hypot(water_center_x - player_base_x, water_center_y - player_base_y)
                # Динамическая интерполяция: от 0.22с (под ноги) до 1.05с (на максимум)
                max_expected_dist = max(300.0, float(water_region["height"] + water_region["width"] // 2))
                calc_time = 0.20 + (dist_px / max_expected_dist) * 0.75
                cast_power_time = round(max(0.18, min(1.15, calc_time)), 2)

            ui_frame_counter += 1
            ui_divisor = 6 if self.current_state == self.STATE_MINIGAME else 3
            should_update_ui = (ui_frame_counter % ui_divisor == 0)

            # === СОСТОЯНИЕ: ПАУЗА ===
            if self.current_state == self.STATE_PAUSED:
                if should_update_ui:
                    water_frame = self.vision.capture_screen(water_region)
                    bar_frame = self.vision.capture_screen(bar_region)

                    hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                    mask_float = cv2.inRange(hsv_water, lower_float, upper_float)

                    hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
                    mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)

                    self.mask_float_ready.emit(mask_float)
                    self.mask_zone_ready.emit(mask_zone)

                    cv2.putText(water_frame, "PAUSED", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    cv2.putText(bar_frame, "PAUSED", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                    self.water_frame_ready.emit(water_frame)
                    self.bar_frame_ready.emit(bar_frame)

                self.msleep(50)
                continue

            # === СОСТОЯНИЕ 0: АВТО-ЗАБРОС УДОЧКИ ===
            elif self.current_state == self.STATE_CASTING:
                self.log_ready.emit(
                    f"[ACTION] Замахиваемся ({cast_power_time}s) в точку ({water_center_x}, {water_center_y})...")
                InputHandler.hold_mouse_start(water_center_x, water_center_y)
                current_lmb_state = True
                time.sleep(cast_power_time)
                InputHandler.hold_mouse_end()
                current_lmb_state = False

                self.log_ready.emit("[ACTION] Ожидаем падения поплавка...")
                time.sleep(2.2)

                is_float_tracked = False
                lost_frames_counter = 0
                fishing_start_time = time.time()
                self.current_state = self.STATE_FISHING
                self.status_changed.emit("СЛЕЖКА ЗА ПОПЛАВКОМ")

            # === СОСТОЯНИЕ 1: СЛЕЖКА ЗА ПОПЛАВКОМ ===
            elif self.current_state == self.STATE_FISHING:
                water_frame = self.vision.capture_screen(water_region)
                center, bbox = self.vision.find_color_object(water_frame, lower_float, upper_float, is_float=True)

                elapsed_time = time.time() - fishing_start_time

                if not is_float_tracked and elapsed_time > 4.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Поплавок не обнаружен после заброса! Перезабрасываем...")
                    time.sleep(0.5)
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("ЗАБРОС")
                    continue

                if elapsed_time > 25.0:
                    self.log_ready.emit("[⚠️ TIMEOUT] Превышено время ожидания поклёвки (25с)! Перезабрасываем...")
                    time.sleep(0.5)
                    self.current_state = self.STATE_CASTING
                    self.status_changed.emit("ЗАБРОС")
                    continue

                if center and bbox:
                    lost_frames_counter = 0
                    if not is_float_tracked:
                        self.log_ready.emit("[FISHING] Поплавок найден, следим...")
                    is_float_tracked = True

                    if auto_cfg.get("adaptive_float", False):
                        x, y, w, h = bbox
                        hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                        crop = hsv_water[y:y + h, x:x + w]
                        if crop.size > 0:
                            n_low, n_up = self.adapt_hsv_range(crop, lower_float, upper_float)
                            self.config["hsv"]["lower_float"] = n_low.tolist()
                            self.config["hsv"]["upper_float"] = n_up.tolist()
                            if ui_frame_counter % 30 == 0:
                                self.hsv_updated.emit()

                    if should_update_ui:
                        x, y, w, h = bbox
                        cv2.rectangle(water_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                        cv2.circle(water_frame, center, 4, (0, 0, 255), -1)
                else:
                    if is_float_tracked:
                        lost_frames_counter += 1
                        if lost_frames_counter >= REQUIRED_LOST_FRAMES:
                            self.log_ready.emit("[🔥 TRIGGER] ПОКЛЕВКА! Подсекаем!")
                            InputHandler.click_mouse(water_center_x, water_center_y)

                            is_float_tracked = False
                            lost_frames_counter = 0
                            minigame_lost_frames = 0
                            self.current_state = self.STATE_MINIGAME
                            self.status_changed.emit("МИНИ-ИГРА")

                if should_update_ui:
                    hsv_water = cv2.cvtColor(water_frame, cv2.COLOR_BGR2HSV)
                    mask_float = cv2.inRange(hsv_water, lower_float, upper_float)
                    self.mask_float_ready.emit(mask_float)

                    cv2.putText(water_frame, f"FISHING... ({int(elapsed_time)}s)", (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0, 255, 0), 2)
                    self.water_frame_ready.emit(water_frame)

                self.msleep(1)

            # === СОСТОЯНИЕ 2: МИНИ-ИГРА (ОБЪЕДИНЕНИЕ ПОЛОВИНОК И ТРЕКИНГ) ===
            elif self.current_state == self.STATE_MINIGAME:
                bar_frame = self.vision.capture_screen(bar_region)
                hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
                mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)

                # 🌉 МОСТИК: Соединяем левую и правую половинки шкалы через щель поплавка
                kernel = np.ones((5, 21), np.uint8)
                mask_zone_closed = cv2.morphologyEx(mask_zone, cv2.MORPH_CLOSE, kernel)

                contours_zone, _ = cv2.findContours(mask_zone_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                zx, zy, zw, zh = 0, 0, 0, 0
                is_valid_bar = False

                if contours_zone:
                    for cnt in sorted(contours_zone, key=cv2.contourArea, reverse=True):
                        area = cv2.contourArea(cnt)
                        x, y, w, h = cv2.boundingRect(cnt)

                        if h > 0 and w >= 180 and h >= 12:
                            aspect_ratio = float(w) / h
                            if 4.5 <= aspect_ratio <= 14.0:
                                zx, zy, zw, zh = x, y, w, h
                                is_valid_bar = True
                                break

                if is_valid_bar:
                    minigame_lost_frames = 0

                    if auto_cfg.get("adaptive_zone", False):
                        crop = hsv_bar[zy:zy + zh, zx:zx + zw]
                        if crop.size > 0:
                            n_low, n_up = self.adapt_hsv_range(crop, lower_zone, upper_zone)
                            self.config["hsv"]["lower_zone"] = n_low.tolist()
                            self.config["hsv"]["upper_zone"] = n_up.tolist()
                            if ui_frame_counter % 30 == 0:
                                self.hsv_updated.emit()

                    # 🎯 Ищем бегунок в исходной маске внутри границ объединенной шкалы
                    float_x = None
                    if zw > 0:
                        x_start = max(0, zx - 30)
                        x_end = min(bar_region["width"], zx + zw + 30)

                        zone_roi_mask = mask_zone[:, x_start:x_end]
                        mask_inv_roi = cv2.bitwise_not(zone_roi_mask)

                        contours_inv, _ = cv2.findContours(mask_inv_roi, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                        for cnt in contours_inv:
                            area = cv2.contourArea(cnt)
                            if 5 < area < 400:
                                fx, fy, fw, fh = cv2.boundingRect(cnt)
                                if zy - 10 <= fy <= zy + zh + 10:
                                    float_x = x_start + fx + fw // 2
                                    break

                if is_valid_bar:
                    minigame_lost_frames = 0

                    if auto_cfg.get("adaptive_zone", False):
                        crop = hsv_bar[zy:zy + zh, zx:zx + zw]
                        if crop.size > 0:
                            n_low, n_up = self.adapt_hsv_range(crop, lower_zone, upper_zone)
                            self.config["hsv"]["lower_zone"] = n_low.tolist()
                            self.config["hsv"]["upper_zone"] = n_up.tolist()
                            if ui_frame_counter % 30 == 0:
                                self.hsv_updated.emit()

                    float_x = None
                    if zw > 0:
                        x_start = max(0, zx - 50)
                        x_end = min(bar_region["width"], zx + zw + 50)

                        zone_roi_mask = mask_zone[:, x_start:x_end]
                        mask_inv_roi = cv2.bitwise_not(zone_roi_mask)

                        contours_inv, _ = cv2.findContours(mask_inv_roi, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                        for cnt in contours_inv:
                            area = cv2.contourArea(cnt)
                            if 8 < area < 350:
                                fx, fy, fw, fh = cv2.boundingRect(cnt)
                                if zy - 10 <= fy <= zy + zh + 10:
                                    float_x = x_start + fx + fw // 2
                                    break

                    t_pct = mg_cfg.get("target_pct", 58) / 100.0
                    l_pct = mg_cfg.get("danger_left_pct", 25) / 100.0
                    r_pct = mg_cfg.get("danger_right_pct", 75) / 100.0

                    target_x = zx + int(zw * t_pct)
                    danger_left_bound = zx + int(zw * l_pct)
                    danger_right_bound = zx + int(zw * r_pct)

                    if float_x is not None and zw > 0:
                        if float_x < danger_left_bound:
                            if not current_lmb_state:
                                InputHandler.hold_mouse_start()
                                current_lmb_state = True
                        elif float_x > danger_right_bound:
                            if current_lmb_state:
                                InputHandler.hold_mouse_end()
                                current_lmb_state = False
                        else:
                            if float_x < target_x - 3:
                                if not current_lmb_state:
                                    InputHandler.hold_mouse_start()
                                    current_lmb_state = True
                            elif float_x > target_x + 3:
                                if current_lmb_state:
                                    InputHandler.hold_mouse_end()
                                    current_lmb_state = False

                    elif zw > 0:
                        if not current_lmb_state:
                            InputHandler.hold_mouse_start()
                            current_lmb_state = True

                    if should_update_ui and zw > 0:
                        cv2.rectangle(bar_frame, (zx, zy), (zx + zw, zy + zh), (0, 255, 0), 2)
                        target_draw_x = zx + int(zw * t_pct)
                        cv2.line(bar_frame, (target_draw_x, zy), (target_draw_x, zy + zh), (255, 255, 0), 2)

                        if float_x is not None:
                            cv2.circle(bar_frame, (float_x, zy + zh // 2), 5, (0, 0, 255), -1)

                else:
                    minigame_lost_frames += 1
                    if minigame_lost_frames >= 80:
                        self.log_ready.emit("[✔ SYSTEM] Рыба вытащена!")
                        if current_lmb_state:
                            InputHandler.hold_mouse_end()
                            current_lmb_state = False

                        time.sleep(2.0)
                        self.current_state = self.STATE_CASTING
                        self.status_changed.emit("ЗАБРОС")

                if should_update_ui:
                    self.mask_zone_ready.emit(mask_zone)
                    cv2.putText(bar_frame, "MINIGAME...", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    self.bar_frame_ready.emit(bar_frame)

                self.msleep(0)

    def stop(self):
        self.running = False
        InputHandler.hold_mouse_end()
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        self.wait()