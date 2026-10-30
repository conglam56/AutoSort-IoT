package vn.autosort;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
public class StationService {
  private final Db db;
  private final AuthService auth;
  private final DeviceRunService runs;

  public StationService(Db db, AuthService auth, DeviceRunService runs) {
    this.db = db;
    this.auth = auth;
    this.runs = runs;
  }

  private Map<String, Object> row() {
    return db.one(
        "SELECT *,last_seen > clock_timestamp()-interval '15 seconds' AS online FROM station_state"
            + " WHERE id=1");
  }

  private Map<String, Object> commandView(Map<String, Object> c) {
    if (c == null) return null;
    return Db.map(
        "id",
        c.get("id").toString(),
        "action",
        c.get("action"),
        "runId",
        c.get("run_id").toString(),
        "status",
        c.get("status"),
        "detail",
        c.get("detail"),
        "expiresAt",
        Db.iso(c.get("expires_at")),
        "expiresInSeconds",
        Math.max(
            0,
            java.time.Duration.between(
                        java.time.Instant.now(),
                        java.time.Instant.parse(Db.iso(c.get("expires_at"))))
                    .toMillis()
                / 1000.0));
  }

  private void endRun(Map<String, Object> s, String reason) {
    if (s.get("run_id") != null)
      runs.stop((UUID) s.get("run_id"), s.get("camera_id").toString(), "CONVEYOR", reason);
  }

  private void expireLocked() {
    var s = row();
    if (s.get("agent_id") != null
        && !Boolean.TRUE.equals(s.get("online"))
        && !s.get("reported").equals("OFFLINE")) {
      endRun(s, "CONNECTION_LOST");
      for (var command :
          db.jdbc.queryForList(
              "SELECT DISTINCT run_id FROM station_commands WHERE status IN"
                  + " ('PENDING','DELIVERED')"))
        runs.stop(
            (UUID) command.get("run_id"),
            s.get("camera_id").toString(),
            "CONVEYOR",
            "CONNECTION_LOST");
      db.jdbc.update(
          "UPDATE station_state SET reported='OFFLINE',run_id=NULL,revision=revision+1 WHERE id=1");
      db.jdbc.update(
          "UPDATE station_commands SET"
              + " status='FAILED',detail='BRIDGE_OFFLINE',finished_at=clock_timestamp() WHERE"
              + " status IN ('PENDING','DELIVERED')");
    }
    var expired =
        db.jdbc.queryForList(
            "SELECT * FROM station_commands WHERE status IN ('PENDING','DELIVERED') AND"
                + " expires_at<=clock_timestamp()");
    for (var c : expired) {
      db.jdbc.update(
          "UPDATE station_commands SET"
              + " status='FAILED',detail='COMMAND_EXPIRED',finished_at=clock_timestamp() WHERE"
              + " id=?",
          c.get("id"));
      if (c.get("status").equals("DELIVERED")) {
        runs.stop(
            (UUID) c.get("run_id"),
            row().get("camera_id").toString(),
            "CONVEYOR",
            "STOP_UNCONFIRMED");
        db.jdbc.update(
            "UPDATE station_state SET reported='FAULT',run_id=NULL,revision=revision+1 WHERE id=1");
      } else if (c.get("action").equals("START")) {
        runs.stop(
            (UUID) c.get("run_id"), row().get("camera_id").toString(), "CONVEYOR", "START_FAILED");
      }
    }
  }

  @Scheduled(fixedDelay = 2000)
  public void sweep() {
    db.transaction(
        () -> {
          db.stationLock();
          expireLocked();
          return null;
        });
  }

  private Map<String, Object> snapshot() {
    var s = row();
    var latest = db.one("SELECT * FROM station_commands ORDER BY created_at DESC LIMIT 1");
    var pending =
        db.one(
            "SELECT * FROM station_commands WHERE status IN ('PENDING','DELIVERED') ORDER BY"
                + " created_at LIMIT 1");
    return Db.map(
        "online",
        Boolean.TRUE.equals(s.get("online")),
        "state",
        s.get("reported"),
        "revision",
        s.get("revision"),
        "pending",
        commandView(pending),
        "lastCommand",
        commandView(latest));
  }

  public Object current() {
    return db.transaction(
        () -> {
          db.stationLock();
          expireLocked();
          return snapshot();
        });
  }

  public Object enqueue(String key, String action, long revision, HttpServletRequest request) {
    return db.transaction(
        () -> {
          var actor = auth.lockActor(request, false);
          db.stationLock();
          expireLocked();
          var prior = db.one("SELECT * FROM station_commands WHERE request_key=?", key);
          if (prior != null) {
            if (!prior.get("actor_id").equals(actor.get("id"))
                || !prior.get("action").equals(action)
                || ((Number) prior.get("request_revision")).longValue() != revision)
              throw new ApiError(409, "IDEMPOTENCY_KEY_REUSED");
            return commandView(prior);
          }
          var s = row();
          if (!Boolean.TRUE.equals(s.get("online"))) throw new ApiError(409, "BRIDGE_OFFLINE");
          if (((Number) s.get("revision")).longValue() != revision)
            throw new ApiError(409, "STATION_CHANGED");
          var pending =
              db.one("SELECT * FROM station_commands WHERE status IN ('PENDING','DELIVERED')");
          if (pending != null && (!action.equals("STOP") || pending.get("action").equals("STOP")))
            throw new ApiError(409, "COMMAND_PENDING");
          String expected = s.get("reported").toString();
          boolean allowed =
              switch (action) {
                case "START" -> expected.equals("IDLE");
                case "PAUSE" -> expected.equals("RUNNING");
                case "RESUME" -> expected.equals("PAUSED");
                case "STOP" -> Set.of("RUNNING", "PAUSED").contains(expected) || pending != null;
                default -> false;
              };
          if (!allowed) throw new ApiError(409, "INVALID_STATION_STATE");
          if (action.equals("START")
              && db.one("SELECT id FROM sorting_sessions WHERE status='RUNNING'") != null)
            throw new ApiError(409, "SESSION_ALREADY_RUNNING");
          UUID run =
              action.equals("START")
                  ? UUID.randomUUID()
                  : pending != null ? (UUID) pending.get("run_id") : (UUID) s.get("run_id");
          if (pending != null)
            db.jdbc.update(
                "UPDATE station_commands SET"
                    + " status='FAILED',detail='SUPERSEDED_BY_STOP',finished_at=clock_timestamp()"
                    + " WHERE id=?",
                pending.get("id"));
          var c =
              db.one(
                  "INSERT INTO"
                      + " station_commands(id,request_key,actor_id,request_revision,agent_id,run_id,action)"
                      + " VALUES(?,?,?,?,?,?,?) RETURNING *",
                  UUID.randomUUID(),
                  key,
                  actor.get("id"),
                  revision,
                  s.get("agent_id"),
                  run,
                  action);
          db.jdbc.update("UPDATE station_state SET revision=revision+1 WHERE id=1");
          db.audit(
              "station.command:" + action + ":" + c.get("id"), actor.get("id"), auth.ip(request));
          return commandView(c);
        });
  }

  public Object register(UUID agent, String camera) {
    return db.transaction(
        () -> {
          db.stationLock();
          expireLocked();
          var s = row();
          if (Boolean.TRUE.equals(s.get("online")) && !Objects.equals(s.get("agent_id"), agent))
            throw new ApiError(409, "BRIDGE_ALREADY_CONNECTED");
          if (Objects.equals(s.get("agent_id"), agent)) {
            if (!Boolean.TRUE.equals(s.get("online"))
                || !Objects.equals(s.get("camera_id"), camera))
              throw new ApiError(409, "AGENT_EXPIRED");
            return snapshot();
          }
          db.jdbc.update(
              "UPDATE station_state SET"
                  + " agent_id=?,camera_id=?,last_seen=clock_timestamp(),reported='IDLE',run_id=NULL,revision=revision+1"
                  + " WHERE id=1",
              agent,
              camera);
          return snapshot();
        });
  }

  private Map<String, Object> agent(UUID agent) {
    var s = row();
    if (!Objects.equals(s.get("agent_id"), agent) || !Boolean.TRUE.equals(s.get("online")))
      throw new ApiError(409, "AGENT_EXPIRED");
    return s;
  }

  public Object poll(UUID agent) {
    return db.transaction(
        () -> {
          db.stationLock();
          expireLocked();
          agent(agent);
          db.jdbc.update("UPDATE station_state SET last_seen=clock_timestamp() WHERE id=1");
          db.jdbc.update(
              "UPDATE device_runs SET last_seen=clock_timestamp() WHERE ended_at IS NULL AND"
                  + " run_id=(SELECT run_id FROM station_state WHERE id=1)");
          var c =
              db.one(
                  "SELECT * FROM station_commands WHERE agent_id=? AND status IN"
                      + " ('PENDING','DELIVERED') ORDER BY created_at LIMIT 1",
                  agent);
          if (c != null && c.get("status").equals("PENDING"))
            c =
                db.one(
                    "UPDATE station_commands SET status='DELIVERED' WHERE id=? RETURNING *",
                    c.get("id"));
          return Db.map("command", commandView(c));
        });
  }

  public Object ack(UUID agent, UUID id, String state, boolean success) {
    return db.transaction(
        () -> {
          db.stationLock();
          db.sortingLock();
          expireLocked();
          var s = agent(agent);
          var c = db.one("SELECT * FROM station_commands WHERE id=? AND agent_id=?", id, agent);
          if (c == null) throw new ApiError(404, "COMMAND_NOT_FOUND");
          if (c.get("status").equals("SUCCEEDED"))
            return commandView(c); // Never reapply an old ACK to a newer run.
          if (!c.get("status").equals("DELIVERED")) throw new ApiError(409, "COMMAND_EXPIRED");
          String expected =
              switch (c.get("action").toString()) {
                case "START", "RESUME" -> "RUNNING";
                case "PAUSE" -> "PAUSED";
                default -> "IDLE";
              };
          if (success && !state.equals(expected)) throw new ApiError(409, "ACK_STATE_MISMATCH");
          if (success && !c.get("action").equals("STOP"))
            runs.assertActive((UUID) c.get("run_id"), s.get("camera_id").toString());
          if (success && c.get("action").equals("STOP"))
            runs.stop(
                (UUID) c.get("run_id"), s.get("camera_id").toString(), "CONVEYOR", "NORMAL_STOP");
          if (!success) {
            runs.stop(
                (UUID) c.get("run_id"),
                s.get("camera_id").toString(),
                "CONVEYOR",
                "CONTROLLER_FAULT");
          }
          String actual = success ? state : "FAULT";
          db.jdbc.update(
              "UPDATE station_state SET reported=?,run_id=?,revision=revision+1 WHERE id=1",
              actual,
              success && !actual.equals("IDLE") ? c.get("run_id") : null);
          db.jdbc.update(
              "UPDATE station_commands SET status=?,detail=?,finished_at=clock_timestamp() WHERE"
                  + " id=?",
              success ? "SUCCEEDED" : "FAILED",
              actual,
              id);
          return commandView(db.one("SELECT * FROM station_commands WHERE id=?", id));
        });
  }

  public Object fault(UUID agent) {
    return db.transaction(
        () -> {
          db.stationLock();
          expireLocked();
          var s = agent(agent);
          endRun(s, "CONTROLLER_FAULT");
          db.jdbc.update(
              "UPDATE station_state SET reported='FAULT',run_id=NULL,revision=revision+1 WHERE"
                  + " id=1");
          db.jdbc.update(
              "UPDATE station_commands SET"
                  + " status='FAILED',detail='CONTROLLER_FAULT',finished_at=clock_timestamp() WHERE"
                  + " status IN ('PENDING','DELIVERED')");
          return snapshot();
        });
  }
}
