import { createBrowserRouter } from "react-router-dom"
import AuthErrorPage from "./features/auth/AuthErrorPage"
import AuthGuardRoute from "./features/auth/AuthGuardRoute"
import AuthLoadingPage from "./features/auth/AuthLoadingPage"
import AuthLoginPage from "./features/auth/AuthLoginPage"
import AuthLogoutPage from "./features/auth/AuthLogoutPage"
import AuthSignupPage from "./features/auth/AuthSignupPage"
import GitPage from "./features/git/GitPage"
import WorkspacePage from "./features/workspace/WorkspacePage"
import MainLayout from "./layouts/MainLayout"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AuthGuardRoute />,
    children: [
      {
        element: <MainLayout />,
        children: [
          {
            index: true,
            element: <WorkspacePage />,
          },
          {
            path: "git",
            element: <GitPage />,
          },
          {
            path: "workspace",
            element: <WorkspacePage />,
          },
        ],
      },
    ],
  },
  {
    path: "/auth/login",
    element: <AuthLoginPage />,
  },
  {
    path: "/auth/signup",
    element: <AuthSignupPage />,
  },
  {
    path: "/auth/logout",
    element: <AuthLogoutPage />,
  },
  {
    path: "/auth/loading",
    element: <AuthLoadingPage />,
  },
  {
    path: "/auth/error",
    element: <AuthErrorPage />,
  },
])
