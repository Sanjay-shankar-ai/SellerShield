import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Camera,
  Bot,
  ShieldCheck,
  CheckCircle2,
  Package,
  RefreshCw,
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
  tool_calls?: Array<{ tool: string; status: string; order?: string }>;
  timestamp: string;
}

interface ChatPageProps {
  currentUser: UserProfile;
  activeOrder?: OrderRecord | null;
  onClearActiveOrder?: () => void;
}

export const ChatPage: React.FC<ChatPageProps> = ({
  currentUser,
  activeOrder,
  onClearActiveOrder
}) => {
  const toast = useToast();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState<string>(activeOrder?.id || '');
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const firstName = currentUser.full_name.split(' ')[0];

  useEffect(() => {
    if (activeOrder) {
      setSelectedOrderId(activeOrder.id);
    }
  }, [activeOrder]);

  // Load history + orders sequentially so activeOrder greeting is never overwritten
  useEffect(() => {
    let cancelled = false;
    const initChat = async () => {
      try {
        const [histRes, ordRes] = await Promise.all([
          authService.authFetch('/api/chat/history'),
          authService.authFetch('/api/orders')
        ]);

        if (cancelled) return;

        if (ordRes.ok) {
          const ordData: OrderRecord[] = await ordRes.json();
          setOrders(ordData);
        }

        let loadedMsgs: ChatMessage[] = [];
        if (histRes.ok) {
          const data = await histRes.json();
          if (data.messages && data.messages.length > 0) {
            loadedMsgs = data.messages;
          }
        }

        if (loadedMsgs.length === 0) {
          loadedMsgs = [
            {
              id: 'init-1',
              sender: 'agent',
              text: `Hey ${firstName}! 👋 I'm your SellerShield support assistant. I can track your shipments, help you cancel or swap sizes, or walk you through a return or refund step by step. What can I help you with?`,
              quick_replies: [
                'Where is my order?',
                'How do I cancel or refund?',
                'Size doesn\'t fit, can I swap?'
              ],
              timestamp: 'Just now'
            }
          ];
        }

        if (activeOrder) {
          loadedMsgs = [
            ...loadedMsgs,
            {
              id: `ctx-${Date.now()}`,
              sender: 'agent',
              text: `I've pulled up order ${activeOrder.order_number} (${activeOrder.items[0]?.product_title || 'Item'}). Tell me what happened or what you'd like to do — swap size, cancel, track, or refund!`,
              quick_replies: activeOrder.is_eligible_return
                ? ['Swap for another size', 'How do I get a refund?', 'Track this order']
                : ['Track this order', 'How do I cancel?'],
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            }
          ];
        }

        setMessages(loadedMsgs);
      } catch {
        if (!cancelled) {
          setMessages([
            {
              id: 'init-fallback',
              sender: 'agent',
              text: `Hey ${firstName}! How can I help with your orders today?`,
              quick_replies: ['Where is my order?', 'How do I cancel or refund?'],
              timestamp: 'Just now'
            }
          ]);
        }
      } finally {
        if (!cancelled) setIsLoadingHistory(false);
      }
    };

    initChat();
    return () => {
      cancelled = true;
    };
  }, [activeOrder?.id]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSendMessage = async (textOverride?: string, photoUrl?: string) => {
    const textToSend = (textOverride || input).trim();
    if ((!textToSend && !photoUrl) || isTyping) return;

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
          orderId: selectedOrderId || activeOrder?.id || undefined,
          evidencePhotoUrl: photoUrl
        })
      });

      if (res.ok) {
        const data = await res.json();
        setIsTyping(false);

        const agentMsg: ChatMessage = {
          id: `agent-${Date.now()}`,
          sender: 'agent',
          text: data.reply_text || data.replyText,
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

    setIsTyping(false);
    setMessages(prev => [
      ...prev,
      {
        id: `agent-err-${Date.now()}`,
        sender: 'agent',
        text: "Sorry, I couldn't reach our server just now. Could you tap Try again?",
        quick_replies: ['Try again'],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
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
      const orderParam = selectedOrderId || activeOrder?.id ? `?order_id=${selectedOrderId || activeOrder?.id}` : '';
      const uploadRes = await authService.authFetch(`/api/chat/upload-evidence${orderParam}`, {
        method: 'POST',
        body: formData
      });

      if (uploadRes.ok) {
        const upData = await uploadRes.json();
        const firstUrl = upData.evidence_photo || upData.file_urls?.[0];
        handleSendMessage("Here's a photo of the item issue.", firstUrl);
        toast.success('Photos attached', `${validFiles.length} photo(s) submitted for forensic inspection.`);
        return;
      }
    } catch (err) {
      console.warn('Multipart upload failed, falling back to base64 reader:', err);
    }

    // Fallback: read first file as base64 data URL
    const reader = new FileReader();
    reader.onload = (event) => {
      const b64 = event.target?.result as string;
      if (b64) {
        handleSendMessage("Here's a photo of the item issue.", b64);
        toast.success('Photo attached', 'Evidence submitted to support.');
      }
    };
    reader.readAsDataURL(validFiles[0]);
  };

  const handleClearChat = async () => {
    try {
      await authService.authFetch('/api/chat/clear', { method: 'POST' });
    } catch {
      // ignore
    }
    setSelectedOrderId('');
    onClearActiveOrder?.();
    setMessages([
      {
        id: `init-${Date.now()}`,
        sender: 'agent',
        text: `Fresh conversation started! How can I help you today, ${firstName}?`,
        quick_replies: ['Where is my order?', 'How do I cancel or refund?', 'Exchange size'],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
    toast.show('Started a fresh conversation', 'info');
  };

  const selectedOrderObj = orders.find(o => o.id === selectedOrderId) || activeOrder;

  return (
    <div className="w-full max-w-4xl mx-auto flex flex-col h-[calc(100vh-5.5rem)]">
      {/* Chat Header */}
      <div className="p-4 sm:p-5 border border-border bg-surface rounded-t-3xl flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-tr from-primary to-accent flex items-center justify-center text-black font-bold text-lg shadow-md">
            <Bot className="w-6 h-6 text-black" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-bold text-sm sm:text-base text-text-main">SellerShield Support</h2>
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-success/15 text-success font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
                <span>Live</span>
              </span>
            </div>
            <p className="text-xs text-text-muted mt-0.5">
              Fast order tracking, cancellations, size swaps & refund guidance
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Order Context Switcher */}
          {orders.length > 0 && (
            <div className="flex items-center gap-1.5 bg-surface-2 border border-border rounded-xl px-2.5 py-1.5 text-xs">
              <Package className="w-3.5 h-3.5 text-primary shrink-0" />
              <select
                value={selectedOrderId}
                onChange={e => setSelectedOrderId(e.target.value)}
                className="bg-transparent text-text-main font-semibold focus:outline-none max-w-[180px] truncate cursor-pointer"
                aria-label="Select order context"
              >
                <option value="">Auto-detect order</option>
                {orders.map(o => (
                  <option key={o.id} value={o.id}>
                    {o.order_number} ({o.status})
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={handleClearChat}
            className="px-3 py-1.5 rounded-xl border border-border bg-surface-2 hover:bg-surface text-text-muted hover:text-text-main transition-colors text-xs font-semibold flex items-center gap-1.5"
            title="Start a fresh conversation"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">New Chat</span>
          </button>
        </div>
      </div>

      {/* Selected Order Context Bar */}
      {selectedOrderObj && (
        <div className="px-4 py-2 bg-primary/10 border-x border-b border-primary/20 flex items-center justify-between text-xs text-text-main">
          <div className="flex items-center gap-2 truncate">
            <ShieldCheck className="w-4 h-4 text-primary shrink-0" />
            <span className="font-mono font-bold">{selectedOrderObj.order_number}</span>
            <span className="truncate text-text-muted">
              {selectedOrderObj.items[0]?.product_title} • Status: <strong className="text-text-main">{selectedOrderObj.status}</strong>
            </span>
          </div>
          <button
            onClick={() => {
              setSelectedOrderId('');
              onClearActiveOrder?.();
            }}
            className="text-text-muted hover:text-text-main font-bold ml-2"
            title="Clear selection"
          >
            ✕
          </button>
        </div>
      )}

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 bg-bg/40 border-x border-border">
        {isLoadingHistory ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex items-center gap-2 text-text-muted text-xs">
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Loading conversation...</span>
            </div>
          </div>
        ) : (
          <>
            {messages.map(m => {
              const isCust = m.sender === 'customer';

              return (
                <div key={m.id} className={`flex ${isCust ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] sm:max-w-[72%] flex flex-col ${isCust ? 'items-end' : 'items-start'}`}>
                    <div className={`flex items-center gap-1.5 mb-1 ${isCust ? 'flex-row-reverse' : ''}`}>
                      <div
                        className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                          isCust ? 'bg-primary/20 text-primary' : 'bg-gradient-to-tr from-primary to-accent text-black'
                        }`}
                      >
                        {isCust ? firstName[0] : <Bot className="w-3.5 h-3.5" />}
                      </div>
                      <span className="text-[10px] text-text-muted font-semibold">
                        {isCust ? 'You' : 'Support Executive'}
                      </span>
                      <span className="text-[9px] text-text-muted font-mono">{m.timestamp}</span>
                    </div>

                    <div
                      className={`p-3.5 sm:p-4 rounded-2xl text-[13px] leading-relaxed shadow-xs ${
                        isCust
                          ? 'bg-primary text-black font-medium rounded-tr-sm'
                          : 'bg-surface border border-border text-text-main rounded-tl-sm'
                      }`}
                    >
                      <p className="whitespace-pre-line">{m.text}</p>

                      {m.photo_url && (
                        <div className="mt-2.5 rounded-xl overflow-hidden border border-border/80">
                          <img src={m.photo_url} alt="Attached proof" className="w-full h-36 object-cover" />
                        </div>
                      )}
                    </div>

                    {/* Priority Technical Callback Simulation Card */}
                    {!isCust && (m.text.includes('priority technical callback') || m.text.includes('re-arranged your priority technical callback')) && (
                      <div className="mt-2.5 p-3.5 rounded-2xl bg-surface border border-primary/40 shadow-xs flex flex-col gap-2 w-full max-w-md">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs font-bold text-primary">
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
                            className="px-3 py-1.5 rounded-xl text-[11px] font-bold bg-success/15 text-success border border-success/40 hover:bg-success hover:text-black transition-all flex items-center justify-center gap-1.5 shadow-2xs"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" /> Answer & Complete
                          </button>
                          <button
                            onClick={() => handleSendMessage('Simulate Call Declined')}
                            className="px-3 py-1.5 rounded-xl text-[11px] font-bold bg-danger/15 text-danger border border-danger/40 hover:bg-danger hover:text-white transition-all flex items-center justify-center gap-1.5 shadow-2xs"
                          >
                            <XCircle className="w-3.5 h-3.5" /> Decline / Miss Call
                          </button>
                        </div>
                      </div>
                    )}

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
                            className="px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-surface border border-primary/30 text-primary hover:bg-primary hover:text-black transition-all shadow-xs"
                          >
                            {qr}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {isTyping && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 text-xs text-text-muted bg-surface border border-border px-4 py-3 rounded-2xl rounded-tl-sm w-fit">
                  <span className="w-2 h-2 rounded-full bg-primary animate-bounce" />
                  <span className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0.1s' }} />
                  <span className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: '0.2s' }} />
                  <span className="text-[11px] ml-1.5">Checking your order...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Bar */}
      <div className="p-3 sm:p-4 bg-surface border border-border rounded-b-3xl flex items-center gap-2.5">
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
          className="p-2.5 rounded-xl border border-border bg-surface-2 text-text-muted hover:text-text-main hover:border-primary/40 transition-colors shrink-0"
          title="Upload damage photo proof"
        >
          <Camera className="w-4 h-4" />
        </button>

        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSendMessage()}
          placeholder="Ask anything — track order, how to cancel, size swap, refund..."
          className="flex-1 bg-surface-2 text-text-main text-sm rounded-xl px-4 py-2.5 border border-border focus:border-primary focus:outline-hidden transition-colors"
        />

        <button
          type="button"
          onClick={() => handleSendMessage()}
          disabled={!input.trim() || isTyping}
          className="p-2.5 rounded-xl bg-primary text-black hover:opacity-90 disabled:opacity-30 transition-all shrink-0 shadow-sm"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
