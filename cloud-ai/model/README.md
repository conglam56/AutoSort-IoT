# Model v1 dùng thử tích hợp

Thư mục chứa `best.onnx` và `classes.json` để Docker nạp detector thật thay
cho MOCK. Phiên bản `autosort-yolo11n-detect-v1`, YOLO11n ba lớp, ảnh 320px,
FP32, opset 17. Ánh xạ: GREEN=0, RIPE=1, REJECT=2. Ngưỡng giữ nguyên 0,7.

**Đây là model thử nghiệm để kiểm tra điện thoại/cloud/dashboard, chưa xác nhận
chất lượng phân loại trên trạm.** Có 3/15 ảnh REJECT một quả trong test bị cho
qua thành GREEN/RIPE. LOW_CONFIDENCE được trả REJECT để xử lý trường hợp không
chắc chắn; không coi các trường hợp này là phát hiện được khuyết tật.

`SHA256SUMS` ghi checksum của graph và metadata đã kiểm tra parity. Không đổi
ngưỡng theo ba ảnh test. Xem [kết quả](../../docs/AI_DETECTION_RESULTS.md) và
[quy trình tái lập](../../docs/AI_DETECTION_TRAINING.md). Nguồn dữ liệu được ghi
trong `ATTRIBUTION.txt`; không đưa checkpoint PyTorch hoặc bộ train vào image.

Sau deploy, `/health` phải có `mode=onnx`, `model_ready=true`, `task=detect` và
đúng model_version. Bridge chỉ thử có điều khiển phần cứng sau khi nhóm xác nhận
camera, vùng chụp, firmware và hành vi xử lý lỗi; dùng `--manual` để thử ảnh trước.
