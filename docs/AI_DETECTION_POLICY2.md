# Chính sách ngưỡng 70% (policy2)

Theo yêu cầu vận hành, chỉ khung có confidence >= 0,7 tham gia quyết định.
Khung có tâm nằm ngoài ROI tiếp tục được bỏ qua. Trên cùng một quả:

- REJECT >= 70% được ưu tiên, kể cả khi GREEN/RIPE có điểm cao hơn.
- Nếu không có REJECT đạt ngưỡng, chọn GREEN/RIPE có điểm cao nhất đạt ngưỡng.
- Không còn loại quả chỉ vì điểm GREEN và RIPE gần nhau (`class_margin` cũ).

Không có khung đạt ngưỡng: LOW_CONFIDENCE/REJECT. Có nhiều quả khác nhau cùng
đạt ngưỡng: MULTIPLE_OR_AMBIGUOUS_TARGETS/REJECT vì chưa xác định mục tiêu trạm.
Confidence của trường hợp này không phải điểm lỗi ngoại quan của quả chính.

Ảnh test `0527ba30cca32bf3c80083d666cb067c0fa1542028bc68fae227bdf698c36122`
có quả chính RIPE 91,83% và hai khung mép 64,32%/62,86%. Policy cũ loại cả ảnh;
policy2 bỏ hai khung yếu và trả RIPE 91,83%, giữ nguyên ảnh/ROI/trọng số/ngưỡng.

Model version được đổi thành `autosort-yolo11n-detect-v1-policy2` để phân biệt
kết quả mới với lịch sử v1. Đây là thay đổi logic, không phải huấn luyện lại.
Không sửa kết quả đã lưu; thử lại phải dùng mã quả/Idempotency-Key mới.

Ảnh này đã được dùng để xây quy tắc theo yêu cầu, nên thử lại chỉ là regression,
không phải bằng chứng độc lập về chất lượng AI. Số liệu trong
AI_DETECTION_RESULTS.md mô tả policy cũ và không tự áp dụng cho policy2.
Model vẫn cần kiểm chứng với camera và sản phẩm thật.
