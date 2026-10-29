package vn.autosort;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.stereotype.Service;

@Service
public class InferenceEngine {
  private final Settings settings;
  private final ObjectMapper json;
  private final ExecutorService reader =
      Executors.newSingleThreadExecutor(
          r -> {
            var t = new Thread(r, "onnx-worker-output");
            t.setDaemon(true);
            return t;
          });
  private volatile Process process;
  private BufferedReader output;
  private BufferedWriter input;
  private volatile Map<String, Object> state =
      Map.of(
          "mode",
          "mock",
          "model_ready",
          false,
          "classes",
          List.of("MOCK"),
          "model_version",
          "mock-v0",
          "threshold",
          0.0);

  public InferenceEngine(Settings settings, ObjectMapper json) {
    this.settings = settings;
    this.json = json;
  }

  @PostConstruct
  public void initialize() {
    state = exchange(Map.of("operation", "health"));
  }

  public Map<String, Object> health() {
    if (process == null || !process.isAlive())
      return Map.of(
          "mode",
          "mock",
          "model_ready",
          false,
          "classes",
          List.of("MOCK"),
          "model_version",
          "mock-v0",
          "threshold",
          0.0);
    return new LinkedHashMap<>(state);
  }

  private void start() throws IOException {
    var builder =
        new ProcessBuilder(
            settings.get("PYTHON_BIN", "python"),
            "-u",
            settings.get("AI_WORKER_PATH", "cloud-ai/worker.py"));
    builder.environment().put("AI_MODEL_DIR", settings.get("AI_MODEL_DIR", "cloud-ai/model"));
    builder.environment().put("OMP_NUM_THREADS", "1");
    builder.redirectError(ProcessBuilder.Redirect.INHERIT);
    process = builder.start();
    output =
        new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
    input =
        new BufferedWriter(
            new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
  }

  private synchronized Map<String, Object> exchange(Map<String, Object> message) {
    Future<String> task = null;
    try {
      if (process == null || !process.isAlive()) start();
      String payload = json.writeValueAsString(message);
      BufferedWriter currentInput = input;
      BufferedReader currentOutput = output;
      // Bound both pipe writing and reading, including a worker restart/model load.
      task =
          reader.submit(
              () -> {
                currentInput.write(payload);
                currentInput.newLine();
                currentInput.flush();
                return currentOutput.readLine();
              });
      String line = task.get(65, TimeUnit.SECONDS);
      if (line == null || line.length() > 32768)
        throw new IOException("Worker response unavailable");
      var response = json.readTree(line);
      if (!response.path("ok").asBoolean())
        throw new ApiError(
            response.path("status").asInt(500), response.path("detail").asText("Inference failed"));
      return json.convertValue(response.get("result"), new TypeReference<>() {});
    } catch (ApiError error) {
      throw error;
    } catch (Exception error) {
      if (task != null) task.cancel(true);
      if (process != null) process.destroyForcibly();
      if (error instanceof InterruptedException) Thread.currentThread().interrupt();
      throw new ApiError(503, "AI worker unavailable. Please try again");
    }
  }

  public synchronized Map<String, Object> classify(String fruit, String camera, byte[] image) {
    var result =
        exchange(
            Map.of(
                "operation",
                "infer",
                "fruit_id",
                fruit,
                "camera_id",
                camera,
                "image",
                Base64.getEncoder().encodeToString(image)));
    String label = Objects.toString(result.get("label"), "");
    if (!Objects.equals(result.get("fruit_id"), fruit)
        || !Objects.equals(result.get("camera_id"), camera)
        || !Set.of("GREEN", "RIPE", "REJECT", "MOCK").contains(label)
        || !(result.get("confidence") instanceof Number confidence)
        || !Double.isFinite(confidence.doubleValue())
        || confidence.doubleValue() < 0
        || confidence.doubleValue() > 1) throw new ApiError(500, "Invalid AI worker response");
    return result;
  }

  @PreDestroy
  public void close() {
    if (process != null) process.destroy();
    reader.shutdownNow();
  }
}
