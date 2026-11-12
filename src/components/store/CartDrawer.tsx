import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  ShoppingBag,
  Trash2,
  ArrowRight,
  ShieldCheck,
  CreditCard,
  MapPin,
  Phone,
  User,
  CheckCircle2,
  Wallet,
  Tag,
  Percent,
  Check,
  Sparkles
} from 'lucide-react';
import { Product, CartItem, UserProfile } from '../../types';
import { authService } from '../../api/authService';
import { useToast } from '../common/ToastContext';

interface CartDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  items: CartItem[];
  currentUser: UserProfile;
  onUpdateQuantity: (productId: string, quantity: number) => void;
  onRemoveItem: (productId: string) => void;
  onOrderPlaced: (orderNumber: string) => void;
}

export const CartDrawer: React.FC<CartDrawerProps> = ({
  isOpen,
  onClose,
  items,
  currentUser,
  onUpdateQuantity,
  onRemoveItem,
  onOrderPlaced
}) => {
  const toast = useToast();
  const [address, setAddress] = useState('Flat 402, Green Glen Layout, Bellandur, Bengaluru 560103');
  const [phone, setPhone] = useState(currentUser.phone || '+91 98450 12891');
  const [paymentMethod, setPaymentMethod] = useState<'COD' | 'MOCK_UPI'>('MOCK_UPI');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [step, setStep] = useState<'cart' | 'checkout'>('cart');

  // Promo code & wallet state
  const [promoCodeInput, setPromoCodeInput] = useState('');
  const [appliedPromo, setAppliedPromo] = useState<{
    code: string;
    discount: number;
    discount_type?: string;
    percent?: number;
    message: string;
  } | null>(null);
  const [isValidatingPromo, setIsValidatingPromo] = useState(false);
  const [promoError, setPromoError] = useState('');
  const [useWallet, setUseWallet] = useState(true);

  const subtotal = items.reduce((acc, item) => acc + item.product.price * item.quantity, 0);

  // Discount & Wallet deduction calculation
  const promoDiscount = appliedPromo
    ? appliedPromo.discount_type === 'PERCENT'
      ? Math.round(subtotal * ((appliedPromo.percent || 10) / 100))
      : Math.min(subtotal, appliedPromo.discount)
    : 0;

  const amountAfterPromo = Math.max(0, subtotal - promoDiscount);
  const walletAvailable = currentUser.wallet_balance || 0;
  const walletDeduction = useWallet && walletAvailable > 0 ? Math.min(walletAvailable, amountAfterPromo) : 0;
  const finalPayable = Math.max(0, amountAfterPromo - walletDeduction);

  const handleApplyPromo = async () => {
    if (!promoCodeInput.trim()) {
      setPromoError('Please enter a coupon code');
      return;
    }
    setIsValidatingPromo(true);
    setPromoError('');
    try {
      const res = await authService.authFetch('/api/promo/validate', {
        method: 'POST',
        body: JSON.stringify({ code: promoCodeInput.trim() })
      });
      const data = await res.json();
      if (!res.ok || !data.valid) {
        throw new Error(data.detail || data.message || 'Invalid promo code');
      }
      setAppliedPromo(data);
      toast.show(data.message, 'success');
      setPromoCodeInput('');
    } catch (err: any) {
      setPromoError(err.message || 'Invalid or expired promo code');
      toast.show(err.message || 'Invalid promo code', 'error');
    } finally {
      setIsValidatingPromo(false);
    }
  };

  const handleRemovePromo = () => {
    setAppliedPromo(null);
    setPromoError('');
    toast.show('Promo code removed', 'info');
  };

  const handleCheckout = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!address.trim() || !phone.trim()) {
      toast.error('Please enter delivery address and phone number');
      return;
    }

    setIsSubmitting(true);
    try {
      const payload = {
        items: items.map(i => ({
          productId: i.product.id,
          selectedSize: i.selectedSize,
          quantity: i.quantity
        })),
        shippingAddress: address,
        phone: phone,
        paymentMethod: finalPayable === 0 ? 'WALLET' : paymentMethod,
        useWallet: useWallet && walletDeduction > 0,
        promoCode: appliedPromo?.code || undefined
      };

      const res = await authService.authFetch('/api/orders', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to place order');
      }

      const data = await res.json();
      toast.success(
        `Order Placed: ${data.order_number}`,
        'Automatic tracking scheduler started! You can track progress in My Orders.'
      );
      setStep('cart');
      setAppliedPromo(null);
      await authService.refreshUser();
      window.dispatchEvent(new Event('wallet_updated'));
      onOrderPlaced(data.order_number);
      onClose();
    } catch (err: any) {
      toast.error(err.message || 'Checkout failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 overflow-hidden">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
          />

          <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 220 }}
              className="w-screen max-w-md bg-surface border-l border-border shadow-2xl flex flex-col"
            >
              {/* Header */}
              <div className="p-4 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShoppingBag className="w-5 h-5 text-primary" />
                  <h2 className="font-bold text-text-main text-base">
                    {step === 'cart' ? 'Your Shopping Bag' : 'Checkout & Delivery'}
                  </h2>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-primary/20 text-primary font-mono font-semibold">
                    {items.reduce((acc, i) => acc + i.quantity, 0)} items
                  </span>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-lg text-text-muted hover:text-text-main hover:bg-surface-2 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Body */}
              {step === 'cart' ? (
                <>
                  <div className="flex-1 overflow-y-auto p-4 divide-y divide-border/60">
                    {items.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-center p-6 text-text-muted">
                        <ShoppingBag className="w-12 h-12 text-border mb-3" />
                        <p className="text-sm font-semibold text-text-main">Your cart is empty</p>
                        <p className="text-xs text-text-muted mt-1 max-w-xs">
                          Explore our collection and add items to experience automated delivery tracking and AI support.
                        </p>
                      </div>
                    ) : (
                      items.map(item => (
                        <div key={`${item.product.id}-${item.selectedSize}`} className="py-3.5 flex gap-3.5 items-start">
                          <img
                            src={item.product.image || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80'}
                            alt={item.product.title}
                            onError={(e) => {
                              e.currentTarget.onerror = null;
                              e.currentTarget.src = 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80';
                            }}
                            className="w-16 h-16 rounded-lg object-cover border border-border shrink-0 bg-surface-2"
                          />
                          <div className="flex-1 min-w-0">
                            <h4 className="text-sm font-bold text-text-main truncate">{item.product.title}</h4>
                            {item.selectedSize && (
                              <span className="text-[11px] text-text-muted block">Size: {item.selectedSize}</span>
                            )}
                            <div className="flex items-center justify-between mt-2">
                              <span className="text-sm font-bold text-text-main font-mono">
                                ₹{(item.product.price * item.quantity).toLocaleString('en-IN')}
                              </span>
                              {/* Quantity control */}
                              <div className="flex items-center border border-border rounded-lg bg-surface-2 text-xs">
                                <button
                                  onClick={() => onUpdateQuantity(item.product.id, Math.max(1, item.quantity - 1))}
                                  className="px-2 py-0.5 text-text-muted hover:text-text-main"
                                >
                                  -
                                </button>
                                <span className="px-2 font-mono font-semibold text-text-main">{item.quantity}</span>
                                <button
                                  onClick={() => onUpdateQuantity(item.product.id, item.quantity + 1)}
                                  className="px-2 py-0.5 text-text-muted hover:text-text-main"
                                >
                                  +
                                </button>
                              </div>
                            </div>
                          </div>
                          <button
                            onClick={() => onRemoveItem(item.product.id)}
                            className="text-text-muted hover:text-danger p-1 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>

                  {items.length > 0 && (
                    <div className="p-4 border-t border-border bg-surface-2/40 space-y-3">
                      <div className="flex justify-between text-xs text-text-muted">
                        <span>Subtotal</span>
                        <span className="text-text-main font-mono">₹{subtotal.toLocaleString('en-IN')}</span>
                      </div>
                      <div className="flex justify-between text-xs text-text-muted">
                        <span>Express Delivery</span>
                        <span className="text-success font-semibold">FREE</span>
                      </div>
                      <div className="flex justify-between text-base font-bold text-text-main pt-2 border-t border-border">
                        <span>Total Amount</span>
                        <span className="font-mono text-primary">₹{subtotal.toLocaleString('en-IN')}</span>
                      </div>

                      <button
                        onClick={() => setStep('checkout')}
                        className="w-full mt-2 py-3 rounded-xl bg-primary text-black font-bold text-sm hover:bg-primary-hover active:scale-[0.98] transition-all flex items-center justify-center gap-2 shadow-md"
                      >
                        <span>Proceed to Checkout</span>
                        <ArrowRight className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                </>
              ) : (
                /* Checkout Form Step */
                <form onSubmit={handleCheckout} className="flex-1 flex flex-col justify-between p-4 overflow-y-auto">
                  <div className="space-y-4">
                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">Customer</label>
                      <input
                        type="text"
                        disabled
                        value={currentUser.full_name}
                        className="w-full bg-surface-2 text-text-main text-xs rounded-xl p-2.5 border border-border opacity-70"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">Delivery Address</label>
                      <textarea
                        required
                        rows={3}
                        value={address}
                        onChange={e => setAddress(e.target.value)}
                        placeholder="House/Flat #, Street, Area, City, Pincode"
                        className="w-full bg-surface-2 text-text-main text-xs rounded-xl p-2.5 border border-border focus:border-primary focus:outline-hidden"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">Contact Phone</label>
                      <input
                        type="text"
                        required
                        value={phone}
                        onChange={e => setPhone(e.target.value)}
                        className="w-full bg-surface-2 text-text-main text-xs rounded-xl p-2.5 border border-border focus:border-primary focus:outline-hidden"
                      />
                    </div>

                    {/* Promo Code Section */}
                    <div className="p-3 rounded-xl border border-border bg-surface-2/40 space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-text-main flex items-center gap-1.5">
                          <Tag className="w-3.5 h-3.5 text-primary" />
                          <span>Promo / Discount Code</span>
                        </label>
                        {appliedPromo && (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-bold">
                            Applied
                          </span>
                        )}
                      </div>

                      {appliedPromo ? (
                        <div className="flex items-center justify-between p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-xs">
                          <div>
                            <span className="font-bold font-mono text-emerald-400">{appliedPromo.code}</span>
                            <span className="text-text-muted text-[11px] ml-2">
                              (-₹{promoDiscount.toLocaleString('en-IN')})
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={handleRemovePromo}
                            className="text-[11px] font-semibold text-rose-400 hover:text-rose-300 transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      ) : (
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={promoCodeInput}
                            onChange={e => {
                              setPromoCodeInput(e.target.value.toUpperCase());
                              setPromoError('');
                            }}
                            placeholder="Enter code (e.g. SELLER10, SHIELD-XXXX)"
                            className="flex-1 bg-surface text-text-main text-xs font-mono uppercase rounded-xl px-3 py-2 border border-border focus:border-primary focus:outline-hidden"
                          />
                          <button
                            type="button"
                            onClick={handleApplyPromo}
                            disabled={isValidatingPromo || !promoCodeInput.trim()}
                            className="px-3.5 py-2 rounded-xl bg-primary/20 hover:bg-primary/30 border border-primary/40 text-primary text-xs font-bold transition-all disabled:opacity-40"
                          >
                            {isValidatingPromo ? 'Checking...' : 'Apply'}
                          </button>
                        </div>
                      )}
                      {promoError && (
                        <p className="text-[11px] text-rose-400 font-medium">{promoError}</p>
                      )}
                    </div>

                    {/* Wallet Money Section */}
                    {walletAvailable > 0 && (
                      <div
                        onClick={() => setUseWallet(!useWallet)}
                        className={`p-3 rounded-xl border transition-all cursor-pointer ${
                          useWallet && walletDeduction > 0
                            ? 'bg-primary/10 border-primary/40 shadow-xs'
                            : 'bg-surface-2/40 border-border opacity-85'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2.5">
                            <input
                              type="checkbox"
                              checked={useWallet}
                              onChange={e => setUseWallet(e.target.checked)}
                              onClick={e => e.stopPropagation()}
                              className="w-4 h-4 rounded text-primary focus:ring-0 cursor-pointer accent-primary"
                            />
                            <div>
                              <div className="text-xs font-bold text-text-main flex items-center gap-1.5">
                                <Wallet className="w-3.5 h-3.5 text-primary" />
                                <span>Use SellerShield Wallet</span>
                              </div>
                              <span className="text-[11px] text-text-muted">
                                Available Balance: ₹{walletAvailable.toLocaleString('en-IN')}
                              </span>
                            </div>
                          </div>

                          <div className="text-right">
                            {useWallet && walletDeduction > 0 ? (
                              <span className="text-xs font-mono font-bold text-emerald-400">
                                -₹{walletDeduction.toLocaleString('en-IN')}
                              </span>
                            ) : (
                              <span className="text-[11px] text-text-muted">Off</span>
                            )}
                          </div>
                        </div>

                        {useWallet && finalPayable === 0 && (
                          <div className="mt-2 pt-2 border-t border-primary/20 flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400">
                            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                            <span>100% covered by your wallet money! ₹0 remaining.</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Payment Method Section */}
                    <div>
                      {finalPayable === 0 ? (
                        <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-xs">
                          <span className="font-bold text-emerald-400 flex items-center gap-1.5">
                            <CheckCircle2 className="w-4 h-4" />
                            Payment Method: SellerShield Wallet
                          </span>
                          <span className="text-[11px] text-text-muted mt-1 block">
                            ₹{walletDeduction.toLocaleString('en-IN')} will be deducted directly from your wallet. No additional payment required!
                          </span>
                        </div>
                      ) : (
                        <div>
                          <label className="text-xs font-semibold text-text-muted block mb-2">
                            {walletDeduction > 0
                              ? `Pay Remaining (₹${finalPayable.toLocaleString('en-IN')}) via:`
                              : 'Payment Method'}
                          </label>
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <button
                              type="button"
                              onClick={() => setPaymentMethod('MOCK_UPI')}
                              className={`p-3 rounded-xl border text-left font-semibold transition-all ${
                                paymentMethod === 'MOCK_UPI'
                                  ? 'border-primary bg-primary/10 text-text-main'
                                  : 'border-border bg-surface-2 text-text-muted'
                              }`}
                            >
                              <span className="block font-bold">Mock UPI</span>
                              <span className="text-[10px] text-text-muted">Instant GPay / PhonePe</span>
                            </button>

                            <button
                              type="button"
                              onClick={() => setPaymentMethod('COD')}
                              className={`p-3 rounded-xl border text-left font-semibold transition-all ${
                                paymentMethod === 'COD'
                                  ? 'border-primary bg-primary/10 text-text-main'
                                  : 'border-border bg-surface-2 text-text-muted'
                              }`}
                            >
                              <span className="block font-bold">Cash on Delivery</span>
                              <span className="text-[10px] text-text-muted">Pay at doorstep</span>
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Summary & Place Order */}
                  <div className="pt-3 border-t border-border space-y-2.5 mt-4">
                    <div className="space-y-1 text-xs text-text-muted">
                      <div className="flex justify-between">
                        <span>Items Subtotal</span>
                        <span className="font-mono text-text-main font-semibold">₹{subtotal.toLocaleString('en-IN')}</span>
                      </div>
                      {promoDiscount > 0 && (
                        <div className="flex justify-between text-emerald-400 font-semibold">
                          <span>Promo Discount ({appliedPromo?.code})</span>
                          <span className="font-mono">-₹{promoDiscount.toLocaleString('en-IN')}</span>
                        </div>
                      )}
                      {walletDeduction > 0 && (
                        <div className="flex justify-between text-emerald-400 font-semibold">
                          <span>Wallet Money Applied</span>
                          <span className="font-mono">-₹{walletDeduction.toLocaleString('en-IN')}</span>
                        </div>
                      )}
                    </div>

                    <div className="flex justify-between text-base font-bold text-text-main pt-2 border-t border-border/70">
                      <span>Total Payable</span>
                      <span className="font-mono text-primary">
                        {finalPayable === 0 ? (
                          <span className="text-emerald-400">₹0 (Paid via Wallet)</span>
                        ) : (
                          `₹${finalPayable.toLocaleString('en-IN')}`
                        )}
                      </span>
                    </div>

                    <div className="flex gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => setStep('cart')}
                        className="py-2.5 px-4 rounded-xl border border-border bg-surface-2 text-xs font-semibold hover:bg-surface transition-colors"
                      >
                        Back
                      </button>

                      <button
                        type="submit"
                        disabled={isSubmitting}
                        className="flex-1 py-2.5 rounded-xl bg-primary text-black font-bold text-xs hover:bg-primary-hover active:scale-[0.98] transition-all flex items-center justify-center gap-1.5 shadow-md disabled:opacity-50"
                      >
                        {isSubmitting ? (
                          <span>Placing Order...</span>
                        ) : (
                          <>
                            <span>
                              Confirm Order {finalPayable > 0 ? `(₹${finalPayable.toLocaleString('en-IN')})` : '(Free via Wallet)'}
                            </span>
                            <CheckCircle2 className="w-4 h-4" />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </form>
              )}
            </motion.div>
          </div>
        </div>
      )}
    </AnimatePresence>
  );
};
