# AutoSort IoT — Web Monitoring Dashboard

Giao diện Web giám sát băng chuyền phân loại quả quất bằng trí tuệ nhân tạo (YOLO11 ONNX) và vi điều khiển ESP32.

---

## 1. Cấu trúc Thư mục

```text
dashboard/
├── index.html        # Giao diện chính (HTML5 Semantic)
├── style.css         # Bộ phong cách công nghiệp Dark Slate & Semantic Colors
├── app.js            # Logic ứng dụng, Canvas Donut Chart, Session Manager & CSV Export
├── samples/          # Ảnh mẫu quất xanh, quất chín, quả loại phục vụ hiển thị & giả lập
└── PLAN.md           # Kế hoạch kiến trúc và thiết kế chi tiết
```

---

## 2. Hướng dẫn Khởi chạy

### Cách 1: Chạy trực tiếp (Độc lập / Không cần cài đặt)
1. Dùng extension **Live Server** trong VS Code hoặc mở trực tiếp file `dashboard/index.html` trên trình duyệt (Chrome, Edge, Firefox).
2. Khi không có kết nối với server FastAPI, web tự động hoạt động ở chế độ **Giả lập (Simulation Mode)**:
   - Có sẵn dữ liệu mẫu cho các phiên.
   - Nhấn nút **⚡ Thử Quả Mới** ở góc trên bên phải để mô phỏng một lượt nhận diện quả quất với ảnh thật và số liệu thời gian thực.
   - Nhấn nút **➕ Phiên Mới** để tạo một đợt chạy mới.

### Cách 2: Chạy tích hợp nguyên khối cùng Cloud AI (FastAPI)
Dashboard đã được tích hợp (mount) trực tiếp vào FastAPI server:
1. Mở PowerShell tại thư mục `cloud-ai`:
   ```powershell
   cd "d:\AutoSort IoT\cloud-ai"
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload
   ```
2. Mở trình duyệt và truy cập:
   ```text
   http://127.0.0.1:8000/dashboard/
   ```
3. Mỗi khi `camera-bridge/bridge.py` hoặc API `/infer` xử lý 1 quả quất, Dashboard sẽ tự động cập nhật kết quả vào phiên làm việc hiện tại.

---

## 3. Các Tính Năng Nổi Bật

### Tab 1: Giám Sát Trực Tiếp (Live Monitor)
- **Live Camera Inspection Feed:** Hiển thị ảnh chụp JPEG sắc nét, nhãn phân loại AI (`RIPE`, `GREEN`, `REJECT`), thanh đo độ tin cậy kèm vạch ngưỡng 70%, thời gian chụp chi tiết và độ trễ suy luận AI.
- **Biểu đồ Phân Bố Tỉ Lệ (Donut Chart):** Tổng hợp riêng cho phiên làm việc hiện tại (tính từ lúc bật máy/tạo phiên).
- **Dải 10 Quả Gần Nhất (Recent Stream):** Theo dõi nhanh các quả vừa đi qua camera.

### Tab 2: Lịch Sử Phiên & KPI (Session Archives)
- **Bộ chọn Phiên (Session Selector):** Cho phép xem lại chi tiết bất kỳ đợt chạy nào trong quá khứ kèm ngày giờ và tổng quả.
- **Thẻ KPI Counters riêng biệt:** Hiển thị tổng quả, số lượng & tỉ lệ % quất xanh, quất chín, quả loại của riêng phiên được chọn.
- **Bảng Nhật Ký Chi Tiết:** Tìm kiếm theo mã quả (`#F0001`), lọc theo nhãn (`GREEN`, `RIPE`, `REJECT`).
- **Xuất Báo Cáo CSV:** Tải xuống file CSV chuẩn UTF-8 (mở được trên Excel không lỗi tiếng Việt) phục vụ chèn vào báo cáo thực nghiệm đồ án.
