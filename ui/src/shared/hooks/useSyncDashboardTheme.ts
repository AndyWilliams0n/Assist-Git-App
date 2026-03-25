import { useEffect } from "react"

import { useDashboardSettingsStore } from "@/shared/store/dashboard-settings.ts"

export function useSyncDashboardTheme() {
  const theme = useDashboardSettingsStore((state) => state.theme)
  const setTheme = useDashboardSettingsStore((state) => state.setTheme)

  useEffect(() => {
    const storedSettings = localStorage.getItem("dashboard-settings")
    const storedTheme = storedSettings
      ? JSON.parse(storedSettings)?.state?.theme
      : null
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
    const nextTheme =
      storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : prefersDark
          ? "dark"
          : "light"

    setTheme(nextTheme)
  }, [setTheme])

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
  }, [theme])
}
