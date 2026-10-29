package vn.autosort;

import jakarta.validation.ConstraintViolationException;
import java.util.Map;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

public class ApiError extends RuntimeException {
  public final int status;

  public ApiError(int status, String detail) {
    super(detail);
    this.status = status;
  }

  @RestControllerAdvice
  public static class Handler {
    @ExceptionHandler(ApiError.class)
    public ResponseEntity<?> api(ApiError error) {
      var result = ResponseEntity.status(error.status);
      if (error.status == 429) result.header("Retry-After", "900");
      return result.body(Map.of("detail", error.getMessage()));
    }

    @ExceptionHandler({
      MethodArgumentNotValidException.class,
      HttpMessageNotReadableException.class,
      ConstraintViolationException.class,
      MethodArgumentTypeMismatchException.class,
      org.springframework.web.bind.MissingServletRequestParameterException.class,
      org.springframework.web.multipart.support.MissingServletRequestPartException.class
    })
    public ResponseEntity<?> invalid(Exception ignored) {
      return ResponseEntity.unprocessableEntity().body(Map.of("detail", "VALIDATION_ERROR"));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<?> large(Exception ignored) {
      return ResponseEntity.status(413).body(Map.of("detail", "Image must be 1 MB or smaller"));
    }

    @ExceptionHandler(org.springframework.web.servlet.resource.NoResourceFoundException.class)
    public ResponseEntity<?> missing(Exception ignored) {
      return ResponseEntity.status(404).body(Map.of("detail", "Resource not found"));
    }

    @ExceptionHandler(org.springframework.web.HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<?> method(Exception ignored) {
      return ResponseEntity.status(405).body(Map.of("detail", "Method not allowed"));
    }

    @ExceptionHandler(org.springframework.web.HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<?> media(Exception ignored) {
      return ResponseEntity.status(415).body(Map.of("detail", "Unsupported media type"));
    }

    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<?> database(Exception error) {
      LoggerFactory.getLogger(Handler.class)
          .error("PostgreSQL operation failed ({})", error.getClass().getSimpleName());
      return ResponseEntity.status(503)
          .body(Map.of("detail", "Database unavailable. Please try again"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> unexpected(Exception error) {
      LoggerFactory.getLogger(Handler.class)
          .error("Request failed ({})", error.getClass().getSimpleName());
      return ResponseEntity.internalServerError().body(Map.of("detail", "Request failed"));
    }
  }
}
