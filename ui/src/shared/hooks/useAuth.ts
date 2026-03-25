import { useAuth0 } from "@auth0/auth0-react"

export function useAuth() {
  const {
    isLoading,
    isAuthenticated,
    error,
    loginWithRedirect: login,
    logout: auth0Logout,
    user,
  } = useAuth0()

  const signup = () =>
    login({ authorizationParams: { screen_hint: "signup" } })

  const logout = () =>
    auth0Logout({ logoutParams: { returnTo: window.location.origin } })

  return {
    isLoading,
    isAuthenticated,
    error,
    login,
    signup,
    logout,
    user,
  }
}
