package vn.autosort;

import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
public class DeviceRunService {
  public static final int LEASE_SECONDS = 90;
  private final Db db;

  public DeviceRunService(Db db) {
    this.db = db;
  }

  private Map<String, Object> view(Map<String, Object> row) {
    return Db.map(
        "runId",
        row.get("run_id").toString(),
        "sessionId",
        row.get("session_id") == null ? null : row.get("session_id").toString(),
        "status",
        row.get("ended_at") == null ? "RUNNING" : "COMPLETED",
        "endReason",
        row.get("end_reason"),
        "leaseSeconds",
        LEASE_SECONDS);
  }

  private void match(Map<String, Object> row, String camera, String mode) {
    if (!Objects.equals(row.get("camera_id"), camera)
        || (mode != null && !Objects.equals(row.get("mode"), mode)))
      throw new ApiError(409, "RUN_ID_REUSED");
  }

  // Called under the same transaction/advisory lock as inference/start/end.
  void expireLocked() {
    var stale =
        db.jdbc.queryForList(
            "SELECT * FROM device_runs WHERE ended_at IS NULL"
                + " AND last_seen < clock_timestamp() - interval '90 seconds' FOR UPDATE");
    for (var row : stale) closeLocked(row, "CONNECTION_LOST");
  }

  @Scheduled(fixedDelay = 10000)
  public void expire() {
    db.transaction(
        () -> {
          db.sortingLock();
          expireLocked();
          return null;
        });
  }

  private Map<String, Object> closeLocked(Map<String, Object> row, String reason) {
    if (row.get("ended_at") != null) return row;
    if (row.get("session_id") != null) {
      db.jdbc.update(
          "UPDATE sorting_sessions SET status='COMPLETED',end_time=clock_timestamp(),"
              + " end_reason=? WHERE id=? AND status='RUNNING'",
          reason,
          row.get("session_id"));
    }
    var closed =
        db.one(
            "UPDATE device_runs SET ended_at=clock_timestamp(),end_reason=?"
                + " WHERE run_id=? RETURNING *",
            reason,
            row.get("run_id"));
    db.audit("session.device-ended:" + reason + ":" + row.get("run_id"), null, "device");
    return closed;
  }

  public Object start(UUID run, String camera, String mode) {
    return db.transaction(
        () -> {
          db.sortingLock();
          expireLocked();
          var existing = db.one("SELECT * FROM device_runs WHERE run_id=?", run);
          if (existing != null) {
            match(existing, camera, mode);
            return view(existing);
          }
          if (db.one("SELECT id FROM sorting_sessions WHERE status='RUNNING'") != null)
            throw new ApiError(409, "SESSION_ALREADY_RUNNING");
          var session = UUID.randomUUID();
          String name =
              (mode.equals("CONVEYOR") ? "Phiên " : "Phiên thử ảnh ")
                  + ZonedDateTime.now(ZoneId.of("Asia/Ho_Chi_Minh"))
                      .format(DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm:ss"));
          db.jdbc.update(
              "INSERT INTO sorting_sessions(id,name,status,start_time)"
                  + " VALUES (?,?,'RUNNING',clock_timestamp())",
              session,
              name);
          var row =
              db.one(
                  "INSERT INTO device_runs(run_id,camera_id,mode,session_id)"
                      + " VALUES (?,?,?,?) RETURNING *",
                  run,
                  camera,
                  mode,
                  session);
          db.jdbc.update("UPDATE sorting_sessions SET device_run_id=? WHERE id=?", run, session);
          db.audit("session.device-started:" + run, null, "device");
          return view(row);
        });
  }

  public Object heartbeat(UUID run, String camera) {
    return db.transaction(
        () -> {
          db.sortingLock();
          expireLocked();
          var row = db.one("SELECT * FROM device_runs WHERE run_id=?", run);
          if (row == null) throw new ApiError(404, "RUN_NOT_FOUND");
          match(row, camera, null);
          if (row.get("ended_at") != null) throw new ApiError(409, "RUN_ENDED");
          return view(
              db.one(
                  "UPDATE device_runs SET last_seen=clock_timestamp() WHERE run_id=? RETURNING *",
                  run));
        });
  }

  public Object stop(UUID run, String camera, String mode, String reason) {
    return db.transaction(
        () -> {
          db.sortingLock();
          expireLocked();
          var row = db.one("SELECT * FROM device_runs WHERE run_id=?", run);
          if (row == null) {
            // Tombstone prevents a delayed/retried START from opening a session after STOP.
            row =
                db.one(
                    "INSERT INTO device_runs(run_id,camera_id,mode,ended_at,end_reason)"
                        + " VALUES (?,?,?,clock_timestamp(),?) RETURNING *",
                    run,
                    camera,
                    mode,
                    reason);
          } else {
            match(row, camera, mode);
            row = closeLocked(row, reason);
          }
          return view(row);
        });
  }

  void assertActive(UUID run, String camera) {
    expireLocked();
    var active = db.one("SELECT * FROM sorting_sessions WHERE status='RUNNING'");
    if (active == null) throw new ApiError(409, "SESSION_NOT_RUNNING");
    if (!Objects.equals(active.get("device_run_id"), run))
      throw new ApiError(409, "DEVICE_RUN_MISMATCH");
    if (run != null) {
      var row = db.one("SELECT * FROM device_runs WHERE run_id=?", run);
      if (row == null || row.get("ended_at") != null) throw new ApiError(409, "RUN_ENDED");
      match(row, camera, null);
    }
  }
}
