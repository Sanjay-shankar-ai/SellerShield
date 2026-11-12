import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  ShieldCheck,
  User,
  Lock,
  ArrowRight,
  ShoppingBag,
  LayoutDashboard,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { UserProfile } from '../../types';
import { authService } from '../../api/authService';

interface LoginPageProps {
  onLoginSuccess: (user: UserProfile) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [role, setRole] = useState<'CUSTOMER' | 'ADMIN'>('CUSTOMER');
  const [email, setEmail] = useState('rahul@gmail.com');
  const [password, setPassword] = useState('rahul123');
  const [errorMsg, setErrorMsg] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSelectRole = (newRole: 'CUSTOMER' | 'ADMIN') => {
    setRole(newRole);
    setErrorMsg('');
    if (newRole === 'ADMIN') {
      setEmail('admin@sellershield.com');
      setPassword('admin123');
    } else {
      setEmail('rahul@gmail.com');
      setPassword('rahul123');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMsg('');

    try {
      const res = await fetch('http://127.0.0.1:8000/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Invalid email or password');
      }

      const data = await res.json();
      authService.setSession(data.access_token, data.user);
      onLoginSuccess(data.user);
    } catch (err: any) {
      setErrorMsg(err.message || 'Login failed. Please verify credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 bg-bg text-text-main relative overflow-hidden">
      {/* Background glow elements */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-accent/10 rounded-full blur-3xl pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-md bg-surface border border-border rounded-3xl shadow-2xl p-6 sm:p-8 relative z-10"
      >
        {/* Brand Header */}
        <div className="text-center mb-6">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-primary to-accent mx-auto flex items-center justify-center text-2xl shadow-lg mb-3">
            🛡️
          </div>
          <h1 className="text-2xl font-black tracking-tight text-text-main">
            SellerShield <span className="text-primary">AI</span>
          </h1>
          <p className="text-xs text-text-muted mt-1">
            Autonomous E-Commerce Store & Support Operations
          </p>
        </div>

        {/* Role Selection Tabs */}
        <div className="grid grid-cols-2 gap-2 p-1 bg-surface-2 rounded-2xl border border-border mb-6 text-xs font-bold">
          <button
            type="button"
            onClick={() => handleSelectRole('CUSTOMER')}
            className={`py-2.5 rounded-xl transition-all flex items-center justify-center gap-2 ${
              role === 'CUSTOMER'
                ? 'bg-primary text-black shadow-sm'
                : 'text-text-muted hover:text-text-main'
            }`}
          >
            <ShoppingBag className="w-4 h-4" />
            <span>Customer Login</span>
          </button>

          <button
            type="button"
            onClick={() => handleSelectRole('ADMIN')}
            className={`py-2.5 rounded-xl transition-all flex items-center justify-center gap-2 ${
              role === 'ADMIN'
                ? 'bg-primary text-black shadow-sm'
                : 'text-text-muted hover:text-text-main'
            }`}
          >
            <LayoutDashboard className="w-4 h-4" />
            <span>Admin / Seller</span>
          </button>
        </div>

        {/* Quick Account Switcher Chips for Demo */}
        {role === 'CUSTOMER' && (
          <div className="flex items-center justify-center gap-2 mb-4 text-xs">
            <span className="text-[11px] text-text-muted">Quick accounts:</span>
            <button
              type="button"
              onClick={() => {
                setEmail('rahul@gmail.com');
                setPassword('rahul123');
              }}
              className={`px-2.5 py-0.5 rounded-lg border font-mono text-[11px] transition-colors ${
                email === 'rahul@gmail.com'
                  ? 'bg-primary/20 text-primary border-primary/40'
                  : 'bg-surface-2 text-text-muted border-border hover:text-text-main'
              }`}
            >
              Rahul (Customer)
            </button>
            <button
              type="button"
              onClick={() => {
                setEmail('ananya@gmail.com');
                setPassword('ananya123');
              }}
              className={`px-2.5 py-0.5 rounded-lg border font-mono text-[11px] transition-colors ${
                email === 'ananya@gmail.com'
                  ? 'bg-primary/20 text-primary border-primary/40'
                  : 'bg-surface-2 text-text-muted border-border hover:text-text-main'
              }`}
            >
              Ananya (Customer)
            </button>
          </div>
        )}

        {/* Error Alert */}
        {errorMsg && (
          <div className="mb-4 p-3 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs font-semibold text-text-muted block mb-1.5">
              Email Address
            </label>
            <div className="relative">
              <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
              <input
                type="email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full bg-surface-2 text-text-main text-xs rounded-xl pl-10 pr-4 py-2.5 border border-border focus:border-primary focus:outline-hidden"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-text-muted block mb-1.5">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
              <input
                type="password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-surface-2 text-text-main text-xs rounded-xl pl-10 pr-4 py-2.5 border border-border focus:border-primary focus:outline-hidden"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 rounded-xl bg-primary text-black font-extrabold text-sm hover:bg-primary-hover active:scale-[0.98] transition-all flex items-center justify-center gap-2 shadow-md mt-6 disabled:opacity-50"
          >
            {isLoading ? (
              <span>Authenticating with JWT...</span>
            ) : (
              <>
                <span>Sign in as {role === 'ADMIN' ? 'Merchant Admin' : 'Customer'}</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {/* Role Information Card */}
        <div className="mt-6 p-3.5 rounded-xl bg-surface-2/60 border border-border/80 text-[11px] text-text-muted space-y-1.5">
          <div className="font-bold text-text-main flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-primary" />
            <span>
              {role === 'CUSTOMER'
                ? 'Customer Capabilities:'
                : 'Admin Capabilities:'}
            </span>
          </div>
          <p>
            {role === 'CUSTOMER'
              ? 'Browse & purchase 10 products, view orders with automatic background tracking, and speak with the AI support concierge.'
              : 'View sales revenue analytics, manage orders, review AI escalation cases (Approve/Reject), audit logs, and settings.'}
          </p>
        </div>
      </motion.div>
    </div>
  );
};
