import { UserPlus } from "lucide-react"
import { Navigate, useLocation, useNavigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"

export default function AuthSignupPage() {
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
      title="Sign up"
      description="Create an account with Google or email using Auth0."
      variant="split"
      icon={<UserPlus className="size-6" />}
    >
      <div className="flex flex-col gap-3">
        {error && <p className="text-sm text-destructive">Error: {error.message}</p>}

        <Button
          onClick={() =>
            login({
              appState: { returnTo },
              authorizationParams: {
                connection: "google-oauth2",
                screen_hint: "signup",
              },
            })
          }
        >
          Sign up with Google
        </Button>

        <Button
          variant="outline"
          onClick={() =>
            login({
              appState: { returnTo },
              authorizationParams: { screen_hint: "signup" },
            })
          }
        >
          Sign up with Email
        </Button>

        <Button variant="ghost" onClick={() => navigate("/auth/login", { state: { returnTo } })}>
          Already have an account? Log in
        </Button>
      </div>
    </AuthFullPageLayout>
  )
}
