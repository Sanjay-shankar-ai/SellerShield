import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Wallet,
  X,
  ArrowDownLeft,
  ArrowUpRight,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Receipt
} from 'lucide-react';
import { UserProfile, WalletTransaction, WalletData } from '../../types';
import { authService } from '../../api/authService';

interface WalletModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentUser: UserProfile;
}

export const WalletModal: React.FC<WalletModalProps> = ({
  isOpen,
  onClose,
  currentUser
}) => {
  const [walletData, setWalletData] = useState<WalletData | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchWallet = async () => {
    setIsLoading(true);
    try {
      const res = await authService.authFetch('/api/wallet');
      if (res.ok) {
        const data = await res.json();
        setWalletData(data);
      }
    } catch (err) {
      console.warn('Failed to fetch wallet transactions:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchWallet();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const balance = walletData?.wallet_balance ?? (currentUser.wallet_balance || 0);
  const transactions = walletData?.transactions || [];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          transition={{ duration: 0.2 }}
          className="relative w-full max-w-lg bg-surface border border-border rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-border bg-surface-2/60">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                <Wallet className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-text-main text-sm flex items-center gap-1.5">
                  SellerShield Wallet
                  <ShieldCheck className="w-4 h-4 text-primary" />
                </h3>
                <p className="text-[11px] text-text-muted">Instant Store Credit & Transaction Ledger</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-text-muted hover:text-text-main hover:bg-surface-2 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Balance Card */}
          <div className="p-4 bg-gradient-to-br from-primary/10 via-surface-2/30 to-surface border-b border-border">
            <div className="flex items-start justify-between">
              <div>
                <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wider block mb-1">
                  Current Available Balance
                </span>
                <div className="text-3xl font-extrabold font-mono text-text-main flex items-baseline gap-1">
                  <span className="text-primary">₹</span>
                  <span>{balance.toLocaleString('en-IN')}</span>
                </div>
              </div>
              <button
                onClick={fetchWallet}
                disabled={isLoading}
                title="Refresh wallet balance"
                className="p-2 rounded-xl bg-surface border border-border hover:border-primary/40 text-text-muted hover:text-text-main transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-primary' : ''}`} />
              </button>
            </div>

            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border/60 text-[11px] text-text-muted">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 font-medium">
                <Sparkles className="w-3 h-3" /> Auto-applies at checkout
              </span>
              <span>• Instant • No expiration</span>
            </div>
          </div>

          {/* Transaction Activity Section */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            <div className="flex items-center justify-between pb-1">
              <div className="flex items-center gap-1.5 text-xs font-bold text-text-main">
                <Receipt className="w-4 h-4 text-text-muted" />
                <span>Wallet Activity (Transactions)</span>
              </div>
              <span className="text-[11px] text-text-muted font-mono">
                {transactions.length} {transactions.length === 1 ? 'record' : 'records'}
              </span>
            </div>

            {isLoading && transactions.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center text-text-muted text-xs gap-2">
                <RefreshCw className="w-5 h-5 animate-spin text-primary" />
                <span>Loading transaction activity...</span>
              </div>
            ) : transactions.length === 0 ? (
              <div className="py-10 text-center text-text-muted text-xs border border-dashed border-border rounded-xl p-4">
                <Wallet className="w-8 h-8 mx-auto mb-2 opacity-30 text-primary" />
                <p className="font-semibold text-text-main">No wallet activity yet</p>
                <p className="text-[11px] mt-1">Refunds and store credits will show here with + and - entries.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {transactions.map((tx: WalletTransaction) => {
                  const isCredit = tx.type === 'CREDIT';
                  return (
                    <div
                      key={tx.id}
                      className="p-3 rounded-xl border border-border bg-surface-2/40 hover:bg-surface-2 transition-colors flex items-center justify-between gap-3"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div
                          className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                            isCredit
                              ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                              : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                          }`}
                        >
                          {isCredit ? (
                            <ArrowDownLeft className="w-5 h-5" />
                          ) : (
                            <ArrowUpRight className="w-5 h-5" />
                          )}
                        </div>

                        <div className="min-w-0">
                          <div className="text-xs font-bold text-text-main truncate">
                            {tx.description}
                          </div>
                          <div className="text-[11px] text-text-muted flex items-center gap-2 mt-0.5">
                            <span>{tx.created_at}</span>
                            {tx.order_number && (
                              <span className="px-1.5 py-0.2 rounded bg-surface border border-border text-[10px] font-mono">
                                {tx.order_number}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <div
                          className={`text-sm font-extrabold font-mono ${
                            isCredit ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {isCredit ? '+' : '-'} ₹{tx.amount.toLocaleString('en-IN')}
                        </div>
                        <div className="text-[10px] text-text-muted font-mono">
                          Bal: ₹{tx.balance_after.toLocaleString('en-IN')}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-border bg-surface-2/60 text-center">
            <button
              onClick={onClose}
              className="w-full py-2.5 rounded-xl bg-surface border border-border text-xs font-bold text-text-main hover:bg-surface-2 transition-colors"
            >
              Done
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
