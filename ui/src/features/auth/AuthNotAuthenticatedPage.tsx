import { ShieldAlert } from "lucide-react"
import { Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"

export default function AuthNotAuthenticatedPage() {
  const navigate = useNavigate()

  const { isAuthenticated } = useAuth()

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return (
    <AuthFullPageLayout
      title="Not authenticated"
      description="You need to log in before you can use the application."
      icon={<ShieldAlert className="size-6" />}
    >
      <div className="flex flex-col gap-3">
        <Button onClick={() => navigate("/auth/login")}>Go to Login</Button>

        <Button variant="outline" onClick={() => navigate("/auth/signup")}>
          Go to Signup
        </Button>
      </div>
    </AuthFullPageLayout>
  )
}
