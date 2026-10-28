# Rà soát dataset ngày 27/10/2026

Dataset duy nhất sau khi dọn là `datasets/kumquat/`; gói giao cho người phụ trách
huấn luyện là `kumquat-dataset-only.zip`, chỉ chứa ảnh và hai tệp mô tả/ghi nguồn.
Đây là bản rà soát trực quan bước đầu, chưa phải bộ nhãn đã được chuyên gia kiểm định.

## Tiêu chí đã được người dùng chốt

Quả có sẹo, đốm hoặc tổn thương vỏ rõ cũng thuộc `REJECT`, dù chưa thối.
`GREEN` và `RIPE` phải đồng thời đạt yêu cầu ngoại hình. Chất lượng ngoại hình
được ưu tiên trước độ chín. Không suy luận quả thối chỉ từ màu vàng hoặc bóng đổ.
Ảnh quá mờ, nhiều quả khó xác định đối tượng, cắt cụt nhiều, nghi có nét vẽ trên
vỏ, hoặc dấu hiệu khó kết luận được cách ly thay vì ép nhãn.

## Kết quả

| Xử lý | Số ảnh |
| --- | ---: |
| Giữ nhãn cũ | 1.221 |
| Chuyển sang REJECT | 126 |
| Cách ly khỏi bản mới | 414 |
| Tổng dùng trong bản mới | 1.347 |

126 ảnh đổi nhãn gồm 22 ảnh từ `GREEN` và 104 ảnh từ `RIPE`.
414 ảnh cách ly gồm 215 ảnh có vấn đề chất lượng/crop và 199 ảnh chưa chắc nhãn
hoặc còn nghi ngờ bề mặt. Đây là phân loại lý do rà soát, không phải chẩn đoán bệnh.

| Nhãn | Train | Validation | Test | Tổng |
| --- | ---: | ---: | ---: | ---: |
| GREEN | 772 | 78 | 14 | 864 |
| REJECT | 294 | 50 | 34 | 378 |
| RIPE | 77 | 22 | 6 | 105 |
| Tổng | 1.143 | 150 | 54 | 1.347 |

Đã xem toàn bộ 1.761 ảnh qua 23 bảng ảnh; xem lại 135 đề xuất đổi nhãn ở kích
thước lớn hơn và giữ 9 trường hợp chưa chắc trong khu cách ly. Chốt 126 ảnh đổi
nhãn theo tiêu chí ngoại hình của người dùng. Đây là các crop ảnh, không phải
1.347 quả vật lý độc lập.

## Bằng chứng và khả năng khôi phục

Các bằng chứng được gom vào **`docs/dataset-review-2026-10-27.zip`**:

- `audit.csv`: đường dẫn gốc, hành động, lý do, SHA-256 và đường dẫn sau xử lý.
- `quarantine/`: 414 ảnh loại, giữ cây thư mục gốc.
- `original_sha256.json`, `original_dataset_manifest.json` và
  `original_ATTRIBUTION.txt`: thông tin bộ gốc 1.761 ảnh.
- `relabel.json`: 126 quyết định đổi nhãn cuối cùng.
- `index.json`, `selections.json`, `summary.json`, `verification.json`: nhật ký
  lượt rà soát trước khi dọn. Các tên đường dẫn cũ trong nhật ký là thông tin lịch sử.
- `examples.jpg`: ví dụ vấn đề trong nhãn gốc.
- `RESTORE.txt`: cách tái tạo bộ gốc từ dataset hiện tại và 414 ảnh trong ZIP.

`datasets/kumquat/dataset_manifest.json` chứa nguồn, giấy phép, số lượng và nhãn
cũ của ảnh đổi nhãn. Các bảng ảnh trung gian đã được bỏ. Bộ gốc có thể tái tạo
đầy đủ: lấy ảnh còn dùng theo `output_file` trong audit, đổi về đường dẫn `file`,
bổ sung ảnh `quarantine/`, rồi kiểm tra SHA-256. Đã kiểm chứng đủ 1.761 ảnh trước
khi xóa bản trùng. Không thay byte ảnh hoặc chuyển ảnh giữa train/val/test.

## Dùng bản mới để train

Gửi **`kumquat-dataset-only.zip`** cho người phụ trách train để họ dùng code riêng.
Giải nén sẽ có trực tiếp `train/`, `val/`, `test/`, `README.txt`, `ATTRIBUTION.txt`.
Không cần giữ thêm bản giải nén ở thư mục gốc dự án.

Nếu train cục bộ với code có sẵn, dùng `--dataset datasets/kumquat` (cũng là mặc
định). Nếu muốn dùng notebook hiện có của dự án, phải tạo gói có đủ code và
đường dẫn mà notebook yêu cầu bằng lệnh dưới; ZIP chỉ chứa dataset không thay
trực tiếp cho gói notebook này. Chọn tên ZIP chưa tồn tại:

```powershell
.\cloud-ai\.venv\Scripts\python.exe training/package_colab.py --dataset datasets/kumquat --output autosort-training.zip
```

## Kiểm tra và giới hạn

Đã kiểm tra tất cả ảnh trong bản mới đọc được; số lượng thư mục khớp manifest;
byte ảnh sao chép/đổi nhãn khớp SHA-256 gốc; toàn bộ 1.761 ảnh nguồn giữ nguyên.
ZIP được kiểm tra CRC và đường dẫn bên trong. Chưa train lại, chưa có bằng chứng
độ chính xác model tăng.

Lớp `RIPE` còn rất ít ảnh; cần bổ sung quả chín đẹp chụp bằng camera thực tế.
Ảnh trên cây và ảnh trên bàn có nền khác nhau; model có thể học nền. Các góc
chụp cùng một quả hoặc ảnh gần trùng có thể xuất hiện ở các tập khác nhau;
đợt này chưa giải quyết được vì không có mã định danh quả vật lý.

Không dùng điểm trên val/test đã lọc để khẳng định model tốt hơn model cũ.
Cần một tập đánh giá độc lập trên đúng giống quất/tắc và camera băng chuyền,
gán nhãn theo tiêu chí ngoại hình vừa chốt, có cả tình huống khó. Các ảnh test
bị cách ly vẫn được giữ để xem lại; nhãn test gốc cũng cần rà soát theo tiêu chí
mới trước khi dùng so sánh.

## Dataset khác đã tìm

| Bộ dữ liệu | Điểm phù hợp | Hạn chế với dự án |
| --- | --- | --- |
| [Jobbie calamansi-ripeness](https://universe.roboflow.com/jobbie/calamansi-ripeness-cvxus) | 989 ảnh nguồn; đúng nhóm quả gần với dữ liệu hiện tại | Chỉ có ripe/unripe/rotten; nhãn rotten không tương đương toàn bộ tiêu chí ngoại hình |
| [NAVSTRIDE Calamansi Ripeness](https://universe.roboflow.com/navstride-detection/calamansi-ripeness) | 492 ảnh calamansi | Nhãn độ chín, chưa có nhãn riêng cho mọi khuyết điểm ngoại hình; chưa kiểm định ảnh/nhãn |
| [Orange Fruit Image Dataset v2](https://data.mendeley.com/datasets/zk4hzhtcdd/2) | Nguồn công bố 15.000 ảnh và 5 lớp fresh, black-spotted, canker-affected, green, rotten; CC BY 4.0 | Là cam, khác giống mục tiêu; chưa tải và kiểm định nhãn, không xem là bản thay thế trực tiếp |

Chưa có bằng chứng để khẳng định bộ thay thế nào chính xác hơn cho quất/tắc
trên băng chuyền. Hướng phù hợp hiện tại là dùng bản rà soát để thử nghiệm,
bổ sung ảnh thật có tiêu chí nhất quán, đặc biệt quả chín đẹp và quả xanh có lỗi.
