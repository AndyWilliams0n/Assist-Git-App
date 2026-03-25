import * as React from "react"

const DEFAULT_AUTH_LOADING_TIMEOUT_MS = 15000
const configuredAuthLoadingTimeoutMs = Number(import.meta.env.VITE_AUTH_LOADING_TIMEOUT_MS)

export const AUTH_LOADING_TIMEOUT_MS =
  Number.isFinite(configuredAuthLoadingTimeoutMs) && configuredAuthLoadingTimeoutMs > 0
    ? configuredAuthLoadingTimeoutMs
    : DEFAULT_AUTH_LOADING_TIMEOUT_MS

export function useAuthLoadingTimeout(isLoading: boolean) {
  const [hasTimedOut, setHasTimedOut] = React.useState(false)

  React.useEffect(() => {
    if (!isLoading) {
      setHasTimedOut(false)
      return
    }

    const timerId = window.setTimeout(() => {
      setHasTimedOut(true)
    }, AUTH_LOADING_TIMEOUT_MS)

    return () => {
      window.clearTimeout(timerId)
    }
  }, [isLoading])

  return hasTimedOut
}

export type AuthTroubleshootingDetails = {
  origin: string
  callbackUrl: string
  logoutUrl: string
  auth0Domain: string
  auth0ClientId: string
}

export function getAuthTroubleshootingDetails(): AuthTroubleshootingDetails {
  const origin = window.location.origin

  return {
    origin,
    callbackUrl: origin,
    logoutUrl: origin,
    auth0Domain: String(import.meta.env.VITE_AUTH0_DOMAIN || ""),
    auth0ClientId: String(import.meta.env.VITE_AUTH0_CLIENT_ID || ""),
  }
}
