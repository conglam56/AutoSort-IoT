package vn.autosort;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.List;
import org.springframework.context.annotation.*;
import org.springframework.dao.DataAccessException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.*;
import org.springframework.web.filter.OncePerRequestFilter;

@Configuration
public class Security {
  @Bean
  public SecurityFilterChain chain(
      HttpSecurity http, AuthService auth, Settings settings, ObjectMapper json) throws Exception {
    // DB-backed cookie sessions and Origin+X-CSRF-Token are validated in the filter below.
    http.csrf(c -> c.disable())
        .cors(c -> c.configurationSource(cors(settings)))
        .sessionManagement(c -> c.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .formLogin(c -> c.disable())
        .httpBasic(c -> c.disable())
        .logout(c -> c.disable())
        .authorizeHttpRequests(
            c ->
                c.requestMatchers("/api/admin/**", "/api/audit-logs")
                    .hasRole("ADMIN")
                    .requestMatchers("/api/auth/login")
                    .permitAll()
                    .requestMatchers("/api/**")
                    .hasAnyRole("ADMIN", "OPERATOR")
                    .anyRequest()
                    .permitAll())
        .exceptionHandling(
            c ->
                c.authenticationEntryPoint((q, r, e) -> error(r, json, 401, "Login required"))
                    .accessDeniedHandler(
                        (q, r, e) -> error(r, json, 403, "Administrator permission required")))
        .addFilterBefore(
            new RequestFilter(auth, settings, json), UsernamePasswordAuthenticationFilter.class);
    return http.build();
  }

  private CorsConfigurationSource cors(Settings settings) {
    CorsConfiguration c = new CorsConfiguration();
    c.setAllowedOrigins(settings.origins);
    c.setAllowCredentials(true);
    c.setAllowedMethods(List.of("GET", "POST", "OPTIONS"));
    c.setAllowedHeaders(List.of("Content-Type", "X-CSRF-Token", "X-API-Key", "Idempotency-Key"));
    UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
    source.registerCorsConfiguration("/**", c);
    return source;
  }

  private static void error(
      HttpServletResponse response, ObjectMapper json, int status, String message)
      throws IOException {
    response.setStatus(status);
    response.setContentType("application/json");
    json.writeValue(response.getOutputStream(), Db.map("detail", message));
  }

  static class RequestFilter extends OncePerRequestFilter {
    private final AuthService auth;
    private final Settings settings;
    private final ObjectMapper json;

    RequestFilter(AuthService auth, Settings settings, ObjectMapper json) {
      this.auth = auth;
      this.settings = settings;
      this.json = json;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest request, HttpServletResponse response, FilterChain chain)
        throws ServletException, IOException {
      String path = request.getRequestURI();
      response.setHeader("X-Content-Type-Options", "nosniff");
      response.setHeader("Referrer-Policy", "same-origin");
      response.setHeader("X-Frame-Options", "DENY");
      if (path.startsWith("/api/") || path.equals("/infer"))
        response.setHeader("Cache-Control", "no-store");
      try {
        if (path.equals("/infer") && !request.getMethod().equals("OPTIONS")) {
          if (!AuthService.equal(request.getHeader("X-API-Key"), settings.deviceKey))
            throw new ApiError(401, "Invalid device API key");
        } else if (path.startsWith("/api/")
            && !path.equals("/api/auth/login")
            && !request.getMethod().equals("OPTIONS")) {
          var user = auth.current(request);
          if (request.getMethod().equals("POST")) auth.csrf(request, user);
          request.setAttribute("autosort.user", user);
          var principal =
              new UsernamePasswordAuthenticationToken(
                  user,
                  null,
                  List.of(
                      new SimpleGrantedAuthority(
                          "ROLE_"
                              + user.get("role").toString().toUpperCase(java.util.Locale.ROOT))));
          SecurityContextHolder.getContext().setAuthentication(principal);
        }
      } catch (ApiError e) {
        error(response, json, e.status, e.getMessage());
        return;
      } catch (DataAccessException e) {
        error(response, json, 503, "Database unavailable. Please try again");
        return;
      }
      chain.doFilter(request, response);
    }
  }
}
