package vn.autosort;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.security.MessageDigest;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.stereotype.Service;

@Service
public class SortingService {
  private final Db db;
  private final AuthService auth;
  private final ObjectMapper json;

  public SortingService(Db db, AuthService auth, ObjectMapper json) {
    this.db = db;
    this.auth = auth;
    this.json = json;
  }

  private Map<String, Object> session(Map<String, Object> row) {
    return Db.map(
        "id",
        row.get("id").toString(),
        "name",
        row.get("name"),
        "status",
        row.get("status"),
        "startTime",
        Db.iso(row.get("start_time")),
        "endTime",
        Db.iso(row.get("end_time")));
  }

  private Map<String, Object> detail(Map<String, Object> row) {
    if (row == null) return null;
    var result = session(row);
    var fruits =
        db.jdbc.queryForList(
            "SELECT * FROM fruit_results WHERE session_id=? ORDER BY sequence", row.get("id"));
    result.put(
        "fruits",
        fruits.stream()
            .map(
                f ->
                    Db.map(
                        "id",
                        f.get("fruit_id"),
                        "recordId",
                        f.get("sequence").toString(),
                        "cameraId",
                        f.get("camera_id"),
                        "sessionId",
                        f.get("session_id").toString(),
                        "label",
                        f.get("label"),
                        "confidence",
                        f.get("confidence"),
                        "timestamp",
                        Db.iso(f.get("recorded_at")),
                        "inferenceMs",
                        f.get("inference_ms"),
                        "image",
                        f.get("image"),
                        "decisionReason",
                        f.get("decision_reason"),
                        "modelVersion",
                        f.get("model_version"),
                        "servoAction",
                        f.get("servo_action")))
            .toList());
    return result;
  }

  public Map<String, Object> current() {
    return detail(db.one("SELECT * FROM sorting_sessions WHERE status='RUNNING'"));
  }

  public Object list() {
    return db
        .jdbc
        .queryForList(
            "SELECT s.*,count(f.sequence) AS fruit_count FROM sorting_sessions s LEFT JOIN"
                + " fruit_results f ON f.session_id=s.id GROUP BY s.id ORDER BY s.start_time")
        .stream()
        .map(
            row -> {
              var result = session(row);
              result.put("fruitCount", row.get("fruit_count"));
              return result;
            })
        .toList();
  }

  public Object get(UUID id) {
    var row = db.one("SELECT * FROM sorting_sessions WHERE id=?", id);
    if (row == null) throw new ApiError(404, "Session not found");
    return detail(row);
  }

  private Map<String, Object> active() {
    var row = db.one("SELECT * FROM sorting_sessions WHERE status='RUNNING'");
    if (row != null) return row;
    String name =
        "Phiên "
            + ZonedDateTime.now(ZoneId.of("Asia/Ho_Chi_Minh"))
                .format(DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm"));
    return db.one(
        "INSERT INTO sorting_sessions(id,name,status) VALUES (?,?,'RUNNING') RETURNING *",
        UUID.randomUUID(),
        name);
  }

  public Object start(HttpServletRequest request) {
    return db.transaction(
        () -> {
          var actor = auth.lockActor(request, true);
          db.sortingLock();
          db.jdbc.update(
              "UPDATE sorting_sessions SET status='COMPLETED',end_time=now() WHERE"
                  + " status='RUNNING'");
          var row = active();
          db.audit("session.created", actor.get("id"), auth.ip(request));
          return detail(row);
        });
  }

  private long insert(Map<String, Object> result, byte[] image) {
    String snapshot =
        image.length < 300_000
            ? "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(image)
            : "";
    String action =
        switch (result.get("label").toString()) {
          case "GREEN" -> "Gạt Cổng 1 (Green)";
          case "RIPE" -> "Gạt Cổng 2 (Ripe)";
          case "REJECT" -> "Trôi Cuối (Reject)";
          case "MOCK" -> "Không điều khiển · MOCK";
          default -> throw new ApiError(500, "Invalid inference label");
        };
    db.sortingLock();
    var session = active();
    var row =
        db.one(
            "INSERT INTO"
                + " fruit_results(session_id,fruit_id,camera_id,label,confidence,inference_ms,image,decision_reason,model_version,servo_action)"
                + " VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING sequence",
            session.get("id"),
            result.get("fruit_id"),
            result.get("camera_id"),
            result.get("label"),
            result.get("confidence"),
            result.get("inference_ms"),
            snapshot,
            result.get("decision_reason"),
            result.get("model_version"),
            action);
    return ((Number) row.get("sequence")).longValue();
  }

  private String fingerprint(byte[] bytes) {
    try {
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (Exception error) {
      throw new IllegalStateException(error);
    }
  }

  public Map<String, Object> infer(
      String key,
      String fruit,
      String camera,
      byte[] bytes,
      Supplier<Map<String, Object>> classify) {
    return db.transaction(
        () -> {
          String hash = fingerprint(bytes);
          if (key != null) {
            db.jdbc.queryForList("SELECT pg_advisory_xact_lock(83417004,hashtext(?))", key);
            var previous =
                db.one(
                    "SELECT image_sha256,response::text FROM inference_requests WHERE"
                        + " request_key=?",
                    key);
            if (previous != null) {
              Map<String, Object> receipt;
              try {
                receipt =
                    json.readValue(previous.get("response").toString(), new TypeReference<>() {});
              } catch (Exception error) {
                throw new ApiError(500, "Invalid stored inference receipt");
              }
              if (!previous.get("image_sha256").equals(hash)
                  || !Objects.equals(receipt.get("fruit_id"), fruit)
                  || !Objects.equals(receipt.get("camera_id"), camera))
                throw new ApiError(409, "IDEMPOTENCY_KEY_REUSED");
              return receipt;
            }
          }
          var result = new LinkedHashMap<>(classify.get());
          if (key != null) result.put("request_id", key);
          long sequence = insert(result, bytes);
          if (key != null) {
            String receipt;
            try {
              receipt = json.writeValueAsString(result);
            } catch (Exception error) {
              throw new ApiError(500, "Invalid inference response");
            }
            db.jdbc.update(
                "INSERT INTO inference_requests(request_key,image_sha256,result_id,response) VALUES"
                    + " (?,?,?,CAST(? AS jsonb))",
                key,
                hash,
                sequence,
                receipt);
          }
          return result;
        });
  }

  public Object audit() {
    var rows =
        db.jdbc.queryForList(
            "SELECT a.id,a.action,a.ip_address,a.created_at,u.username FROM audit_logs a LEFT JOIN"
                + " app_users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100");
    rows.forEach(row -> row.put("created_at", Db.iso(row.get("created_at"))));
    return rows;
  }
}
