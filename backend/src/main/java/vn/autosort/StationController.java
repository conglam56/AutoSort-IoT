package vn.autosort;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.UUID;
import org.springframework.web.bind.annotation.*;

@RestController
public class StationController {
  public record Command(
      @NotNull @Pattern(regexp = "START|PAUSE|RESUME|STOP") String action,
      @NotNull @PositiveOrZero Long revision) {}

  public record Register(@NotNull @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}") String cameraId) {}

  public record Ack(
      @NotNull @Pattern(regexp = "IDLE|RUNNING|PAUSED|FAULT") String state,
      @NotNull Boolean success) {}

  private final StationService station;

  public StationController(StationService station) {
    this.station = station;
  }

  @GetMapping("/api/station")
  public Object current() {
    return station.current();
  }

  @PostMapping("/api/station/commands")
  public Object command(
      @RequestHeader("Idempotency-Key") @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}") String key,
      @Valid @RequestBody Command body,
      HttpServletRequest request) {
    return station.enqueue(key, body.action(), body.revision(), request);
  }

  @PostMapping("/device/station/{agent}/register")
  public Object register(@PathVariable UUID agent, @Valid @RequestBody Register body) {
    return station.register(agent, body.cameraId());
  }

  @PostMapping("/device/station/{agent}/poll")
  public Object poll(@PathVariable UUID agent) {
    return station.poll(agent);
  }

  @PostMapping("/device/station/{agent}/ack/{id}")
  public Object ack(@PathVariable UUID agent, @PathVariable UUID id, @Valid @RequestBody Ack body) {
    return station.ack(agent, id, body.state(), body.success());
  }

  @PostMapping("/device/station/{agent}/fault")
  public Object fault(@PathVariable UUID agent) {
    return station.fault(agent);
  }
}
