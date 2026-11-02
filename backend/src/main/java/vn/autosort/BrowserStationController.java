package vn.autosort;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Pattern;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Function;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

/** A cookie/CSRF-authenticated station agent. No device key is sent to the browser. */
@RestController
@Validated
@RequestMapping("/api/browser-station/{connection}")
public class BrowserStationController {
  private final Db db;
  private final AuthService auth;
  private final StationService station;
  private final ApiController api;

  public BrowserStationController(
      Db db, AuthService auth, StationService station, ApiController api) {
    this.db = db;
    this.auth = auth;
    this.station = station;
    this.api = api;
  }

  private UUID identity(HttpServletRequest request, UUID connection) {
    try {
      var mac = Mac.getInstance("HmacSHA256");
      mac.init(
          new SecretKeySpec(
              auth.actor(request).get("token_hash").toString().getBytes(StandardCharsets.UTF_8),
              "HmacSHA256"));
      var bytes =
          ByteBuffer.wrap(mac.doFinal(connection.toString().getBytes(StandardCharsets.UTF_8)));
      return new UUID(bytes.getLong(), bytes.getLong());
    } catch (java.security.GeneralSecurityException error) {
      throw new IllegalStateException("Cannot bind browser station identity", error);
    }
  }

  private <T> T authorized(
      HttpServletRequest request, UUID connection, Function<UUID, T> operation) {
    return db.transaction(
        () -> {
          auth.lockActor(request, false);
          db.stationLock();
          return operation.apply(identity(request, connection));
        });
  }

  private String camera(UUID agent) {
    return "browser-" + agent.toString().replace("-", "");
  }

  @PostMapping("/register")
  public Object register(@PathVariable UUID connection, HttpServletRequest request) {
    return authorized(
        request,
        connection,
        agent ->
            Db.map("cameraId", camera(agent), "station", station.register(agent, camera(agent))));
  }

  @PostMapping("/poll")
  public Object poll(@PathVariable UUID connection, HttpServletRequest request) {
    return authorized(request, connection, station::poll);
  }

  @PostMapping("/prepare/{id}")
  public Object prepare(
      @PathVariable UUID connection, @PathVariable UUID id, HttpServletRequest request) {
    return authorized(request, connection, agent -> station.prepareBrowserStart(agent, id));
  }

  @PostMapping("/ack/{id}")
  public Object ack(
      @PathVariable UUID connection,
      @PathVariable UUID id,
      @Valid @RequestBody StationController.Ack body,
      HttpServletRequest request) {
    return authorized(
        request, connection, agent -> station.ack(agent, id, body.state(), body.success()));
  }

  @PostMapping("/disconnect")
  public Object disconnect(@PathVariable UUID connection, HttpServletRequest request) {
    return authorized(request, connection, station::disconnectBrowser);
  }

  @PostMapping(value = "/infer", consumes = "multipart/form-data")
  public Object infer(
      @PathVariable UUID connection,
      @RequestParam UUID runId,
      @RequestParam @Pattern(regexp = "[1-9][0-9]{0,9}") String counter,
      @RequestPart MultipartFile image,
      HttpServletRequest request)
      throws java.io.IOException {
    if (Long.parseLong(counter) > 0xffffffffL) throw new ApiError(400, "Invalid fruit counter");
    UUID agent =
        authorized(
            request,
            connection,
            current -> {
              var row =
                  db.one(
                      "SELECT *,last_seen > clock_timestamp()-interval '15 seconds' AS online"
                          + " FROM station_state WHERE id=1");
              if (!Objects.equals(row.get("agent_id"), current)
                  || !Boolean.TRUE.equals(row.get("online")))
                throw new ApiError(409, "AGENT_EXPIRED");
              if (!Objects.equals(row.get("run_id"), runId)
                  || !Set.of("RUNNING", "PAUSED").contains(row.get("reported"))
                  || db.one(
                          "SELECT id FROM station_commands WHERE agent_id=? AND action='STOP'"
                              + " AND status IN ('PENDING','DELIVERED')",
                          current)
                      != null) throw new ApiError(409, "DEVICE_RUN_MISMATCH");
              return current;
            });
    // Release the station lock during AI. SortingService still serializes run/end/inference;
    // the browser discards late results after STOP, just like the Python bridge.
    String key = "browser:" + agent + ":" + runId + ":" + counter;
    String fruit = "F-" + runId.toString().replace("-", "") + "-" + counter;
    return api.infer(fruit, camera(agent), image, key, runId);
  }
}
