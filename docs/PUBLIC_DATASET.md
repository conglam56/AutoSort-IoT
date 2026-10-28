# Dataset AutoSort sau khi dọn

Chỉ dùng **`datasets/kumquat/`**, gồm **1.347 ảnh** đã rà soát.
**`kumquat-dataset-only.zip`** là bản nén để gửi người phụ trách huấn luyện,
không chứa code train. Không cần giữ thêm bản giải nén ở thư mục gốc.

## Cấu trúc

```text
datasets/kumquat/
├── train/{GREEN,REJECT,RIPE}/
├── val/{GREEN,REJECT,RIPE}/
├── test/{GREEN,REJECT,RIPE}/
├── dataset_manifest.json
└── ATTRIBUTION.txt
```

| Nhãn | Train | Validation | Test | Tổng |
| --- | ---: | ---: | ---: | ---: |
| GREEN | 772 | 78 | 14 | 864 |
| REJECT | 294 | 50 | 34 | 378 |
| RIPE | 77 | 22 | 6 | 105 |
| Tổng | 1.143 | 150 | 54 | 1.347 |

`REJECT` bao gồm quả có sẹo, đốm hoặc tổn thương vỏ rõ dù chưa thối, theo tiêu
chí người dùng đã chốt. 126 ảnh đã đổi nhãn sang REJECT; 414 ảnh mờ, crop lỗi
hoặc nhãn chưa chắc đã cách ly. Đây là lượt rà soát trực quan bước đầu, chưa
được chuyên gia kiểm định hoặc train/đánh giá lại. RIPE chỉ còn 77 ảnh train;
cần bổ sung ảnh thực tế. Xem [báo cáo rà soát](DATASET_REVIEW.md).

## Nguồn và giấy phép

- [calamansi-ripeness, phiên bản 1](https://universe.roboflow.com/jobbie/calamansi-ripeness-cvxus/dataset/1), Jobbie, 2025.
- Nguồn công bố 989 ảnh detection với nhãn unripe, ripe, rotten.
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); giữ ATTRIBUTION.txt khi chia sẻ.
- Dữ liệu calamansi tham khảo, cần kiểm chứng trên đúng giống quất/tắc và camera hệ thống.

Bản trước rà soát có 1.761 crop ảnh, cắt theo COCO bbox với 10% padding, bỏ
crop cạnh ngắn dưới 32 pixel, ban đầu ánh xạ unripe → GREEN, ripe → RIPE,
rotten → REJECT. Bản hiện tại đã bổ sung quyết định sửa nhãn ngoại hình;
chạy lại importer đơn thuần sẽ không tái tạo các sửa nhãn này.

## Những bản đã dọn

Đã bỏ bản dữ liệu cũ tại đường dẫn chính, thư mục `datasets/kumquat-curated/`,
bản giải nén `kumquat-dataset-only/` và thư mục rà soát trung gian `dataset-review/`.
Bản đã sửa nhãn được chuyển về đường dẫn chính `datasets/kumquat/`, nên code
đang dùng đường dẫn mặc định tiếp tục lấy đúng dữ liệu mới.

Nhật ký, 414 ảnh loại, metadata gốc và hướng dẫn khôi phục được nén vào
**`docs/dataset-review-2026-10-27.zip`**. Đây là hồ sơ đối chiếu, không phải bộ
huấn luyện thứ hai. Có thể tái tạo đủ 1.761 ảnh gốc bằng hồ sơ này và ảnh trong
dataset hiện tại; đã đối chiếu SHA-256 trước và sau khi dọn.

## Bàn giao và huấn luyện

Gửi `kumquat-dataset-only.zip` cho người phụ trách train. Giải nén gói sẽ có
trực tiếp train/, val/, test/, README.txt và ATTRIBUTION.txt. Mỗi tập có ba
thư mục nhãn; đây là dữ liệu classification, không yêu cầu file bbox riêng.

Nếu dùng code sẵn của dự án để train cục bộ, dùng `--dataset datasets/kumquat`.
Nếu dùng notebook có sẵn của dự án, cần tạo gói đầy đủ theo
[AI_TRAIN_DEPLOY.md](AI_TRAIN_DEPLOY.md); ZIP chỉ chứa dataset không thay trực
tiếp cho gói notebook. Các file huấn luyện vẫn giữ để người phụ trách xử lý.

Ba ảnh mẫu trong cloud-ai/ phục vụ đối chiếu suy luận, không phải dataset dư.
