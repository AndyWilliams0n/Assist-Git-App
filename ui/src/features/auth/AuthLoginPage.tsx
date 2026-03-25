import { LogIn } from "lucide-react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"

export default function AuthLoginPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const locationState = location.state as { returnTo?: string } | null
  const returnTo = locationState?.returnTo || "/"

  const { isAuthenticated, login, error } = useAuth()

  if (isAuthenticated) {
    return <Navigate to={returnTo} replace />
  }

  return (
    <AuthFullPageLayout
      title="Log in"
      description="Use Google or continue with email via Auth0."
      variant="split"
      icon={<LogIn className="size-6" />}
    >
      <div className="flex flex-col gap-3">
        {error && <p className="text-sm text-destructive">Error: {error.message}</p>}

        <Button
          onClick={() =>
            login({
              appState: { returnTo },
              authorizationParams: { connection: "google-oauth2" },
            })
          }
        >
          Continue with Google
        </Button>

        <Button
          variant="outline"
          onClick={() =>
            login({
              appState: { returnTo },
            })
          }
        >
          Continue with Email
        </Button>

        <Button variant="ghost" onClick={() => navigate("/auth/signup", { state: { returnTo } })}>
          Need an account? Sign up
        </Button>
      </div>
    </AuthFullPageLayout>
  )
}
