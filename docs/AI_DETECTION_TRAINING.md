# Huấn luyện detector ba lớp từ bộ bàn giao AI

Ba checkpoint GREEN/RIPE/REJECT được bàn giao là ba YOLO11n detector một lớp.
Kiểm thử chéo cho thấy chúng thường cùng nhận một quả. Luồng mới huấn luyện
một detector ba lớp với ID cố định: GREEN=0, RIPE=1, REJECT=2.

Quy tắc nghiệp vụ đã xác nhận: quả có lỗi ngoại quan luôn vào REJECT, dù còn
xanh hay đã chín. Đây là quy tắc cho cùng một quả, không phải ưu tiên bất kỳ
quả REJECT nào xuất hiện ở vị trí khác trong ảnh.

## Chuẩn bị dữ liệu

Chạy trong môi trường có NumPy, Pillow và PyYAML:

```powershell
python training/prepare_detection_dataset.py --green D:/green_fruit.zip --ripe D:/ripe_fruit.zip --reject D:/reject_fruit.zip --destination .local/ai-training/unified-detection-v1
```

Script không sửa các ZIP nguồn và không ghi đè thư mục đích đã tồn tại. Nó:

- Kiểm tra định dạng, nhãn nguồn và các entry trùng trong ZIP.
- Gộp ảnh trùng SHA-256, hợp nhất annotation và đổi class ID.
- Gộp box IoU >= 0,8 khi nhất quán là cùng một đối tượng; REJECT thắng độ chín.
- Cách ly ảnh nhãn rỗng, GREEN/RIPE xung đột hoặc overlap chưa đủ chắc chắn.
- Giữ cùng ảnh nguồn và các cặp gần trùng bảo thủ trong cùng split. Ưu tiên
  train, rồi validation, rồi test khi nguồn bị chia không thống nhất.
- Lưu manifest, lịch sử chuyển nhãn, ảnh cần rà soát và attribution.

Nhóm gần trùng dựa trên pHash, chênh lệch pixel RGB và kích thước. Kiểm tra này
không chứng minh độc lập hoàn toàn giữa các cảnh chụp. Nhãn nguồn vẫn cần rà
soát ngoại quan và độ đầy đủ; script không tự xác định bệnh hoặc chất lượng quả.

## Huấn luyện

Môi trường đã kiểm tra: Python 3.12, PyTorch CPU 2.7.1, torchvision 0.22.1,
Ultralytics 8.4.191; export với ONNX 1.23.2 và ONNX Runtime 1.31.1.
Cài PyTorch theo hướng dẫn chính thức cho thiết bị thực tế;
không đưa PyTorch/Ultralytics vào image phục vụ suy luận trên Render.

```powershell
python training/train_detection.py --dataset .local/ai-training/unified-detection-v1 --project .local/ai-training/runs --name unified-v1 --epochs 30 --imgsz 320 --batch 8 --device cpu --freeze 10 --threads 4
```

Đây là cấu hình transfer learning CPU ban đầu: khóa 10 module backbone đầu,
huấn luyện phần còn lại và dùng validation để chọn checkpoint/early stopping.
Đổi `--freeze 0` để fine-tune toàn bộ khi cần; có thể dùng GPU và ảnh lớn hơn
nếu có tài nguyên. Không lựa chọn cấu hình hoặc threshold bằng tập test.

Script xác minh manifest/nhãn/hash, tắt các tích hợp theo dõi bên ngoài trong
profile riêng, ghi progress JSON, giữ best.pt/last.pt và đánh giá best.pt trên
test sau khi kết thúc. Không ghi credentials vào source hoặc artifact.

## Xuất ONNX và kiểm tra parity

Cài ONNX/ONNX Runtime vào môi trường export, sau đó:

```powershell
python training/export_detection.py --weights .local/ai-training/runs/unified-v1/weights/best.pt --dataset .local/ai-training/unified-detection-v1 --destination .local/ai-training/export-v1 --imgsz 320 --threshold 0.7
```

Export cố định batch 1, FP32, opset 17, không gắn NMS vào graph. Metadata
`task=detect`, `output_format=yolo11_raw` cho worker biết định dạng đầu ra.
Kiểm tra dùng ảnh validation và ba ảnh mẫu, so sánh tensor đầu vào với
Ultralytics LetterBox, so sánh đầu ra PyTorch/ONNX và quyết định của worker.

Đánh giá quyết định cuối của chính worker trên tập test cố định, không tự chọn
threshold/ROI bằng tập test:

```powershell
python training/evaluate_detection.py --dataset .local/ai-training/unified-detection-v1 --model-dir .local/ai-training/export-v1 --output .local/ai-training/decisions-test-v1.json
```

Ảnh nhiều quả không được chấm như một sản phẩm. Báo cáo tách kết quả CLASSIFIED
khỏi REJECT do lỗi/không chắc chắn, đồng thời đếm quả mang nhãn REJECT được
chấp nhận thành GREEN/RIPE và quả tốt bị đưa vào REJECT.

## Hợp đồng với Camera Bridge

Worker vẫn trả GREEN/RIPE/REJECT hoặc MOCK và giữ hai reason mà Bridge hiểu:

- CLASSIFIED: một quả mục tiêu được phân loại đủ tin cậy.
- LOW_CONFIDENCE: REJECT do không có mục tiêu, nhiều mục tiêu, độ tin cậy thấp
  hoặc xung đột độ chín. `decision_detail` phân biệt nguyên nhân.

NMS giữ riêng từng lớp để áp dụng REJECT cho cùng quả. Mặc định ROI là toàn
ảnh và worker từ chối tự chọn một quả khi nhiều mục tiêu không nhất quán.
Từ [policy2](AI_DETECTION_POLICY2.md), chỉ khung đạt ngưỡng quyết định (>= 70%
mặc định) mới tham gia kiểm tra nhiều mục tiêu. Khung yếu ở mép không phủ
quyết quả chính đã đủ tin cậy; không còn veto bởi `class_margin` cũ.
`target_roi` trong classes.json là [left, top, right, bottom] chuẩn hóa và cần
hiệu chỉnh bằng camera trạm. Không coi nhiều mục tiêu là một quả chỉ vì có
điểm confidence lớn hơn.

Metadata cũ không có task tiếp tục dùng classification như trước. Đặt model
vào cloud-ai/model chỉ sau khi kiểm tra chất lượng, parity và tài nguyên.
Parity thành công không thay thế đánh giá AI hoặc kiểm thử phần cứng.

## Bàn giao

Giữ best.pt, best.onnx, classes.json, manifest, attribution, cấu hình train,
kết quả validation/test và parity. Các ZIP/notebook nguồn không được tự động
commit; notebook được bàn giao có API key cần loại khỏi bản chia sẻ.
Không báo model sẵn sàng chạy thiết bị thật chỉ dựa trên mAP nội bộ.
