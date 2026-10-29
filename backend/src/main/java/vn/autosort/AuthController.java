package vn.autosort;

import jakarta.servlet.http.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
  private final AuthService auth;

  public AuthController(AuthService auth) {
    this.auth = auth;
  }

  public record Login(
      @NotNull @Size(min = 1, max = 64) String username,
      @NotNull @Size(min = 1, max = 256) String password) {}

  public record Password(
      @NotNull @Size(min = 1, max = 256) String current_password,
      @NotNull @Size(min = 12, max = 256) String new_password) {}

  @PostMapping("/login")
  public Object login(
      @Valid @RequestBody Login body, HttpServletRequest request, HttpServletResponse response) {
    return auth.login(body.username, body.password, request, response);
  }

  @GetMapping("/me")
  public Object me(HttpServletRequest request) {
    return auth.publicUser(auth.actor(request));
  }

  @PostMapping("/logout")
  public Object logout(HttpServletRequest request, HttpServletResponse response) {
    auth.logout(request, response);
    return Map.of("ok", true);
  }

  @PostMapping("/password")
  public Object password(
      @Valid @RequestBody Password body, HttpServletRequest request, HttpServletResponse response) {
    auth.changePassword(body.current_password, body.new_password, request, response);
    return Map.of("ok", true, "loginRequired", true);
  }
}
