package vn.autosort;

import jakarta.servlet.http.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Instant;
import java.util.*;
import org.springframework.http.ResponseCookie;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
  public static final String COOKIE = "autosort_session";
  private final Db db;
  private final Settings settings;
  private final PasswordEncoder passwords;
  private final SecureRandom random = new SecureRandom();
  private final String dummy;

  public AuthService(Db db, Settings settings, PasswordEncoder passwords) {
    this.db = db;
    this.settings = settings;
    this.passwords = passwords;
    dummy = passwords.encode(token());
  }

  public static String digest(String value) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (NoSuchAlgorithmException error) {
      throw new IllegalStateException(error);
    }
  }

  public static boolean equal(String a, String b) {
    return MessageDigest.isEqual(
        digest(a == null ? "" : a).getBytes(StandardCharsets.US_ASCII),
        digest(b == null ? "" : b).getBytes(StandardCharsets.US_ASCII));
  }

  public String token() {
    byte[] data = new byte[32];
    random.nextBytes(data);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(data);
  }

  public String cookie(HttpServletRequest request) {
    if (request.getCookies() != null)
      for (var cookie : request.getCookies())
        if (cookie.getName().equals(COOKIE)) return cookie.getValue();
    return "";
  }

  public String ip(HttpServletRequest request) {
    return request.getRemoteAddr();
  }

  public void origin(HttpServletRequest request) {
    String value = Objects.toString(request.getHeader("Origin"), "").replaceAll("/+$", "");
    if (!settings.origins.contains(value)) throw new ApiError(403, "Dashboard origin not allowed");
  }

  public Map<String, Object> current(HttpServletRequest request) {
    String token = cookie(request);
    if (token.isEmpty() || token.length() > 256) throw new ApiError(401, "Login required");
    var user =
        db.one(
            "SELECT u.id,u.username,u.role,s.csrf_token,s.token_hash,s.expires_at FROM"
                + " auth_sessions s JOIN app_users u ON u.id=s.user_id WHERE s.token_hash=? AND"
                + " s.expires_at>now() AND u.active",
            digest(token));
    if (user == null) throw new ApiError(401, "Session expired. Please log in again");
    return user;
  }

  @SuppressWarnings("unchecked")
  public Map<String, Object> actor(HttpServletRequest request) {
    return (Map<String, Object>) request.getAttribute("autosort.user");
  }

  public void csrf(HttpServletRequest request, Map<String, Object> user) {
    origin(request);
    if (!equal(request.getHeader("X-CSRF-Token"), (String) user.get("csrf_token")))
      throw new ApiError(403, "CSRF token invalid");
  }

  public Map<String, Object> lockActor(HttpServletRequest request, boolean admin) {
    db.accountLock();
    var actor = actor(request);
    var fresh =
        db.one(
            "SELECT u.* FROM app_users u JOIN auth_sessions s ON s.user_id=u.id WHERE u.id=? AND"
                + " s.token_hash=? AND s.expires_at>now() AND u.active FOR UPDATE OF u,s",
            actor.get("id"),
            actor.get("token_hash"));
    if (fresh == null) throw new ApiError(401, "Login required");
    if (admin && !fresh.get("role").equals("admin"))
      throw new ApiError(403, "Administrator permission required");
    return fresh;
  }

  public Map<String, Object> publicUser(Map<String, Object> user) {
    return Db.map(
        "id",
        user.get("id").toString(),
        "username",
        user.get("username"),
        "role",
        user.get("role"),
        "csrfToken",
        user.get("csrf_token"),
        "expiresAt",
        Db.iso(user.get("expires_at")));
  }

  public void cookie(HttpServletResponse response, String token) {
    response.addHeader(
        "Set-Cookie",
        ResponseCookie.from(COOKIE, token)
            .httpOnly(true)
            .secure(settings.secure)
            .sameSite("Lax")
            .path("/")
            .maxAge(token.isEmpty() ? 0 : 8 * 3600)
            .build()
            .toString());
  }

  public void rateLimit(String ip, String username) {
    boolean limited =
        db.transaction(
            () -> {
              db.jdbc.update("DELETE FROM login_limits WHERE window_start<now()-interval '1 day'");
              boolean result = false;
              var buckets = new TreeMap<String, Integer>();
              buckets.put("ip:" + digest(ip), 30);
              buckets.put("user:" + digest(username), 10);
              for (var entry : buckets.entrySet()) {
                var row =
                    db.one(
                        "INSERT INTO login_limits(bucket,attempts) VALUES (?,1) ON CONFLICT(bucket)"
                            + " DO UPDATE SET attempts=CASE WHEN"
                            + " login_limits.window_start<now()-interval '15 minutes' THEN 1 ELSE"
                            + " login_limits.attempts+1 END,window_start=CASE WHEN"
                            + " login_limits.window_start<now()-interval '15 minutes' THEN now()"
                            + " ELSE login_limits.window_start END RETURNING attempts",
                        entry.getKey());
                result |= ((Number) row.get("attempts")).intValue() > entry.getValue();
              }
              return result;
            });
    if (limited) throw new ApiError(429, "Too many login attempts. Try again in 15 minutes");
  }

  public Map<String, Object> login(
      String name, String password, HttpServletRequest request, HttpServletResponse response) {
    origin(request);
    String username = name.strip().toLowerCase(Locale.ROOT);
    rateLimit(ip(request), username);
    var initial = db.one("SELECT * FROM app_users WHERE username=?", username);
    boolean valid =
        passwords.matches(
            password, initial == null ? dummy : (String) initial.get("password_hash"));
    if (initial == null || !valid || !Boolean.TRUE.equals(initial.get("active"))) {
      db.audit("login.failed", null, ip(request));
      throw new ApiError(401, "Invalid username or password");
    }
    String token = token(), csrf = token();
    Instant expires = Instant.now().plusSeconds(8 * 3600);
    var result =
        db.transaction(
            () -> {
              db.accountLock();
              var fresh =
                  db.one("SELECT * FROM app_users WHERE id=? FOR UPDATE", initial.get("id"));
              if (fresh == null
                  || !Boolean.TRUE.equals(fresh.get("active"))
                  || !fresh.get("password_hash").equals(initial.get("password_hash")))
                throw new ApiError(401, "Invalid username or password");
              db.jdbc.update(
                  "DELETE FROM auth_sessions WHERE expires_at<=now() OR token_hash=?",
                  digest(cookie(request)));
              db.jdbc.update(
                  "INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at) VALUES"
                      + " (?,?,?,?)",
                  digest(token),
                  fresh.get("id"),
                  csrf,
                  java.sql.Timestamp.from(expires));
              db.audit("login.succeeded", fresh.get("id"), ip(request));
              fresh.put("csrf_token", csrf);
              fresh.put("expires_at", expires);
              return publicUser(fresh);
            });
    cookie(response, token);
    return result;
  }

  public void logout(HttpServletRequest request, HttpServletResponse response) {
    var actor = actor(request);
    db.transaction(
        () -> {
          db.jdbc.update("DELETE FROM auth_sessions WHERE token_hash=?", actor.get("token_hash"));
          db.audit("logout", actor.get("id"), ip(request));
          return null;
        });
    cookie(response, "");
  }

  public void changePassword(
      String current,
      String replacement,
      HttpServletRequest request,
      HttpServletResponse response) {
    rateLimit(ip(request), (String) actor(request).get("username"));
    db.transaction(
        () -> {
          var fresh = lockActor(request, false);
          String hash = (String) fresh.get("password_hash");
          if (!passwords.matches(current, hash))
            throw new ApiError(400, "CURRENT_PASSWORD_INCORRECT");
          if (passwords.matches(replacement, hash)) throw new ApiError(400, "PASSWORD_UNCHANGED");
          db.jdbc.update(
              "UPDATE app_users SET password_hash=? WHERE id=?",
              passwords.encode(replacement),
              fresh.get("id"));
          db.jdbc.update("DELETE FROM auth_sessions WHERE user_id=?", fresh.get("id"));
          db.audit(
              "account.password_changed:" + fresh.get("username"), fresh.get("id"), ip(request));
          return null;
        });
    cookie(response, "");
  }
}
