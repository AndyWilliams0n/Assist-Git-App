import { RouterProvider } from "react-router-dom"

import { useSyncDashboardTheme } from "./shared/hooks/useSyncDashboardTheme.ts"
import { useDashboardSettingsStore } from "./shared/store/dashboard-settings"
import { Toaster } from "./shared/components/ui/sonner"
import { router } from "./router"

export function App() {
  useSyncDashboardTheme()

  const theme = useDashboardSettingsStore((state) => state.theme)

  return (
    <>
      <RouterProvider router={router} />

      <Toaster richColors position='bottom-right' theme={theme} />
    </>
  )
}

export default App
