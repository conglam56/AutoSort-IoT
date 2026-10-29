package vn.autosort;

import jakarta.annotation.PostConstruct;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceUtils;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class Db {
  public final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final Settings settings;
  private final PasswordEncoder passwords;

  public Db(
      JdbcTemplate jdbc, TransactionTemplate tx, Settings settings, PasswordEncoder passwords) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.settings = settings;
    this.passwords = passwords;
  }

  public <T> T transaction(Supplier<T> action) {
    return tx.execute(status -> action.get());
  }

  public Map<String, Object> one(String sql, Object... args) {
    var rows = jdbc.queryForList(sql, args);
    return rows.isEmpty() ? null : rows.getFirst();
  }

  public void accountLock() {
    jdbc.queryForList("SELECT pg_advisory_xact_lock(83417003)");
  }

  public void sortingLock() {
    jdbc.queryForList("SELECT pg_advisory_xact_lock(83417001)");
  }

  public void audit(String action, Object user, String ip) {
    jdbc.update(
        "INSERT INTO audit_logs(user_id,action,ip_address) VALUES (?,?,?)", user, action, ip);
  }

  public static String iso(Object value) {
    if (value == null) return null;
    return value instanceof Timestamp t
        ? t.toInstant().toString()
        : value instanceof OffsetDateTime t ? t.toInstant().toString() : value.toString();
  }

  public static Map<String, Object> map(Object... pairs) {
    var result = new LinkedHashMap<String, Object>();
    for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }

  @PostConstruct
  public void initialize() {
    transaction(
        () -> {
          jdbc.queryForList("SELECT pg_advisory_xact_lock(83417002)");
          boolean exists = one("SELECT to_regclass('schema_version') AS name").get("name") != null;
          if (!exists && !settings.enabled("INITIALIZE_DATABASE"))
            throw new IllegalStateException(
                "Initialize the database explicitly with INITIALIZE_DATABASE=true");
          boolean migrate =
              exists && one("SELECT version FROM schema_version WHERE version=3") == null;
          if (migrate && !settings.enabled("MIGRATE_DATABASE"))
            throw new IllegalStateException(
                "Set MIGRATE_DATABASE=true to migrate roles and session lifecycle to schema v3");
          if (!exists || migrate) {
            var ds = Objects.requireNonNull(jdbc.getDataSource());
            var connection = DataSourceUtils.getConnection(ds);
            try {
              ScriptUtils.executeSqlScript(connection, new ClassPathResource("schema.sql"));
              if (one("SELECT version FROM schema_version WHERE version=3") == null)
                ScriptUtils.executeSqlScript(
                    connection,
                    new ClassPathResource(
                        "db/migration/V3__operator_roles_and_session_lifecycle.sql"));
            } finally {
              DataSourceUtils.releaseConnection(connection, ds);
            }
          }
          if (one("SELECT id FROM app_users WHERE active AND role='admin' LIMIT 1") != null)
            return null;
          if (one("SELECT id FROM app_users LIMIT 1") != null)
            throw new IllegalStateException(
                "No active admin; recover existing accounts before starting");
          String
              username =
                  settings
                      .get("BOOTSTRAP_ADMIN_USERNAME", "admin")
                      .strip()
                      .toLowerCase(Locale.ROOT),
              password = settings.get("BOOTSTRAP_ADMIN_PASSWORD", "");
          if (!username.matches("[a-z0-9_.-]{3,64}")
              || password.length() < 12
              || password.length() > 256)
            throw new IllegalStateException(
                "An empty database requires valid bootstrap administrator credentials");
          UUID id = UUID.randomUUID();
          jdbc.update(
              "INSERT INTO app_users(id,username,password_hash,role) VALUES (?,?,?,'admin')",
              id,
              username,
              passwords.encode(password));
          audit("account.bootstrap", id, "deploy");
          return null;
        });
  }

  public void ready() {
    if (one("SELECT version FROM schema_version WHERE version=3") == null)
      throw new ApiError(503, "Database schema not ready");
  }
}
