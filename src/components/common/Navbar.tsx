import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  ShoppingBag,
  Package,
  MessageSquare,
  LayoutDashboard,
  Sun,
  Moon,
  Sparkles,
  Key,
  LogOut,
  User as UserIcon,
  CheckCircle2,
  Wallet
} from 'lucide-react';
import { useTheme } from '../../theme/ThemeContext';
import { UserProfile } from '../../types';

export type CustomerPage = 'store' | 'orders' | 'chat';
export type ActivePage = 'store' | 'orders' | 'chat' | 'dashboard';

interface NavbarProps {
  currentUser: UserProfile;
  activeCustomerPage: CustomerPage;
  onNavigateCustomer: (page: CustomerPage) => void;
  cartCount: number;
  onOpenCart: () => void;
  onLogout: () => void;
  onOpenWallet?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  currentUser,
  activeCustomerPage,
  onNavigateCustomer,
  cartCount,
  onOpenCart,
  onLogout,
  onOpenWallet
}) => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';
  const isAdmin = currentUser.role === 'ADMIN';

  return (
    <header className="sticky top-0 z-40 w-full bg-surface/90 backdrop-blur-md border-b border-border shadow-xs transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Brand Logo */}
        <div
          onClick={() => {
            if (!isAdmin) onNavigateCustomer('store');
          }}
          className="flex items-center gap-2.5 cursor-pointer select-none group"
        >
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-primary to-accent flex items-center justify-center text-black font-bold shadow-md group-hover:scale-105 transition-transform">
            🛡️
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-extrabold text-base tracking-tight text-text-main">SellerShield</span>
              <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-primary text-black font-mono">
                AI
              </span>
            </div>
            <p className="text-[10px] text-text-muted hidden sm:block">
              {isAdmin ? 'Seller Control & Analytics Center' : 'Autonomous E-Commerce Store'}
            </p>
          </div>
        </div>

        {/* Customer Navigation Tabs (Only shown for customer accounts) */}
        {!isAdmin && (
          <nav className="flex items-center gap-1 bg-surface-2 p-1 rounded-xl border border-border text-xs">
            <button
              onClick={() => onNavigateCustomer('store')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeCustomerPage === 'store'
                  ? 'bg-primary text-black shadow-xs font-bold'
                  : 'text-text-muted hover:text-text-main'
              }`}
            >
              <ShoppingBag className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Store</span>
            </button>

            <button
              onClick={() => onNavigateCustomer('orders')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeCustomerPage === 'orders'
                  ? 'bg-primary text-black shadow-xs font-bold'
                  : 'text-text-muted hover:text-text-main'
              }`}
            >
              <Package className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">My Orders</span>
            </button>

            <button
              onClick={() => onNavigateCustomer('chat')}
              className={`px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all ${
                activeCustomerPage === 'chat'
                  ? 'bg-primary text-black shadow-xs font-bold'
                  : 'text-text-muted hover:text-text-main'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">AI Concierge</span>
              <span className="sm:hidden">Chat</span>
            </button>
          </nav>
        )}

        {/* Right Side Controls */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Active LLM Pill */}
          <div className="hidden lg:flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded-xl bg-surface border border-border text-text-muted">
            <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
            <span>SellerShield AI</span>
          </div>

          {/* Wallet Balance (Customer Only) - Clickable to open Wallet Activity Modal */}
          {!isAdmin && currentUser.wallet_balance !== undefined && (
            <button
              onClick={onOpenWallet}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary/10 hover:bg-primary/20 border border-primary/30 text-xs font-mono font-bold text-text-main transition-all cursor-pointer shadow-xs active:scale-95 group"
              title="Click to view Wallet Balance & Activity Ledger"
            >
              <Wallet className="w-3.5 h-3.5 text-primary group-hover:scale-110 transition-transform" />
              <span className="text-primary font-bold">₹</span>
              <span>{(currentUser.wallet_balance || 0).toLocaleString('en-IN')}</span>
            </button>
          )}

          {/* Cart Icon (Customer Only) */}
          {!isAdmin && (
            <button
              onClick={onOpenCart}
              className="relative p-2 rounded-xl border border-border bg-surface hover:bg-surface-2 text-text-main transition-colors"
              aria-label="View Cart"
            >
              <ShoppingBag className="w-4 h-4 text-text-main" />
              {cartCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-primary text-black font-extrabold text-[10px] flex items-center justify-center font-mono shadow-xs">
                  {cartCount}
                </span>
              )}
            </button>
          )}

          {/* User Profile Pill */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-surface-2 border border-border text-xs">
            <div className="w-5 h-5 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-[10px]">
              {currentUser.full_name[0]?.toUpperCase()}
            </div>
            <div className="hidden md:block">
              <span className="font-semibold text-text-main text-xs">{currentUser.full_name.split(' ')[0]}</span>
              <span className="text-[10px] text-text-muted ml-1">({currentUser.role})</span>
            </div>
          </div>

          {/* Theme Toggle (Dark / Light) */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-xl border border-border bg-surface hover:bg-surface-2 text-text-main transition-colors"
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? <Sun className="w-4 h-4 text-warning" /> : <Moon className="w-4 h-4 text-accent" />}
          </button>

          {/* Logout Button */}
          <button
            onClick={onLogout}
            className="p-2 rounded-xl border border-border bg-surface hover:bg-danger/15 hover:text-danger text-text-muted transition-colors"
            aria-label="Logout"
            title="Log out of account"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
};
