export type Role = 'ADMIN' | 'CUSTOMER';

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  phone?: string;
  role: Role;
  wallet_balance?: number;
}

export interface Product {
  id: string;
  title: string;
  sku: string;
  category: string;
  description: string;
  price: number;
  original_price?: number;
  rating: number;
  review_count: number;
  image: string;
  stock_count: number;
  is_returnable: boolean;
  sizes?: string[];
  features?: string[];
}

export interface OrderItemSummary {
  product_title: string;
  product_sku: string;
  selected_size?: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
}

export interface OrderRecord {
  id: string;
  order_number: string;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  shipping_address: string;
  payment_method: string;
  total_amount: number;
  status: 'PLACED' | 'PACKED' | 'SHIPPED' | 'OUT_FOR_DELIVERY' | 'DELIVERED' | 'RETURN_REQUESTED' | 'EXCHANGED' | 'REFUNDED';
  return_reason?: string;
  is_eligible_return: boolean;
  is_active?: boolean;
  delivered_at?: string;
  created_at: string;
  items: OrderItemSummary[];
}

export interface TrackingEventItem {
  id: string;
  status: string;
  title: string;
  location: string;
  description: string;
  timestamp: string;
}

export interface EscalationRecord {
  id: string;
  case_number: string;
  customer_id: string;
  customer_name: string;
  order_id: string;
  order_number: string;
  product_title: string;
  amount: number;
  reason: string;
  urgency: 'LOW' | 'MEDIUM' | 'HIGH';
  evidence_photo?: string;
  evidence_photos?: string;
  vision_analysis?: string;
  fraud_flags?: string;
  chat_summary: string;
  checks_done?: string;
  escalation_reason: string;
  agent_recommendation: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  admin_notes?: string;
  created_at: string;
  resolved_at?: string;
}

export interface AuditLogItem {
  id: string;
  timestamp: string;
  actor: string;
  customer_id?: string;
  order_id?: string;
  tool: string;
  input_payload?: string;
  output_payload?: string;
  verdict?: string;
  status: string;
  error?: string;
  idempotency_key?: string;
}

export interface SettingItem {
  id: string;
  key: string;
  value: string;
  description?: string;
  updated_at?: string;
}

export interface CartItem {
  product: Product;
  quantity: number;
  selectedSize?: string;
}

// ============================================================================
// Compatibility & Legacy Types
// ============================================================================

export type TrustTier = 'HIGH' | 'NORMAL' | 'RISKY';
export type CaseStatus = 'Auto-resolved' | 'Awaiting approval' | 'Escalated' | 'In progress';

export interface OrderItem {
  id: string;
  orderNumber: string;
  customerName: string;
  customerPhone: string;
  customerEmail: string;
  customerAvatar: string;
  itemTitle: string;
  itemSku: string;
  itemBatch: string;
  itemPrice: number;
  orderDate: string;
  deliveryDate: string;
  status: string;
  returnWindowDays: number;
  trustScore: number;
  trustTier: TrustTier;
  riskScore: number;
  productType: 'box' | 'shoe' | 'blazer' | 'earbuds';
}

export interface CaseRecord {
  id: string;
  orderNumber: string;
  customerName: string;
  itemTitle: string;
  amount: number;
  status: CaseStatus;
  statusType: 'auto-resolved' | 'awaiting' | 'escalated';
  timeAgo: string;
  issueType: string;
  actionTaken: string;
  transcriptSnippet: string;
  timeline: Array<{ time: string; event: string; status: 'completed' | 'pending' | 'failed' }>;
}

export interface ApprovalQueueItem {
  id: string;
  caseId: string;
  customerName: string;
  customerAvatar: string;
  itemTitle: string;
  itemPrice: number;
  reason: string;
  evidencePhotoUrl: string;
  policyVerdict: string;
  riskFlag: 'Low' | 'Medium' | 'High';
  agentRecommendation: string;
  savingsVsRefund: number;
  orderDate: string;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  tool: string;
  inputPayload: Record<string, any>;
  outputPayload: Record<string, any>;
  verdict: 'AUTO_APPROVE' | 'ESCALATE' | 'REJECT' | 'POLICY_MATCH';
  idempotencyKey: string;
}

export interface ReturnLeakageCluster {
  id: string;
  sku: string;
  title: string;
  batch: string;
  reason: string;
  returnCount: number;
  threshold: number;
  amountAtRisk: number;
  inTransitAffectedCount: number;
  isPulsingAlert: boolean;
}

export interface P2PRouteInfo {
  id: string;
  customerA: { name: string; lat: number; lng: number; address: string };
  customerB: { name: string; lat: number; lng: number; address: string };
  courier: { name: string; currentProgress: number; lat: number; lng: number };
  radiusKm: number;
  distanceKm: number;
  etaMinutes: number;
  escrowStatus: 'Holding' | 'Released on scan';
  itemTitle: string;
}

export interface SmartSalvageItem {
  id: string;
  itemTitle: string;
  sku: string;
  originalPrice: number;
  scrapLoss: number;
  refurbCost: number;
  openBoxResale: number;
  netRecovered: number;
  suggestedAction: 'Create Open-Box listing' | 'Extract Parts' | 'Liquidate';
}

export interface CustomerTrustProfile {
  customerId: string;
  name: string;
  score: number;
  tier: TrustTier;
  factors: {
    accountAgeMonths: number;
    totalOrders: number;
    lifetimeValue: number;
    claimVelocity30d: number;
  };
}

export interface PolicySettings {
  autoRefundLimit: number;
  returnWindowDays: number;
  p2pRadiusKm: number;
  leakageThresholdCount: number;
}

export interface DashboardKPIs {
  casesHandledToday: number;
  avgResolutionTimeSec: number;
  autoResolvedPct: number;
  refundsIssued: number;
  autoRefundLimit: number;
  moneySaved: number;
}

export interface ThinkingStep {
  name: 'Understand' | 'Look up' | 'Check policy' | 'Act' | 'Verify';
  status: 'pending' | 'running' | 'completed' | 'failed';
  toolCallName?: string;
  timestamp?: string;
}

export interface ChatMessage {
  id: string;
  sender: 'customer' | 'agent';
  text: string;
  timestamp: string;
  toolCalls?: Array<{ tool: string; status: string; details?: string }>;
  evidencePhotoUrl?: string;
}

export interface WalletTransaction {
  id: string;
  amount: number;
  type: 'CREDIT' | 'DEBIT';
  description: string;
  balance_after: number;
  order_number?: string;
  created_at: string;
}

export interface WalletData {
  wallet_balance: number;
  customer_id: string;
  currency: string;
  transactions: WalletTransaction[];
}

export interface PromoValidationResult {
  valid: boolean;
  code?: string;
  discount?: number;
  discount_type?: 'FLAT' | 'PERCENT';
  percent?: number;
  message: string;
}
