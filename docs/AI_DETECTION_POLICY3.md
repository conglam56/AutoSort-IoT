# Chọn nhãn có điểm cao nhất (policy3)

Theo yêu cầu mới, bỏ ngưỡng quyết định 70% và bỏ ưu tiên riêng REJECT.
Ví dụ cùng quả có RIPE 61% và REJECT 59% thì trả RIPE 61%; GREEN 99% và
REJECT 80% thì trả GREEN 99%. REJECT chỉ thắng khi có điểm cao nhất.

Worker giữ tiền xử lý, graph ONNX, ROI và bộ lọc phát hiện 25%/NMS hiện có.
Sau lọc, chọn khung có điểm cao nhất trong ROI và nhãn cao nhất của khung đó.
Khung của quả khác không phủ quyết khung được chọn; khi các quả cùng xuất
hiện, kết quả là cho khung có điểm cao nhất, không phải toàn bộ ảnh.
ROI phải được căn với vị trí chụp để tránh chọn quả nền. Nếu không còn khung
hợp lệ thì NO_TARGET/LOW_CONFIDENCE/REJECT, không tự tạo nhãn từ nền ảnh.

Metadata: decision_policy=highest_confidence, threshold=0,
model_version=autosort-yolo11n-detect-v1-policy3. Threshold bằng 0 biểu thị
không có ngưỡng quyết định; candidate_threshold=0.25 vẫn là lọc phát hiện.
Health công bố decision_policy; dashboard ẩn mốc 70% và ghi Chọn điểm cao nhất.
Metadata cũ thiếu decision_policy giữ chính sách threshold để tương thích.

Trọng số/nhãn train không đổi; kết quả cũ trong PostgreSQL không được sửa.
Các số liệu v1/policy2 chỉ là lịch sử, không chứng minh chất lượng policy3.
Kiểm thử ảnh dataset đã xem là regression, không phải đánh giá độc lập.
