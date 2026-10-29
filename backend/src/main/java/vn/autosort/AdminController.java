package vn.autosort;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/admin")
@Validated
public class AdminController {
  private final Db db;
  private final AuthService auth;
  private final PasswordEncoder passwords;

  public AdminController(Db db, AuthService auth, PasswordEncoder passwords) {
    this.db = db;
    this.auth = auth;
    this.passwords = passwords;
  }

  public record Create(
      @NotNull @Pattern(regexp = "[a-z0-9_.-]{3,64}") String username,
      @NotNull @Size(min = 12, max = 256) String password,
      @NotNull @Pattern(regexp = "admin|viewer") String role) {
    public Create {
      username = username == null ? null : username.strip().toLowerCase(Locale.ROOT);
      role = role == null ? "viewer" : role;
    }
  }

  public record Edit(
      @NotNull @Pattern(regexp = "admin|viewer") String role, @NotNull Boolean active) {}

  public record Password(@NotNull @Size(min = 12, max = 256) String password) {}

  static Map<String, Object> account(Map<String, Object> row) {
    return Db.map(
        "id",
        row.get("id").toString(),
        "username",
        row.get("username"),
        "role",
        row.get("role"),
        "active",
        row.get("active"),
        "createdAt",
        Db.iso(row.get("created_at")),
        "activeSessions",
        row.getOrDefault("active_sessions", 0));
  }

  private Map<String, Object> target(UUID id) {
    var row = db.one("SELECT * FROM app_users WHERE id=? FOR UPDATE", id);
    if (row == null) throw new ApiError(404, "ACCOUNT_NOT_FOUND");
    return row;
  }

  @GetMapping("/users")
  public Object users(
      @RequestParam(defaultValue = "") @Size(max = 64) String search,
      @RequestParam(defaultValue = "25") @Min(1) @Max(100) int limit,
      @RequestParam(defaultValue = "0") @Min(0) int offset) {
    String term = search.strip().toLowerCase(Locale.ROOT);
    var total =
        db.one("SELECT count(*) AS n FROM app_users WHERE position(? in username)>0", term)
            .get("n");
    var rows =
        db.jdbc.queryForList(
            "SELECT u.*,(SELECT count(*) FROM auth_sessions s WHERE s.user_id=u.id AND"
                + " s.expires_at>now()) AS active_sessions FROM app_users u WHERE position(? in"
                + " username)>0 ORDER BY u.created_at,u.id LIMIT ? OFFSET ?",
            term,
            limit,
            offset);
    return Db.map(
        "users",
        rows.stream().map(AdminController::account).toList(),
        "total",
        total,
        "limit",
        limit,
        "offset",
        offset);
  }

  @PostMapping("/users")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public Object create(@Valid @RequestBody Create body, HttpServletRequest request) {
    String hash = passwords.encode(body.password);
    try {
      return db.transaction(
          () -> {
            var actor = auth.lockActor(request, true);
            var row =
                db.one(
                    "INSERT INTO app_users(id,username,password_hash,role) VALUES (?,?,?,?)"
                        + " RETURNING *",
                    UUID.randomUUID(),
                    body.username,
                    hash,
                    body.role);
            db.audit("account.created:" + body.username, actor.get("id"), auth.ip(request));
            return account(row);
          });
    } catch (DuplicateKeyException error) {
      throw new ApiError(409, "USERNAME_EXISTS");
    }
  }

  @PostMapping("/users/{id}/settings")
  public Object edit(
      @PathVariable UUID id, @Valid @RequestBody Edit body, HttpServletRequest request) {
    return db.transaction(
        () -> {
          var actor = auth.lockActor(request, true);
          var target = target(id);
          boolean changed =
              !body.role.equals(target.get("role")) || !body.active.equals(target.get("active"));
          if (target.get("role").equals("admin")
              && Boolean.TRUE.equals(target.get("active"))
              && (!body.role.equals("admin") || !body.active)
              && db.one(
                      "SELECT id FROM app_users WHERE active AND role='admin' AND id<>? LIMIT 1",
                      id)
                  == null) throw new ApiError(409, "LAST_ADMIN_REQUIRED");
          if (id.equals(actor.get("id")) && changed)
            throw new ApiError(409, "CANNOT_CHANGE_OWN_ACCESS");
          if (changed) {
            db.jdbc.update(
                "UPDATE app_users SET role=?,active=? WHERE id=?", body.role, body.active, id);
            db.jdbc.update("DELETE FROM auth_sessions WHERE user_id=?", id);
            if (!body.role.equals(target.get("role")))
              db.audit(
                  "account.role_changed:" + target.get("username"),
                  actor.get("id"),
                  auth.ip(request));
            if (!body.active.equals(target.get("active")))
              db.audit(
                  (body.active ? "account.enabled:" : "account.disabled:") + target.get("username"),
                  actor.get("id"),
                  auth.ip(request));
          }
          return Map.of("ok", true);
        });
  }

  @PostMapping("/users/{id}/password")
  public Object reset(
      @PathVariable UUID id, @Valid @RequestBody Password body, HttpServletRequest request) {
    if (id.equals(auth.actor(request).get("id"))) throw new ApiError(409, "USE_OWN_PASSWORD_FORM");
    String hash = passwords.encode(body.password);
    return db.transaction(
        () -> {
          var actor = auth.lockActor(request, true);
          var target = target(id);
          db.jdbc.update("UPDATE app_users SET password_hash=? WHERE id=?", hash, id);
          db.jdbc.update("DELETE FROM auth_sessions WHERE user_id=?", id);
          db.audit(
              "account.password_reset:" + target.get("username"),
              actor.get("id"),
              auth.ip(request));
          return Map.of("ok", true);
        });
  }

  @PostMapping("/users/{id}/revoke-sessions")
  public Object revoke(@PathVariable UUID id, HttpServletRequest request) {
    if (id.equals(auth.actor(request).get("id"))) throw new ApiError(409, "USE_LOGOUT");
    return db.transaction(
        () -> {
          var actor = auth.lockActor(request, true);
          var target = target(id);
          db.jdbc.update("DELETE FROM auth_sessions WHERE user_id=?", id);
          db.audit(
              "account.sessions_revoked:" + target.get("username"),
              actor.get("id"),
              auth.ip(request));
          return Map.of("ok", true);
        });
  }

  @GetMapping("/audit-logs")
  public Object audit(
      @RequestParam(defaultValue = "all") @Pattern(regexp = "all|login|account|session")
          String kind,
      @RequestParam(defaultValue = "25") @Min(1) @Max(100) int limit,
      @RequestParam(defaultValue = "0") @Min(0) int offset) {
    String prefix = kind.equals("all") ? "" : kind + ".";
    var total =
        db.one(
                "SELECT count(*) AS n FROM audit_logs WHERE starts_with(action,?) OR (?='login' AND"
                    + " action='logout')",
                prefix,
                kind)
            .get("n");
    var rows =
        db.jdbc.queryForList(
            "SELECT a.id,a.action,a.ip_address,a.created_at,u.username FROM audit_logs a LEFT JOIN"
                + " app_users u ON u.id=a.user_id WHERE starts_with(a.action,?) OR (?='login' AND"
                + " a.action='logout') ORDER BY a.id DESC LIMIT ? OFFSET ?",
            prefix,
            kind,
            limit,
            offset);
    rows.forEach(row -> row.put("created_at", Db.iso(row.get("created_at"))));
    return Db.map("logs", rows, "total", total, "limit", limit, "offset", offset);
  }
}
