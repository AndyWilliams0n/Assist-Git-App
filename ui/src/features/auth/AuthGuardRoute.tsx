import { Link, Navigate, Outlet, useLocation } from "react-router-dom"
import * as React from "react"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"
import {
  AUTH_LOADING_TIMEOUT_MS,
  getAuthTroubleshootingDetails,
  useAuthLoadingTimeout,
} from "@/features/auth/auth-loading-timeout"

export default function AuthGuardRoute() {
  const location = useLocation()
  const { isLoading, isAuthenticated, error } = useAuth()
  const hasTimedOut = useAuthLoadingTimeout(isLoading)
  const returnTo = `${location.pathname}${location.search}${location.hash}`
  const [wasAuthenticated, setWasAuthenticated] = React.useState(isAuthenticated)

  React.useEffect(() => {
    if (isAuthenticated) {
      setWasAuthenticated(true)
      return
    }

    if (!isLoading && !isAuthenticated) {
      setWasAuthenticated(false)
    }
  }, [isAuthenticated, isLoading])

  if (wasAuthenticated && isAuthenticated) {
    return <Outlet />
  }

  if (wasAuthenticated && isLoading) {
    return <Outlet />
  }

  if (isLoading && !hasTimedOut) {
    return (
      <AuthFullPageLayout
        title="Checking session"
        description="Please wait while we connect to Auth0."
      >
        <div className="text-center text-sm text-muted-foreground">
          Validating your authentication state...
        </div>
      </AuthFullPageLayout>
    )
  }

  if (isLoading && hasTimedOut) {
    const details = getAuthTroubleshootingDetails()

    return (
      <AuthFullPageLayout
        title="Session check timed out"
        description={`Auth0 did not respond within ${Math.round(AUTH_LOADING_TIMEOUT_MS / 1000)} seconds.`}
      >
        <div className="flex flex-col gap-3">
          <p className="text-center text-sm text-muted-foreground">
            This can happen if the network is unstable or browser session checks are blocked.
          </p>

          <div className="rounded-md border p-3 text-xs">
            <p className="font-medium">Verify Auth0 SPA settings include this origin:</p>

            <p className="mt-2 text-muted-foreground">Allowed Web Origins: {details.origin}</p>

            <p className="text-muted-foreground">Allowed Callback URLs: {details.callbackUrl}</p>

            <p className="text-muted-foreground">Allowed Logout URLs: {details.logoutUrl}</p>

            <p className="mt-2 text-muted-foreground">Domain: {details.auth0Domain || "(missing)"}</p>

            <p className="text-muted-foreground">
              Client ID: {details.auth0ClientId || "(missing)"}
            </p>
          </div>

          <Button asChild>
            <Link to="/auth/login" replace state={{ returnTo }}>
              Continue to login
            </Link>
          </Button>

          <Button variant="outline" onClick={() => window.location.reload()}>
            Retry session check
          </Button>
        </div>
      </AuthFullPageLayout>
    )
  }

  if (error) {
    return <Navigate to="/auth/error" replace />
  }

  if (!isAuthenticated) {
    return <Navigate to="/auth/login" replace state={{ returnTo }} />
  }

  return <Outlet />
}
