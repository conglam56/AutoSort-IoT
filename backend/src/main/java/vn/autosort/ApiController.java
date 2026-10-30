package vn.autosort;

import com.fasterxml.jackson.databind.node.NullNode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@Validated
public class ApiController {
  private final Db db;
  private final SortingService sorting;
  private final InferenceEngine engine;

  public ApiController(Db db, SortingService sorting, InferenceEngine engine) {
    this.db = db;
    this.sorting = sorting;
    this.engine = engine;
  }

  @GetMapping("/")
  public ResponseEntity<?> root() {
    return ResponseEntity.status(307).header("Location", "/dashboard/").build();
  }

  @GetMapping({"/dashboard", "/dashboard/"})
  public ResponseEntity<?> dashboard() {
    return ResponseEntity.status(307).header("Location", "/dashboard/index.html").build();
  }

  @GetMapping("/ready")
  public Object ready() {
    db.ready();
    return Db.map("status", "ready", "model_ready", engine.health().get("model_ready"));
  }

  @GetMapping("/health")
  public Object health() {
    var result =
        Db.map(
            "status",
            "ok",
            "service",
            "quat-sort-ai",
            "backend",
            "spring-boot",
            "idempotency_supported",
            true);
    result.put("automatic_sessions_supported", true);
    result.put("web_control_supported", true);
    result.putAll(engine.health());
    return result;
  }

  @GetMapping("/api/session/current")
  public Object current() {
    var result = sorting.current();
    return result == null ? NullNode.getInstance() : result;
  }

  @GetMapping("/api/sessions")
  public Object sessions() {
    return sorting.list();
  }

  @GetMapping("/api/sessions/{id}")
  public Object session(@PathVariable String id) {
    try {
      return sorting.get(UUID.fromString(id));
    } catch (IllegalArgumentException error) {
      throw new ApiError(404, "Session not found");
    }
  }

  @PostMapping("/api/sessions/new")
  public Object start(
      HttpServletRequest request,
      @RequestHeader(value = "Idempotency-Key", required = false)
          @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}")
          String key) {
    return sorting.start(request, key);
  }

  @PostMapping("/api/sessions/{id}/end")
  public Object end(
      @PathVariable UUID id,
      HttpServletRequest request,
      @RequestHeader(value = "Idempotency-Key", required = false)
          @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}")
          String key) {
    return sorting.end(id, request, key);
  }

  @GetMapping("/api/audit-logs")
  public Object audit() {
    return sorting.audit();
  }

  @PostMapping(value = "/infer", consumes = "multipart/form-data")
  public Object infer(
      @RequestParam @Size(min = 1, max = 128) String fruit_id,
      @RequestParam @Size(min = 1, max = 128) String camera_id,
      @RequestPart MultipartFile image,
      @RequestHeader(value = "Idempotency-Key", required = false)
          @Pattern(regexp = "[A-Za-z0-9_.:-]{1,128}")
          String key,
      @RequestHeader(value = "X-Run-Id", required = false) UUID runId)
      throws java.io.IOException {
    if (!Set.of("image/jpeg", "image/jpg").contains(Objects.toString(image.getContentType(), "")))
      throw new ApiError(415, "Only image/jpeg is supported");
    if (image.isEmpty()) throw new ApiError(400, "Image is empty");
    if (image.getSize() > 1_000_000) throw new ApiError(413, "Image must be 1 MB or smaller");
    byte[] bytes = image.getInputStream().readNBytes(1_000_001);
    if (bytes.length > 1_000_000) throw new ApiError(413, "Image must be 1 MB or smaller");
    if (bytes.length < 2 || bytes[0] != (byte) 0xff || bytes[1] != (byte) 0xd8)
      throw new ApiError(400, "Invalid JPEG data");
    return sorting.infer(
        key, fruit_id, camera_id, bytes, runId, () -> engine.classify(fruit_id, camera_id, bytes));
  }
}
