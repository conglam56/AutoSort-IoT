# Detector V2-640 dùng thử trên cloud

Bản phát hành `autosort-yolo11n-detect-v2-13714d07b0-640` dùng checkpoint V2
`autosort-v2-3classes-13714d07b0`, không phải V2.1. YOLO11n detection, input
640×640, FP32, ONNX opset 17. Nhãn: GREEN=0, RIPE=1, REJECT=2.

Checkpoint PyTorch nguồn SHA256:
`acdf830cafbfa8afeef04f8b1a99a1374348462ed4f6a5e1f0befd3a3810e618`.
Graph và metadata có checksum trong `SHA256SUMS`. Đã kiểm tra parity PyTorch /
ONNX trên 15 ảnh; parity kiểm tra tính nhất quán khi chuyển đổi, không chứng
minh độ chính xác phân loại. Attribution của GREEN v1 và RIPE/REJECT v2 được
lưu trong `ATTRIBUTION.txt`. Không đưa checkpoint PyTorch hoặc bộ train vào image.

## Quy tắc suy luận

Giữ `highest_confidence`: chọn nhãn có điểm cao nhất trong các khung hợp lệ
trong ROI. Không áp ngưỡng quyết định 70% và không ưu tiên REJECT. Bộ lọc phát
hiện 25% và NMS IoU 0.7 giữ nguyên. `threshold=0` không tắt bộ lọc phát hiện.
Không có phát hiện thì trả NO_TARGET/REJECT; đó là hướng dự phòng, không phải
đã phát hiện khuyết tật. Xem `docs/AI_DETECTION_POLICY3.md` về quy tắc.

## Phạm vi đã kiểm tra

Test dữ liệu gốc: 175 ảnh, GREEN 209 / RIPE 40 / REJECT 50 đối tượng.
GREEN precision 93.208%, recall 70.813%, mAP50 87.027%; RIPE/REJECT recall
100% trên tập gốc. Đây không phải độ chính xác vận hành từ DroidCam.

Trên nhóm ảnh camera do người dùng xác nhận trước deploy: GREEN đúng 1/4,
RIPE đúng 1/3, REJECT đúng 6/6. Có thể nhiều góc cùng một quả; số lượng nhỏ,
không phải phép đo trên các quả độc lập. Model có thể loại nhầm quả đạt và
phụ thuộc khoảng cách, ánh sáng, nền. Chưa có xác nhận rằng zoom/crop khắc
phục V2-640; lần crop GREEN thử trước đó dùng V2.1. Bản này chưa tự thêm crop,
không ghép V1/V2.1 hoặc đổi quy tắc phân loại.

Người dùng chọn triển khai V2-640 để thử tiếp. Model V1 trước đây còn trong
lịch sử Git; không ghi đè dữ liệu train hoặc kết quả lịch sử trong PostgreSQL.
Sau deploy, `/health` phải có `mode=onnx`, `model_ready=true`, `task=detect`,
đúng model_version ở trên; `/ready` trả HTTP 200. Model này vẫn là bản thử nghiệm.
