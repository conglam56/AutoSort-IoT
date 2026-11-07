# Detector V2.1-640 dùng thử trên cloud

Bản phát hành `autosort-yolo11n-detect-v21-5414fbf368-640` dùng checkpoint V2.1
`autosort-v21-green-5414fbf368`. YOLO11n detection, input
640×640, FP32, ONNX opset 17. Nhãn: GREEN=0, RIPE=1, REJECT=2.

Checkpoint PyTorch nguồn SHA256:
`0609cf39df89ce6961a745393933e183cad59964d0e86a85ba48da2fefa98974`.
Graph và metadata có checksum trong `SHA256SUMS`. Đã kiểm tra parity PyTorch /
ONNX trên 15 ảnh; parity kiểm tra tính nhất quán khi chuyển đổi, không chứng
minh độ chính xác phân loại. Attribution của GREEN v1, RIPE/REJECT v2 và ảnh
GREEN bổ sung được lưu trong `ATTRIBUTION.txt`. Không đưa checkpoint PyTorch
hoặc bộ train vào image.

## Quy tắc suy luận

Giữ `highest_confidence`: chọn nhãn có điểm cao nhất trong các khung hợp lệ
trong ROI. Không áp ngưỡng quyết định 70% và không ưu tiên REJECT. Bộ lọc phát
hiện 25% và NMS IoU 0.7 giữ nguyên. `threshold=0` không tắt bộ lọc phát hiện.
Không có phát hiện thì trả NO_TARGET/REJECT; đó là hướng dự phòng, không phải
đã phát hiện khuyết tật. Xem `docs/AI_DETECTION_POLICY3.md` về quy tắc.

## Phạm vi đã kiểm tra

V2.1 được tinh chỉnh từ checkpoint V2 với ảnh GREEN bổ sung. Tập test trong
gói bàn giao gồm 175 ảnh với 209 đối tượng GREEN, 40 RIPE và 50 REJECT.
Trên tập này, lớp GREEN đạt precision 89.435%, recall 76.956% và mAP50 88.245%.

Kiểm tra bằng ảnh DroidCam ghi nhận trường hợp quả xanh đạt bị phân loại
thành REJECT. V2.1 được triển khai để đối chiếu với V2, và chất lượng phân
loại trên băng chuyền cần được xác nhận bằng một tập quả mới chụp tại trạm.
Khi báo cáo, ghi riêng kết quả chạy demo trên mẫu đã dùng để huấn luyện và
kết quả đánh giá trên mẫu độc lập. Worker dùng toàn ảnh với một model ONNX.

Model V2 trước đây còn trong lịch sử Git (bản trước thay model: `9210302`)
và bản sao lưu cục bộ. Không ghi đè dữ liệu train hoặc kết quả lịch sử trong PostgreSQL.
Sau deploy, `/health` phải có `mode=onnx`, `model_ready=true`, `task=detect`,
đúng model_version ở trên; `/ready` trả HTTP 200. Model này vẫn là bản thử nghiệm.
