import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  Star,
  ShoppingBag,
  ShieldCheck,
  CheckCircle2,
  Truck,
  RotateCcw,
  Sparkles,
  ArrowRight,
  X,
  AlertTriangle,
  Info
} from 'lucide-react';
import { Product } from '../../types';

interface StoreViewProps {
  products: Product[];
  isLoading?: boolean;
  hasError?: boolean;
  onRetry?: () => void;
  onAddToCart: (product: Product, size?: string) => void;
  onInstantBuy: (product: Product, size?: string) => void;
  onOpenChatWithProduct?: (productTitle: string) => void;
}

export const StoreView: React.FC<StoreViewProps> = ({
  products,
  isLoading = false,
  hasError = false,
  onRetry,
  onAddToCart,
  onInstantBuy,
  onOpenChatWithProduct
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeModalProduct, setActiveModalProduct] = useState<Product | null>(null);
  const [selectedSize, setSelectedSize] = useState<string>('');

  const categories = [
    'All',
    'Footwear',
    'Audio',
    'Apparel',
    'Gadgets',
    'Hygiene & Essentials',
    'Travel',
    'Tech',
    'Home'
  ];

  const filteredProducts = products.filter(p => {
    const matchesCategory = selectedCategory === 'All' || p.category.toLowerCase() === selectedCategory.toLowerCase();
    const matchesSearch =
      p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.category.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.sku.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const handleOpenDetail = (product: Product) => {
    setActiveModalProduct(product);
    setSelectedSize(product.sizes && product.sizes.length > 0 ? product.sizes[0] : '');
  };

  const FALLBACK_PRODUCT_IMAGE = 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80';

  return (
    <div className="w-full flex flex-col gap-8 pb-16">
      {/* Hero Banner (Clean, Fast, Responsive - No 3D overhead) */}
      <section className="relative overflow-hidden rounded-3xl bg-surface border border-border shadow-xl p-6 sm:p-10">
        <div className="absolute top-0 right-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-1/4 w-96 h-96 bg-accent/10 rounded-full blur-3xl pointer-events-none" />

        <div className="max-w-3xl relative z-10 flex flex-col gap-4 text-left">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/15 border border-primary/30 text-primary text-xs font-semibold w-fit">
            <ShieldCheck className="w-4 h-4 text-primary" />
            <span>SellerShield Protection & AI Support Active</span>
          </div>

          <h1 className="text-3xl sm:text-5xl font-extrabold text-text-main tracking-tight leading-tight">
            Curated Goods.{' '}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-accent">
              Zero-Friction Support.
            </span>
          </h1>

          <p className="text-text-muted text-sm sm:text-base leading-relaxed">
            Order premium lifestyle and tech gear with automatic tracking. If your shoes feel tight or an item arrives damaged, our integrated AI concierge provides instant size exchanges, doorstep pickups, and refunds in seconds.
          </p>

          {/* Guarantees Bar */}
          <div className="grid grid-cols-3 gap-3 pt-3 border-t border-border/60">
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <RotateCcw className="w-4 h-4 text-primary shrink-0" />
              <span>7-Day Return Window</span>
            </div>
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <Truck className="w-4 h-4 text-accent shrink-0" />
              <span>Automatic Live Tracking</span>
            </div>
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
              <span>Escrow Security</span>
            </div>
          </div>
        </div>
      </section>

      {/* Filter and Search Bar */}
      <section className="flex flex-col sm:flex-row items-center justify-between gap-4">
        {/* Category Pills */}
        <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto pb-1 sm:pb-0">
          {categories.map(category => (
            <button
              key={category}
              onClick={() => setSelectedCategory(category)}
              className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all shrink-0 ${
                selectedCategory === category
                  ? 'bg-primary text-black shadow-sm font-bold'
                  : 'bg-surface border border-border text-text-muted hover:text-text-main hover:bg-surface-2'
              }`}
            >
              {category}
            </button>
          ))}
        </div>

        {/* Search input */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search products, SKUs, styles..."
            className="w-full bg-surface text-text-main text-xs rounded-xl pl-9 pr-4 py-2.5 border border-border focus:border-primary focus:outline-hidden transition-colors shadow-xs"
          />
        </div>
      </section>

      {/* Loading / Error / Empty States */}
      {isLoading && products.length === 0 ? (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <div key={i} className="rounded-2xl bg-surface border border-border overflow-hidden animate-pulse h-96">
              <div className="h-56 bg-surface-2" />
              <div className="p-5 space-y-3">
                <div className="h-4 bg-surface-2 rounded w-3/4" />
                <div className="h-3 bg-surface-2 rounded w-full" />
                <div className="h-6 bg-surface-2 rounded w-1/3 mt-4" />
              </div>
            </div>
          ))}
        </section>
      ) : hasError && products.length === 0 ? (
        <section className="p-10 rounded-3xl bg-surface border border-border text-center space-y-3">
          <AlertTriangle className="w-10 h-10 text-warning mx-auto" />
          <h3 className="text-base font-bold text-text-main">Couldn't load store products</h3>
          <p className="text-xs text-text-muted">Make sure the FastAPI server is running on port 8000.</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-5 py-2 rounded-xl bg-primary text-black font-bold text-xs hover:opacity-90"
            >
              Retry Loading Products
            </button>
          )}
        </section>
      ) : filteredProducts.length === 0 ? (
        <section className="p-10 rounded-3xl bg-surface border border-border text-center space-y-3">
          <Search className="w-10 h-10 text-text-muted mx-auto" />
          <h3 className="text-base font-bold text-text-main">No matching products found</h3>
          <p className="text-xs text-text-muted">Try clearing your search or selecting "All" categories.</p>
          <button
            onClick={() => {
              setSelectedCategory('All');
              setSearchQuery('');
            }}
            className="px-4 py-2 rounded-xl bg-surface-2 border border-border text-text-main font-semibold text-xs hover:bg-surface"
          >
            Reset Filters
          </button>
        </section>
      ) : null}

      {/* Product Grid */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredProducts.map(product => {
          const discountPct = product.original_price
            ? Math.round(((product.original_price - product.price) / product.original_price) * 100)
            : null;

          return (
            <motion.div
              key={product.id}
              whileHover={{ y: -3 }}
              transition={{ duration: 0.15 }}
              className="group rounded-2xl bg-surface border border-border overflow-hidden shadow-sm hover:shadow-xl hover:border-primary/40 transition-all flex flex-col justify-between"
            >
              <div>
                {/* Product Image */}
                <div
                  onClick={() => handleOpenDetail(product)}
                  className="relative w-full h-56 bg-surface-2 overflow-hidden cursor-pointer"
                >
                  <img
                    src={product.image || FALLBACK_PRODUCT_IMAGE}
                    alt={product.title}
                    onError={(e) => {
                      e.currentTarget.onerror = null;
                      e.currentTarget.src = FALLBACK_PRODUCT_IMAGE;
                    }}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                  {/* Category Chip */}
                  <span className="absolute top-3 left-3 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-surface/90 backdrop-blur-md text-text-main border border-border shadow-xs">
                    {product.category}
                  </span>

                  {discountPct && (
                    <span className="absolute top-3 right-3 px-2 py-0.5 rounded-md text-[11px] font-bold bg-danger text-white shadow-xs">
                      {discountPct}% OFF
                    </span>
                  )}

                  {/* Non-Returnable Warning Badge on Card if applicable */}
                  {!product.is_returnable && (
                    <span className="absolute bottom-3 left-3 px-2.5 py-1 rounded-lg text-[10px] font-bold bg-warning/90 backdrop-blur-md text-black flex items-center gap-1 shadow-sm">
                      <AlertTriangle className="w-3 h-3" />
                      <span>Hygiene: Non-Returnable</span>
                    </span>
                  )}
                </div>

                {/* Content */}
                <div className="p-4 sm:p-5">
                  <div className="flex items-center gap-1.5 text-amber-500 mb-1.5">
                    <Star className="w-3.5 h-3.5 fill-amber-500" />
                    <span className="text-xs font-bold text-text-main">{product.rating}</span>
                    <span className="text-[11px] text-text-muted">({product.review_count} reviews)</span>
                  </div>

                  <h3
                    onClick={() => handleOpenDetail(product)}
                    className="font-bold text-text-main text-base group-hover:text-primary transition-colors cursor-pointer line-clamp-1"
                  >
                    {product.title}
                  </h3>

                  <p className="text-xs text-text-muted line-clamp-2 mt-1 leading-relaxed">
                    {product.description}
                  </p>

                  <div className="mt-3 flex items-baseline justify-between">
                    <div className="flex items-baseline gap-2">
                      <span className="text-lg font-extrabold text-text-main font-mono">
                        ₹{product.price.toLocaleString('en-IN')}
                      </span>
                      {product.original_price && (
                        <span className="text-xs text-text-muted line-through font-mono">
                          ₹{product.original_price.toLocaleString('en-IN')}
                        </span>
                      )}
                    </div>
                    <span className="text-[11px] font-mono text-text-muted">
                      {product.stock_count} in stock
                    </span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="p-4 sm:p-5 pt-0 border-t border-border/40 mt-2 flex items-center gap-2">
                <button
                  onClick={() => onAddToCart(product, product.sizes?.[0])}
                  className="flex-1 py-2.5 rounded-xl border border-border bg-surface-2 hover:bg-surface hover:border-primary/50 text-text-main font-semibold text-xs transition-all flex items-center justify-center gap-1.5"
                >
                  <ShoppingBag className="w-3.5 h-3.5 text-primary" />
                  <span>Add to Cart</span>
                </button>

                <button
                  onClick={() => onInstantBuy(product, product.sizes?.[0])}
                  className="px-4 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-black font-bold text-xs transition-all flex items-center justify-center gap-1 shadow-sm active:scale-95"
                >
                  <span>Buy Now</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </motion.div>
          );
        })}
      </section>

      {/* Product Detail Modal */}
      <AnimatePresence>
        {activeModalProduct && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setActiveModalProduct(null)}
              className="absolute inset-0 bg-black/70 backdrop-blur-xs"
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 15 }}
              className="relative w-full max-w-2xl bg-surface border border-border rounded-3xl shadow-2xl overflow-hidden z-10 max-h-[90vh] flex flex-col"
            >
              {/* Header */}
              <div className="p-4 border-b border-border flex items-center justify-between">
                <span className="text-xs uppercase font-bold text-primary font-mono">
                  {activeModalProduct.sku}
                </span>
                <button
                  onClick={() => setActiveModalProduct(null)}
                  className="p-1.5 rounded-lg text-text-muted hover:text-text-main hover:bg-surface-2 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Body */}
              <div className="overflow-y-auto p-6 flex flex-col gap-5">
                <div className="w-full h-64 sm:h-72 rounded-2xl overflow-hidden bg-surface-2 border border-border">
                  <img
                    src={activeModalProduct.image || FALLBACK_PRODUCT_IMAGE}
                    alt={activeModalProduct.title}
                    onError={(e) => {
                      e.currentTarget.onerror = null;
                      e.currentTarget.src = FALLBACK_PRODUCT_IMAGE;
                    }}
                    className="w-full h-full object-cover"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl sm:text-2xl font-bold text-text-main">
                      {activeModalProduct.title}
                    </h2>
                    <span className="text-xl font-mono font-extrabold text-primary">
                      ₹{activeModalProduct.price.toLocaleString('en-IN')}
                    </span>
                  </div>

                  <p className="text-sm text-text-muted mt-2 leading-relaxed">
                    {activeModalProduct.description}
                  </p>

                  {/* Non-returnable notice if applicable */}
                  {!activeModalProduct.is_returnable ? (
                    <div className="mt-4 p-3 rounded-xl bg-warning/15 border border-warning/30 text-warning text-xs flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <div>
                        <strong className="block">Hygiene Product Notice:</strong>
                        <span>This item cannot be returned or exchanged once delivered due to hygiene and sanitation standards.</span>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-4 p-3 rounded-xl bg-primary/10 border border-primary/20 text-xs flex items-center gap-2 text-text-main">
                      <CheckCircle2 className="w-4 h-4 text-primary shrink-0" />
                      <span>Eligible for 7-day doorstep size exchange or return.</span>
                    </div>
                  )}

                  {/* Size selector if sizes exist */}
                  {activeModalProduct.sizes && (
                    <div className="mt-4">
                      <label className="text-xs font-bold text-text-main block mb-2">
                        Select Size:
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {activeModalProduct.sizes.map(size => (
                          <button
                            key={size}
                            onClick={() => setSelectedSize(size)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
                              selectedSize === size
                                ? 'bg-primary text-black border-primary font-bold'
                                : 'bg-surface-2 text-text-muted border-border hover:border-text-muted'
                            }`}
                          >
                            {size}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Modal Footer */}
              <div className="p-4 border-t border-border bg-surface-2/40 flex items-center justify-end gap-3">
                <button
                  onClick={() => {
                    onAddToCart(activeModalProduct, selectedSize);
                    setActiveModalProduct(null);
                  }}
                  className="px-5 py-2.5 rounded-xl border border-border bg-surface hover:bg-surface-2 text-text-main font-semibold text-xs transition-colors"
                >
                  Add to Cart
                </button>
                <button
                  onClick={() => {
                    onInstantBuy(activeModalProduct, selectedSize);
                    setActiveModalProduct(null);
                  }}
                  className="px-6 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-black font-bold text-xs transition-all shadow-md active:scale-95"
                >
                  Buy Now (₹{activeModalProduct.price.toLocaleString('en-IN')})
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};
