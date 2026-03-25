import { LogOut } from "lucide-react"
import { Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/shared/components/ui/button"
import { useAuth } from "@/shared/hooks/useAuth.ts"
import AuthFullPageLayout from "@/layouts/AuthFullPageLayout"

export default function AuthLogoutPage() {
  const navigate = useNavigate()

  const { isAuthenticated, logout } = useAuth()

  if (!isAuthenticated) {
    return <Navigate to="/auth/login" replace />
  }

  return (
    <AuthFullPageLayout
      title="Logout"
      description="You are currently signed in. End your session when you are ready."
      icon={<LogOut className="size-6" />}
    >
      <div className="flex flex-col gap-3">
        <Button onClick={logout}>Logout now</Button>

        <Button variant="outline" onClick={() => navigate("/")}>
          Back to app
        </Button>
      </div>
    </AuthFullPageLayout>
  )
}
