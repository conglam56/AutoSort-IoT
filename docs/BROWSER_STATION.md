# Kết nối trạm ngay trên dashboard

Mở dashboard bằng Chrome trên laptop nối ESP32. Trình duyệt thay bridge
Python: đọc ảnh camera, gửi cloud AI và nhận/gửi lệnh USB Serial.
Không cần terminal, Python hoặc nhập device API key để dùng cách này.
DroidCam Client/driver vẫn cần hoạt động để điện thoại xuất hiện như camera
trên laptop. Dùng HTTPS trên cloud; localhost được cho phép khi kiểm thử.

## Vận hành

1. Nạp firmware AutoSortSerial điều khiển web, giữ đủ ba file của gói firmware.
   Với bản chờ vật ngày 02/11, IR nằm ngay đầu vào. Đóng Serial Monitor và bridge
   Python. Nếu ESP32 đang FAULT, kiểm tra rồi nhấn EN/RESET.
2. Mở DroidCam, cắm điện thoại và ESP32 vào laptop, xác nhận DroidCam có hình.
3. Đăng nhập Admin/Operator, bấm **Kết nối thiết bị**.
4. Bấm **Chọn ESP32**, cấp quyền đúng cổng USB. Bấm **Bật camera**,
   chọn DroidCam, kiểm tra hình xem trước. Quyền do Chrome quản lý; web có
   thể dùng lại cổng duy nhất đã được cấp quyền.
5. Bấm **Kết nối trạm**, chờ ESP32 xác nhận. Motor vẫn dừng, chưa mở phiên.
6. Để IR trống rồi bấm **Bắt đầu**. Firmware chờ vật sẽ chờ IR trước khi quay.
   Đặt từng vật; chụp/chờ AI và chờ vật kế tiếp giữ cùng phiên.
7. **Tạm dừng / Tiếp tục / Kết thúc** như trước. Kết thúc chờ ACK trước
   khi đóng phiên; bridge vẫn kết nối để có thể bắt đầu phiên khác.
8. Muốn nhả USB/camera: mở hộp kết nối, bấm **Ngắt thiết bị**.
   Đăng xuất cũng ngắt kết nối trước khi kết thúc đăng nhập.

Giữ tab điều khiển **hiển thị** khi vận hành. Bản này chủ động ngắt nếu tab
bị ẩn, vì trình duyệt có thể hạn chế timer ở nền. Ẩn/đóng/tải lại trang hoặc
mất USB/mạng có thể cần RESET ESP32 và kết nối lại; không tự phát lại lệnh.
Khi trang đang đóng, gửi STOP/ngắt cloud chỉ là cố gắng; watchdog firmware và
lease server vẫn dừng/đóng phiên khi không còn liên lạc. Không cam kết dừng
tức thì khi trang hoặc máy tính bị treo.

## Luồng và quyền

- Chỉ một agent giữ trạm online. Browser/Python dùng chung lease/command/ACK,
  không vận hành đồng thời. Web Locks ngăn hai tab mở bridge cùng lúc.
- Các route /api/browser-station dùng cookie HttpOnly và CSRF. Identity agent
  được HMAC từ phiên đăng nhập và nonce kết nối; phiên đăng nhập khác không
  thể dùng nonce đó để chiếm trạm. Không có device key/database URL trong JS.
- Register/poll/prepare/ack/disconnect dùng StationService hiện có. Prepare
  chỉ mở run cho START đang DELIVERED, trước khi CONTROL xuống ESP32.
  Nếu STOP đã thay START thì không mở phiên hoặc gửi START muộn.
- Route infer trình duyệt chỉ nhận ảnh của agent/run thuộc phiên hiện tại.
  Server sinh camera/fruit/key, giữ giới hạn JPEG, idempotency và transaction.
  Route /infer cũ của thiết bị vẫn yêu cầu device key.
- PING USB độc lập với request AI/poll. Buffer Serial có giới hạn, ghép
  CRLF/LF và hạn 1 giây cho dòng dở; ghi lỗi không nối STOP vào dòng chưa rõ.
- Timeout mạng ngắn hoặc HTTP 408/429/500/502/503/504 khi poll được thử lại
  sau 0,5 giây, giữ PING USB. Hạn mỗi request tối đa 4 giây và hạn im lặng
  cloud 12 giây tính bảo thủ từ lúc gửi poll thành công gần nhất; timer USB
  cũng kiểm tra hạn này, trước lease server 15 giây. Quá hạn thì ngắt trạm;
  phản hồi đến muộn không làm trạm chạy lại. Lỗi quyền/xung đột ngắt ngay.
  Chỉ thử lại poll, không phát lại lệnh motor, prepare hoặc ACK.
- Mỗi TRIGGER tạo một JPEG mới, tối đa một RESULT đúng run/counter.
  STOP hủy job và bỏ kết quả muộn. PAUSE giữ phiên.
- Model vẫn là V2-640, giữ policy hiện tại; không thêm zoom/crop/ghép model.

## Kiểm thử

Chạy node --test tests/browser_station.test.mjs để kiểm tra Serial chia đoạn,
lệnh trùng, ACK sai/quá hạn, STOP thay START, AI muộn, auth/run conflict,
fallback và ghi Serial không rõ kết quả.

BackendIntegrationTest dùng PostgreSQL localhost riêng để kiểm tra login,
CSRF, ràng buộc phiên, bridge thứ hai, START/STOP, ảnh đúng run, idempotency,
disconnect và route device cũ. Không thêm migration.

tests/browser_station_e2e.cjs cần server Spring/ONNX/PostgreSQL localhost riêng
và Playwright. Truyền AUTOSORT_BROWSER_ORIGIN, BOOTSTRAP_ADMIN_PASSWORD cho
tài khoản test admin, PLAYWRIGHT_MODULE nếu không nằm trong node_modules.
Test dùng camera Chromium giả lập và Serial fixture qua backend/ONNX/DB thật;
không mở COM thật hay ghi cloud. Nó kiểm tra desktop/mobile, multipart JPEG,
PAUSE giữ phiên, STOP hủy AI muộn và ẩn tab ngắt agent.

Chưa kiểm chứng Web Serial với board/driver ESP32 và DroidCam thật của nhóm
trong lượt này. Chạy thử tại trạm để kiểm tra quyền, reset USB và đúng camera.
