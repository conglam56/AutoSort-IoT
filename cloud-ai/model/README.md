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

V2.1 fine-tune từ checkpoint V2, bổ sung ảnh GREEN do người dùng cung cấp.
Handoff khai báo test 175 ảnh, GREEN 209 / RIPE 40 / REJECT 50 đối tượng;
GREEN precision 89.435%, recall 76.956%, mAP50 88.245%. Các chỉ số của tập
dữ liệu gốc không phải độ chính xác vận hành từ DroidCam.

Người dùng đã thấy V2.1 nhận nhầm GREEN thành REJECT trên ảnh camera và chọn
triển khai để đối chiếu trực tiếp trên cloud. Chưa xác nhận V2.1 tốt hơn V2
ở trạm thật. Bản này giữ nguyên ảnh đầu vào, không thêm crop hoặc ghép model.

Model V2 trước đây còn trong lịch sử Git (bản trước thay model: `9210302`)
và bản sao lưu cục bộ. Không ghi đè dữ liệu train hoặc kết quả lịch sử trong PostgreSQL.
Sau deploy, `/health` phải có `mode=onnx`, `model_ready=true`, `task=detect`,
đúng model_version ở trên; `/ready` trả HTTP 200. Model này vẫn là bản thử nghiệm.
