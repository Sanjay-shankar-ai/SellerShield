import { UserProfile } from '../types';
import { getApiBaseUrl } from './config';

const TOKEN_KEY = 'sellershield_jwt_token';
const USER_KEY = 'sellershield_user_profile';

export const authService = {
  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },

  getUser(): UserProfile | null {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },

  setSession(token: string, user: UserProfile) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },

  clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },

  async refreshUser(): Promise<UserProfile | null> {
    const token = this.getToken();
    if (!token) return null;
    try {
      const res = await this.authFetch('/api/auth/me');
      if (res.ok) {
        const user: UserProfile = await res.json();
        const stored = this.getUser();
        const updatedUser: UserProfile = { ...(stored || {}), ...user };
        localStorage.setItem(USER_KEY, JSON.stringify(updatedUser));
        window.dispatchEvent(new CustomEvent('user_profile_updated', { detail: updatedUser }));
        return updatedUser;
      }
    } catch (e) {
      console.error('Failed to refresh user profile:', e);
    }
    return null;
  },

  updateWalletBalance(newBalance: number): UserProfile | null {
    const user = this.getUser();
    if (user) {
      user.wallet_balance = newBalance;
      localStorage.setItem(USER_KEY, JSON.stringify(user));
      window.dispatchEvent(new CustomEvent('user_profile_updated', { detail: user }));
      return user;
    }
    return null;
  },

  async authFetch(url: string, options: RequestInit = {}): Promise<Response> {
    const token = this.getToken();
    const headers = new Headers(options.headers || {});
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }

    const apiBase = getApiBaseUrl();
    const fullUrl = url.startsWith('http') ? url : `${apiBase}${url}`;
    try {
      const res = await fetch(fullUrl, { ...options, headers });
      if (res.status === 401) {
        this.clearSession();
        window.dispatchEvent(new Event('auth_unauthorized'));
      }
      return res;
    } catch (err: any) {
      console.error(`[SellerShield API Error] Request to ${fullUrl} failed:`, err);
      throw err;
    }
  }
};
