import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  ShoppingBag,
  AlertCircle,
  FileText,
  Sliders,
  Package,
  Truck,
  TrendingUp,
  Clock,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Download,
  Search,
  Filter,
  RefreshCw,
  Edit2,
  Save,
  Check,
  X,
  ExternalLink,
  ChevronRight,
  Eye,
  AlertTriangle
} from 'lucide-react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import {
  UserProfile,
  OrderRecord,
  EscalationRecord,
  AuditLogItem,
  Product,
  SettingItem,
  TrackingEventItem
} from '../../types';
import { authService } from '../../api/authService';
import { useToast } from '../common/ToastContext';

type AdminTab = 'overview' | 'orders' | 'escalations' | 'audit' | 'products' | 'settings';

interface AdminDashboardProps {
  currentUser: UserProfile;
}

export const AdminDashboard: React.FC<AdminDashboardProps> = ({ currentUser }) => {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState<AdminTab>('overview');
  const [isLoading, setIsLoading] = useState(false);

  // Dashboard Data States
  const [dashboardData, setDashboardData] = useState<{
    kpis: {
      totalRevenue: number;
      totalOrders: number;
      avgOrderValue: number;
      autoResolvedPct: number;
      refundsIssued: number;
      refundLimit: number;
      openEscalations: number;
    };
    salesTrends: Array<{ date: string; revenue: number; orders: number }>;
    categoryBreakdown: Array<{ category: string; orders_count: number }>;
  } | null>(null);

  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [escalations, setEscalations] = useState<EscalationRecord[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [settings, setSettings] = useState<SettingItem[]>([]);

  // Filtering states
  const [orderStatusFilter, setOrderStatusFilter] = useState('ALL');
  const [escalationFilter, setEscalationFilter] = useState('PENDING');
  const [auditToolFilter, setAuditToolFilter] = useState('');
  const [auditVerdictFilter, setAuditVerdictFilter] = useState('ALL');

  // Modals and Active Selections
  const [selectedOrderForTracking, setSelectedOrderForTracking] = useState<OrderRecord | null>(null);
  const [trackingTimeline, setTrackingTimeline] = useState<{ order?: OrderRecord; events: TrackingEventItem[]; [key: string]: any } | null>(null);
  const [loadingTracking, setLoadingTracking] = useState(false);
  const [selectedEscalation, setSelectedEscalation] = useState<EscalationRecord | null>(null);
  const [adminResolutionNotes, setAdminResolutionNotes] = useState('');
  const [isSubmittingResolution, setIsSubmittingResolution] = useState(false);

  // Product editing
  const [editingProductId, setEditingProductId] = useState<string | null>(null);
  const [editPrice, setEditPrice] = useState<number>(0);
  const [editStock, setEditStock] = useState<number>(0);
  const [editReturnable, setEditReturnable] = useState<boolean>(true);

  // Settings editing state
  const [settingRefundLimit, setSettingRefundLimit] = useState<number>(2000);
  const [settingReturnWindow, setSettingReturnWindow] = useState<number>(7);
  const [settingTrackingInterval, setSettingTrackingInterval] = useState<number>(45);

  // Manual Shipment Control States
  const [selectedOrderForShipment, setSelectedOrderForShipment] = useState<OrderRecord | null>(null);
  const [shipmentStage, setShipmentStage] = useState('PACKED');
  const [shipmentLocation, setShipmentLocation] = useState('Central Fulfillment Hub, Whitefield');
  const [shipmentTitle, setShipmentTitle] = useState('Order Packed & Sealed');
  const [shipmentDesc, setShipmentDesc] = useState('Items verified, barcoded, and sealed with tamper-proof security tape.');
  const [notifyCustomer, setNotifyCustomer] = useState(true);
  const [isUpdatingShipment, setIsUpdatingShipment] = useState(false);

  const STAGE_PRESETS: Record<string, { title: string; location: string; description: string }> = {
    PLACED: {
      title: 'Order Placed & Confirmed',
      location: 'Fulfillment Logistics Network',
      description: 'Order confirmed and queued for fulfillment.'
    },
    PACKED: {
      title: 'Order Packed & Sealed',
      location: 'Central Fulfillment Hub, Whitefield',
      description: 'Items verified, barcoded, and sealed with tamper-proof security tape.'
    },
    SHIPPED: {
      title: 'Dispatched on Linehaul Transit',
      location: 'Bengaluru South Distribution Hub',
      description: 'Package dispatched via Delhivery Express Air Cargo linehaul route.'
    },
    OUT_FOR_DELIVERY: {
      title: 'Out for Doorstep Delivery',
      location: 'Local Delivery Hub, Sector 4',
      description: 'Courier executive Ramesh (+91 98451 22100) is out for doorstep delivery.'
    },
    DELIVERED: {
      title: 'Delivered Successfully',
      location: 'Customer Doorstep Address',
      description: 'Delivered to recipient. 7-day return and doorstep size swap window is now active!'
    }
  };

  const fetchOverview = async () => {
    try {
      const res = await authService.authFetch('/api/admin/dashboard');
      if (res.ok) {
        const data = await res.json();
        setDashboardData(data);
      }
    } catch (e) {
      console.error('Failed to load dashboard', e);
    }
  };

  const fetchOrders = async () => {
    try {
      const res = await authService.authFetch('/api/orders');
      if (res.ok) {
        const data = await res.json();
        setOrders(data);
      }
    } catch (e) {
      console.error('Failed to load orders', e);
    }
  };

  const fetchEscalations = async () => {
    try {
      const res = await authService.authFetch('/api/admin/escalations');
      if (res.ok) {
        const data = await res.json();
        setEscalations(data);
      }
    } catch (e) {
      console.error('Failed to load escalations', e);
    }
  };

  const fetchAuditLogs = async () => {
    try {
      let url = '/api/admin/audit-logs?';
      if (auditToolFilter) url += `tool=${encodeURIComponent(auditToolFilter)}&`;
      if (auditVerdictFilter !== 'ALL') url += `verdict=${encodeURIComponent(auditVerdictFilter)}&`;
      const res = await authService.authFetch(url);
      if (res.ok) {
        const data = await res.json();
        setAuditLogs(data);
      }
    } catch (e) {
      console.error('Failed to load audit logs', e);
    }
  };

  const fetchProducts = async () => {
    try {
      const res = await authService.authFetch('/api/products');
      if (res.ok) {
        const data = await res.json();
        setProducts(data);
      }
    } catch (e) {
      console.error('Failed to load products', e);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await authService.authFetch('/api/admin/settings');
      if (res.ok) {
        const data: SettingItem[] = await res.json();
        setSettings(data);
        const refLimit = data.find(s => s.key === 'refund_limit');
        if (refLimit) setSettingRefundLimit(parseFloat(refLimit.value) || 2000);
        const retWin = data.find(s => s.key === 'return_window_days');
        if (retWin) setSettingReturnWindow(parseInt(retWin.value) || 7);
        const trkInt = data.find(s => s.key === 'tracking_advance_interval_sec');
        if (trkInt) setSettingTrackingInterval(parseInt(trkInt.value) || 45);
      }
    } catch (e) {
      console.error('Failed to load settings', e);
    }
  };

  // Initial load
  useEffect(() => {
    fetchOverview();
    fetchOrders();
    fetchEscalations();
    fetchProducts();
    fetchSettings();
  }, []);

  // Poll orders & dashboard periodically for automatic tracking updates
  useEffect(() => {
    const interval = setInterval(() => {
      fetchOrders();
      if (activeTab === 'overview') fetchOverview();
    }, 15000);
    return () => clearInterval(interval);
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === 'audit') fetchAuditLogs();
  }, [activeTab, auditToolFilter, auditVerdictFilter]);

  // Open Tracking Timeline Modal
  const handleOpenTracking = async (order: OrderRecord) => {
    setSelectedOrderForTracking(order);
    setLoadingTracking(true);
    try {
      const res = await authService.authFetch(`/api/orders/${order.id}/tracking`);
      if (res.ok) {
        const data = await res.json();
        setTrackingTimeline(data);
      } else {
        toast.show('Failed to fetch tracking details', 'error');
      }
    } catch (e) {
      toast.show('Failed to fetch tracking details', 'error');
    } finally {
      setLoadingTracking(false);
    }
  };

  // Open Shipment Manual Update Modal
  const handleOpenShipmentUpdate = (order: OrderRecord) => {
    setSelectedOrderForShipment(order);
    let nextStage = 'PACKED';
    if (order.status === 'PLACED') nextStage = 'PACKED';
    else if (order.status === 'PACKED') nextStage = 'SHIPPED';
    else if (order.status === 'SHIPPED') nextStage = 'OUT_FOR_DELIVERY';
    else if (order.status === 'OUT_FOR_DELIVERY') nextStage = 'DELIVERED';
    else nextStage = order.status;

    setShipmentStage(nextStage);
    const preset = STAGE_PRESETS[nextStage] || STAGE_PRESETS.PACKED;
    setShipmentLocation(preset.location);
    setShipmentTitle(preset.title);
    setShipmentDesc(preset.description);
    setNotifyCustomer(true);
  };

  const handleSelectStage = (stage: string) => {
    setShipmentStage(stage);
    const preset = STAGE_PRESETS[stage];
    if (preset) {
      setShipmentLocation(preset.location);
      setShipmentTitle(preset.title);
      setShipmentDesc(preset.description);
    }
  };

  const handleSaveShipmentUpdate = async () => {
    if (!selectedOrderForShipment) return;
    setIsUpdatingShipment(true);
    try {
      const res = await authService.authFetch(`/api/admin/orders/${selectedOrderForShipment.id}/shipment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: shipmentStage,
          location: shipmentLocation,
          title: shipmentTitle,
          description: shipmentDesc,
          notify_customer: notifyCustomer
        })
      });

      if (res.ok) {
        toast.show(`Shipment for ${selectedOrderForShipment.order_number} updated to ${shipmentStage}!`, 'success');
        setSelectedOrderForShipment(null);
        fetchOrders();
        fetchOverview();
      } else {
        const err = await res.json();
        toast.show(err.detail || 'Failed to update shipment', 'error');
      }
    } catch (e) {
      toast.show('Network error while updating shipment', 'error');
    } finally {
      setIsUpdatingShipment(false);
    }
  };

  // Resolve Escalation
  const handleResolveEscalation = async (decision: 'APPROVED' | 'REJECTED') => {
    if (!selectedEscalation) return;
    setIsSubmittingResolution(true);
    try {
      const res = await authService.authFetch(`/api/admin/escalations/${selectedEscalation.id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision,
          adminNotes: adminResolutionNotes || `Admin marked as ${decision.toLowerCase()}`
        })
      });

      if (res.ok) {
        toast.show(`Escalation ${selectedEscalation.case_number} successfully ${decision.toLowerCase()}!`, 'success');
        setSelectedEscalation(null);
        setAdminResolutionNotes('');
        fetchEscalations();
        fetchOrders();
        fetchOverview();
      } else {
        const err = await res.json();
        toast.show(err.detail || 'Failed to update escalation', 'error');
      }
    } catch (e) {
      toast.show('Network error while resolving escalation', 'error');
    } finally {
      setIsSubmittingResolution(false);
    }
  };

  // Save product update
  const handleSaveProduct = async (productId: string) => {
    try {
      const res = await authService.authFetch(`/api/products/${productId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          price: editPrice,
          stock_count: editStock,
          is_returnable: editReturnable
        })
      });
      if (res.ok) {
        toast.show('Product updated successfully!', 'success');
        setEditingProductId(null);
        fetchProducts();
      } else {
        toast.show('Failed to update product', 'error');
      }
    } catch {
      toast.show('Error saving product changes', 'error');
    }
  };

  // Save settings
  const handleSaveSettings = async () => {
    try {
      await Promise.all([
        authService.authFetch('/api/admin/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: 'refund_limit', value: settingRefundLimit.toString() })
        }),
        authService.authFetch('/api/admin/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: 'return_window_days', value: settingReturnWindow.toString() })
        }),
        authService.authFetch('/api/admin/settings', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: 'tracking_advance_interval_sec', value: settingTrackingInterval.toString() })
        })
      ]);
      toast.show('Policy & automation settings updated!', 'success');
      fetchSettings();
      fetchOverview();
    } catch {
      toast.show('Failed to save settings', 'error');
    }
  };

  // Export CSV
  const handleExportCSV = () => {
    const token = authService.getToken();
    const apiBase = import.meta.env.VITE_API_BASE_URL !== undefined
      ? import.meta.env.VITE_API_BASE_URL
      : (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');
    window.open(`${apiBase}/api/admin/audit-logs/export-csv?token=${token}`, '_blank');
  };

  const getStatusBadge = (status: string) => {
    const s = status.toUpperCase();
    if (s === 'DELIVERED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-success/15 text-success">Delivered</span>;
    if (s === 'SHIPPED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-accent/15 text-accent">Shipped</span>;
    if (s === 'OUT_FOR_DELIVERY') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/15 text-primary">Out for Delivery</span>;
    if (s === 'PACKED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-warning/15 text-warning">Packed</span>;
    if (s === 'REFUNDED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-500">Refunded</span>;
    if (s === 'EXCHANGED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/15 text-indigo-500">Exchanged</span>;
    if (s === 'ESCALATED') return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-danger/15 text-danger animate-pulse">Escalated</span>;
    return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-surface-2 text-text-muted">{status}</span>;
  };

  const filteredOrders = orders.filter(o => {
    if (orderStatusFilter === 'ALL') return true;
    return o.status === orderStatusFilter;
  });

  const filteredEscalations = escalations.filter(e => {
    if (escalationFilter === 'ALL') return true;
    return e.status === escalationFilter;
  });

  return (
    <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 py-6 pb-20 space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-primary animate-pulse" />
            <h1 className="text-2xl font-black tracking-tight text-text-main">Seller Control Center</h1>
            <span className="text-xs px-2 py-0.5 rounded bg-surface-2 border border-border text-primary font-mono font-bold">
              ADMIN MODE
            </span>
          </div>
          <p className="text-xs text-text-muted mt-1">
            Real-time sales monitoring, automatic order lifecycle engine, AI escalations & policy guardrails
          </p>
        </div>

        {/* Navigation Tabs */}
        <div className="flex flex-wrap items-center gap-1 bg-surface-2 p-1 rounded-2xl border border-border text-xs font-bold">
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all ${
              activeTab === 'overview' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            <span>Overview & Sales</span>
          </button>

          <button
            onClick={() => setActiveTab('orders')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all ${
              activeTab === 'orders' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <Package className="w-3.5 h-3.5" />
            <span>Orders ({orders.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('escalations')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all relative ${
              activeTab === 'escalations' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <AlertCircle className="w-3.5 h-3.5" />
            <span>Escalations</span>
            {dashboardData?.kpis.openEscalations ? (
              <span className="w-2 h-2 rounded-full bg-danger animate-ping ml-0.5" />
            ) : null}
          </button>

          <button
            onClick={() => setActiveTab('audit')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all ${
              activeTab === 'audit' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Audit Trail</span>
          </button>

          <button
            onClick={() => setActiveTab('products')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all ${
              activeTab === 'products' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <ShoppingBag className="w-3.5 h-3.5" />
            <span>Products</span>
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all ${
              activeTab === 'settings' ? 'bg-primary text-black shadow-sm' : 'text-text-muted hover:text-text-main'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Settings</span>
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: OVERVIEW & SALES */}
      {/* ========================================================================= */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* KPI Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Total Revenue</span>
              <div className="text-xl sm:text-2xl font-black text-text-main mt-1">
                ₹{(dashboardData?.kpis.totalRevenue || 0).toLocaleString('en-IN')}
              </div>
              <span className="text-[10px] text-success flex items-center gap-1 mt-1">
                <TrendingUp className="w-3 h-3" /> +18.4% this week
              </span>
            </div>

            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Total Orders</span>
              <div className="text-xl sm:text-2xl font-black text-text-main mt-1">
                {dashboardData?.kpis.totalOrders || orders.length}
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">Automatic scheduler active</span>
            </div>

            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Average Order Value</span>
              <div className="text-xl sm:text-2xl font-black text-text-main mt-1">
                ₹{(dashboardData?.kpis.avgOrderValue || 0).toLocaleString('en-IN')}
              </div>
              <span className="text-[10px] text-accent mt-1 block">High margin mix</span>
            </div>

            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Auto-Resolved by AI</span>
              <div className="text-xl sm:text-2xl font-black text-primary mt-1">
                {dashboardData?.kpis.autoResolvedPct || 86}%
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">Autonomous AI Engine</span>
            </div>

            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Refunds vs Limit</span>
              <div className="text-xl sm:text-2xl font-black text-text-main mt-1">
                ₹{(dashboardData?.kpis.refundsIssued || 0).toLocaleString('en-IN')}
              </div>
              <div className="w-full bg-surface-2 h-1.5 rounded-full mt-2 overflow-hidden">
                <div
                  className="bg-primary h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(100, ((dashboardData?.kpis.refundsIssued || 0) / (dashboardData?.kpis.refundLimit || 2000)) * 100)}%`
                  }}
                />
              </div>
            </div>

            <div className="bg-surface border border-border p-4 rounded-2xl shadow-sm">
              <span className="text-[11px] font-medium text-text-muted">Open Escalations</span>
              <div className="text-xl sm:text-2xl font-black text-danger mt-1 flex items-center justify-between">
                <span>{dashboardData?.kpis.openEscalations || 0}</span>
                {dashboardData?.kpis.openEscalations ? (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-danger/15 text-danger font-bold">Needs Review</span>
                ) : (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-success/15 text-success font-bold">Clear</span>
                )}
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">Pending seller decision</span>
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Sales Trends Chart */}
            <div className="lg:col-span-2 bg-surface border border-border p-5 rounded-3xl shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-bold text-text-main">Weekly Sales & Volume Trend</h3>
                  <p className="text-xs text-text-muted">Calculated from completed checkout orders</p>
                </div>
                <span className="text-xs font-mono font-semibold text-primary">₹ Net Revenue</span>
              </div>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={dashboardData?.salesTrends || []} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="salesGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3DD6A0" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#3DD6A0" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2A3644" opacity={0.3} />
                    <XAxis dataKey="date" stroke="#A9B6C4" fontSize={11} />
                    <YAxis stroke="#A9B6C4" fontSize={11} tickFormatter={val => `₹${val / 1000}k`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#131A22', borderColor: '#2A3644', borderRadius: '12px', fontSize: '12px' }}
                      formatter={(val: any) => [`₹${val.toLocaleString('en-IN')}`, 'Revenue']}
                    />
                    <Area type="monotone" dataKey="revenue" stroke="#3DD6A0" strokeWidth={2.5} fillOpacity={1} fill="url(#salesGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Category Breakdown Bar Chart */}
            <div className="bg-surface border border-border p-5 rounded-3xl shadow-sm flex flex-col justify-between">
              <div>
                <h3 className="text-sm font-bold text-text-main mb-1">Orders by Category</h3>
                <p className="text-xs text-text-muted mb-4">Breakdown of product volume</p>
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dashboardData?.categoryBreakdown || []} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2A3644" opacity={0.3} />
                      <XAxis dataKey="category" stroke="#A9B6C4" fontSize={10} />
                      <YAxis stroke="#A9B6C4" fontSize={10} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#131A22', borderColor: '#2A3644', borderRadius: '12px', fontSize: '12px' }}
                      />
                      <Bar dataKey="orders_count" fill="#7C8CFF" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="p-3 bg-surface-2 rounded-2xl border border-border text-xs flex items-center justify-between mt-2">
                <span className="text-text-muted">Auto-tracking frequency:</span>
                <span className="font-bold text-text-main">{settingTrackingInterval}s interval</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: ALL ORDERS (LIFECYCLE & AUTOMATIC TRACKING) */}
      {/* ========================================================================= */}
      {activeTab === 'orders' && (
        <div className="space-y-4">
          {/* Header & Filter Bar */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface p-4 rounded-2xl border border-border">
            <div>
              <h2 className="text-sm font-bold text-text-main">Order Lifecycle Management</h2>
              <p className="text-xs text-text-muted">
                Orders placed by customers automatically advance through tracking phases via the background scheduler.
              </p>
            </div>

            {/* Status Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Filter:</span>
              <select
                value={orderStatusFilter}
                onChange={e => setOrderStatusFilter(e.target.value)}
                className="bg-surface-2 border border-border text-xs rounded-xl px-3 py-1.5 text-text-main focus:outline-none focus:border-primary"
              >
                <option value="ALL">All Statuses</option>
                <option value="PLACED">Placed</option>
                <option value="PACKED">Packed</option>
                <option value="SHIPPED">Shipped</option>
                <option value="OUT_FOR_DELIVERY">Out for Delivery</option>
                <option value="DELIVERED">Delivered</option>
                <option value="RETURN_REQUESTED">Return Requested</option>
                <option value="REFUNDED">Refunded</option>
                <option value="EXCHANGED">Exchanged</option>
              </select>
            </div>
          </div>

          {/* Orders Table */}
          <div className="bg-surface border border-border rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-text-main">
                <thead className="bg-surface-2 border-b border-border text-text-muted font-bold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Order #</th>
                    <th className="py-3 px-4">Customer</th>
                    <th className="py-3 px-4">Items</th>
                    <th className="py-3 px-4">Total Amount</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Date Placed</th>
                    <th className="py-3 px-4 text-right">Shipment Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {filteredOrders.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="text-center py-8 text-text-muted">
                        No orders match the selected filter.
                      </td>
                    </tr>
                  ) : (
                    filteredOrders.map(order => (
                      <tr key={order.id} className="hover:bg-surface-2/40 transition-colors">
                        <td className="py-3 px-4 font-mono font-bold text-text-main">
                          {order.order_number}
                        </td>
                        <td className="py-3 px-4">
                          <div className="font-semibold text-text-main">{order.customer_name}</div>
                          <div className="text-[11px] text-text-muted">{order.customer_email}</div>
                        </td>
                        <td className="py-3 px-4">
                          <div className="max-w-xs truncate text-text-main">
                            {order.items.map(i => `${i.product_title} (${i.selected_size || 'Std'}) x${i.quantity}`).join(', ')}
                          </div>
                        </td>
                        <td className="py-3 px-4 font-bold text-text-main">
                          ₹{order.total_amount.toLocaleString('en-IN')}
                        </td>
                        <td className="py-3 px-4">
                          {getStatusBadge(order.status)}
                        </td>
                        <td className="py-3 px-4 text-text-muted">
                          {order.created_at}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => handleOpenShipmentUpdate(order)}
                              className="px-2.5 py-1.5 rounded-xl bg-primary/15 hover:bg-primary hover:text-black border border-primary/30 text-[11px] font-bold inline-flex items-center gap-1 transition-all text-primary"
                              title="Manually enter & advance shipment stage"
                            >
                              <Truck className="w-3.5 h-3.5" />
                              <span>Update Stage</span>
                            </button>
                            <button
                              onClick={() => handleOpenTracking(order)}
                              className="px-2 py-1.5 rounded-xl bg-surface-2 hover:bg-surface-2/80 border border-border text-[11px] font-semibold inline-flex items-center gap-1 transition-all text-text-muted hover:text-text-main"
                              title="View tracking timeline"
                            >
                              <Eye className="w-3.5 h-3.5" />
                              <span>Timeline</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: ESCALATIONS & APPROVAL QUEUE */}
      {/* ========================================================================= */}
      {activeTab === 'escalations' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface p-4 rounded-2xl border border-border">
            <div>
              <h2 className="text-sm font-bold text-text-main">Human-in-the-Loop Escalation Queue</h2>
              <p className="text-xs text-text-muted">
                Edge cases, out-of-policy claims, or high-value exceptions routed from the AI agent for admin verdict.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Status:</span>
              <select
                value={escalationFilter}
                onChange={e => setEscalationFilter(e.target.value)}
                className="bg-surface-2 border border-border text-xs rounded-xl px-3 py-1.5 text-text-main focus:outline-none focus:border-primary"
              >
                <option value="ALL">All Escalations</option>
                <option value="PENDING">Pending Action</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredEscalations.length === 0 ? (
              <div className="col-span-full py-12 text-center bg-surface border border-border rounded-2xl">
                <CheckCircle2 className="w-10 h-10 text-success mx-auto mb-2 opacity-80" />
                <h3 className="text-sm font-bold text-text-main">No Escalations in Queue</h3>
                <p className="text-xs text-text-muted mt-1">
                  The AI agent is autonomously handling standard customer returns and exchanges within policy!
                </p>
              </div>
            ) : (
              filteredEscalations.map(esc => (
                <div
                  key={esc.id}
                  className="bg-surface border border-border p-5 rounded-3xl shadow-sm flex flex-col justify-between space-y-4"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-bold text-primary">{esc.case_number}</span>
                    </div>

                    <div>
                      <h4 className="font-bold text-sm text-text-main">{esc.customer_name}</h4>
                      <p className="text-xs text-text-muted">
                        Order #{esc.order_number} • ₹{esc.amount.toLocaleString('en-IN')}
                      </p>
                    </div>

                    <div className="p-3 bg-surface-2 rounded-2xl border border-border text-xs space-y-1.5">
                      <div className="font-semibold text-text-main flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5 text-warning" />
                        <span>{esc.reason}</span>
                      </div>
                      <p className="text-[11px] text-text-muted leading-relaxed">
                        {esc.escalation_reason}
                      </p>
                    </div>

                    {/* 2E: Internal Fraud Warning Flags (Admin Eyes Only) */}
                    {(() => {
                      try {
                        const flags: string[] = esc.fraud_flags ? JSON.parse(esc.fraud_flags) : [];
                        if (flags.length > 0) {
                          return (
                            <div className="p-2.5 rounded-xl bg-danger/10 border border-danger/30 text-[11px] text-danger space-y-1">
                              <div className="font-bold flex items-center gap-1.5">
                                <AlertTriangle className="w-3.5 h-3.5 text-danger" />
                                <span>Risk & Integrity Warning</span>
                              </div>
                              {flags.map((fl, i) => (
                                <p key={i} className="leading-tight font-mono text-[10px]">{fl}</p>
                              ))}
                            </div>
                          );
                        }
                      } catch {
                        // ignore
                      }
                      return null;
                    })()}

                    {/* 2A, 2G: Evidence Photos Preview */}
                    {(() => {
                      let photoUrls: string[] = [];
                      try {
                        if (esc.evidence_photos) {
                          photoUrls = JSON.parse(esc.evidence_photos);
                        }
                      } catch {
                        // ignore
                      }
                      if (photoUrls.length === 0 && esc.evidence_photo) {
                        photoUrls = [esc.evidence_photo];
                      }

                      if (photoUrls.length > 0) {
                        return (
                          <div className="space-y-1.5">
                            <div className="grid grid-cols-2 gap-1.5">
                              {photoUrls.slice(0, 4).map((url, i) => (
                                <div key={i} className="rounded-xl overflow-hidden border border-border bg-black/10 aspect-video relative">
                                  <img
                                    src={url}
                                    alt={`Evidence ${i + 1}`}
                                    className="w-full h-full object-cover"
                                  />
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      }
                      return null;
                    })()}

                    {/* 2B, 2G, 2H: Vision AI Inspection Summary */}
                    {(() => {
                      try {
                        if (!esc.vision_analysis) return null;
                        const vData = typeof esc.vision_analysis === 'string' ? JSON.parse(esc.vision_analysis) : esc.vision_analysis;
                        const vStatus = vData.status || 'UNCLEAR';
                        return (
                          <div className="p-2.5 rounded-xl bg-surface-2 border border-border text-[11px] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-text-main flex items-center gap-1">
                                <Search className="w-3 h-3 text-primary" />
                                AI Inspection:
                              </span>
                              <span className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${
                                vStatus === 'VERIFIED' ? 'bg-success/20 text-success' :
                                vStatus === 'MISMATCH' ? 'bg-danger/20 text-danger' :
                                'bg-warning/20 text-warning'
                              }`}>
                                {vStatus} ({Math.round((vData.confidence || 0) * 100)}%)
                              </span>
                            </div>
                            <p className="text-text-muted text-[10px] italic">
                              "{vData.observations}"
                            </p>
                            <div className="flex items-center justify-between text-[10px] text-text-muted pt-1 border-t border-border/50">
                              <span>Damage: <strong className="text-text-main">{vData.damage_type || 'none'}</strong> ({vData.severity || 'none'})</span>
                              <span>Match: <strong className="text-text-main">{vData.product_matches || 'unsure'}</strong></span>
                            </div>
                            <div className="text-[9px] text-text-muted text-right italic pt-0.5">
                              AI assist assist only • Human reviewer final decision
                            </div>
                          </div>
                        );
                      } catch {
                        return null;
                      }
                    })()}

                    <div className="text-xs text-text-muted">
                      <span className="font-semibold text-text-main">AI Recommendation: </span>
                      {esc.agent_recommendation}
                    </div>
                  </div>

                  {esc.status === 'PENDING' ? (
                    <div className="flex items-center gap-2 pt-2 border-t border-border">
                      <button
                        onClick={() => setSelectedEscalation(esc)}
                        className="flex-1 py-2 px-3 rounded-xl bg-primary hover:bg-primary-hover text-black font-bold text-xs flex items-center justify-center gap-1 shadow-sm transition-all"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Review & Decide</span>
                      </button>
                    </div>
                  ) : (
                    <div className="pt-2 border-t border-border flex items-center justify-between text-xs">
                      <span className="text-text-muted">Status:</span>
                      <span
                        className={`font-bold ${
                          esc.status === 'APPROVED' ? 'text-success' : 'text-danger'
                        }`}
                      >
                        {esc.status}
                      </span>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: AUDIT LOG TRAIL */}
      {/* ========================================================================= */}
      {activeTab === 'audit' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface p-4 rounded-2xl border border-border">
            <div>
              <h2 className="text-sm font-bold text-text-main">Autonomous Audit Log Trail</h2>
              <p className="text-xs text-text-muted">
                Tamper-evident log of every AI agent invocation, policy decision, refund, and admin action.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                placeholder="Filter by tool (e.g. policy)..."
                value={auditToolFilter}
                onChange={e => setAuditToolFilter(e.target.value)}
                className="bg-surface-2 border border-border text-xs rounded-xl px-3 py-1.5 text-text-main focus:outline-none focus:border-primary"
              />

              <select
                value={auditVerdictFilter}
                onChange={e => setAuditVerdictFilter(e.target.value)}
                className="bg-surface-2 border border-border text-xs rounded-xl px-3 py-1.5 text-text-main focus:outline-none focus:border-primary"
              >
                <option value="ALL">All Verdicts</option>
                <option value="AUTO_APPROVE">Auto Approve</option>
                <option value="ESCALATE">Escalate</option>
                <option value="REJECT">Reject</option>
                <option value="APPROVED">Admin Approved</option>
              </select>

              <button
                onClick={handleExportCSV}
                className="px-3 py-1.5 rounded-xl bg-primary text-black font-bold text-xs flex items-center gap-1.5 shadow-sm hover:opacity-90 transition-opacity"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export CSV</span>
              </button>
            </div>
          </div>

          <div className="bg-surface border border-border rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-text-main">
                <thead className="bg-surface-2 border-b border-border text-text-muted font-bold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Time</th>
                    <th className="py-3 px-4">Actor</th>
                    <th className="py-3 px-4">Tool</th>
                    <th className="py-3 px-4">Verdict</th>
                    <th className="py-3 px-4">Input & Output Payloads</th>
                    <th className="py-3 px-4 font-mono">Idempotency Key</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {auditLogs.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="text-center py-8 text-text-muted">
                        No audit log entries recorded yet.
                      </td>
                    </tr>
                  ) : (
                    auditLogs.map(log => (
                      <tr key={log.id} className="hover:bg-surface-2/40 transition-colors">
                        <td className="py-3 px-4 text-text-muted font-mono whitespace-nowrap">
                          {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td className="py-3 px-4 font-semibold text-text-main">
                          {log.actor}
                        </td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded bg-surface-2 font-mono text-[11px] border border-border">
                            {log.tool}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              log.verdict === 'AUTO_APPROVE' || log.verdict === 'APPROVED'
                                ? 'bg-success/15 text-success'
                                : log.verdict === 'ESCALATE'
                                ? 'bg-warning/15 text-warning'
                                : log.verdict === 'REJECT'
                                ? 'bg-danger/15 text-danger'
                                : 'bg-surface-2 text-text-muted'
                            }`}
                          >
                            {log.verdict || 'N/A'}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="max-w-md truncate text-[11px] font-mono text-text-muted" title={log.output_payload || log.input_payload}>
                            {log.output_payload || log.input_payload || '{}'}
                          </div>
                        </td>
                        <td className="py-3 px-4 font-mono text-[10px] text-text-muted">
                          {log.idempotency_key || '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 5: PRODUCT CATALOG (PRICE & STOCK EDITING) */}
      {/* ========================================================================= */}
      {activeTab === 'products' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface p-4 rounded-2xl border border-border">
            <div>
              <h2 className="text-sm font-bold text-text-main">Live Catalog & Stock Management</h2>
              <p className="text-xs text-text-muted">
                Edit prices, adjust inventory, and configure return eligibility (e.g. non-returnable hygiene items).
              </p>
            </div>
            <span className="text-xs text-text-muted">10 Seeded Catalog Products</span>
          </div>

          <div className="bg-surface border border-border rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-text-main">
                <thead className="bg-surface-2 border-b border-border text-text-muted font-bold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Product</th>
                    <th className="py-3 px-4">SKU / Category</th>
                    <th className="py-3 px-4">Price (₹)</th>
                    <th className="py-3 px-4">Stock Count</th>
                    <th className="py-3 px-4">Policy</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {products.map(prod => {
                    const isEditing = editingProductId === prod.id;
                    return (
                      <tr key={prod.id} className="hover:bg-surface-2/40 transition-colors">
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-3">
                            <img
                              src={prod.image || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80'}
                              alt={prod.title}
                              onError={(e) => {
                                e.currentTarget.onerror = null;
                                e.currentTarget.src = 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80';
                              }}
                              className="w-10 h-10 rounded-xl object-cover border border-border"
                            />
                            <div>
                              <div className="font-bold text-text-main">{prod.title}</div>
                              <div className="text-[11px] text-text-muted">Rating: {prod.rating} ★</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <div className="font-mono text-[11px] text-text-main">{prod.sku}</div>
                          <div className="text-[11px] text-text-muted">{prod.category}</div>
                        </td>
                        <td className="py-3 px-4">
                          {isEditing ? (
                            <input
                              type="number"
                              value={editPrice}
                              onChange={e => setEditPrice(parseFloat(e.target.value) || 0)}
                              className="w-24 bg-surface-2 border border-primary rounded-lg px-2 py-1 text-xs text-text-main font-bold"
                            />
                          ) : (
                            <span className="font-bold text-text-main">₹{prod.price.toLocaleString('en-IN')}</span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          {isEditing ? (
                            <input
                              type="number"
                              value={editStock}
                              onChange={e => setEditStock(parseInt(e.target.value) || 0)}
                              className="w-20 bg-surface-2 border border-primary rounded-lg px-2 py-1 text-xs text-text-main font-bold"
                            />
                          ) : (
                            <span className={`font-semibold ${prod.stock_count < 10 ? 'text-danger' : 'text-text-main'}`}>
                              {prod.stock_count} units
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          {isEditing ? (
                            <label className="flex items-center gap-1.5 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={editReturnable}
                                onChange={e => setEditReturnable(e.target.checked)}
                                className="rounded text-primary focus:ring-0"
                              />
                              <span className="text-[11px]">Returnable</span>
                            </label>
                          ) : prod.is_returnable ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-success/15 text-success">
                              Eligible (7-Day)
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-danger/15 text-danger">
                              Hygiene (Non-Returnable)
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right">
                          {isEditing ? (
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                onClick={() => handleSaveProduct(prod.id)}
                                className="px-2.5 py-1 rounded-lg bg-primary text-black font-bold text-xs flex items-center gap-1 hover:opacity-90"
                              >
                                <Save className="w-3 h-3" />
                                <span>Save</span>
                              </button>
                              <button
                                onClick={() => setEditingProductId(null)}
                                className="px-2 py-1 rounded-lg bg-surface-2 border border-border text-text-muted hover:text-text-main text-xs"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => {
                                setEditingProductId(prod.id);
                                setEditPrice(prod.price);
                                setEditStock(prod.stock_count);
                                setEditReturnable(prod.is_returnable);
                              }}
                              className="px-2.5 py-1 rounded-lg bg-surface-2 hover:bg-surface-2/80 border border-border text-text-main font-semibold text-xs inline-flex items-center gap-1 transition-all"
                            >
                              <Edit2 className="w-3 h-3" />
                              <span>Edit</span>
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 6: SETTINGS & POLICIES */}
      {/* ========================================================================= */}
      {activeTab === 'settings' && (
        <div className="max-w-3xl space-y-6">
          <div className="bg-surface border border-border p-5 rounded-3xl shadow-sm space-y-6">
            <div>
              <h2 className="text-base font-bold text-text-main">Automated Policy & Engine Settings</h2>
              <p className="text-xs text-text-muted mt-1">
                Configure deterministic guardrails enforced before any refund, replacement, or tracking action is performed.
              </p>
            </div>

            {/* Refund Limit Slider */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-text-main">Autonomous Refund Limit (₹)</label>
                <span className="font-mono text-sm font-bold text-primary">₹{settingRefundLimit.toLocaleString('en-IN')}</span>
              </div>
              <input
                type="range"
                min="500"
                max="10000"
                step="250"
                value={settingRefundLimit}
                onChange={e => setSettingRefundLimit(parseFloat(e.target.value))}
                className="w-full accent-primary cursor-pointer"
              />
              <p className="text-[11px] text-text-muted">
                Refunds above this threshold are automatically escalated to the human admin queue instead of auto-disbursed.
              </p>
            </div>

            {/* Return Window Slider */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-text-main">Return / Exchange Window (Days)</label>
                <span className="font-mono text-sm font-bold text-primary">{settingReturnWindow} Days</span>
              </div>
              <input
                type="range"
                min="3"
                max="30"
                step="1"
                value={settingReturnWindow}
                onChange={e => setSettingReturnWindow(parseInt(e.target.value))}
                className="w-full accent-primary cursor-pointer"
              />
              <p className="text-[11px] text-text-muted">
                Orders delivered more than {settingReturnWindow} days ago are flagged as out-of-policy by the AI agent.
              </p>
            </div>

            {/* Automatic Tracking Advance Interval */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-text-main">Tracking Progression Interval (Seconds)</label>
                <span className="font-mono text-sm font-bold text-primary">{settingTrackingInterval}s</span>
              </div>
              <input
                type="range"
                min="10"
                max="120"
                step="5"
                value={settingTrackingInterval}
                onChange={e => setSettingTrackingInterval(parseInt(e.target.value))}
                className="w-full accent-primary cursor-pointer"
              />
              <p className="text-[11px] text-text-muted">
                Background worker tick interval for advancing active customer shipments through the supply chain.
              </p>
            </div>

            <div className="pt-4 border-t border-border flex justify-end">
              <button
                onClick={handleSaveSettings}
                className="py-2.5 px-6 rounded-xl bg-primary hover:bg-primary-hover text-black font-bold text-xs flex items-center gap-1.5 shadow-md transition-all"
              >
                <Save className="w-4 h-4" />
                <span>Save Policy Settings</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 1: TRACKING TIMELINE VIEWER */}
      {/* ========================================================================= */}
      <AnimatePresence>
        {selectedOrderForTracking && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg bg-surface border border-border rounded-3xl shadow-2xl p-6 relative max-h-[85vh] flex flex-col"
            >
              <div className="flex items-center justify-between pb-4 border-b border-border">
                <div>
                  <h3 className="font-bold text-base text-text-main flex items-center gap-2">
                    Shipment Timeline
                    <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-surface-2 text-primary border border-border">
                      {selectedOrderForTracking.order_number}
                    </span>
                  </h3>
                  <p className="text-xs text-text-muted mt-0.5">
                    Customer: <span className="text-text-main font-semibold">{selectedOrderForTracking.customer_name}</span> • Status: <span className="text-text-main font-semibold">{selectedOrderForTracking.status}</span>
                  </p>
                </div>
                <button
                  onClick={() => {
                    setSelectedOrderForTracking(null);
                    setTrackingTimeline(null);
                  }}
                  className="p-1 rounded-full hover:bg-surface-2 text-text-muted hover:text-text-main transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {loadingTracking ? (
                <div className="py-16 text-center text-xs text-text-muted">
                  <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-primary" />
                  <span>Fetching tracking timeline...</span>
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto py-4 space-y-4 pr-1">
                  {(!trackingTimeline?.events || trackingTimeline.events.length === 0) ? (
                    <div className="py-12 text-center text-xs text-text-muted">
                      No tracking milestones recorded yet for this order.
                    </div>
                  ) : (
                    trackingTimeline.events.map((event, idx) => (
                      <div key={event.id || idx} className="flex items-start gap-3 relative">
                        {idx < trackingTimeline.events.length - 1 && (
                          <div className="absolute left-3.5 top-6 bottom-0 w-0.5 bg-border -mb-4" />
                        )}
                        <div
                          className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                            idx === trackingTimeline.events.length - 1
                              ? 'bg-primary text-black ring-4 ring-primary/20'
                              : 'bg-surface-2 border border-border text-text-muted'
                          }`}
                        >
                          {idx === trackingTimeline.events.length - 1 ? '✓' : '•'}
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-xs text-text-main">{event.title}</span>
                            <span className="text-[10px] text-text-muted">{event.timestamp}</span>
                          </div>
                          <div className="text-[11px] text-primary font-semibold mt-0.5">
                            📍 {event.location}
                          </div>
                          <p className="text-xs text-text-muted mt-0.5">{event.description}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              <div className="pt-3 border-t border-border flex items-center justify-between">
                <button
                  onClick={() => {
                    const orderToUpdate = selectedOrderForTracking;
                    setSelectedOrderForTracking(null);
                    setTrackingTimeline(null);
                    if (orderToUpdate) {
                      handleOpenShipmentUpdate(orderToUpdate);
                    }
                  }}
                  className="px-3.5 py-1.5 rounded-xl bg-primary/10 hover:bg-primary hover:text-black border border-primary/30 text-xs font-bold text-primary flex items-center gap-1.5 transition-all"
                >
                  <Truck className="w-3.5 h-3.5" />
                  <span>Update Stage</span>
                </button>
                <button
                  onClick={() => {
                    setSelectedOrderForTracking(null);
                    setTrackingTimeline(null);
                  }}
                  className="px-4 py-2 rounded-xl bg-surface-2 hover:bg-surface-2/80 text-xs font-bold text-text-main transition-colors"
                >
                  Close
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ========================================================================= */}
      {/* MODAL 1.5: MANUAL SHIPMENT PROCESS ENTRY & CONTROLS (ADMIN) */}
      {/* ========================================================================= */}
      <AnimatePresence>
        {selectedOrderForShipment && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg bg-surface border border-border rounded-3xl shadow-2xl p-6 relative max-h-[90vh] flex flex-col"
            >
              {/* Header */}
              <div className="flex items-center justify-between pb-4 border-b border-border">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary">
                    <Truck className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="font-bold text-base text-text-main flex items-center gap-2">
                      Update Shipment Process
                      <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-surface-2 text-primary border border-border">
                        {selectedOrderForShipment.order_number}
                      </span>
                    </h3>
                    <p className="text-xs text-text-muted">
                      Customer: {selectedOrderForShipment.customer_name} • Current Status: <span className="text-text-main font-semibold">{selectedOrderForShipment.status}</span>
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedOrderForShipment(null)}
                  className="p-1 rounded-full hover:bg-surface-2 text-text-muted hover:text-text-main transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Form Content */}
              <div className="py-4 space-y-4 overflow-y-auto pr-1">
                {/* Stage Selector */}
                <div>
                  <label className="text-xs font-bold text-text-main block mb-2">
                    Select New Shipment Stage:
                  </label>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {[
                      { key: 'PLACED', label: 'Placed' },
                      { key: 'PACKED', label: 'Packed' },
                      { key: 'SHIPPED', label: 'Shipped (Transit)' },
                      { key: 'OUT_FOR_DELIVERY', label: 'Out for Delivery' },
                      { key: 'DELIVERED', label: 'Delivered' }
                    ].map(stage => (
                      <button
                        key={stage.key}
                        type="button"
                        onClick={() => handleSelectStage(stage.key)}
                        className={`py-2 px-3 rounded-xl text-xs font-semibold border transition-all text-left flex items-center justify-between ${
                          shipmentStage === stage.key
                            ? 'bg-primary text-black border-primary shadow-sm font-bold'
                            : 'bg-surface-2 border-border text-text-muted hover:text-text-main hover:border-primary/40'
                        }`}
                      >
                        <span>{stage.label}</span>
                        {shipmentStage === stage.key && <Check className="w-3.5 h-3.5" />}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Milestone Title */}
                <div>
                  <label className="text-xs font-bold text-text-main block mb-1">
                    Milestone Title / Status Name:
                  </label>
                  <input
                    type="text"
                    value={shipmentTitle}
                    onChange={e => setShipmentTitle(e.target.value)}
                    placeholder="e.g. Dispatched on Linehaul Transit"
                    className="w-full bg-surface-2 border border-border text-xs rounded-xl px-3 py-2 text-text-main focus:outline-none focus:border-primary"
                  />
                </div>

                {/* Facility / Location */}
                <div>
                  <label className="text-xs font-bold text-text-main block mb-1">
                    Facility / Current Hub Location:
                  </label>
                  <input
                    type="text"
                    value={shipmentLocation}
                    onChange={e => setShipmentLocation(e.target.value)}
                    placeholder="e.g. Bengaluru South Distribution Hub"
                    className="w-full bg-surface-2 border border-border text-xs rounded-xl px-3 py-2 text-text-main focus:outline-none focus:border-primary"
                  />
                </div>

                {/* Tracking Description Note */}
                <div>
                  <label className="text-xs font-bold text-text-main block mb-1">
                    Customer Tracking Note / Event Description:
                  </label>
                  <textarea
                    rows={2}
                    value={shipmentDesc}
                    onChange={e => setShipmentDesc(e.target.value)}
                    placeholder="Description displayed on customer tracking timeline"
                    className="w-full bg-surface-2 border border-border text-xs rounded-xl px-3 py-2 text-text-main focus:outline-none focus:border-primary resize-none"
                  />
                </div>

                {/* Proactive Notification Checkbox */}
                <div className="p-3 bg-surface-2 rounded-xl border border-border flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="notify_cust_shipment"
                    checked={notifyCustomer}
                    onChange={e => setNotifyCustomer(e.target.checked)}
                    className="rounded text-primary focus:ring-0"
                  />
                  <label htmlFor="notify_cust_shipment" className="text-xs text-text-main cursor-pointer select-none">
                    Send real-time shipment notification to customer in live chat
                  </label>
                </div>
              </div>

              {/* Actions */}
              <div className="pt-4 border-t border-border flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedOrderForShipment(null)}
                  className="px-4 py-2 rounded-xl bg-surface-2 text-text-muted hover:text-text-main text-xs font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveShipmentUpdate}
                  disabled={isUpdatingShipment}
                  className="px-5 py-2 rounded-xl bg-primary text-black text-xs font-bold flex items-center gap-1.5 hover:opacity-90 disabled:opacity-50 transition-all shadow-md"
                >
                  {isUpdatingShipment ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  <span>Save Shipment Update</span>
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ========================================================================= */}
      {/* MODAL 2: RESOLVE ESCALATION MODAL */}
      {/* ========================================================================= */}
      <AnimatePresence>
        {selectedEscalation && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-lg bg-surface border border-border rounded-3xl shadow-2xl p-6 relative max-h-[90vh] flex flex-col space-y-4"
            >
              <div className="flex items-center justify-between pb-3 border-b border-border">
                <div>
                  <h3 className="font-bold text-base text-text-main">
                    Resolve Escalation • {selectedEscalation.case_number}
                  </h3>
                  <p className="text-xs text-text-muted">
                    Customer: {selectedEscalation.customer_name} • Order: #{selectedEscalation.order_number}
                  </p>
                </div>
                <button
                  onClick={() => setSelectedEscalation(null)}
                  className="p-1 rounded-full hover:bg-surface-2 text-text-muted"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-3 overflow-y-auto pr-1">
                <div className="p-3 bg-surface-2 rounded-2xl border border-border text-xs space-y-1">
                  <span className="font-bold text-text-main">Claim Reason:</span>
                  <p className="text-text-muted">{selectedEscalation.escalation_reason}</p>
                </div>

                <div className="p-3 bg-surface-2 rounded-2xl border border-border text-xs space-y-1">
                  <span className="font-bold text-primary">AI Agent Recommendation:</span>
                  <p className="text-text-muted">{selectedEscalation.agent_recommendation}</p>
                </div>

                {selectedEscalation.evidence_photo && (
                  <div>
                    <span className="text-xs font-semibold text-text-muted block mb-1">Attached Photo Evidence:</span>
                    <img
                      src={selectedEscalation.evidence_photo}
                      alt="Evidence"
                      className="w-full h-40 object-cover rounded-xl border border-border"
                    />
                  </div>
                )}

                <div>
                  <label className="text-xs font-bold text-text-main block mb-1">
                    Seller Notes / Resolution Rationale:
                  </label>
                  <textarea
                    rows={3}
                    value={adminResolutionNotes}
                    onChange={e => setAdminResolutionNotes(e.target.value)}
                    placeholder="e.g. Approved courtesy replacement based on customer loyalty and photo verification."
                    className="w-full bg-surface-2 border border-border rounded-xl p-3 text-xs text-text-main focus:outline-none focus:border-primary"
                  />
                </div>
              </div>

              <div className="pt-3 border-t border-border flex items-center justify-end gap-2">
                <button
                  type="button"
                  disabled={isSubmittingResolution}
                  onClick={() => handleResolveEscalation('REJECTED')}
                  className="px-4 py-2 rounded-xl bg-danger/15 hover:bg-danger text-danger hover:text-white font-bold text-xs transition-all"
                >
                  Reject Claim
                </button>
                <button
                  type="button"
                  disabled={isSubmittingResolution}
                  onClick={() => handleResolveEscalation('APPROVED')}
                  className="px-5 py-2 rounded-xl bg-primary hover:bg-primary-hover text-black font-bold text-xs flex items-center gap-1 shadow-md transition-all"
                >
                  <Check className="w-4 h-4" />
                  <span>Approve Claim</span>
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};
