# Model v2: rà nhãn và bổ sung ví dụ quả mốc

Trạng thái: đã huấn luyện xong ứng viên riêng `unified-v2-640` trên nhánh
`feature/fruit-model-v2`. Model v1, dữ liệu v1 và dịch vụ cloud được giữ nguyên.
Đây chưa phải bản được duyệt triển khai.

## Tiêu chí đã chốt ngày 30/10/2026

- GREEN: quả xanh đạt yêu cầu ngoại quan.
- RIPE: quả chín đạt yêu cầu ngoại quan.
- REJECT: mốc, thối, dập, nứt, **đốm đen, vết thâm hoặc sẹo vỏ**, dù chưa mốc/thối.
- Vết cuống tự nhiên không tự động đồng nghĩa với lỗi. Ảnh chưa phân biệt được
  cuống với tổn thương, ảnh mờ hoặc nhiều quả không rõ nhãn được cách ly.
- Annotation dùng khung toàn bộ quả. Không gán RIPE cho cả quả và REJECT cho
  một mảng hỏng nằm trên chính quả đó.

Đây là quy tắc ground truth. Chính sách suy luận vẫn là `highest_confidence`,
không khôi phục ưu tiên REJECT hoặc ngưỡng quyết định 70%. Bộ lọc phát hiện
25% và hành vi khi không có mục tiêu vẫn theo policy3.

## Thay đổi dữ liệu

Đã sàng lọc trực quan 428 ảnh nguồn: mọi ảnh train có REJECT, mọi ảnh có RIPE,
mọi ảnh held-out có REJECT và các bất đồng bổ sung trong train. Một số ảnh
cuống được xem ở độ phân giải gốc. Codex hỗ trợ sàng lọc theo tiêu chí người
dùng chốt; nhãn từng ảnh chưa được người dùng hay chuyên gia thẩm định độc
lập. Đây là rà soát sơ bộ và chưa rà toàn bộ ảnh chỉ mang GREEN.

- 105 ảnh được sửa annotation, gồm đổi RIPE có lỗi rõ sang REJECT và hợp nhất
  một số khung mảng hỏng với khung toàn quả đã xác minh.
- 117 ảnh được cách ly thêm; 31 ảnh cách ly của v1 tiếp tục giữ riêng.
- 116 ảnh bổ trợ được chọn sau khi rà 160 ảnh: 57 RIPE, 59 REJECT.
- Ảnh bổ trợ chỉ vào **train**, cùng một group bảo thủ, không vào val/test.
  Sàng lọc pHash/pixel không thấy cặp gần trùng hiển nhiên với 341 ảnh held-out;
  kiểm tra này không chứng minh độc lập theo quả thật hay cảnh chụp.

| Split | Ảnh dùng | Khung GREEN | Khung RIPE | Khung REJECT |
|---|---:|---:|---:|---:|
| Train | 953 | 930 | 67 | 272 |
| Validation | 224 | 260 | 1 | 52 |
| Test | 117 | 131 | 4 | 27 |

Ảnh và nhãn gốc không bị sửa. Bản mới ở
`.local/ai-training/unified-detection-v2-balanced`. Mỗi thay đổi có SHA-256,
lý do, annotation trước/sau trong manifest và bản review đi kèm.
`unique_source_images` là thống kê kế thừa của nguồn v1; 116 ảnh bổ trợ được
ghi riêng trong `supplement_review` và đã được tính vào `counts` ở trên.

Nguồn bổ trợ: Shuvo, A.; Monika, M. S. A.; Bhuian, W. J. O. (2026),
[Orange Fruit Image Dataset for Classification, V2](https://data.mendeley.com/datasets/zk4hzhtcdd/2),
DOI `10.17632/zk4hzhtcdd.2`,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Thay đổi: chọn ảnh, sàng lọc ngoại quan, thêm khung toàn quả và ánh xạ lớp.
Không hàm ý tác giả nguồn chứng thực hệ thống AutoSort.

Ảnh bổ trợ là cam 224 px, có nhiều biến thể gần trùng/tăng cường của cùng
quả. Không được coi 116 file là 116 quả độc lập, hoặc coi upscale 640 px là
thêm chi tiết thật. Dữ liệu vẫn cần ảnh quất từ camera trạm; đặc biệt
validation chỉ có một khung RIPE sạch, test có bốn khung nên chỉ số RIPE
rất thiếu ổn định. Các split cũ cũng chưa được xác minh độc lập theo quả thật.

## Tái tạo và huấn luyện

Môi trường đang dùng: Python 3.12, PyTorch CPU 2.7.1, Ultralytics 8.4.191.
Máy không có CUDA; batch 2, 4 thread, không cache ảnh và workers 0.

Chuẩn bị v1 theo `AI_DETECTION_TRAINING.md`, tải ZIP từ trang nguồn trên vào
`.local/ai-training/OrangeClassificationDataset.zip`, sau đó:

```powershell
python training/refine_detection_dataset.py --source .local/ai-training/unified-detection-v1 --destination .local/ai-training/unified-detection-v2-balanced --review training/reviews/fruit-v2-review.json --supplement-archive .local/ai-training/OrangeClassificationDataset.zip --supplement-review training/reviews/fruit-v2-supplement.json

python training/train_detection.py --dataset .local/ai-training/unified-detection-v2-balanced --project .local/ai-training/runs --name unified-v2-640 --model .local/ai-training/runs/unified-v1/weights/best.pt --epochs 20 --imgsz 640 --batch 2 --device cpu --freeze 0 --threads 4 --patience 5 --lr0 0.0003 --class-weight-power 0.5
```

Builder kiểm tra checksum ZIP, manifest, nhãn và class ID, từ chối ghi đè
thư mục có sẵn. Không tự tải ảnh, không đọc API key. `cls_pw=0.5` tăng trọng số
loss cho lớp ít mẫu; không nhân bản file hoặc thay đổi chính sách suy luận.
Seed 42, AdamW, LR ban đầu 0.0003, fine-tune toàn bộ từ best.pt v1.
Validation chọn checkpoint/dừng sớm; không chọn cấu hình bằng kết quả test.

Chạy lại cần chọn tên dataset/run mới. `best.pt`, `last.pt`, `args.yaml`,
`results.csv`, progress và `handoff.json` đều lưu riêng. Mặc định v1 của
trainer vẫn giữ LR 0.001 và tắt class weighting nếu không truyền tham số mới.

Nếu một run mới bị ngắt trước khi hoàn tất, thêm `--resume` vào đúng lệnh
và dùng cùng dataset/project/name. Trainer cần `last.pt` còn optimizer/epoch
và fingerprint dataset gốc trong `<name>-input.json`; nó từ chối resume khi
dataset thay đổi hoặc run đã có handoff hoàn tất. Checkpoint đã strip optimizer
chỉ dùng để suy luận hoặc bắt đầu một lượt fine-tune mới. Run hiện tại đã
khôi phục từ epoch 4 sau khi phiên thực thi đầu bị đóng; giữ bản sao checkpoint
trước phục hồi và chạy tiếp bằng tiến trình nền ẩn.

## Đối chiếu cố định

Nhãn test được chốt trước khi train v2. Cùng tập test đã rà được dùng cho cả
v1 và v2; không so trực tiếp số lỗi này với báo cáo cũ dùng nhãn khác.

88 ảnh có đúng một khung annotation: 59 GREEN, 4 RIPE, 25 REJECT. 29 ảnh
nhiều khung được giữ để chấm detector, không chấm thành một sản phẩm.

| Quyết định worker | v1 đang phục vụ, 320 px | v2, 640 px |
|---|---:|---:|
| REJECT bị cho qua GREEN/RIPE | 12/25 | 1/25 |
| GREEN/RIPE bị đưa vào REJECT | 0/63 | 4/63 |

V1: REJECT 13, RIPE 11, GREEN 1 trên 25 ảnh REJECT một quả. Ảnh mốc hai quả
`cloud-ai/reject.jpg` hiện được chọn RIPE, điểm 0.3205. Các ảnh mẫu đã được
nhóm xem và thảo luận là chẩn đoán phát triển, không phải kiểm thử độc lập.
Điểm confidence của detector không phải xác suất chất lượng được hiệu chuẩn.

Khi hoàn tất, xuất ONNX FP32 ở thư mục riêng và kiểm tra parity, sau đó chấm
đúng worker với policy3. Phải tách REJECT được model nhận dạng khỏi REJECT do
không tìm thấy mục tiêu. V1 320 px và v2 640 px là so sánh toàn pipeline,
không cô lập riêng ảnh hưởng của trọng số.

Không chép ứng viên vào `cloud-ai/model`, không push/deploy thay model cloud
trong lượt huấn luyện này. Chỉ cân nhắc nâng cấp sau khi xem lỗi còn lại,
kiểm thử camera trạm và kiểm tra tài nguyên phục vụ ở 640 px.

## Kết quả ứng viên đã hoàn tất

Train hoàn tất 20 epoch, tối đa 20 và patience 5. Lượt đầu bị ngắt sau epoch 4; đã giữ checkpoint phục hồi và tiếp tục optimizer/epoch bằng `--resume` trong tiến trình nền. Không khẳng định bit-for-bit giống một lượt train liên tục.

| Nhãn đúng và CLASSIFIED | v1 | v2 |
|---|---:|---:|
| GREEN | 59/59 | 58/59 |
| RIPE | 4/4 | 1/4 |
| REJECT | 13/25 | 24/25 |

Tổng đúng nhãn và CLASSIFIED: v1 76/88, v2 83/88. Fallback REJECT của v2 theo ground truth: {"GREEN": 0, "RIPE": 0, "REJECT": 0}. Không tính fallback như bằng chứng model nhìn thấy lỗi.

| Ảnh chẩn đoán đã biết | v1 | v2 |
|---|---|---|
| quatsample.jpg | REJECT 82.65% (CLASSIFIED) | GREEN 91.94% (CLASSIFIED) |
| reject.jpg | RIPE 32.05% (CLASSIFIED) | GREEN 82.12% (CLASSIFIED) |
| ripe.jpg | RIPE 84.05% (CLASSIFIED) | REJECT 51.70% (CLASSIFIED) |

Xem `comparison-v1-v2.json`, danh sách lỗi `candidate-v2-errors.json`, metric detector theo từng lớp trong handoff và `parity.json` trong gói bàn giao. Bản này vẫn là ứng viên cần kiểm thử ảnh quất/camera trạm, chưa thay v1 trên cloud.

## Mốc đối chiếu cùng 640 px

V1 được xuất riêng ở 640 px từ checkpoint v1 không đổi (đã kiểm tra parity), cùng policy3 và cùng tập test. Không ghi đè graph/checkpoint v1 gốc.

| Quyết định worker | V1 320 px | V1 640 px | V2 640 px |
|---|---:|---:|---:|
| REJECT bị cho qua | 12/25 | 11/25 | 1/25 |
| Quả tốt bị đưa vào REJECT | 0/63 | 4/63 | 4/63 |
| Đúng nhãn và CLASSIFIED | 76/88 | 65/88 | 83/88 |

Mốc V1 640 px giúp đối chiếu ảnh hưởng của trọng số khi giữ cùng độ phân giải với V2. File `baseline-v1-640-test.json` chứa đầy đủ kết quả; ảnh mốc đã biết vẫn là RIPE 83.01% ở mốc này. Không chọn cấu hình mới dựa vào tập test.

## Phục hồi định vị trong ảnh rộng

V2 thuần nhận sai ảnh mốc `reject.jpg` thành GREEN 82.12%: khung dự đoán
phủ gần toàn ảnh gỗ, thay vì hai quả nhỏ. Khi cắt vùng quả để chẩn đoán,
model nhận ra REJECT. Các khung cắt thủ công này chỉ phục vụ chẩn đoán,
không được đưa vào huấn luyện hay dùng làm tọa độ cố định trong worker.

Ứng viên thứ hai `autosort-yolo11n-detect-v2-recovery-320-candidate` bổ sung
một graph [YOLO11n pretrained COCO-80](https://docs.ultralytics.com/models/yolo11/)
ở 320 px để tìm vùng quả. Nhãn `apple`/`orange` chỉ tạo khung đề xuất;
chúng không trở thành nhãn chất lượng. Graph chất lượng vẫn là v2 640 px.

- Giữ nguyên kết quả native nếu khung tốt nhất chiếm dưới 90% diện tích ảnh.
- Nếu khung phủ gần toàn ảnh hoặc chưa có mục tiêu, thử tìm vùng quả.
  Với khung gần toàn ảnh, đề xuất phải nhỏ hơn hoặc bằng một nửa diện tích
  khung đó. Không có đề xuất phù hợp thì giữ đường xử lý native.
- Cắt vùng quả với padding 5%, tối đa bốn vùng, chạy graph chất lượng rồi
  chiếu các khung trở lại ảnh gốc. Không sửa ảnh nguồn hoặc vẽ đè để suy luận.
- Chọn điểm chất lượng cao nhất trên các vùng: không nhân điểm định vị,
  không ưu tiên REJECT, không đặt lại ngưỡng 70%. Nếu các crop không có
  detection hợp lệ, worker trả fallback `NO_TARGET`, không nhận là đã thấy lỗi.

Thử dùng bộ định vị cho **mọi** ảnh làm validation kém rõ rệt: đúng nhãn
CLASSIFIED từ 159/169 giảm còn 70/169 ở 320 px và 35/169 ở 640 px; nó bỏ sót
nhiều quất xanh. Vì vậy đường định vị chỉ được gọi theo điều kiện hình học
ở trên. Cả hai cấu hình phục hồi 320/640 giữ 159/169 trên validation, không
có ảnh validation nào thực sự dùng crop phục hồi. Điều này kiểm tra tương
thích, **chưa chứng minh độ tin cậy của phục hồi trên ảnh rộng mới**.

Chọn bản 320 nhỏ hơn theo quy tắc đã ghi trước khi chấm regression test:
giữ chỉ số validation không giảm, khắc phục được ảnh mốc phát triển đã biết,
ưu tiên kích thước nhỏ nếu cùng đạt. Không chọn bản 640 chỉ vì confidence
của ảnh mốc cao hơn. Các ngưỡng hình học là heuristic phát triển, chưa được
kiểm chứng trên tập ảnh camera trạm độc lập.

| Ảnh đã biết | v1 đang phục vụ | v2 + phục hồi 320 |
|---|---|---|
| Quả xanh / vết cuống | REJECT 82.65% | GREEN 91.94% |
| Hai quả mốc trên nền gỗ | RIPE 32.05% | REJECT 82.97% |
| `ripe.jpg` | RIPE 84.05% | REJECT 51.70% — vẫn cần rà |

Ảnh mốc có khung quả thật và kết quả `CLASSIFIED`, không phải REJECT do
không phát hiện được gì. Bộ định vị 320 chỉ đề xuất một trong hai quả ở ảnh
này; đây vẫn là một kết quả cho ảnh, chưa phải hệ thống đếm mọi quả trong ảnh.
Trạm cần đưa từng quả vào vùng chụp như thiết kế.

Trên regression test 117 ảnh cố định, bản phục hồi cho cùng các quyết định
như v2 thuần: đúng 83/88 ảnh một annotation, REJECT 24/25, GREEN 58/59,
RIPE chỉ 1/4. Không có fallback trên 88 ảnh này. **Vẫn loại nhầm 4/63 ảnh
mang nhãn tốt, trong đó 3/4 ảnh RIPE**. Không đề xuất thay cloud ngay hoặc
coi đây là độ chính xác thực tế của trạm.

Graph phụ đã đối chiếu PyTorch/ONNX trên chín probe (ba ảnh đã biết và sáu
ảnh validation); công cụ export mới được chạy kiểm chứng lại với ba probe.
Kiểm thử ONNX nhân tạo kiểm tra cả crop từ pixel, chiếu khung, ROI,
không nhân confidence, chọn RIPE dưới 70% khi điểm cao nhất và từ chối
model phụ thiếu/sai. Worker cũ không có trường `localizer` vẫn dùng đường cũ.

## Dùng và tái tạo gói phục hồi

Gói model phục hồi có `best.pt`, `best.onnx`, `classes.json`,
`fruit-localizer.onnx`, báo cáo, license upstream và mã worker tương ứng.
`best.pt` là detector chất lượng; chạy riêng file này sẽ **không** có bước
phục hồi định vị. Muốn chạy đúng pipeline phải dùng cả hai graph và metadata.
Không chép vào thư mục model của dịch vụ đang chạy khi chưa kiểm thử camera
và tài nguyên Render. Chưa đo tải RAM/latency trên Render Free với hai graph.

Có thể tái tạo graph phụ từ checkpoint pretrained COCO-80 gốc của nhóm:

```powershell
python training/export_fruit_localizer.py --weights yolo11n.pt --destination runs/localizer-320-new --imgsz 320 --probe cloud-ai/quatsample.jpg --probe cloud-ai/reject.jpg --probe cloud-ai/ripe.jpg
```

Đặt graph chất lượng và `classes.json` từ export v2 vào một thư mục ứng viên
mới, sao chép graph phụ, đưa cấu hình `localizer.json` vào trường `localizer`
của `classes.json`, đổi `file` thành `fruit-localizer.onnx`, giữ checksum của
graph tương ứng và dùng version mới. Worker kiểm tra tên file, checksum,
shape và policy trước khi báo sẵn sàng. Đánh giá lại bằng
`training/evaluate_detection.py --dataset <v2-dataset> --model-dir <candidate> --split test --output <new-report.json>`.

Các gói kết quả chỉ lưu cục bộ. Bản v1 và lần train trước đã được kiểm tra
SHA-256 không đổi; cloud vẫn dùng v1. Việc cần ưu tiên tiếp theo cho v3 là
thẩm định nhãn RIPE sạch và thu ảnh quất chín đạt yêu cầu từ camera trạm,
tách train/val/test theo quả thật hoặc buổi chụp. Không sửa nhãn test chỉ để
làm đẹp chỉ số sau khi đã xem dự đoán.
