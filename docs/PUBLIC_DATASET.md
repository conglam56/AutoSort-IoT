# Bộ ảnh tham khảo và gói huấn luyện AutoSort

## Hiện tại chỉ cần dùng

- `datasets/kumquat/`: bộ dữ liệu đã lọc, 1.761 ảnh; đây là dataset chính.
- `autosort-training.zip`: gói dataset và code để tải lên Colab.
- `training/AutoSort_Train.ipynb`: notebook huấn luyện.

Dataset và ZIP huấn luyện chỉ lưu trên máy, không nằm trong Git. Giữ ZIP COCO
nguồn riêng để có thể tạo lại dữ liệu theo hướng dẫn bên dưới. Ba ảnh mẫu gốc
nằm trong `cloud-ai/` và được đưa vào Git để chạy kiểm thử và parity.

Để train ngay, mở notebook và tải gói ZIP lên Colab; không cần giải nén lại,
chuyển nhãn hoặc tạo thêm thư mục dataset.

## Nguồn đã xác định

- Dataset: [calamansi-ripeness, phiên bản 1](https://universe.roboflow.com/jobbie/calamansi-ripeness-cvxus/dataset/1).
- Tác giả: Jobbie; công bố năm 2025.
- Trang nguồn ghi 989 ảnh: 830 train, 113 valid, 46 test; chưa áp dụng augmentation.
- Nhãn gốc: `unripe`, `ripe`, `rotten`.
- Giấy phép do nguồn công bố: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Đây là ảnh calamansi tham khảo. Cần kiểm tra lại trên đúng giống quất/tắc và camera của hệ thống.

Đây là dataset **object detection**, không đưa nguyên thư mục ảnh vào classification
rồi tự gán một nhãn cho toàn cảnh. Công cụ bên dưới cắt từng quả theo COCO bbox,
thêm 10% vùng đệm mặc định, bỏ crop có cạnh ngắn dưới 32 pixel và ánh xạ `unripe → GREEN`, `ripe → RIPE`,
`rotten → REJECT`.

## Tạo lại dữ liệu khi cần (không cần trước khi train)

Phần này chỉ dùng khi muốn xây dựng lại dataset từ ZIP nguồn. Dữ liệu hiện tại
đã chuẩn bị xong; công cụ sẽ từ chối ghi đè `datasets/kumquat/` đang có.

Trên trang phiên bản nguồn, chọn **COCO JSON → Download dataset → Download zip
to computer**. Roboflow có thể yêu cầu đăng nhập và chấp nhận điều khoản tài khoản.
Không đưa API key hoặc mã tải có khóa riêng vào repository.

Giải nén ZIP vào `dataset_raw/calamansi-coco/`, sao cho các thư mục `train`,
`valid`, `test` nằm trực tiếp bên trong thư mục đó. Mỗi tập có
`_annotations.coco.json` và các ảnh nguồn.

```powershell
.\cloud-ai\.venv\Scripts\python.exe training/import_roboflow.py --src dataset_raw/calamansi-coco --dest datasets/kumquat
```

Công cụ kiểm tra nhãn, đường dẫn, kích thước ảnh và bbox trước khi tạo đầu ra;
giữ nguyên các tập của nguồn, loại bản sao ảnh gốc trùng pixel, rồi xuất:

```text
datasets/kumquat/
├── train/{GREEN,REJECT,RIPE}/
├── val/{GREEN,REJECT,RIPE}/
├── test/{GREEN,REJECT,RIPE}/
├── dataset_manifest.json
└── ATTRIBUTION.txt
```

Tất cả crop từ cùng một ảnh gốc ở cùng tập. Dữ liệu không có mã định danh từng
quả vật lý nên chưa bảo đảm phát hiện các ảnh gần trùng hoặc các góc chụp khác nhau
của cùng một quả. Công cụ từ chối ghi đè thư mục đầu ra đã tồn tại.

Ba ảnh `quatsample.jpg`, `ripe.jpg`, `reject.jpg` của bạn vẫn được giữ riêng để
đối chiếu PyTorch–ONNX, không được nhân bản để tạo tập validation/test.

## Đóng gói và huấn luyện

Bộ dữ liệu đã chuyển trong workspace ngày 20/10/2026:

| Nhãn | Train | Validation | Test | Tổng |
| --- | ---: | ---: | ---: | ---: |
| GREEN | 1.059 | 88 | 18 | 1.165 |
| RIPE | 268 | 57 | 11 | 336 |
| REJECT | 178 | 48 | 34 | 260 |
| Tổng | 1.505 | 193 | 63 | 1.761 |

Đã loại 19 crop có cạnh ngắn dưới 32 pixel (17 train, 2 validation); không phát
hiện ảnh gốc trùng pixel. Dữ liệu có sự chênh lệch số
lượng giữa các lớp; cần xem kết quả theo lớp và các nhầm lẫn khi đánh giá,
không chỉ dựa vào Top-1 tổng thể.

Gói `autosort-training.zip` đã có sẵn. Lệnh dưới chỉ dùng khi cần đóng gói lại;
chọn tên đầu ra mới nếu muốn giữ gói hiện có:

```powershell
.\cloud-ai\.venv\Scripts\python.exe training/package_colab.py --dataset datasets/kumquat --output autosort-training.zip
```

Gói giữ đúng đường dẫn `datasets/kumquat/`, gồm mã huấn luyện, notebook,
helper inference và ba ảnh parity. Công cụ chỉ đóng gói danh sách file cần thiết,
kiểm tra ZIP sau khi tạo và từ chối ghi đè gói đã có.

Mở `training/AutoSort_Train.ipynb` trong Google Colab, chọn T4 GPU, chạy từng ô
và tải `autosort-training.zip` lên khi được hỏi. Notebook lần lượt kiểm tra ảnh,
huấn luyện 30 epochs, xuất ONNX, đối chiếu ba ảnh mẫu và tải về
`autosort-model-artifacts.zip`.

`training/train.py` kiểm tra các lớp không rỗng và ảnh đọc được trước khi tải mô
hình/thư viện huấn luyện. Mỗi lần chạy dùng một thư mục run mới; đường dẫn
`best.pt` và kết quả test được ghi tại `runs/autosort/latest_run.json`.

Chỉ có file model và kết quả kiểm thử thật sau khi các ô huấn luyện đã chạy thành công.
