# Kết quả detector thống nhất phiên unified-v1

Trạng thái: **model thử nghiệm, chưa xác nhận vận hành trên trạm thật**.
Các số liệu trong tài liệu này là của policy v1 trước khi thay đổi cách xét
ngưỡng. Bản tích hợp mới dùng [policy2](AI_DETECTION_POLICY2.md); không dùng
những số liệu cũ như đánh giá độc lập cho policy mới.
Model đã train, xuất ONNX và kiểm tra bằng worker thực tế; chưa đưa vào cloud
đang phục vụ hoặc điều khiển phần cứng. Không gọi mAP là độ chính xác băng chuyền.

## Dữ liệu và cấu hình

- Ba lớp: GREEN=0, RIPE=1, REJECT=2. Quả lỗi ưu tiên REJECT trên cùng đối tượng.
- Nguồn: ba ZIP một lớp do nhóm bàn giao; nguồn/giấy phép được giữ trong manifest.
- 1.326 nội dung ảnh nguồn khác nhau; giữ 1.295 ảnh, cách ly 31 ảnh.
- Train 931 ảnh, validation 241 ảnh, test 123 ảnh.
- Xử lý 100 cụm box cùng quả theo ưu tiên REJECT; cách ly 28 ảnh nhãn rỗng và
  3 ảnh overlap khác lớp chưa đủ rõ. Bốn cặp ảnh gần trùng được giữ cùng split.
- Manifest SHA-256: `b25311d2f7fe822f613132bb6eb98a063a27e977421fb2ae55c50ac2d9947be6`.
- YOLO11n pretrained, 30 epochs, ảnh 320, batch 8, CPU 4 thread, freeze 10,
  AdamW lr0=0,001, seed 42. Validation chọn best.pt; không chọn theo test.
- Thời gian cả train và test khoảng 36,8 phút trên Intel Core Ultra 5 125H.
- PyTorch 2.7.1 CPU, Ultralytics 8.4.191; export ONNX 1.23.2, ORT 1.31.1.

Nhãn được hợp nhất từ annotation nguồn, chưa phải kết quả gán nhãn trực quan
toàn bộ ảnh theo một tiêu chí lỗi ngoại quan mới. Grouping bảo thủ không bảo đảm
độc lập hoàn toàn giữa mọi cảnh chụp.

## Đánh giá detection trên test riêng

Bộ test có 123 ảnh và 173 box. Các chỉ số dưới đây do Ultralytics tính; bước
đánh giá độc lập bổ sung bằng faster-coco-eval chưa chạy vì không cài gói đó.
Không dùng các chỉ số này như độ chính xác phân loại sản phẩm trên máy thật.

| Lớp | Box test | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|---:|
| GREEN | 131 | 0,91039 | 0,89313 | 0,93092 | 0,84042 |
| RIPE | 25 | 0,76267 | 0,88000 | 0,91810 | 0,88496 |
| REJECT | 17 | 0,78268 | 0,84819 | 0,87143 | 0,87143 |
| Trung bình | 173 | 0,81858 | 0,87377 | 0,90682 | 0,86560 |

## Quyết định cuối của worker ONNX

Giữ nguyên threshold 0,7 và ROI toàn ảnh đã khai báo trước đánh giá. Test này
không được dùng để chọn lại threshold hoặc ROI. Chấm sơ bộ 92 ảnh chỉ có một
quả được gán nhãn; 31 ảnh nhiều quả được để riêng cho đánh giá tình huống.

| Nhãn nguồn | Trả GREEN | Trả RIPE | Trả REJECT | Tổng |
|---|---:|---:|---:|---:|
| GREEN | 42 | 0 | 17 | 59 |
| RIPE | 0 | 14 | 4 | 18 |
| REJECT | 1 | 2 | 12 | 15 |

- Có 69 quyết định CLASSIFIED, trong đó 65 khớp nhãn nguồn.
- Có 23 quyết định LOW_CONFIDENCE: 19 ảnh nhiều mục tiêu/khung không nhất quán
  và 4 ảnh dưới ngưỡng. REJECT ở đây là nhánh loại bỏ, không chứng minh phát
  hiện lỗi ngoại quan.
- Ba ảnh nhãn REJECT được chấp nhận thành GREEN/RIPE; 21 ảnh GREEN/RIPE bị loại.
- Các ca nhãn REJECT bị nhận sai vẫn xảy ra với confidence cao, nên không thể
  khẳng định chỉ tăng ngưỡng là giải quyết được.

Các giới hạn này cần được xử lý bằng tiêu chí nhãn rõ ràng, dữ liệu trạm,
hiệu chỉnh vùng chụp và đánh giá tiếp theo. Không sửa tham số theo ba ảnh test
rồi báo lại trên chính tập này như một phép đánh giá độc lập mới.

## Parity và kiểm thử phần mềm

- Export cố định FP32, batch 1, opset 17, input 1x3x320x320, output 1x7x2100.
- So sánh 14 ảnh validation/ảnh mẫu: tensor LetterBox khớp; sai số score tối đa
  khoảng 0,00001054; sai số tọa độ box tối đa 0,002656 pixel.
- Quyết định PyTorch, ONNX và production worker khớp trên các probe đã chọn.
- 65 kiểm thử Python và 27 kiểm thử Java đạt.
- E2E classification và detection đạt: ảnh JPEG điện thoại giả lập, Bridge,
  Spring Boot, ORT thật, PostgreSQL test và một lệnh Serial fixture sau retry.
- Đây không phải kiểm thử motor/servo/camera điện thoại thật hoặc đo tài nguyên
  trên Render Free. Không thay model live chỉ dựa trên những kiểm thử này.

## Gói bàn giao

Các artifact cục bộ được đóng gói riêng: best.pt, best.onnx, classes.json,
parity, handoff, manifest/attribution, kết quả test và các ca nhận sai. Gói train
gồm dataset hợp nhất, script và notebook sạch, không chứa API key Roboflow.
Xem [quy trình tái lập](AI_DETECTION_TRAINING.md).
