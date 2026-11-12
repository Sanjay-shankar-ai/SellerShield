import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MessageSquare,
  X,
  Send,
  Camera,
  Bot,
  User,
  ShieldCheck,
  CheckCircle2,
  Clock,
  Sparkles,
  ArrowRight,
  Maximize2,
  Minimize2,
  PhoneCall,
  XCircle
} from 'lucide-react';
import { OrderRecord, UserProfile } from '../../types';
import { authService } from '../../api/authService';
import { useToast } from '../common/ToastContext';

interface ChatMessage {
  id: string;
  sender: 'customer' | 'agent';
  text: string;
  photo_url?: string;
  quick_replies?: string[];
  tool_calls?: Array<{ tool: string; status: string }>;
  timestamp: string;
}

interface FloatingChatWidgetProps {
  currentUser: UserProfile;
  activeOrder?: OrderRecord | null;
  onClearActiveOrder?: () => void;
}

export const FloatingChatWidget: React.FC<FloatingChatWidgetProps> = ({
  currentUser,
  activeOrder,
  onClearActiveOrder
}) => {
  const toast = useToast();
  const [isOpen, setIsOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Automatically open floating chat when an order context is passed from "Return / Exchange with AI"
  useEffect(() => {
    if (activeOrder) {
      setIsOpen(true);
      setMessages(prev => [
        ...prev,
        {
          id: `ctx-${Date.now()}`,
          sender: 'agent',
          text: `Hi ${currentUser.full_name.split(' ')[0]}! I've opened the details for order ${activeOrder.order_number} (${activeOrder.items[0]?.product_title || 'Item'}). What went wrong, and how can I help?`,
          quick_replies: activeOrder.is_eligible_return ? ['Size fits tight', 'Item arrived damaged', 'Track shipment'] : ['Track shipment'],
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    }
  }, [activeOrder]);

  // Load chat history from backend on first open
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      const loadHistory = async () => {
        try {
          const res = await authService.authFetch('/api/chat/history');
          if (res.ok) {
            const data = await res.json();
            if (data.messages && data.messages.length > 0) {
              setMessages(data.messages);
              return;
            }
          }
        } catch {
          // fallback initial greeting
        }
        setMessages([
          {
            id: 'init-1',
            sender: 'agent',
            text: `Hi ${currentUser.full_name.split(' ')[0]}! I'm your SellerShield support assistant. How can I help you today? You can ask about tracking, size swaps, or return requests!`,
            quick_replies: ['Where is my order?', 'Swap shoe size', 'Return policy'],
            timestamp: 'Just now'
          }
        ]);
      };
      loadHistory();
    }
  }, [isOpen]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSendMessage = async (textOverride?: string, photoUrl?: string) => {
    const textToSend = (textOverride || input).trim();
    if (!textToSend && !photoUrl) return;

    if (!textOverride) setInput('');

    const newCustomerMsg: ChatMessage = {
      id: `cust-${Date.now()}`,
      sender: 'customer',
      text: textToSend,
      photo_url: photoUrl,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, newCustomerMsg]);
    setIsTyping(true);

    try {
      const res = await authService.authFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: textToSend,
          orderId: activeOrder?.id || activeOrder?.order_number,
          evidencePhotoUrl: photoUrl
        })
      });

      if (res.ok) {
        const data = await res.json();
        setIsTyping(false);

        const agentMsg: ChatMessage = {
          id: `agent-${Date.now()}`,
          sender: 'agent',
          text: data.reply_text,
          quick_replies: data.quick_replies,
          tool_calls: data.tool_calls,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };

        setMessages(prev => [...prev, agentMsg]);
        if (data.wallet_balance !== undefined) {
          authService.updateWalletBalance(data.wallet_balance);
        } else {
          authService.refreshUser();
        }
        return;
      }
    } catch (err) {
      console.warn('Backend chat failed:', err);
    }

    // Fallback if network is delayed
    setTimeout(() => {
      setIsTyping(false);
      setMessages(prev => [
        ...prev,
        {
          id: `agent-${Date.now()}`,
          sender: 'agent',
          text: "I'm checking the details for you right now. Could you please specify your preferred size or order number?",
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    }, 1000);
  };

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const fileList = Array.from(files).slice(0, 4);
    const validFiles = fileList.filter(f => f.size <= 5 * 1024 * 1024);
    if (validFiles.length < fileList.length) {
      toast.show('Some photos exceed the 5 MB limit and were skipped.', 'warning');
    }
    if (validFiles.length === 0) return;

    try {
      const formData = new FormData();
      validFiles.forEach(f => formData.append('files', f));
      const orderParam = activeOrder?.id ? `?order_id=${activeOrder.id}` : '';
      const uploadRes = await authService.authFetch(`/api/chat/upload-evidence${orderParam}`, {
        method: 'POST',
        body: formData
      });

      if (uploadRes.ok) {
        const upData = await uploadRes.json();
        const firstUrl = upData.evidence_photo || upData.file_urls?.[0];
        handleSendMessage("Here's a photo of the item issue.", firstUrl);
        toast.success('Photos Attached', `${validFiles.length} photo(s) submitted for forensic inspection.`);
        return;
      }
    } catch (err) {
      console.warn('Multipart upload failed in widget, falling back to data URL:', err);
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const b64 = event.target?.result as string;
      if (b64) {
        handleSendMessage("Here's a photo of the item issue.", b64);
        toast.success('Photo Attached', 'Forensic inspection tool triggered.');
      }
    };
    reader.readAsDataURL(validFiles[0]);
  };

  return (
    <>
      {/* Floating Toggle Button */}
      {!isOpen && (
        <motion.button
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-50 p-4 rounded-full bg-primary text-black font-bold shadow-2xl flex items-center gap-2 group ring-4 ring-primary/20"
          aria-label="Open AI Customer Support"
        >
          <Bot className="w-6 h-6 text-black" />
          <span className="text-xs font-extrabold pr-1 hidden sm:inline">AI Support Concierge</span>
          {activeOrder && (
            <span className="w-2.5 h-2.5 rounded-full bg-danger animate-ping" />
          )}
        </motion.button>
      )}

      {/* Floating Modern Conversation Window */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: 'spring', damping: 25, stiffness: 250 }}
            className={`fixed bottom-6 right-6 z-50 bg-surface border border-border shadow-2xl rounded-3xl overflow-hidden flex flex-col transition-all duration-300 ${
              isExpanded
                ? 'w-[90vw] sm:w-[680px] h-[82vh]'
                : 'w-[92vw] sm:w-[420px] h-[580px]'
            }`}
          >
            {/* Header */}
            <div className="p-4 bg-surface-2 border-b border-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-2xl bg-gradient-to-tr from-primary to-accent flex items-center justify-center text-black font-bold">
                  <Bot className="w-5 h-5 text-black" />
                </div>
                <div>
                  <div className="flex items-center gap-1.5">
                    <h3 className="font-bold text-xs sm:text-sm text-text-main">SellerShield AI Support</h3>
                    <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
                  </div>
                  <p className="text-[10px] text-text-muted">
                    {activeOrder ? `Context: ${activeOrder.order_number}` : 'AI Support Concierge'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1 text-text-muted">
                <button
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="p-1 rounded-lg hover:text-text-main hover:bg-surface transition-colors"
                  title={isExpanded ? 'Collapse' : 'Expand'}
                >
                  {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => {
                    setIsOpen(false);
                    onClearActiveOrder?.();
                  }}
                  className="p-1 rounded-lg hover:text-text-main hover:bg-surface transition-colors"
                  aria-label="Close chat"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Active Order Context Strip (if selected) */}
            {activeOrder && (
              <div className="px-3.5 py-2 bg-primary/10 border-b border-primary/20 flex items-center justify-between text-[11px] text-text-main">
                <div className="flex items-center gap-1.5 truncate">
                  <ShieldCheck className="w-3.5 h-3.5 text-primary shrink-0" />
                  <span className="font-mono font-bold">{activeOrder.order_number}:</span>
                  <span className="truncate">{activeOrder.items[0]?.product_title}</span>
                </div>
                <button
                  onClick={onClearActiveOrder}
                  className="text-text-muted hover:text-text-main font-bold ml-2 text-xs"
                  title="Clear order context"
                >
                  ✕
                </button>
              </div>
            )}

            {/* Messages Thread */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3.5 bg-bg/40">
              {messages.map(m => {
                const isCust = m.sender === 'customer';

                return (
                  <div
                    key={m.id}
                    className={`flex flex-col ${isCust ? 'items-end' : 'items-start'} max-w-[90%] ${
                      isCust ? 'ml-auto' : 'mr-auto'
                    }`}
                  >
                    <div
                      className={`p-3.5 rounded-2xl text-xs sm:text-[13px] leading-relaxed shadow-2xs ${
                        isCust
                          ? 'bg-primary text-black font-medium rounded-tr-none'
                          : 'bg-surface border border-border text-text-main rounded-tl-none'
                      }`}
                    >
                      <p className="whitespace-pre-line">{m.text}</p>

                      {/* Photo preview if attached */}
                      {m.photo_url && (
                        <div className="mt-2 rounded-lg overflow-hidden border border-border/80">
                          <img src={m.photo_url} alt="Attached proof" className="w-full h-32 object-cover" />
                        </div>
                      )}

                      <span
                        className={`block text-[9px] mt-1 text-right font-mono ${
                          isCust ? 'text-black/70' : 'text-text-muted'
                        }`}
                      >
                        {m.timestamp}
                      </span>
                    </div>

                    {/* Priority Technical Callback Simulation Card */}
                    {!isCust && (m.text.includes('priority technical callback') || m.text.includes('re-arranged your priority technical callback')) && (
                      <div className="mt-2.5 p-3 rounded-2xl bg-surface border border-primary/40 shadow-xs flex flex-col gap-2 w-full">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-xs font-bold text-primary">
                            <PhoneCall className="w-4 h-4 animate-pulse text-primary" />
                            <span>Technical Support Callback</span>
                          </div>
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-warning/20 text-warning font-semibold">
                            Dialing +91 98450 12891
                          </span>
                        </div>
                        <p className="text-[11px] text-text-muted">
                          Simulate the customer care phone call response:
                        </p>
                        <div className="grid grid-cols-2 gap-2 mt-0.5">
                          <button
                            onClick={() => handleSendMessage('Simulate Call Completed')}
                            className="px-2.5 py-1.5 rounded-xl text-[11px] font-bold bg-success/15 text-success border border-success/40 hover:bg-success hover:text-black transition-all flex items-center justify-center gap-1 shadow-2xs"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" /> Answer & Complete
                          </button>
                          <button
                            onClick={() => handleSendMessage('Simulate Call Declined')}
                            className="px-2.5 py-1.5 rounded-xl text-[11px] font-bold bg-danger/15 text-danger border border-danger/40 hover:bg-danger hover:text-white transition-all flex items-center justify-center gap-1 shadow-2xs"
                          >
                            <XCircle className="w-3.5 h-3.5" /> Decline / Miss Call
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Quick Reply Choices */}
                    {m.quick_replies && m.quick_replies.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {m.quick_replies.map((qr, idx) => (
                          <button
                            key={idx}
                            onClick={() => {
                              if (qr.toLowerCase().includes('wallet activity') || qr.toLowerCase() === 'check my wallet') {
                                window.dispatchEvent(new Event('open_wallet_modal'));
                              } else {
                                handleSendMessage(qr);
                              }
                            }}
                            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-surface border border-primary/40 text-primary hover:bg-primary hover:text-black transition-colors"
                          >
                            {qr}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Typing indicator */}
              {isTyping && (
                <div className="flex items-center gap-1.5 text-xs text-text-muted bg-surface border border-border px-3 py-1.5 rounded-2xl w-fit">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce" />
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce delay-100" />
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce delay-200" />
                  <span className="text-[10px] ml-1">AI agent formulating response...</span>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Bar */}
            <div className="p-3 bg-surface border-t border-border flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                className="hidden"
                onChange={handlePhotoUpload}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="p-2 rounded-xl border border-border bg-surface-2 text-text-muted hover:text-text-main transition-colors shrink-0"
                title="Upload damage photo proof"
              >
                <Camera className="w-4 h-4" />
              </button>

              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
                placeholder="Ask a question or request a swap..."
                className="flex-1 bg-surface-2 text-text-main text-xs rounded-xl px-3.5 py-2 border border-border focus:border-primary focus:outline-hidden transition-colors"
              />

              <button
                type="button"
                onClick={() => handleSendMessage()}
                disabled={!input.trim()}
                className="p-2 rounded-xl bg-primary text-black hover:bg-primary-hover disabled:opacity-40 transition-all shrink-0"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
