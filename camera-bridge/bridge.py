"""
AutoSort IoT — Camera Bridge (Smartphone IP Webcam + Serial ESP32 + Cloud AI)
-----------------------------------------------------------------------------
Kịch bản hoạt động:
1. Lắng nghe cổng Serial từ ESP32 DevKit (cắm qua cáp Type-C).
2. Khi cảm biến IR LM393 phát hiện quả quất -> ESP32 gửi 'TRIGGER\n'.
3. Script này tự động lấy 1 ảnh snapshot JPEG từ app IP Webcam trên điện thoại.
4. Gửi ảnh lên Cloud Render FastAPI (POST /infer).
5. Nhận nhãn (GREEN, RIPE, REJECT) và gửi lệnh lại cho ESP32 ('SORT:GREEN\n', v.v.)
"""

import sys
import os
import time
import requests
import serial

# --- CẤU HÌNH HỆ THỐNG ---
SERIAL_PORT = "COM3"          # Đổi thành cổng COM của ESP32 (xem trong Device Manager)
BAUD_RATE = 115200

# URL snapshot từ app IP Webcam trên điện thoại (đảm bảo điện thoại và laptop cùng mạng Wi-Fi)
# Ví dụ: http://192.168.1.15:8080/shot.jpg
PHONE_IP_WEBCAM_URL = "http://192.168.1.15:8080/shot.jpg"

# Endpoint Cloud AI (FastAPI trên Render hoặc Localhost khi test)
CLOUD_INFER_URL = os.getenv("CLOUD_INFER_URL", "http://127.0.0.1:8000/infer")

def fetch_image_from_phone(url: str) -> bytes:
    """Tải 1 frame ảnh JPEG chất lượng cao từ app IP Webcam trên điện thoại."""
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.content

def call_cloud_ai(image_bytes: bytes, fruit_id: str = "F0001") -> str:
    """Gửi ảnh lên Cloud AI để nhận nhãn phân loại."""
    files = {
        "image": ("fruit.jpg", image_bytes, "image/jpeg")
    }
    data = {
        "fruit_id": fruit_id,
        "camera_id": "phone_cam01"
    }
    api_key = os.getenv("DEVICE_API_KEY", "")
    if not api_key:
        raise RuntimeError("Chưa cấu hình biến môi trường DEVICE_API_KEY cho Camera Bridge")
    resp = requests.post(CLOUD_INFER_URL, data=data, files=files, headers={"X-API-Key": api_key}, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    return result.get("label", "REJECT")

def main():
    print("=" * 60)
    print("   AUTOSORT IoT — SMARTPHONE CAMERA BRIDGE")
    print("=" * 60)
    print(f"[*] Cổng Serial ESP32: {SERIAL_PORT} (Baud: {BAUD_RATE})")
    print(f"[*] IP Webcam URL    : {PHONE_IP_WEBCAM_URL}")
    print(f"[*] Cloud AI URL     : {CLOUD_INFER_URL}")
    print("=" * 60)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  # Đợi kết nối Serial ổn định
        print(f"[+] Đã kết nối thành công với ESP32 trên cổng {SERIAL_PORT}!")
    except Exception as e:
        print(f"[!] Không thể mở cổng Serial {SERIAL_PORT}: {e}")
        print("[*] Chạy chế độ giả lập (Không có ESP32). Nhấn Enter để mô phỏng chụp...")
        ser = None

    fruit_counter = 0

    while True:
        try:
            line = ""
            if ser and ser.in_waiting > 0:
                line = ser.readline().decode("utf-8", errors="ignore").strip()

            # Khi nhận tín hiệu TRIGGER từ ESP32 hoặc nhấn Enter trong chế độ giả lập
            trigger = False
            if line == "TRIGGER":
                print("\n[>>] Nhận tín hiệu TRIGGER từ cảm biến IR trên ESP32!")
                trigger = True
            elif not ser:
                input("\n[TEST] Nhấn [Enter] để kích hoạt 1 lượt chụp...")
                trigger = True

            if trigger:
                fruit_counter += 1
                fruit_id = f"F{fruit_counter:04d}"
                print(f"[*] [Quả #{fruit_id}] Đang lấy ảnh từ camera điện thoại...")

                # 1. Lấy ảnh từ điện thoại
                try:
                    img_bytes = fetch_image_from_phone(PHONE_IP_WEBCAM_URL)
                    print(f"    -> Đã lấy ảnh JPEG thành công ({len(img_bytes)} bytes)")
                except Exception as ex:
                    print(f"    [!] Lỗi lấy ảnh từ điện thoại: {ex}")
                    label = "REJECT"
                    if ser:
                        ser.write(f"SORT:{label}\n".encode())
                    continue

                # 2. Gửi ảnh lên Cloud AI
                print(f"[*] [Quả #{fruit_id}] Đang gửi ảnh lên Cloud AI ({CLOUD_INFER_URL})...")
                try:
                    label = call_cloud_ai(img_bytes, fruit_id)
                    print(f"    [+] KẾT QUẢ AI: {label}")
                except Exception as ex:
                    print(f"    [!] Lỗi gọi Cloud AI: {ex}. Chuyển nhánh an toàn REJECT.")
                    label = "REJECT"

                # 3. Gửi lệnh xuống ESP32 điều khiển Servo gạt
                command = f"SORT:{label}\n"
                if ser:
                    ser.write(command.encode())
                    print(f"[<<] Đã gửi lệnh xuống ESP32: {command.strip()}")
                else:
                    print(f"[Mô phỏng] Gửi lệnh xuống ESP32: {command.strip()}")

            time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n[*] Đã dừng chương trình.")
            break
        except Exception as e:
            print(f"[!] Lỗi vòng lặp: {e}")
            time.sleep(1)

    if ser:
        ser.close()

if __name__ == "__main__":
    main()
