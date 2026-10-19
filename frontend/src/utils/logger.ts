/// <reference types="vite/client" />

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'

const LEVELS: Record<LogLevel, number> = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
}

// Keys whose values are always redacted before logging
const SENSITIVE_KEYS = new Set([
  'password',
  'token',
  'secret',
  'authorization',
  'cookie',
  'jenkins_token',
  'jenkins_token_uuid',
  'api_key',
  'apikey',
  'access_token',
  'refresh_token',
])

function sanitize(value: unknown, depth = 0): unknown {
  if (depth > 5 || value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map((v) => sanitize(v, depth + 1))
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = SENSITIVE_KEYS.has(k.toLowerCase()) ? '[REDACTED]' : sanitize(v, depth + 1)
  }
  return out
}

const rawLevel = (import.meta.env.VITE_LOG_LEVEL as string | undefined)?.toUpperCase() as LogLevel | undefined
const minLevel = LEVELS[rawLevel ?? 'INFO'] ?? LEVELS.INFO

function shouldLog(level: LogLevel): boolean {
  return LEVELS[level] >= minLevel
}

function sanitizeArgs(args: unknown[]): unknown[] {
  return args.map((a) => (a !== null && typeof a === 'object' ? sanitize(a) : a))
}

export const logger = {
  debug(message: string, ...args: unknown[]): void {
    if (shouldLog('DEBUG')) console.debug(`[DEBUG] ${message}`, ...sanitizeArgs(args))
  },
  info(message: string, ...args: unknown[]): void {
    if (shouldLog('INFO')) console.info(`[INFO] ${message}`, ...sanitizeArgs(args))
  },
  warn(message: string, ...args: unknown[]): void {
    if (shouldLog('WARN')) console.warn(`[WARN] ${message}`, ...sanitizeArgs(args))
  },
  error(message: string, ...args: unknown[]): void {
    if (shouldLog('ERROR')) console.error(`[ERROR] ${message}`, ...sanitizeArgs(args))
  },
}
