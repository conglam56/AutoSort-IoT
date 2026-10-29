package vn.autosort;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.Cookie;
import java.net.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

@SpringBootTest
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "AUTOSORT_TEST_DATABASE_URL", matches = ".+")
class BackendIntegrationTest {
  @Test
  void inferenceAndEndSerializeWithoutWritingAfterCompletion() throws Exception {
    var operator = login("operator");
    String id = value(write("/api/sessions/new", Map.of(), operator, 200)).path("id").asText();
    var entered = new CountDownLatch(1);
    var release = new CountDownLatch(1);
    try (var pool = Executors.newFixedThreadPool(2)) {
      var image =
          pool.submit(
              () ->
                  sorting.infer(
                      "inflight",
                      "F-inflight",
                      "phone",
                      new byte[] {1},
                      () -> {
                        entered.countDown();
                        try {
                          if (!release.await(10, TimeUnit.SECONDS))
                            throw new IllegalStateException("Test release timeout");
                        } catch (InterruptedException error) {
                          throw new IllegalStateException(error);
                        }
                        return Db.map(
                            "fruit_id",
                            "F-inflight",
                            "camera_id",
                            "phone",
                            "label",
                            "MOCK",
                            "confidence",
                            0.,
                            "inference_ms",
                            0.,
                            "decision_reason",
                            "MOCK_MODE",
                            "model_version",
                            "mock-v0");
                      }));
      try {
        assertTrue(entered.await(5, TimeUnit.SECONDS));
        var end = pool.submit(() -> write("/api/sessions/" + id + "/end", Map.of(), operator, 200));
        release.countDown();
        image.get(10, TimeUnit.SECONDS);
        end.get(10, TimeUnit.SECONDS);
      } finally {
        release.countDown();
      }
    }
    assertEquals(
        0,
        ((Number)
                db.one(
                        "SELECT count(*) AS n FROM fruit_results f JOIN sorting_sessions s ON"
                            + " s.id=f.session_id WHERE f.recorded_at>s.end_time")
                    .get("n"))
            .intValue());
    assertEquals(
        409,
        assertThrows(
                ApiError.class,
                () ->
                    sorting.infer(
                        "late-after-end",
                        "F-late",
                        "phone",
                        new byte[] {1},
                        () -> {
                          throw new AssertionError("AI must not run without session");
                        }))
            .status);
  }

  @Test
  void guestAndForgedOperatorCannotBypassPolicies() throws Exception {
    mvc.perform(post("/api/sessions/new")).andExpect(status().isUnauthorized());
    var operator = login("operator");
    mvc.perform(get("/api/admin/users").cookie(operator.cookie).header("X-Role", "admin"))
        .andExpect(status().isForbidden());
    write(
        "/api/admin/users",
        Map.of("username", "intruder", "password", PASSWORD, "role", "admin"),
        operator,
        403);
    var admin = login("admin");
    for (String role : List.of("guest", "viewer"))
      write(
          "/api/admin/users",
          Map.of("username", "invalidrole", "password", PASSWORD, "role", role),
          admin,
          422);
    mvc.perform(
            post("/api/auth/login")
                .header("Origin", ORIGIN)
                .contentType("application/json")
                .content(
                    json.writeValueAsString(
                        Map.of("username", "operator", "password", PASSWORD, "role", "admin"))))
        .andExpect(status().isUnprocessableEntity());
  }

  @Test
  void sessionStartAndEndRetriesAreIdempotentAndAudited() throws Exception {
    var operator = login("operator");
    var first =
        mvc.perform(
                post("/api/sessions/new")
                    .cookie(operator.cookie)
                    .header("Origin", ORIGIN)
                    .header("X-CSRF-Token", operator.csrf)
                    .header("Idempotency-Key", "start-once"))
            .andExpect(status().isOk())
            .andReturn();
    String id = value(first).path("id").asText();
    mvc.perform(
            post("/api/sessions/new")
                .cookie(operator.cookie)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", operator.csrf)
                .header("Idempotency-Key", "start-once"))
        .andExpect(jsonPath("$.id").value(id));
    mvc.perform(
            post("/api/sessions/" + id + "/end").cookie(operator.cookie).header("Origin", ORIGIN))
        .andExpect(status().isForbidden());
    var ended = value(write("/api/sessions/" + id + "/end", Map.of(), operator, 200));
    assertEquals(ended, value(write("/api/sessions/" + id + "/end", Map.of(), operator, 200)));
    String next = value(write("/api/sessions/new", Map.of(), operator, 200)).path("id").asText();
    write("/api/sessions/" + id + "/end", Map.of(), operator, 200);
    assertEquals(
        next,
        db.one("SELECT id FROM sorting_sessions WHERE status='RUNNING'").get("id").toString());
    assertEquals(
        1,
        ((Number)
                db.one(
                        "SELECT count(*) AS n FROM audit_logs WHERE"
                            + " starts_with(action,'session.completed:') AND user_id=?",
                        UUID.fromString(operator.id))
                    .get("n"))
            .intValue());
  }

  @Test
  void endedSessionsRejectNewImagesWithoutAutoStartingAndReplayOldReceipts() throws Exception {
    var operator = login("operator");
    infer("no-session", "F-0", "phone", sample(), 409);
    assertEquals(
        0, ((Number) db.one("SELECT count(*) AS n FROM sorting_sessions").get("n")).intValue());
    String id = value(write("/api/sessions/new", Map.of(), operator, 200)).path("id").asText();
    var result = value(infer("original", "F-1", "phone", sample(), 200));
    write("/api/sessions/" + id + "/end", Map.of(), operator, 200);
    infer("late", "F-2", "phone", sample(), 409);
    assertEquals(result, value(infer("original", "F-1", "phone", sample(), 200)));
    assertEquals(
        1, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
    mvc.perform(get("/api/session/current").cookie(operator.cookie))
        .andExpect(content().string("null"));
    mvc.perform(get("/api/auth/me").cookie(operator.cookie))
        .andExpect(jsonPath("$.role").value("operator"));
  }

  @Test
  void rollbackDisablesOperatorsAndPreservesRowsThenCanMigrateAgain() throws Exception {
    var operator = login("operator");
    write("/api/sessions/new", Map.of(), operator, 200);
    infer("rollback-data", "F-1", "phone", sample(), 200);
    var overrides = new HashMap<String, Object>();
    overrides.put("MIGRATE_DATABASE", "true");
    environment
        .getPropertySources()
        .addFirst(new org.springframework.core.env.MapPropertySource("rollback-test", overrides));
    try {
      var ds = db.jdbc.getDataSource();
      try (var connection = ds.getConnection()) {
        org.springframework.jdbc.datasource.init.ScriptUtils.executeSqlScript(
            connection,
            new org.springframework.core.io.ClassPathResource(
                "db/rollback/V3__operator_roles_and_session_lifecycle.sql"));
      }
      assertEquals(
          false, db.one("SELECT active FROM app_users WHERE username='operator'").get("active"));
      assertEquals(
          "viewer", db.one("SELECT role FROM app_users WHERE username='operator'").get("role"));
      assertEquals(
          1, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
      assertEquals(
          0,
          ((Number)
                  db.one(
                          "SELECT count(*) AS n FROM auth_sessions WHERE user_id=?",
                          UUID.fromString(operator.id))
                      .get("n"))
              .intValue());
    } finally {
      db.initialize();
      environment.getPropertySources().remove("rollback-test");
    }
  }

  @Autowired org.springframework.core.env.ConfigurableEnvironment environment;
  static final String SCHEMA =
      "autosort_java_test_" + UUID.randomUUID().toString().replace("-", "");
  static final String PASSWORD = "Integration-only-password-2026!",
      KEY = "integration-only-device-" + UUID.randomUUID();
  static final String ORIGIN = "http://localhost:8000";
  static final Path ROOT =
      Path.of(System.getProperty("projectRoot", "..")).toAbsolutePath().normalize();
  @Autowired MockMvc mvc;
  @Autowired Db db;
  @Autowired AuthService auth;
  @Autowired SortingService sorting;
  @Autowired ObjectMapper json;
  @Autowired PasswordEncoder passwords;

  static Connection connection() throws Exception {
    URI uri = URI.create(System.getenv("AUTOSORT_TEST_DATABASE_URL"));
    if (!List.of("127.0.0.1", "localhost").contains(uri.getHost()))
      throw new IllegalStateException("Tests require a dedicated localhost PostgreSQL");
    String[] user = uri.getUserInfo().split(":", 2);
    return DriverManager.getConnection(
        "jdbc:postgresql://"
            + uri.getHost()
            + ":"
            + (uri.getPort() < 0 ? 5432 : uri.getPort())
            + uri.getPath(),
        user[0],
        user[1]);
  }

  @DynamicPropertySource
  static void configure(DynamicPropertyRegistry registry) throws Exception {
    try (var c = connection();
        var s = c.createStatement()) {
      s.execute("CREATE SCHEMA " + SCHEMA);
    }
    registry.add("DATABASE_URL", () -> System.getenv("AUTOSORT_TEST_DATABASE_URL"));
    registry.add("DATABASE_SCHEMA", () -> SCHEMA);
    registry.add("DATABASE_SSLMODE", () -> "disable");
    registry.add("COOKIE_SECURE", () -> "false");
    registry.add("ALLOWED_ORIGINS", () -> ORIGIN);
    registry.add("DEVICE_API_KEY", () -> KEY);
    registry.add("INITIALIZE_DATABASE", () -> "true");
    registry.add("BOOTSTRAP_ADMIN_PASSWORD", () -> PASSWORD);
    registry.add(
        "PYTHON_BIN",
        () ->
            System.getenv()
                .getOrDefault(
                    "AUTOSORT_TEST_PYTHON",
                    ROOT.resolve("cloud-ai/.venv312/Scripts/python.exe").toString()));
    registry.add("AI_WORKER_PATH", () -> ROOT.resolve("cloud-ai/worker.py").toString());
    registry.add(
        "AI_MODEL_DIR", () -> ROOT.resolve("backend/target/missing-test-model").toString());
    registry.add("RENDER", () -> "false");
  }

  @AfterAll
  static void cleanSchema() throws Exception {
    try (var c = connection();
        var s = c.createStatement()) {
      s.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
    }
  }

  @BeforeEach
  void reset() {
    db.jdbc.execute(
        "TRUNCATE app_users,auth_sessions,sorting_sessions,fruit_results,audit_logs,login_limits"
            + " RESTART IDENTITY CASCADE");
    for (String role : List.of("admin", "operator"))
      db.jdbc.update(
          "INSERT INTO app_users(id,username,password_hash,role) VALUES (?,?,?,?)",
          UUID.randomUUID(),
          role,
          passwords.encode(PASSWORD),
          role);
  }

  record Session(Cookie cookie, String csrf, String id) {}

  Session login(String user, String password) throws Exception {
    var result =
        mvc.perform(
                post("/api/auth/login")
                    .header("Origin", ORIGIN)
                    .contentType("application/json")
                    .content(
                        json.writeValueAsString(Map.of("username", user, "password", password))))
            .andExpect(status().isOk())
            .andReturn();
    var value = json.readTree(result.getResponse().getContentAsString());
    return new Session(
        result.getResponse().getCookie(AuthService.COOKIE),
        value.path("csrfToken").asText(),
        value.path("id").asText());
  }

  Session login(String user) throws Exception {
    return login(user, PASSWORD);
  }

  MvcResult write(String path, Object body, Session session, int expected) throws Exception {
    return mvc.perform(
            post(path)
                .cookie(session.cookie)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", session.csrf)
                .contentType("application/json")
                .content(json.writeValueAsString(body)))
        .andExpect(status().is(expected))
        .andReturn();
  }

  JsonNode value(MvcResult result) throws Exception {
    return json.readTree(result.getResponse().getContentAsString());
  }

  UUID id(String name) {
    return (UUID) db.one("SELECT id FROM app_users WHERE username=?", name).get("id");
  }

  byte[] sample() throws Exception {
    return Files.readAllBytes(ROOT.resolve("cloud-ai/quatsample.jpg"));
  }

  MvcResult infer(String key, String fruit, String camera, byte[] image, int expected)
      throws Exception {
    return mvc.perform(
            multipart("/infer")
                .file(new MockMultipartFile("image", "fruit.jpg", "image/jpeg", image))
                .param("fruit_id", fruit)
                .param("camera_id", camera)
                .header("X-API-Key", KEY)
                .header("Idempotency-Key", key))
        .andExpect(status().is(expected))
        .andReturn();
  }

  @Test
  void servesDashboardModulesAndHealth() throws Exception {
    mvc.perform(get("/dashboard/index.html"))
        .andExpect(status().isOk())
        .andExpect(content().string(org.hamcrest.Matchers.containsString("tab-admin-btn")));
    mvc.perform(get("/dashboard/admin.js")).andExpect(status().isOk());
    mvc.perform(get("/dashboard/app.js")).andExpect(status().isOk());
    mvc.perform(get("/ready"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("ready"));
    mvc.perform(get("/health"))
        .andExpect(jsonPath("$.backend").value("spring-boot"))
        .andExpect(jsonPath("$.mode").value("mock"))
        .andExpect(jsonPath("$.idempotency_supported").value(true));
  }

  @Test
  void anonymousAndDeviceAuthenticationAreSeparate() throws Exception {
    mvc.perform(get("/api/sessions")).andExpect(status().isUnauthorized());
    mvc.perform(get("/api/admin/users")).andExpect(status().isUnauthorized());
    var operator = login("operator");
    mvc.perform(
            multipart("/infer")
                .file(new MockMultipartFile("image", sample()))
                .cookie(operator.cookie))
        .andExpect(status().isUnauthorized());
    mvc.perform(get("/api/sessions").header("X-API-Key", KEY)).andExpect(status().isUnauthorized());
  }

  @Test
  void operatorReadsDoNotCreateSessionAndCanOperateButNotAdmin() throws Exception {
    var operator = login("operator");
    mvc.perform(get("/api/session/current").cookie(operator.cookie))
        .andExpect(content().string("null"));
    write("/api/sessions/new", Map.of(), operator, 200);
    write("/api/sessions/new", Map.of(), operator, 409);
    write("/api/admin/users", Map.of("username", "intruder", "password", PASSWORD), operator, 403);
    mvc.perform(get("/api/admin/users").cookie(operator.cookie)).andExpect(status().isForbidden());
    assertEquals(
        1,
        ((Number)
                db.one("SELECT count(*) AS n FROM sorting_sessions WHERE status='RUNNING'")
                    .get("n"))
            .intValue());
  }

  @Test
  void cookieCsrfOriginAndLogoutMatchContract() throws Exception {
    var admin = login("admin");
    assertTrue(admin.cookie.isHttpOnly());
    assertEquals("Lax", admin.cookie.getAttribute("SameSite"));
    assertEquals(28800, admin.cookie.getMaxAge());
    mvc.perform(post("/api/sessions/new").cookie(admin.cookie).header("Origin", ORIGIN))
        .andExpect(status().isForbidden());
    mvc.perform(
            post("/api/sessions/new")
                .cookie(admin.cookie)
                .header("Origin", "https://evil.example")
                .header("X-CSRF-Token", admin.csrf))
        .andExpect(status().isForbidden());
    mvc.perform(get("/api/auth/me").cookie(admin.cookie))
        .andExpect(jsonPath("$.id").value(admin.id));
    assertEquals(
        AuthService.digest(admin.cookie.getValue()),
        db.one("SELECT token_hash FROM auth_sessions").get("token_hash"));
    write("/api/auth/logout", Map.of(), admin, 200);
    mvc.perform(get("/api/auth/me").cookie(admin.cookie)).andExpect(status().isUnauthorized());
  }

  @Test
  void expiredOrDisabledAccountCannotUseCookie() throws Exception {
    var operator = login("operator");
    db.jdbc.update("UPDATE auth_sessions SET expires_at=now()-interval '1 second'");
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    operator = login("operator");
    db.jdbc.update("UPDATE app_users SET active=false WHERE username='operator'");
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
  }

  @Test
  void loginLimitsPersistAndErrorsDoNotRevealAccount() throws Exception {
    for (int i = 0; i < 10; i++)
      mvc.perform(
              post("/api/auth/login")
                  .header("Origin", ORIGIN)
                  .contentType("application/json")
                  .content("{\"username\":\"admin\",\"password\":\"incorrect-password\"}"))
          .andExpect(status().isUnauthorized())
          .andExpect(jsonPath("$.detail").value("Invalid username or password"));
    mvc.perform(
            post("/api/auth/login")
                .header("Origin", ORIGIN)
                .contentType("application/json")
                .content("{\"username\":\"admin\",\"password\":\"incorrect-password\"}"))
        .andExpect(status().isTooManyRequests())
        .andExpect(header().string("Retry-After", "900"));
    assertEquals(
        0, ((Number) db.one("SELECT count(*) AS n FROM auth_sessions").get("n")).intValue());
  }

  @Test
  void adminCreatesSearchesPaginatesAndNeverExposesSecrets() throws Exception {
    var admin = login("admin");
    var created =
        value(
            write(
                "/api/admin/users",
                Map.of("username", " New.Member ", "password", PASSWORD),
                admin,
                201));
    assertEquals("new.member", created.path("username").asText());
    assertEquals("operator", created.path("role").asText());
    write("/api/admin/users", Map.of("username", "new.member", "password", PASSWORD), admin, 409);
    var list =
        mvc.perform(get("/api/admin/users").param("search", "new.member").cookie(admin.cookie))
            .andExpect(status().isOk())
            .andReturn();
    assertEquals(1, value(list).path("total").asInt());
    assertFalse(list.getResponse().getContentAsString().contains("password_hash"));
    mvc.perform(get("/api/admin/users").param("limit", "101").cookie(admin.cookie))
        .andExpect(status().isUnprocessableEntity());
    write("/api/admin/users", Map.of("username", "invalid name", "password", PASSWORD), admin, 422);
    write("/api/admin/users", Map.of("username", "validname", "password", "short"), admin, 422);
    write(
        "/api/admin/users",
        Map.of("username", "validname", "password", PASSWORD, "unknown", true),
        admin,
        422);
    mvc.perform(get("/api/admin/audit-logs").param("kind", "account").cookie(admin.cookie))
        .andExpect(jsonPath("$.logs[0].username").value("admin"));
  }

  @Test
  void lastAdminAndOwnAccessAreProtected() throws Exception {
    var admin = login("admin");
    var response =
        value(
            write(
                "/api/admin/users/" + admin.id + "/settings",
                Map.of("role", "operator", "active", false),
                admin,
                409));
    assertEquals("LAST_ADMIN_REQUIRED", response.path("detail").asText());
    write(
        "/api/admin/users",
        Map.of("username", "secondadmin", "password", PASSWORD, "role", "admin"),
        admin,
        201);
    response =
        value(
            write(
                "/api/admin/users/" + admin.id + "/settings",
                Map.of("role", "operator", "active", true),
                admin,
                409));
    assertEquals("CANNOT_CHANGE_OWN_ACCESS", response.path("detail").asText());
    write("/api/admin/users/" + admin.id + "/password", Map.of("password", PASSWORD), admin, 409);
    write("/api/admin/users/" + admin.id + "/revoke-sessions", Map.of(), admin, 409);
  }

  @Test
  void roleAndStatusChangesRevokeExistingSessions() throws Exception {
    var admin = login("admin");
    var operator = login("operator");
    String path = "/api/admin/users/" + operator.id + "/settings";
    write(path, Map.of("role", "admin", "active", true), admin, 200);
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    operator = login("operator");
    mvc.perform(get("/api/admin/users").cookie(operator.cookie)).andExpect(status().isOk());
    write(path, Map.of("role", "operator", "active", false), admin, 200);
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    write(path, Map.of("role", "operator", "active", true), admin, 200);
    login("operator");
    write(path, Map.of("role", "operator", "active", "true"), admin, 422);
  }

  @Test
  void resetRevokeAndOwnPasswordChangeInvalidateSessions() throws Exception {
    var admin = login("admin");
    var operator = login("operator");
    String prefix = "/api/admin/users/" + operator.id;
    write(prefix + "/revoke-sessions", Map.of(), admin, 200);
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    operator = login("operator");
    write(prefix + "/password", Map.of("password", "Replacement-only-password!"), admin, 200);
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    operator = login("operator", "Replacement-only-password!");
    write(
        "/api/auth/password",
        Map.of("current_password", "wrong", "new_password", PASSWORD),
        operator,
        400);
    write(
        "/api/auth/password",
        Map.of("current_password", "Replacement-only-password!", "new_password", PASSWORD),
        operator,
        200);
    mvc.perform(get("/api/auth/me").cookie(operator.cookie)).andExpect(status().isUnauthorized());
    login("operator");
  }

  @Test
  void staleAdminActorIsRecheckedWithinWriteTransaction() throws Exception {
    var admin = login("admin");
    var request = new MockHttpServletRequest();
    request.setCookies(admin.cookie);
    request.setAttribute("autosort.user", auth.current(request));
    db.jdbc.update("UPDATE app_users SET role='operator' WHERE id=?", UUID.fromString(admin.id));
    assertEquals(
        403,
        assertThrows(ApiError.class, () -> db.transaction(() -> auth.lockActor(request, true)))
            .status);
    sorting.start(request);
    db.jdbc.update("DELETE FROM auth_sessions");
    assertEquals(401, assertThrows(ApiError.class, () -> sorting.start(request)).status);
  }

  @Test
  void inferenceUsesWorkerAndReceiptIsStableAcrossRolloverAndConcurrentRetries() throws Exception {
    write("/api/sessions/new", Map.of(), login("operator"), 200);
    byte[] jpeg = sample();
    String first = value(infer("same-key", "F-1", "phone", jpeg, 200)).toString();
    var admin = login("admin");
    String original =
        value(mvc.perform(get("/api/session/current").cookie(admin.cookie)).andReturn())
            .path("id")
            .asText();
    write("/api/sessions/" + original + "/end", Map.of(), admin, 200);
    write("/api/sessions/new", Map.of(), admin, 200);
    try (var executor = Executors.newFixedThreadPool(4)) {
      var tasks = new ArrayList<Callable<String>>();
      for (int i = 0; i < 8; i++)
        tasks.add(() -> value(infer("same-key", "F-1", "phone", jpeg, 200)).toString());
      for (var future : executor.invokeAll(tasks))
        assertEquals(json.readTree(first), json.readTree(future.get()));
    }
    assertEquals(
        1, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
    assertEquals(
        original, db.one("SELECT session_id FROM fruit_results").get("session_id").toString());
    mvc.perform(get("/api/sessions/" + original).cookie(admin.cookie))
        .andExpect(jsonPath("$.fruits[0].decisionReason").value("MOCK_MODE"));
    infer("same-key", "other", "phone", jpeg, 409);
    infer("same-key", "F-1", "other", jpeg, 409);
    infer("same-key", "F-1", "phone", Files.readAllBytes(ROOT.resolve("cloud-ai/ripe.jpg")), 409);
  }

  @Test
  void concurrentStartsCreateOnlyOneRunningSession() throws Exception {
    var operator = login("operator");
    try (var pool = Executors.newFixedThreadPool(2)) {
      var tasks =
          List.<Callable<Integer>>of(() -> startStatus(operator), () -> startStatus(operator));
      var statuses = new ArrayList<Integer>();
      for (var future : pool.invokeAll(tasks)) statuses.add(future.get());
      Collections.sort(statuses);
      assertEquals(List.of(200, 409), statuses);
    }
    assertEquals(
        1, ((Number) db.one("SELECT count(*) AS n FROM sorting_sessions").get("n")).intValue());
  }

  int startStatus(Session operator) throws Exception {
    return mvc.perform(
            post("/api/sessions/new")
                .cookie(operator.cookie)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", operator.csrf))
        .andReturn()
        .getResponse()
        .getStatus();
  }

  @Test
  void invalidImagesAndBadKeysDoNotCreateRows() throws Exception {
    write("/api/sessions/new", Map.of(), login("operator"), 200);
    infer("bad-key", "F-1", "phone", new byte[] {(byte) 0xff, (byte) 0xd8, 1, 2}, 400);
    infer("bad key", "F-1", "phone", sample(), 422);
    infer("oversize", "F-1", "phone", new byte[1_000_001], 413);
    mvc.perform(
            multipart("/infer")
                .file(new MockMultipartFile("image", "bad.png", "image/png", sample()))
                .param("fruit_id", "F-1")
                .param("camera_id", "phone")
                .header("X-API-Key", KEY))
        .andExpect(status().isUnsupportedMediaType());
    assertEquals(
        0, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
  }

  @Test
  void inferenceAndReceiptRollbackTogether() throws Exception {
    write("/api/sessions/new", Map.of(), login("operator"), 200);
    byte[] jpeg = sample();
    assertThrows(
        IllegalStateException.class,
        () ->
            sorting.infer(
                "rollback",
                "F-1",
                "phone",
                jpeg,
                () -> {
                  throw new IllegalStateException("test failure");
                }));
    assertEquals(
        0, ((Number) db.one("SELECT count(*) AS n FROM inference_requests").get("n")).intValue());
    infer("rollback", "F-1", "phone", jpeg, 200);
  }

  @Test
  void bootstrapAndAdditiveMigrationPreserveExistingAccounts() {
    var before = db.one("SELECT * FROM app_users WHERE username='admin'");
    db.initialize();
    assertEquals(before, db.one("SELECT * FROM app_users WHERE username='admin'"));
  }

  @Test
  void migrationQuarantinesLegacyViewersWithoutGrantingOperatorAndKeepsData() throws Exception {
    write("/api/sessions/new", Map.of(), login("admin"), 200);
    infer("old-data", "F-old", "phone", sample(), 200);
    var old = login("operator");
    db.jdbc.execute("DROP TABLE session_requests");
    db.jdbc.execute("DROP TABLE legacy_viewer_quarantine");
    db.jdbc.update("DELETE FROM schema_version WHERE version=3");
    db.jdbc.execute("ALTER TABLE app_users DROP CONSTRAINT app_users_role_check");
    db.jdbc.update("UPDATE app_users SET role='viewer' WHERE username='operator'");
    db.jdbc.execute(
        "ALTER TABLE app_users ADD CONSTRAINT app_users_role_check CHECK(role IN"
            + " ('admin','viewer'))");
    var before = db.one("SELECT password_hash FROM app_users WHERE username='operator'");
    var overrides = new HashMap<String, Object>();
    overrides.put("MIGRATE_DATABASE", "false");
    environment
        .getPropertySources()
        .addFirst(new org.springframework.core.env.MapPropertySource("migration-test", overrides));
    try {
      assertThrows(IllegalStateException.class, db::initialize);
      overrides.put("MIGRATE_DATABASE", "true");
      db.initialize();
      db.ready();
      var legacy = db.one("SELECT * FROM app_users WHERE username='operator'");
      assertEquals("viewer", legacy.get("role"));
      assertEquals(false, legacy.get("active"));
      assertEquals(before.get("password_hash"), legacy.get("password_hash"));
      mvc.perform(get("/api/auth/me").cookie(old.cookie)).andExpect(status().isUnauthorized());
      assertEquals(
          1, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
      var admin = login("admin");
      write(
          "/api/admin/users/" + old.id + "/settings",
          Map.of("role", "operator", "active", true),
          admin,
          200);
      login("operator");
    } finally {
      overrides.put("MIGRATE_DATABASE", "true");
      db.initialize();
      environment.getPropertySources().remove("migration-test");
    }
  }

  @Test
  void simultaneousFirstRequestsUseOneReceipt() throws Exception {
    write("/api/sessions/new", Map.of(), login("operator"), 200);
    byte[] jpeg = sample();
    try (var executor = Executors.newFixedThreadPool(4)) {
      var tasks = new ArrayList<Callable<JsonNode>>();
      for (int i = 0; i < 8; i++) tasks.add(() -> value(infer("first", "F-1", "phone", jpeg, 200)));
      JsonNode first = null;
      for (var future : executor.invokeAll(tasks)) {
        var result = future.get();
        if (first == null) first = result;
        else assertEquals(first, result);
      }
    }
    assertEquals(
        1, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
    assertEquals(
        1, ((Number) db.one("SELECT count(*) AS n FROM inference_requests").get("n")).intValue());
  }

  @Test
  void concurrentAdminsCannotDisableAllAdministrators() throws Exception {
    var first = login("admin");
    write(
        "/api/admin/users",
        Map.of("username", "secondadmin", "password", PASSWORD, "role", "admin"),
        first,
        201);
    var second = login("secondadmin");
    try (var executor = Executors.newFixedThreadPool(2)) {
      var tasks =
          List.<Callable<Integer>>of(
              () -> disable(second, first.id), () -> disable(first, second.id));
      for (var future : executor.invokeAll(tasks))
        assertTrue(List.of(200, 401, 409).contains(future.get()));
    }
    assertEquals(
        1,
        ((Number)
                db.one("SELECT count(*) AS n FROM app_users WHERE active AND role='admin'")
                    .get("n"))
            .intValue());
  }

  int disable(Session actor, String target) throws Exception {
    return mvc.perform(
            post("/api/admin/users/" + target + "/settings")
                .cookie(actor.cookie)
                .header("Origin", ORIGIN)
                .header("X-CSRF-Token", actor.csrf)
                .contentType("application/json")
                .content("{\"role\":\"admin\",\"active\":false}"))
        .andReturn()
        .getResponse()
        .getStatus();
  }

  @Test
  void failedReceiptSerializationRollsBackTheFruitInsert() throws Exception {
    write("/api/sessions/new", Map.of(), login("operator"), 200);
    byte[] jpeg = sample();
    assertThrows(
        ApiError.class,
        () ->
            sorting.infer(
                "atomic",
                "F-1",
                "phone",
                jpeg,
                () ->
                    Db.map(
                        "fruit_id",
                        "F-1",
                        "camera_id",
                        "phone",
                        "label",
                        "MOCK",
                        "confidence",
                        0.,
                        "inference_ms",
                        0.,
                        "decision_reason",
                        "MOCK_MODE",
                        "model_version",
                        "mock-v0",
                        "invalid",
                        new Object())));
    assertEquals(
        0, ((Number) db.one("SELECT count(*) AS n FROM fruit_results").get("n")).intValue());
    infer("atomic", "F-1", "phone", jpeg, 200);
  }
}
