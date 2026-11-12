import React, { createContext, useContext, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X, Undo2 } from 'lucide-react';

export interface ToastItem {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
  onUndo?: () => void;
  duration?: number;
}

interface ToastContextType {
  showToast: (toast: Omit<ToastItem, 'id'>) => string;
  show: (message: string, type?: 'success' | 'error' | 'warning' | 'info') => string;
  success: (title: string, message?: string, onUndo?: () => void) => string;
  error: (title: string, message?: string, onUndo?: () => void) => string;
  warning: (title: string, message?: string, onUndo?: () => void) => string;
  info: (title: string, message?: string, onUndo?: () => void) => string;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const showToast = useCallback((toast: Omit<ToastItem, 'id'>) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
    const newToast: ToastItem = { ...toast, id };

    setToasts(prev => [newToast, ...prev].slice(0, 5)); // Keep max 5

    const duration = toast.duration || (toast.onUndo ? 7000 : 4500);
    setTimeout(() => {
      dismissToast(id);
    }, duration);

    return id;
  }, [dismissToast]);

  const show = useCallback((message: string, type: 'success' | 'error' | 'warning' | 'info' = 'info') => {
    return showToast({ type, title: message });
  }, [showToast]);

  const success = useCallback((title: string, message?: string, onUndo?: () => void) => {
    return showToast({ type: 'success', title, message, onUndo });
  }, [showToast]);

  const error = useCallback((title: string, message?: string, onUndo?: () => void) => {
    return showToast({ type: 'error', title, message, onUndo });
  }, [showToast]);

  const warning = useCallback((title: string, message?: string, onUndo?: () => void) => {
    return showToast({ type: 'warning', title, message, onUndo });
  }, [showToast]);

  const info = useCallback((title: string, message?: string) => {
    return showToast({ type: 'info', title, message });
  }, [showToast]);

  return (
    <ToastContext.Provider value={{ showToast, show, success, error, warning, info, dismissToast }}>
      {children}
      {/* Toast Render Container */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none px-4 sm:px-0">
        <AnimatePresence>
          {toasts.map(toast => {
            const Icon =
              toast.type === 'success'
                ? CheckCircle2
                : toast.type === 'error'
                ? AlertCircle
                : toast.type === 'warning'
                ? AlertTriangle
                : Info;

            const borderClass =
              toast.type === 'success'
                ? 'border-success/30'
                : toast.type === 'error'
                ? 'border-danger/30'
                : toast.type === 'warning'
                ? 'border-warning/30'
                : 'border-accent/30';

            const iconClass =
              toast.type === 'success'
                ? 'text-success'
                : toast.type === 'error'
                ? 'text-danger'
                : toast.type === 'warning'
                ? 'text-warning'
                : 'text-accent';

            return (
              <motion.div
                key={toast.id}
                initial={{ opacity: 0, y: 20, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 15, scale: 0.95 }}
                transition={{ duration: 0.2 }}
                className={`pointer-events-auto p-3.5 rounded-xl bg-surface border ${borderClass} shadow-xl backdrop-blur-md flex items-start gap-3 relative overflow-hidden`}
              >
                <Icon className={`w-5 h-5 shrink-0 mt-0.5 ${iconClass}`} />
                <div className="flex-1 min-w-0 pr-4">
                  <p className="text-sm font-semibold text-text-main leading-tight">{toast.title}</p>
                  {toast.message && (
                    <p className="text-xs text-text-muted mt-1 leading-relaxed break-words">{toast.message}</p>
                  )}
                  {toast.onUndo && (
                    <div className="mt-2.5 flex items-center gap-2">
                      <button
                        onClick={() => {
                          toast.onUndo?.();
                          dismissToast(toast.id);
                        }}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-surface-2 border border-border text-primary hover:bg-primary/10 transition-colors"
                      >
                        <Undo2 className="w-3.5 h-3.5" />
                        Undo Action
                      </button>
                    </div>
                  )}
                </div>
                <button
                  onClick={() => dismissToast(toast.id)}
                  className="p-1 rounded text-text-muted hover:text-text-main shrink-0 transition-colors"
                  aria-label="Close notification"
                >
                  <X className="w-4 h-4" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
