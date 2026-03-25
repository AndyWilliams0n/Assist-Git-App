import { AlertTriangle } from "lucide-react"
import { Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"

export default function AuthErrorPage() {
  const navigate = useNavigate()

  const { error, isAuthenticated } = useAuth()

  if (!error && isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return (
    <AuthFullPageLayout
      title="Authentication error"
      description={error?.message || "Something went wrong while authenticating."}
      icon={<AlertTriangle className="size-6" />}
    >
      <div className="flex flex-col gap-3">
        <Button onClick={() => navigate("/auth/login")}>Try Login Again</Button>

        <Button variant="outline" onClick={() => navigate("/auth/signup")}>
          Go to Signup
        </Button>
      </div>
    </AuthFullPageLayout>
  )
}
