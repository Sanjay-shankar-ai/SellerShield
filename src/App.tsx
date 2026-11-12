import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Navbar, CustomerPage } from './components/common/Navbar';
import { LoginPage } from './components/auth/LoginPage';
import { StoreView } from './components/store/StoreView';
import { OrdersView } from './components/store/OrdersView';
import { CartDrawer } from './components/store/CartDrawer';
import { AdminDashboard } from './components/admin/AdminDashboard';
import { ChatPage } from './components/chat/ChatPage';
import { WalletModal } from './components/wallet/WalletModal';
import { ToastProvider, useToast } from './components/common/ToastContext';
import { ThemeProvider } from './theme/ThemeContext';
import { Product, CartItem, UserProfile, OrderRecord } from './types';
import { authService } from './api/authService';
import { getApiBaseUrl } from './api/config';

function AppContent() {
  const toast = useToast();
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(() => authService.getUser());
  const [activeCustomerPage, setActiveCustomerPage] = useState<CustomerPage>('store');
  const [cartItems, setCartItems] = useState<CartItem[]>([]);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [isWalletModalOpen, setIsWalletModalOpen] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoadingProducts, setIsLoadingProducts] = useState(true);
  const [productsError, setProductsError] = useState(false);
  const [activeOrderForChat, setActiveOrderForChat] = useState<OrderRecord | null>(null);

  // Fetch catalog products from FastAPI backend
  const fetchProducts = async () => {
    setIsLoadingProducts(true);
    setProductsError(false);
    try {
      const apiBase = getApiBaseUrl();
      const res = await fetch(`${apiBase}/api/products`);
      if (res.ok) {
        const data = await res.json();
        setProducts(Array.isArray(data) ? data : []);
      } else {
        setProductsError(true);
      }
    } catch (e) {
      console.warn('Failed to fetch products', e);
      setProductsError(true);
    } finally {
      setIsLoadingProducts(false);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, [currentUser?.id]);

  // Listen for unauthorized events to auto-logout
  useEffect(() => {
    const handleUnauth = () => {
      setCurrentUser(null);
      toast.show('Session expired. Please log in again.', 'warning');
    };
    window.addEventListener('auth_unauthorized', handleUnauth);
    return () => window.removeEventListener('auth_unauthorized', handleUnauth);
  }, []);

  // Listen for user profile updates & wallet balance changes (real-time sync)
  useEffect(() => {
    const handleProfileUpdate = (e: any) => {
      if (e.detail) {
        setCurrentUser(e.detail);
      }
    };
    const handleWalletUpdate = () => {
      authService.refreshUser();
    };
    const handleOpenWalletModal = () => {
      setIsWalletModalOpen(true);
    };
    window.addEventListener('user_profile_updated', handleProfileUpdate);
    window.addEventListener('wallet_updated', handleWalletUpdate);
    window.addEventListener('open_wallet_modal', handleOpenWalletModal);

    if (authService.getToken()) {
      authService.refreshUser();
    }
    const interval = setInterval(() => {
      if (authService.getToken()) {
        authService.refreshUser();
      }
    }, 4000);

    return () => {
      window.removeEventListener('user_profile_updated', handleProfileUpdate);
      window.removeEventListener('wallet_updated', handleWalletUpdate);
      window.removeEventListener('open_wallet_modal', handleOpenWalletModal);
      clearInterval(interval);
    };
  }, []);

  const handleLogout = () => {
    authService.clearSession();
    setCurrentUser(null);
    setCartItems([]);
    toast.show('Logged out successfully', 'info');
  };

  const handleAddToCart = (product: Product, size?: string) => {
    setCartItems(prev => {
      const existing = prev.find(
        item => item.product.id === product.id && item.selectedSize === size
      );
      if (existing) {
        return prev.map(item =>
          item.product.id === product.id && item.selectedSize === size
            ? { ...item, quantity: item.quantity + 1 }
            : item
        );
      }
      return [...prev, { product, quantity: 1, selectedSize: size }];
    });
    toast.show(`Added ${product.title} to cart!`, 'success');
  };

  const handleInstantBuy = (product: Product, size?: string) => {
    handleAddToCart(product, size);
    setIsCartOpen(true);
  };

  const handleUpdateCartQuantity = (productId: string, quantity: number) => {
    if (quantity <= 0) {
      handleRemoveCartItem(productId);
      return;
    }
    setCartItems(prev =>
      prev.map(item =>
        item.product.id === productId ? { ...item, quantity } : item
      )
    );
  };

  const handleRemoveCartItem = (productId: string) => {
    setCartItems(prev => prev.filter(item => item.product.id !== productId));
  };

  const handleOrderPlaced = (orderNumber: string) => {
    setCartItems([]);
    setIsCartOpen(false);
    toast.show(`Order ${orderNumber} placed! Automatic tracking is now live.`, 'success');
    setActiveCustomerPage('orders');
  };

  // If user is not authenticated, render Login Page first
  if (!currentUser) {
    return (
      <LoginPage
        onLoginSuccess={user => {
          setCurrentUser(user);
          toast.show(`Welcome back, ${user.full_name}!`, 'success');
        }}
      />
    );
  }

  const cartCount = cartItems.reduce((acc, item) => acc + item.quantity, 0);

  return (
    <div className="min-h-screen bg-bg text-text-main flex flex-col font-sans selection:bg-primary/20 selection:text-primary">
      {/* Universal Top Navigation */}
      <Navbar
        currentUser={currentUser}
        activeCustomerPage={activeCustomerPage}
        onNavigateCustomer={page => {
          setActiveCustomerPage(page);
          // Clear order context when navigating away from chat
          if (page !== 'chat') {
            setActiveOrderForChat(null);
          }
        }}
        cartCount={cartCount}
        onOpenCart={() => setIsCartOpen(true)}
        onLogout={handleLogout}
        onOpenWallet={() => setIsWalletModalOpen(true)}
      />

      {/* Main Content Area */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 py-4">
        {currentUser.role === 'ADMIN' ? (
          <AdminDashboard currentUser={currentUser} />
        ) : (
          <div className="w-full">
            {activeCustomerPage === 'store' && (
              <StoreView
                products={products}
                isLoading={isLoadingProducts}
                hasError={productsError}
                onRetry={fetchProducts}
                onAddToCart={handleAddToCart}
                onInstantBuy={handleInstantBuy}
                onOpenChatWithProduct={title => {
                  setActiveCustomerPage('chat');
                  toast.show(`Ask the AI about ${title}`, 'info');
                }}
              />
            )}

            {activeCustomerPage === 'orders' && (
              <OrdersView
                onOpenChatWithOrder={order => {
                  setActiveOrderForChat(order);
                  setActiveCustomerPage('chat');
                }}
              />
            )}

            {activeCustomerPage === 'chat' && (
              <ChatPage
                currentUser={currentUser}
                activeOrder={activeOrderForChat}
                onClearActiveOrder={() => setActiveOrderForChat(null)}
              />
            )}
          </div>
        )}
      </main>

      {/* Cart Drawer (Customer Only) */}
      {currentUser.role === 'CUSTOMER' && (
        <>
          <CartDrawer
            isOpen={isCartOpen}
            onClose={() => setIsCartOpen(false)}
            items={cartItems}
            currentUser={currentUser}
            onUpdateQuantity={handleUpdateCartQuantity}
            onRemoveItem={handleRemoveCartItem}
            onOrderPlaced={handleOrderPlaced}
          />
          <WalletModal
            isOpen={isWalletModalOpen}
            onClose={() => setIsWalletModalOpen(false)}
            currentUser={currentUser}
          />
        </>
      )}
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
