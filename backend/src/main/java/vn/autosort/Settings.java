package vn.autosort;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import javax.sql.DataSource;
import org.springframework.context.annotation.*;
import org.springframework.core.env.Environment;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
public class Settings {
  private final Environment env;
  public final boolean secure;
  public final List<String> origins;
  public final String deviceKey;

  public Settings(Environment env) {
    this.env = env;
    secure = Boolean.parseBoolean(get("COOKIE_SECURE", "true"));
    deviceKey = get("DEVICE_API_KEY", "");
    String fallback =
        get("RENDER", "false").equals("true")
            ? get("RENDER_EXTERNAL_URL", "")
            : "http://127.0.0.1:8000,http://localhost:8000";
    origins =
        Arrays.stream(get("ALLOWED_ORIGINS", fallback).split(","))
            .map(String::trim)
            .map(s -> s.replaceAll("/+$", ""))
            .filter(s -> !s.isBlank())
            .toList();
    if (deviceKey.length() < 32 || deviceKey.startsWith("replace_"))
      fail("Set DEVICE_API_KEY to a private random value of at least 32 characters");
    if (origins.isEmpty() || origins.contains("*")) fail("Set explicit ALLOWED_ORIGINS");
    boolean render = get("RENDER", "false").equals("true");
    if (render && (!secure || origins.stream().anyMatch(s -> !s.startsWith("https://"))))
      fail("Render requires HTTPS origins and COOKIE_SECURE=true");
    if (!secure
        && origins.stream()
            .anyMatch(
                s -> !s.startsWith("http://127.0.0.1:") && !s.startsWith("http://localhost:")))
      fail("Insecure cookies are allowed only on localhost");
  }

  public String get(String key, String fallback) {
    return env.getProperty(key, fallback);
  }

  public boolean enabled(String key) {
    return get(key, "false").equals("true");
  }

  private static void fail(String message) {
    throw new IllegalStateException(message);
  }

  private static String decode(String value) {
    return URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8);
  }

  @Bean
  public DataSource dataSource() {
    HikariConfig pool = new HikariConfig();
    try {
      URI uri = URI.create(get("DATABASE_URL", ""));
      if (!Set.of("postgres", "postgresql").contains(uri.getScheme())
          || uri.getHost() == null
          || uri.getRawUserInfo() == null) throw new IllegalArgumentException();
      String[] user = uri.getRawUserInfo().split(":", 2);
      pool.setJdbcUrl(
          "jdbc:postgresql://"
              + uri.getHost()
              + ":"
              + (uri.getPort() < 0 ? 5432 : uri.getPort())
              + uri.getRawPath());
      pool.setUsername(decode(user[0]));
      pool.setPassword(user.length == 2 ? decode(user[1]) : "");
      if (uri.getRawQuery() != null)
        for (String part : uri.getRawQuery().split("&")) {
          String[] kv = part.split("=", 2);
          if (kv.length == 2) pool.addDataSourceProperty(decode(kv[0]), decode(kv[1]));
        }
      String tls = get("DATABASE_SSLMODE", "");
      if (!tls.isBlank()) pool.addDataSourceProperty("sslmode", tls);
      String schema = get("DATABASE_SCHEMA", "public");
      if (!schema.matches("[a-z_][a-z0-9_]{0,62}")) throw new IllegalArgumentException();
      pool.addDataSourceProperty("currentSchema", schema);
    } catch (RuntimeException error) {
      throw new IllegalStateException(
          "Set DATABASE_URL to a valid PostgreSQL URL; check DATABASE_SCHEMA");
    }
    pool.addDataSourceProperty("connectTimeout", "5");
    pool.addDataSourceProperty("socketTimeout", "75");
    pool.setMaximumPoolSize(6);
    pool.setMinimumIdle(1);
    pool.setConnectionTimeout(5000);
    pool.setInitializationFailTimeout(5000);
    pool.setPoolName("autosort");
    return new HikariDataSource(pool);
  }

  @Bean
  public PasswordEncoder passwordEncoder() {
    return Argon2PasswordEncoder.defaultsForSpringSecurity_v5_8();
  }
}
