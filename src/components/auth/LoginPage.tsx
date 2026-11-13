import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck,
  User,
  Lock,
  ArrowRight,
  ShoppingBag,
  LayoutDashboard,
  CheckCircle2,
  AlertCircle,
  Sun,
  Moon,
  Sparkles,
  CreditCard,
  Check,
  X,
  HelpCircle,
  Store,
  Clock,
  Zap,
  ChevronRight
} from 'lucide-react';
import { UserProfile, PlanItem, SubscriptionData } from '../../types';
import { authService } from '../../api/authService';
import { getApiBaseUrl } from '../../api/config';
import { useTheme } from '../../theme/ThemeContext';

interface LoginPageProps {
  onLoginSuccess: (user: UserProfile) => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const { theme, toggleTheme } = useTheme();

  // Role toggle for demo convenience (Admin is default for the Seller Admin Portal)
  const [role, setRole] = useState<'ADMIN' | 'CUSTOMER'>('ADMIN');

  // Login form state
  const [email, setEmail] = useState('admin@sellershield.com');
  const [password, setPassword] = useState('admin123');
  const [errorMsg, setErrorMsg] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Plans state (fetched dynamically from GET /api/plans)
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [isLoadingPlans, setIsLoadingPlans] = useState(true);
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');

  // Sign up & Mock Checkout Modal states
  const [isSignupModalOpen, setIsSignupModalOpen] = useState(false);
  const [selectedPlanForSignup, setSelectedPlanForSignup] = useState<string>('pro');
  const [isTrialIntent, setIsTrialIntent] = useState<boolean>(true);

  // Signup form
  const [signupStoreName, setSignupStoreName] = useState('');
  const [signupEmail, setSignupEmail] = useState('');
  const [signupPassword, setSignupPassword] = useState('');
  const [signupStep, setSignupStep] = useState<'account' | 'checkout'>('account');
  const [signupError, setSignupError] = useState('');
  const [isSubmittingSignup, setIsSubmittingSignup] = useState(false);

  // Mock test card form (test card only - NEVER stored!)
  const [testCardNumber, setTestCardNumber] = useState('4242 4242 4242 4242');
  const [testCardExp, setTestCardExp] = useState('12/28');
  const [testCardCvc, setTestCardCvc] = useState('123');
  const [testCardName, setTestCardName] = useState('Demo Merchant');

  // Fetch plans from GET /api/plans (public)
  useEffect(() => {
    const fetchPlans = async () => {
      setIsLoadingPlans(true);
      try {
        const apiBase = getApiBaseUrl();
        const res = await fetch(`${apiBase}/api/plans`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setPlans(data);
          } else {
            setFallbackPlans();
          }
        } else {
          setFallbackPlans();
        }
      } catch (err) {
        setFallbackPlans();
      } finally {
        setIsLoadingPlans(false);
      }
    };

    fetchPlans();
  }, []);

  const setFallbackPlans = () => {
    setPlans([
      {
        id: 'starter',
        name: 'Starter',
        price_monthly: 0,
        price_yearly: 0,
        chat_limit: 50,
        features: ['50 AI chats a month', 'Order tracking', 'Basic audit log'],
        feature_keys: ['order_tracking', 'basic_audit']
      },
      {
        id: 'growth',
        name: 'Growth',
        price_monthly: 999,
        price_yearly: 9990,
        chat_limit: 1000,
        features: [
          '1,000 AI chats a month',
          'Returns/refunds/exchanges',
          'Escalation queue',
          'CSV export'
        ],
        feature_keys: ['order_tracking', 'basic_audit', 'returns_refunds', 'escalation_queue', 'csv_export']
      },
      {
        id: 'pro',
        name: 'Pro',
        price_monthly: 2999,
        price_yearly: 29990,
        chat_limit: -1,
        features: [
          'Unlimited AI chats',
          'Image defect analysis',
          'Voice assistant',
          'Leakage detector and salvage',
          'Trust tiers and priority support'
        ],
        feature_keys: ['order_tracking', 'basic_audit', 'returns_refunds', 'escalation_queue', 'csv_export', 'image_defect_analysis', 'voice_assistant', 'leakage_salvage', 'priority_support']
      }
    ]);
  };

  const handleSelectRole = (newRole: 'ADMIN' | 'CUSTOMER') => {
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

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMsg('');

    try {
      const apiBase = getApiBaseUrl();
      const res = await fetch(`${apiBase}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password })
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Incorrect email or password');
      }

      const data = await res.json();
      authService.setSession(data.access_token, data.user);

      // If Admin, prefetch subscription to verify plan load
      if (data.user.role === 'ADMIN') {
        try {
          await fetch(`${apiBase}/api/subscription`, {
            headers: { Authorization: `Bearer ${data.access_token}` }
          });
        } catch {
          // ignore background prefetch error
        }
      }

      onLoginSuccess(data.user);
    } catch (err: any) {
      if (err.name === 'TypeError' && err.message?.toLowerCase().includes('fetch')) {
        setErrorMsg('Unable to connect to backend server. Please verify the service is running.');
      } else {
        setErrorMsg(err.message || 'Incorrect email or password');
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Open the Create Account / Checkout flow for a selected plan
  const handleChoosePlan = (planId: string, isTrial: boolean = false) => {
    setSelectedPlanForSignup(planId);
    setIsTrialIntent(isTrial);
    setSignupStep('account');
    setSignupError('');
    setIsSignupModalOpen(true);
  };

  // Execute complete signup + mock checkout
  const handleCompleteRegistrationAndCheckout = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setIsSubmittingSignup(true);
    setSignupError('');

    try {
      const apiBase = getApiBaseUrl();

      // Step 1: POST /api/auth/signup
      const signupRes = await fetch(`${apiBase}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          store_name: signupStoreName.trim(),
          email: signupEmail.trim(),
          password: signupPassword,
          full_name: signupStoreName.trim()
        })
      });

      if (!signupRes.ok) {
        const errData = await signupRes.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to create account. Please try again.');
      }

      const signupData = await signupRes.json();
      const token = signupData.access_token;
      const user = signupData.user;

      // Step 2: POST /api/subscription/checkout
      const isPaid = selectedPlanForSignup !== 'starter' && !isTrialIntent;
      const checkoutPayload: any = {
        plan_id: selectedPlanForSignup,
        billing_cycle: billingCycle,
        is_trial: isTrialIntent
      };

      if (isPaid) {
        checkoutPayload.test_card = {
          number: testCardNumber,
          exp: testCardExp,
          cvc: testCardCvc,
          name: testCardName
        };
      }

      const checkoutRes = await fetch(`${apiBase}/api/subscription/checkout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(checkoutPayload)
      });

      if (!checkoutRes.ok) {
        const chkErr = await checkoutRes.json().catch(() => ({}));
        throw new Error(chkErr.detail || 'Subscription setup failed. Please verify test card.');
      }

      // Success! Set session and route to Admin Dashboard
      authService.setSession(token, user);
      setIsSignupModalOpen(false);
      onLoginSuccess(user);
    } catch (err: any) {
      setSignupError(err.message || 'Registration failed. Please try again.');
    } finally {
      setIsSubmittingSignup(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-[#F6F8FB] dark:bg-[#0B0F14] text-[#0F1720] dark:text-[#F2F6FA] font-sans antialiased transition-colors duration-200">
      {/* ══ HEADER ══ */}
      <header className="w-full border-b border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#131A22] sticky top-0 z-40 transition-colors">
        <div className="max-w-[1280px] mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          {/* Logo square + SellerShield AI */}
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-[10px] bg-[#0B7A5A] text-white flex items-center justify-center font-black text-xl shadow-sm"
              aria-hidden="true"
            >
              🛡️
            </div>
            <div>
              <span className="font-extrabold text-lg tracking-tight text-[#0F1720] dark:text-white">
                SellerShield <span className="text-[#0B7A5A] dark:text-[#3DD6A0]">AI</span>
              </span>
            </div>
          </div>

          {/* Right header: Seller admin portal + Dark theme toggle */}
          <div className="flex items-center gap-3 sm:gap-4">
            <span className="text-xs sm:text-sm font-semibold text-[#4A5868] dark:text-[#A9B6C4] hidden xs:inline-block">
              Seller admin portal
            </span>

            {/* Dark Theme Toggle Button */}
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              className="p-2 rounded-xl border border-[#D5DCE5] dark:border-[#2A3644] bg-[#F6F8FB] dark:bg-[#1B2430] text-[#0F1720] dark:text-[#F2F6FA] hover:border-[#0B7A5A] focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden transition-all flex items-center gap-1.5 text-xs font-semibold"
            >
              {theme === 'dark' ? (
                <>
                  <Sun className="w-4 h-4 text-[#FFB84D]" aria-hidden="true" />
                  <span className="hidden sm:inline">Light</span>
                </>
              ) : (
                <>
                  <Moon className="w-4 h-4 text-[#4A5868]" aria-hidden="true" />
                  <span className="hidden sm:inline">Dark</span>
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* ══ MAIN CONTAINER (1280px design width, responsive grid) ══ */}
      <main className="max-w-[1280px] mx-auto px-4 sm:px-6 py-8 sm:py-12">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-start">
          
          {/* ══ LEFT COLUMN: LOGIN CARD (Max 400px, stacks first under 900px) ══ */}
          <div className="w-full lg:col-span-5 xl:col-span-4 max-w-[420px] mx-auto lg:mx-0">
            <div className="bg-white dark:bg-[#131A22] rounded-[16px] border border-[#D5DCE5] dark:border-[#2A3644] p-6 sm:p-8 shadow-sm transition-colors">
              
              {/* Card Header */}
              <div className="mb-6">
                <h1 className="text-2xl font-extrabold text-[#0F1720] dark:text-white tracking-tight">
                  Welcome back
                </h1>
                <p className="text-sm text-[#4A5868] dark:text-[#A9B6C4] mt-1">
                  Sign in to manage your autonomous AI store operations.
                </p>
              </div>

              {/* Portal Mode Tab (Admin by default; customer option preserved for testing) */}
              <div className="flex rounded-xl bg-[#F6F8FB] dark:bg-[#1B2430] p-1 border border-[#D5DCE5] dark:border-[#2A3644] mb-6 text-xs font-bold">
                <button
                  type="button"
                  onClick={() => handleSelectRole('ADMIN')}
                  className={`flex-1 py-2 rounded-lg transition-all flex items-center justify-center gap-2 ${
                    role === 'ADMIN'
                      ? 'bg-[#0B7A5A] text-white shadow-xs'
                      : 'text-[#4A5868] dark:text-[#A9B6C4] hover:text-[#0F1720] dark:hover:text-white'
                  }`}
                >
                  <LayoutDashboard className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Seller Admin</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectRole('CUSTOMER')}
                  className={`flex-1 py-2 rounded-lg transition-all flex items-center justify-center gap-2 ${
                    role === 'CUSTOMER'
                      ? 'bg-[#0B7A5A] text-white shadow-xs'
                      : 'text-[#4A5868] dark:text-[#A9B6C4] hover:text-[#0F1720] dark:hover:text-white'
                  }`}
                >
                  <ShoppingBag className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Customer View</span>
                </button>
              </div>

              {/* Demo Account Switcher Chips */}
              <div className="mb-5 flex flex-wrap items-center gap-1.5 text-[11px] text-[#4A5868] dark:text-[#A9B6C4]">
                <span className="font-medium">Quick fill:</span>
                {role === 'ADMIN' ? (
                  <button
                    type="button"
                    onClick={() => {
                      setEmail('admin@sellershield.com');
                      setPassword('admin123');
                    }}
                    className="px-2.5 py-1 rounded-md border border-[#D5DCE5] dark:border-[#2A3644] bg-[#F6F8FB] dark:bg-[#1B2430] font-mono text-[11px] hover:border-[#0B7A5A] text-[#0F1720] dark:text-[#F2F6FA]"
                  >
                    Sarah (Store Admin)
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        setEmail('rahul@gmail.com');
                        setPassword('rahul123');
                      }}
                      className="px-2 py-0.5 rounded-md border border-[#D5DCE5] dark:border-[#2A3644] bg-[#F6F8FB] dark:bg-[#1B2430] font-mono hover:border-[#0B7A5A] text-[#0F1720] dark:text-[#F2F6FA]"
                    >
                      Rahul
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEmail('ananya@gmail.com');
                        setPassword('ananya123');
                      }}
                      className="px-2 py-0.5 rounded-md border border-[#D5DCE5] dark:border-[#2A3644] bg-[#F6F8FB] dark:bg-[#1B2430] font-mono hover:border-[#0B7A5A] text-[#0F1720] dark:text-[#F2F6FA]"
                    >
                      Ananya
                    </button>
                  </>
                )}
              </div>

              {/* Error Alert */}
              {errorMsg && (
                <div
                  role="alert"
                  className="mb-4 p-3 rounded-[10px] bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-xs flex items-center gap-2"
                >
                  <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span>{errorMsg}</span>
                </div>
              )}

              {/* Login Form */}
              <form onSubmit={handleLoginSubmit} className="space-y-4">
                {/* Email Input */}
                <div>
                  <label
                    htmlFor="login-email"
                    className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1.5"
                  >
                    Email
                  </label>
                  <input
                    id="login-email"
                    name="email"
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="seller@example.com"
                    className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden transition-all"
                  />
                </div>

                {/* Password Input */}
                <div>
                  <label
                    htmlFor="login-password"
                    className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1.5"
                  >
                    Password
                  </label>
                  <input
                    id="login-password"
                    name="password"
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden transition-all"
                  />
                </div>

                {/* Submit Button (48px height, #0B7A5A primary, white text) */}
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full h-[48px] rounded-[10px] bg-[#0B7A5A] text-white font-bold text-sm hover:bg-[#085f46] active:scale-[0.99] transition-all flex items-center justify-center gap-2 shadow-sm disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus-visible:ring-offset-2 focus:outline-hidden mt-2"
                >
                  {isLoading ? (
                    <span>Authenticating...</span>
                  ) : (
                    <>
                      <span>Log in</span>
                      <ArrowRight className="w-4 h-4" aria-hidden="true" />
                    </>
                  )}
                </button>
              </form>

              {/* Bottom Notice: "New seller? Create account and get a 14-day Pro trial." */}
              <div className="mt-6 pt-5 border-t border-[#D5DCE5] dark:border-[#2A3644] text-center text-xs text-[#4A5868] dark:text-[#A9B6C4]">
                New seller?{' '}
                <button
                  type="button"
                  onClick={() => handleChoosePlan('pro', true)}
                  className="font-bold text-[#0B7A5A] dark:text-[#3DD6A0] hover:underline focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden rounded-xs"
                >
                  Create account
                </button>{' '}
                and get a 14-day Pro trial.
              </div>
            </div>
          </div>

          {/* ══ RIGHT COLUMN: SUBSCRIPTION PLANS (Cards wrap, responsive) ══ */}
          <div className="w-full lg:col-span-7 xl:col-span-8">
            <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-2xl font-extrabold text-[#0F1720] dark:text-white tracking-tight">
                  Choose your plan
                </h2>
                <p className="text-xs sm:text-sm text-[#4A5868] dark:text-[#A9B6C4] mt-0.5">
                  Flexible plans designed to scale with your e-commerce order volume.
                </p>
              </div>

              {/* Pill Toggle: [Monthly | Yearly, 2 months free] (role="switch", accessible keyboard navigation) */}
              <div
                role="radiogroup"
                aria-label="Billing frequency"
                className="inline-flex items-center rounded-full bg-white dark:bg-[#131A22] border border-[#D5DCE5] dark:border-[#2A3644] p-1 shadow-xs self-start sm:self-auto"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={billingCycle === 'monthly'}
                  tabIndex={0}
                  onClick={() => setBillingCycle('monthly')}
                  onKeyDown={e => {
                    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') setBillingCycle('yearly');
                  }}
                  className={`px-3 sm:px-4 py-1.5 rounded-full text-xs font-bold transition-all flex items-center gap-1.5 ${
                    billingCycle === 'monthly'
                      ? 'bg-[#0B7A5A] text-white shadow-xs'
                      : 'text-[#4A5868] dark:text-[#A9B6C4] hover:text-[#0F1720] dark:hover:text-white'
                  }`}
                >
                  {billingCycle === 'monthly' && <Check className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />}
                  <span>Monthly</span>
                </button>

                <button
                  type="button"
                  role="radio"
                  aria-checked={billingCycle === 'yearly'}
                  tabIndex={0}
                  onClick={() => setBillingCycle('yearly')}
                  onKeyDown={e => {
                    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') setBillingCycle('monthly');
                  }}
                  className={`px-3 sm:px-4 py-1.5 rounded-full text-xs font-bold transition-all flex items-center gap-1.5 ${
                    billingCycle === 'yearly'
                      ? 'bg-[#0B7A5A] text-white shadow-xs'
                      : 'text-[#4A5868] dark:text-[#A9B6C4] hover:text-[#0F1720] dark:hover:text-white'
                  }`}
                >
                  {billingCycle === 'yearly' && <Check className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />}
                  <span>Yearly</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full uppercase tracking-wider font-extrabold ${
                    billingCycle === 'yearly'
                      ? 'bg-white/20 text-white'
                      : 'bg-emerald-100 text-[#0B7A5A] dark:bg-emerald-950 dark:text-[#3DD6A0]'
                  }`}>
                    2 months free
                  </span>
                </button>
              </div>
            </div>

            {/* 3 Plan Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {plans.map(p => {
                const isGrowth = p.id === 'growth';
                const isPro = p.id === 'pro';
                const isStarter = p.id === 'starter';

                // Price display: yearly = monthly x 10
                const priceDisplay =
                  billingCycle === 'yearly'
                    ? (p.price_yearly === 0 ? '₹0' : `₹${p.price_yearly.toLocaleString('en-IN')}`)
                    : (p.price_monthly === 0 ? '₹0' : `₹${p.price_monthly.toLocaleString('en-IN')}`);

                const periodText = billingCycle === 'yearly' ? '/year' : '/month';

                return (
                  <div
                    key={p.id}
                    className={`bg-white dark:bg-[#131A22] rounded-[16px] p-5 sm:p-6 flex flex-col justify-between transition-all duration-200 shadow-sm relative ${
                      isGrowth
                        ? 'border-2 border-[#0B7A5A] dark:border-[#3DD6A0] shadow-md ring-1 ring-[#0B7A5A]/20'
                        : 'border border-[#D5DCE5] dark:border-[#2A3644]'
                    }`}
                  >
                    {/* "Most popular" badge for Growth */}
                    {isGrowth && (
                      <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0B7A5A] text-white text-[11px] font-extrabold uppercase tracking-wider px-3 py-0.5 rounded-full shadow-sm flex items-center gap-1">
                        <Sparkles className="w-3 h-3" aria-hidden="true" />
                        <span>Most popular</span>
                      </div>
                    )}

                    <div>
                      {/* Plan Title & Limits */}
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="font-extrabold text-lg text-[#0F1720] dark:text-white">
                          {p.name}
                        </h3>
                        {isPro && (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300">
                            Enterprise AI
                          </span>
                        )}
                      </div>

                      {/* Price Section */}
                      <div className="my-3">
                        <span className="text-3xl font-black text-[#0F1720] dark:text-white">
                          {priceDisplay}
                        </span>
                        <span className="text-xs font-semibold text-[#4A5868] dark:text-[#A9B6C4] ml-1">
                          {periodText}
                        </span>
                        {billingCycle === 'yearly' && p.price_monthly > 0 && (
                          <div className="text-[11px] text-[#0B7A5A] dark:text-[#3DD6A0] font-bold mt-0.5">
                            Save ₹{(p.price_monthly * 2).toLocaleString('en-IN')} (2 months free)
                          </div>
                        )}
                      </div>

                      {/* Feature Bullet List */}
                      <ul className="space-y-2.5 my-5 text-xs text-[#0F1720] dark:text-[#F2F6FA]">
                        {p.features.map((feature, idx) => (
                          <li key={idx} className="flex items-start gap-2">
                            <CheckCircle2
                              className={`w-4 h-4 shrink-0 mt-0.5 ${
                                isGrowth || isPro ? 'text-[#0B7A5A] dark:text-[#3DD6A0]' : 'text-[#4A5868] dark:text-[#A9B6C4]'
                              }`}
                              aria-hidden="true"
                            />
                            <span className="leading-tight">{feature}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Action Button */}
                    <div className="pt-4 border-t border-[#D5DCE5]/60 dark:border-[#2A3644]/60">
                      {isStarter && (
                        <button
                          type="button"
                          onClick={() => handleChoosePlan('starter', false)}
                          className="w-full py-2.5 rounded-[10px] border border-[#0B7A5A] text-[#0B7A5A] dark:text-[#3DD6A0] dark:border-[#3DD6A0] font-bold text-xs hover:bg-[#0B7A5A]/10 active:scale-[0.99] transition-all focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                        >
                          Start free
                        </button>
                      )}

                      {isGrowth && (
                        <button
                          type="button"
                          onClick={() => handleChoosePlan('growth', false)}
                          className="w-full py-2.5 rounded-[10px] bg-[#0B7A5A] text-white font-bold text-xs hover:bg-[#085f46] active:scale-[0.99] transition-all shadow-xs focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                        >
                          Choose Growth
                        </button>
                      )}

                      {isPro && (
                        <button
                          type="button"
                          onClick={() => handleChoosePlan('pro', true)}
                          className="w-full py-2.5 rounded-[10px] border-2 border-[#0B7A5A] text-[#0B7A5A] dark:text-[#3DD6A0] dark:border-[#3DD6A0] font-bold text-xs hover:bg-[#0B7A5A]/10 active:scale-[0.99] transition-all focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                        >
                          Try Pro free for 14 days
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Footnote */}
            <p className="mt-5 text-center text-xs text-[#4A5868] dark:text-[#A9B6C4]">
              Sample prices. Checkout uses a test card only, so no real payment is taken.
            </p>
          </div>
        </div>
      </main>

      {/* ══ CREATE ACCOUNT & MOCK CHECKOUT MODAL ══ */}
      <AnimatePresence>
        {isSignupModalOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs overflow-y-auto"
            role="dialog"
            aria-modal="true"
            aria-labelledby="signup-modal-title"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white dark:bg-[#131A22] rounded-[16px] border border-[#D5DCE5] dark:border-[#2A3644] w-full max-w-lg p-6 sm:p-7 shadow-2xl relative"
            >
              {/* Close button */}
              <button
                type="button"
                onClick={() => setIsSignupModalOpen(false)}
                aria-label="Close dialog"
                className="absolute top-4 right-4 p-1.5 rounded-lg text-[#4A5868] hover:text-[#0F1720] dark:hover:text-white border border-transparent hover:border-[#D5DCE5] dark:hover:border-[#2A3644]"
              >
                <X className="w-4 h-4" aria-hidden="true" />
              </button>

              {/* Title & Plan Summary */}
              <div className="mb-5">
                <span className="text-[11px] font-extrabold uppercase tracking-wider text-[#0B7A5A] dark:text-[#3DD6A0] flex items-center gap-1 mb-1">
                  <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>
                    Selected: {selectedPlanForSignup.toUpperCase()} (
                    {isTrialIntent ? '14-Day Free Trial' : billingCycle}
                    )
                  </span>
                </span>
                <h3 id="signup-modal-title" className="text-xl font-extrabold text-[#0F1720] dark:text-white">
                  {signupStep === 'account' ? 'Create your seller account' : 'Confirm mock checkout'}
                </h3>
                <p className="text-xs text-[#4A5868] dark:text-[#A9B6C4] mt-0.5">
                  {signupStep === 'account'
                    ? 'Enter your store details to set up your AI support workspace.'
                    : 'Checkout uses test credentials only. No actual financial charge is made.'}
                </p>
              </div>

              {/* Error in modal */}
              {signupError && (
                <div
                  role="alert"
                  className="mb-4 p-3 rounded-[10px] bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-xs flex items-center gap-2"
                >
                  <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span>{signupError}</span>
                </div>
              )}

              {/* Step 1: Account Creation Form */}
              {signupStep === 'account' ? (
                <form
                  onSubmit={e => {
                    e.preventDefault();
                    if (!signupStoreName.trim() || !signupEmail.trim() || signupPassword.length < 6) {
                      setSignupError('Please provide store name, valid email, and password (min 6 chars).');
                      return;
                    }
                    setSignupError('');
                    // If Starter or Free Pro Trial, we can directly create and checkout!
                    if (selectedPlanForSignup === 'starter' || isTrialIntent) {
                      handleCompleteRegistrationAndCheckout();
                    } else {
                      // Paid plan: proceed to mock card verification step
                      setSignupStep('checkout');
                    }
                  }}
                  className="space-y-4"
                >
                  <div>
                    <label
                      htmlFor="signup-store-name"
                      className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                    >
                      Store Name
                    </label>
                    <input
                      id="signup-store-name"
                      type="text"
                      required
                      value={signupStoreName}
                      onChange={e => setSignupStoreName(e.target.value)}
                      placeholder="e.g. Apex Apparel Store"
                      className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="signup-email"
                      className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                    >
                      Business Email
                    </label>
                    <input
                      id="signup-email"
                      type="email"
                      required
                      value={signupEmail}
                      onChange={e => setSignupEmail(e.target.value)}
                      placeholder="owner@store.com"
                      className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="signup-password"
                      className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                    >
                      Password (min 6 characters)
                    </label>
                    <input
                      id="signup-password"
                      type="password"
                      required
                      minLength={6}
                      value={signupPassword}
                      onChange={e => setSignupPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={isSubmittingSignup}
                    className="w-full h-[48px] rounded-[10px] bg-[#0B7A5A] text-white font-bold text-sm hover:bg-[#085f46] transition-all flex items-center justify-center gap-2 shadow-sm disabled:opacity-60 mt-4 focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                  >
                    {isSubmittingSignup ? (
                      <span>Setting up your store...</span>
                    ) : (
                      <>
                        <span>
                          {selectedPlanForSignup === 'starter'
                            ? 'Activate Starter plan'
                            : isTrialIntent
                            ? 'Start 14-day Pro trial'
                            : 'Continue to mock checkout'}
                        </span>
                        <ArrowRight className="w-4 h-4" aria-hidden="true" />
                      </>
                    )}
                  </button>
                </form>
              ) : (
                /* Step 2: Mock Test Card Checkout */
                <form onSubmit={handleCompleteRegistrationAndCheckout} className="space-y-4">
                  <div className="p-3 rounded-[10px] bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-xs text-emerald-800 dark:text-emerald-300 flex items-center justify-between">
                    <span>Test Card Verification Mode</span>
                    <button
                      type="button"
                      onClick={() => {
                        setTestCardNumber('4242 4242 4242 4242');
                        setTestCardExp('12/28');
                        setTestCardCvc('123');
                        setTestCardName('Demo Merchant');
                      }}
                      className="underline font-bold text-[11px]"
                    >
                      Fill Demo Card
                    </button>
                  </div>

                  <div>
                    <label
                      htmlFor="test-card-name"
                      className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                    >
                      Cardholder Name
                    </label>
                    <input
                      id="test-card-name"
                      type="text"
                      required
                      value={testCardName}
                      onChange={e => setTestCardName(e.target.value)}
                      className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="test-card-num"
                      className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                    >
                      Test Card Number
                    </label>
                    <div className="relative">
                      <CreditCard className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-[#4A5868]" aria-hidden="true" />
                      <input
                        id="test-card-num"
                        type="text"
                        required
                        value={testCardNumber}
                        onChange={e => setTestCardNumber(e.target.value)}
                        placeholder="4242 4242 4242 4242"
                        className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white pl-10 pr-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden font-mono"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label
                        htmlFor="test-card-exp"
                        className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                      >
                        Expiry (MM/YY)
                      </label>
                      <input
                        id="test-card-exp"
                        type="text"
                        required
                        value={testCardExp}
                        onChange={e => setTestCardExp(e.target.value)}
                        placeholder="12/28"
                        className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden font-mono"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="test-card-cvc"
                        className="block text-xs font-bold text-[#0F1720] dark:text-[#F2F6FA] mb-1"
                      >
                        CVC
                      </label>
                      <input
                        id="test-card-cvc"
                        type="password"
                        maxLength={4}
                        required
                        value={testCardCvc}
                        onChange={e => setTestCardCvc(e.target.value)}
                        placeholder="123"
                        className="w-full h-[46px] rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] bg-white dark:bg-[#1B2430] text-[#0F1720] dark:text-white px-3.5 text-sm focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden font-mono"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-3 mt-5">
                    <button
                      type="button"
                      onClick={() => setSignupStep('account')}
                      className="px-4 py-3 rounded-[10px] border border-[#D5DCE5] dark:border-[#2A3644] text-xs font-bold hover:bg-[#F6F8FB] dark:hover:bg-[#1B2430]"
                    >
                      Back
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmittingSignup}
                      className="flex-1 h-[48px] rounded-[10px] bg-[#0B7A5A] text-white font-bold text-sm hover:bg-[#085f46] transition-all flex items-center justify-center gap-2 shadow-sm disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-[#0B7A5A] focus:outline-hidden"
                    >
                      {isSubmittingSignup ? (
                        <span>Processing mock test card...</span>
                      ) : (
                        <>
                          <span>Complete & Launch Dashboard</span>
                          <Check className="w-4 h-4" aria-hidden="true" />
                        </>
                      )}
                    </button>
                  </div>
                </form>
              )}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};
