const SENSITIVE_QUERY_PARAM_PATTERN = /^(access_token|token|private_token)$/i

const GITHUB_PAT_PATTERN = /\b(github_pat_[A-Za-z0-9_]+)\b/g
const GITHUB_LEGACY_TOKEN_PATTERN = /\b(gh[pousr]_[A-Za-z0-9]+)\b/gi
const GITLAB_PAT_PATTERN = /\b(glpat-[A-Za-z0-9_-]+)\b/g

export function maskSecret(secret: string, visibleTailLength = 4): string {
  const trimmed = secret.trim()
  if (!trimmed) return trimmed
  if (trimmed.length <= visibleTailLength) return '****'
  return `****${trimmed.slice(-visibleTailLength)}`
}

export function obfuscateSecretsInText(value: string): string {
  let obfuscated = value

  obfuscated = obfuscated.replace(/(https?:\/\/)([^@\s/]+)@/gi, (_match, protocol: string, userInfo: string) => {
    const [username, ...rest] = userInfo.split(':')
    if (rest.length === 0) {
      return `${protocol}${maskSecret(userInfo)}@`
    }

    const token = rest.join(':')
    return `${protocol}${username}:${maskSecret(token)}@`
  })

  obfuscated = obfuscated.replace(GITHUB_PAT_PATTERN, (token) => maskSecret(token))
  obfuscated = obfuscated.replace(GITHUB_LEGACY_TOKEN_PATTERN, (token) => maskSecret(token))
  obfuscated = obfuscated.replace(GITLAB_PAT_PATTERN, (token) => maskSecret(token))

  obfuscated = obfuscated.replace(
    /([?&](?:access_token|token|private_token)=)([^&#]+)/gi,
    (_match, prefix: string, token: string) => `${prefix}${maskSecret(token)}`
  )

  return obfuscated
}

export function sanitizeUrlForNavigation(value: string): string {
  try {
    const parsed = new URL(value)
    parsed.username = ''
    parsed.password = ''

    const keysToDelete = Array.from(parsed.searchParams.keys()).filter((key) => SENSITIVE_QUERY_PARAM_PATTERN.test(key))
    for (const key of keysToDelete) {
      parsed.searchParams.delete(key)
    }

    return parsed.toString()
  } catch {
    let sanitized = value.replace(/(https?:\/\/)([^@\s/]+)@/gi, '$1')
    sanitized = sanitized.replace(/([?&])(access_token|token|private_token)=[^&#]*(&)?/gi, (_match, separator: string, _key: string, hasTail: string) => {
      if (separator === '?' && hasTail) return '?'
      if (separator === '?') return ''
      return hasTail ? '&' : ''
    })
    sanitized = sanitized.replace(/\?&/g, '?').replace(/&&/g, '&').replace(/\?$/g, '').replace(/&$/g, '')
    return sanitized
  }
}
