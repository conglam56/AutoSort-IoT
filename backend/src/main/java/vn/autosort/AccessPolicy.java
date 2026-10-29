package vn.autosort;

/** Guest is absence of authentication; only these two roles can authenticate. */
public final class AccessPolicy {
  private AccessPolicy() {}

  public static boolean isAdmin(Object role) {
    return "admin".equals(role);
  }

  public static boolean canOperate(Object role) {
    return isAdmin(role) || "operator".equals(role);
  }

  public static void requireOperator(Object role) {
    if (!canOperate(role)) throw new ApiError(403, "Operator permission required");
  }
}
