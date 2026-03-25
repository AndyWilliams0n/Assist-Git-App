export const healthTone = (health?: string | null) => {
  switch (health) {
    case "ok":
      return { label: "healthy", color: "#22c55e" }
    case "degraded":
      return { label: "degraded", color: "#f59e0b" }
    case "unconfigured":
      return { label: "unconfigured", color: "#ef4444" }
    default:
      return { label: "unknown", color: "#9ca3af" }
  }
}
