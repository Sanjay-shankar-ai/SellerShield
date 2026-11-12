/**
 * Single Source of Truth for Backend API URL Resolution
 * Priority:
 *   1. VITE_API_URL (Standard Vercel environment variable)
 *   2. VITE_API_BASE_URL (Fallback alias)
 *   3. http://127.0.0.1:8000 (Local development default)
 *   4. "" (Production relative fallback)
 * Automatically normalizes trailing slashes.
 */
export const getApiBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim().length > 0) {
    return envUrl.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    return 'http://127.0.0.1:8000';
  }
  return '';
};
