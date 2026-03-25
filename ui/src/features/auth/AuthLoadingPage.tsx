import { LoaderCircle } from "lucide-react"
import { Link, Navigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"
import {
  AUTH_LOADING_TIMEOUT_MS,
  getAuthTroubleshootingDetails,
  useAuthLoadingTimeout,
} from "@/features/auth/auth-loading-timeout"

export default function AuthLoadingPage() {
  const { isLoading, isAuthenticated } = useAuth()
  const hasTimedOut = useAuthLoadingTimeout(isLoading)

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/" replace />
  }

  if (!isLoading && !isAuthenticated) {
    return <Navigate to="/auth/login" replace />
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
            Continue to login to re-establish your session.
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
            <Link to="/auth/login" replace>
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

  return (
    <AuthFullPageLayout
      title="Checking session"
      description="Please wait while we connect to Auth0."
      icon={<LoaderCircle className="size-6 animate-spin" />}
    >
      <div className="text-center text-sm text-muted-foreground">
        Validating your authentication state...
      </div>
    </AuthFullPageLayout>
  )
}
