package vn.autosort;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.util.UUID;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/device/runs")
public class DeviceRunController {
  public record Run(
      @NotNull @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}") String cameraId,
      @NotNull @Pattern(regexp = "CONVEYOR|MANUAL_TEST") String mode) {}

  public record Beat(@NotNull @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}") String cameraId) {}

  public record Stop(
      @NotNull @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}") String cameraId,
      @NotNull @Pattern(regexp = "CONVEYOR|MANUAL_TEST") String mode,
      @NotNull
          @Pattern(
              regexp =
                  "NORMAL_STOP|CONTROLLER_FAULT|SERIAL_ERROR|START_FAILED|STOP_UNCONFIRMED|BRIDGE_ERROR")
          String reason) {}

  private final DeviceRunService runs;

  public DeviceRunController(DeviceRunService runs) {
    this.runs = runs;
  }

  @PostMapping("/{id}/start")
  public Object start(@PathVariable UUID id, @Valid @RequestBody Run body) {
    return runs.start(id, body.cameraId(), body.mode());
  }

  @PostMapping("/{id}/heartbeat")
  public Object heartbeat(@PathVariable UUID id, @Valid @RequestBody Beat body) {
    return runs.heartbeat(id, body.cameraId());
  }

  @PostMapping("/{id}/stop")
  public Object stop(@PathVariable UUID id, @Valid @RequestBody Stop body) {
    return runs.stop(id, body.cameraId(), body.mode(), body.reason());
  }
}
