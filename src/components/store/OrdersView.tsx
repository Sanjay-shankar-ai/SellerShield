import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Package,
  RotateCcw,
  Truck,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ArrowRight,
  X,
  MessageSquare,
  RefreshCw
} from 'lucide-react';
import { OrderRecord, TrackingEventItem } from '../../types';
import { authService } from '../../api/authService';
import { useToast } from '../common/ToastContext';

interface OrdersViewProps {
  onOpenChatWithOrder: (order: OrderRecord) => void;
}

export const OrdersView: React.FC<OrdersViewProps> = ({ onOpenChatWithOrder }) => {
  const toast = useToast();
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [activeTab, setActiveTab] = useState<'active' | 'past'>('active');
  const [isLoading, setIsLoading] = useState(true);
  const [trackingOrder, setTrackingOrder] = useState<OrderRecord | null>(null);
  const [trackingEvents, setTrackingEvents] = useState<TrackingEventItem[]>([]);
  const [loadingTracking, setLoadingTracking] = useState(false);

  const fetchOrders = async (tabToFetch: 'active' | 'past' = activeTab) => {
    try {
      const res = await authService.authFetch(`/api/orders?tab=${tabToFetch}`);
      if (res.ok) {
        const data = await res.json();
        setOrders(data);
      }
    } catch (err) {
      console.warn('Failed to fetch orders:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders(activeTab);
    // Poll every 10s to see automatic tracking progression in real-time
    const interval = setInterval(() => fetchOrders(activeTab), 10000);
    return () => clearInterval(interval);
  }, [activeTab]);

  const handleTabChange = (tab: 'active' | 'past') => {
    setActiveTab(tab);
    setIsLoading(true);
    fetchOrders(tab);
  };

  const handleOpenTracking = async (order: OrderRecord) => {
    setTrackingOrder(order);
    setLoadingTracking(true);
    try {
      const res = await authService.authFetch(`/api/orders/${order.id}/tracking`);
      if (res.ok) {
        const data = await res.json();
        setTrackingEvents(data.events || []);
      }
    } catch (err) {
      toast.error('Failed to load tracking events');
    } finally {
      setLoadingTracking(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'DELIVERED':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-success/15 text-success border border-success/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Delivered</span>
          </span>
        );
      case 'SHIPPED':
      case 'OUT_FOR_DELIVERY':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-accent/15 text-accent border border-accent/30 animate-pulse">
            <Truck className="w-3.5 h-3.5" />
            <span>{status === 'OUT_FOR_DELIVERY' ? 'Out for Delivery' : 'In Transit'}</span>
          </span>
        );
      case 'PACKED':
      case 'PLACED':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/15 text-primary border border-primary/30">
            <Clock className="w-3.5 h-3.5" />
            <span>{status}</span>
          </span>
        );
      case 'RETURN_REQUESTED':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-warning/15 text-warning border border-warning/30">
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Return Requested</span>
          </span>
        );
      case 'EXCHANGED':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/20 text-primary border border-primary/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Doorstep Exchange</span>
          </span>
        );
      case 'REFUNDED':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-success/20 text-success border border-success/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Refunded</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-surface-2 text-text-muted">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="w-full flex flex-col gap-6 max-w-5xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface border border-border p-5 rounded-3xl shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <Package className="w-6 h-6 text-primary" />
            <h1 className="text-xl sm:text-2xl font-bold text-text-main">My Orders & Tracking</h1>
          </div>
          <p className="text-xs text-text-muted mt-1">
            Orders automatically progress via the background tracking scheduler. Eligible delivered items include 1-click AI size swap.
          </p>
        </div>

        <button
          onClick={() => fetchOrders(activeTab)}
          className="px-3 py-1.5 rounded-xl border border-border bg-surface-2 hover:bg-surface text-text-main text-xs font-semibold flex items-center gap-1.5 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh Status</span>
        </button>
      </div>

      {/* Active vs Past Orders Tabs */}
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <button
          onClick={() => handleTabChange('active')}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
            activeTab === 'active'
              ? 'bg-primary text-black shadow-xs font-bold'
              : 'bg-surface-2 text-text-muted hover:text-text-main hover:bg-surface'
          }`}
        >
          <Truck className="w-3.5 h-3.5" />
          <span>Active Orders</span>
        </button>

        <button
          onClick={() => handleTabChange('past')}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
            activeTab === 'past'
              ? 'bg-primary text-black shadow-xs font-bold'
              : 'bg-surface-2 text-text-muted hover:text-text-main hover:bg-surface'
          }`}
        >
          <Clock className="w-3.5 h-3.5" />
          <span>Past Orders</span>
          <span className="text-[10px] text-text-muted font-normal">(Delivered &gt; 7 days)</span>
        </button>
      </div>

      {/* Orders List */}
      {isLoading ? (
        <div className="p-12 text-center text-text-muted text-xs">
          <Clock className="w-6 h-6 animate-spin mx-auto mb-2 text-primary" />
          <span>Loading orders...</span>
        </div>
      ) : orders.length === 0 ? (
        <div className="p-12 text-center rounded-3xl bg-surface border border-border text-text-muted">
          <Package className="w-12 h-12 text-border mx-auto mb-3" />
          <h3 className="text-base font-bold text-text-main">
            {activeTab === 'active' ? 'No active orders' : 'No past orders'}
          </h3>
          <p className="text-xs text-text-muted mt-1">
            {activeTab === 'active'
              ? 'In-transit orders and orders delivered in the last 7 days appear here. Older orders are in Past Orders.'
              : 'Orders delivered more than 7 days ago will appear here.'}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {orders.map(order => {
            const firstItem = order.items[0];

            return (
              <motion.div
                key={order.id}
                whileHover={{ y: -2 }}
                className="rounded-3xl bg-surface border border-border p-5 sm:p-6 shadow-sm hover:shadow-md transition-all flex flex-col gap-4"
              >
                {/* Header Row */}
                <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border/60">
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-sm text-text-main">{order.order_number}</span>
                    <span className="text-xs text-text-muted">{order.created_at}</span>
                  </div>
                  <div>{getStatusBadge(order.status)}</div>
                </div>

                {/* Items & Amount */}
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <div className="space-y-1">
                    {order.items.map((it, idx) => (
                      <div key={idx} className="flex items-center gap-2 text-sm font-semibold text-text-main">
                        <span>•</span>
                        <span>{it.product_title}</span>
                        {it.selected_size && (
                          <span className="text-xs text-text-muted font-normal">({it.selected_size})</span>
                        )}
                        <span className="text-xs text-text-muted">x{it.quantity}</span>
                      </div>
                    ))}
                    <div className="text-xs font-mono text-text-muted pt-1">
                      Total: <span className="font-bold text-text-main font-mono">₹{order.total_amount.toLocaleString('en-IN')}</span> ({order.payment_method})
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                    <button
                      onClick={() => handleOpenTracking(order)}
                      className="px-3.5 py-2 rounded-xl border border-border bg-surface-2 hover:bg-surface text-text-main text-xs font-semibold transition-colors flex items-center gap-1.5"
                    >
                      <Truck className="w-3.5 h-3.5 text-accent" />
                      <span>Track Shipment</span>
                    </button>

                    {/* Return/Exchange AI button on eligible orders */}
                    {order.status === 'DELIVERED' && order.is_eligible_return && (
                      <button
                        onClick={() => onOpenChatWithOrder(order)}
                        className="px-4 py-2 rounded-xl bg-primary text-black font-bold text-xs hover:bg-primary-hover transition-all flex items-center gap-1.5 shadow-sm active:scale-95"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>Return / Swap with AI</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Non-returnable hygiene item warning */}
                    {order.status === 'DELIVERED' && !order.is_eligible_return && (
                      <span className="px-3 py-1.5 rounded-xl bg-surface-2 text-text-muted text-xs font-semibold flex items-center gap-1 border border-border">
                        <AlertTriangle className="w-3.5 h-3.5 text-warning" />
                        <span>Non-Returnable Item</span>
                      </span>
                    )}

                    {order.status !== 'DELIVERED' && (
                      <button
                        onClick={() => onOpenChatWithOrder(order)}
                        className="px-3 py-2 rounded-xl border border-border bg-surface-2 hover:bg-surface text-text-main text-xs font-semibold transition-colors flex items-center gap-1"
                      >
                        <MessageSquare className="w-3.5 h-3.5 text-primary" />
                        <span>Ask AI Agent</span>
                      </button>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}

      {/* Automatic Tracking Timeline Modal */}
      <AnimatePresence>
        {trackingOrder && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setTrackingOrder(null)}
              className="absolute inset-0 bg-black/60 backdrop-blur-xs"
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="relative w-full max-w-lg bg-surface border border-border rounded-3xl shadow-2xl p-6 z-10"
            >
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <div>
                  <h3 className="font-bold text-text-main text-base">Live Shipment Tracking</h3>
                  <span className="text-xs text-text-muted font-mono">{trackingOrder.order_number}</span>
                </div>
                <button
                  onClick={() => setTrackingOrder(null)}
                  className="p-1.5 rounded-lg text-text-muted hover:text-text-main hover:bg-surface-2 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {loadingTracking ? (
                <div className="py-12 text-center text-xs text-text-muted">
                  <Clock className="w-6 h-6 animate-spin mx-auto mb-2 text-primary" />
                  <span>Fetching tracking timeline...</span>
                </div>
              ) : (
                <div className="py-6 space-y-4 max-h-[400px] overflow-y-auto">
                  {trackingEvents.map((ev, idx) => (
                    <div key={idx} className="flex items-start gap-3 relative">
                      <div className="w-7 h-7 rounded-full bg-primary/20 text-primary border border-primary/40 flex items-center justify-center text-xs font-bold shrink-0">
                        ✓
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <h4 className="text-xs font-bold text-text-main">{ev.title}</h4>
                          <span className="text-[10px] text-text-muted font-mono">{ev.timestamp}</span>
                        </div>
                        <p className="text-[11px] text-primary font-medium mt-0.5">{ev.location}</p>
                        <p className="text-[11px] text-text-muted mt-0.5 leading-snug">{ev.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="pt-3 border-t border-border flex justify-end">
                <button
                  onClick={() => setTrackingOrder(null)}
                  className="px-4 py-2 rounded-xl bg-surface-2 border border-border text-xs font-semibold text-text-main hover:bg-surface"
                >
                  Close
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};
