"""
Trader17_osmium — OSMIUM only, LAYERED make + take + flatten.

Evidence from Trader 15 / Trader 16:
  - Take-only PnL = 505 (can't do more, limited by sub-FV opportunities)
  - Make-only PnL = ~1985 (captured by current penny-jump)
  - Single-depth make misses ~80% of market flow that hits wall prices

Fix: split the 80-unit quote budget across 3 depths per side.
  Layer A — 10 units at FV±1 (edge 1, catches aggressive crossers)
  Layer B — 20 units at FV±4 (edge 4, catches mid-depth flow)
  Layer C — 50 units at penny-jump (best_bid+1 / best_ask-1, edge ~7, the bulk)

Plus:
  - TAKE every sub-FV ask and super-FV bid (Trader 15's +515 PnL)
  - FLATTEN at FV when a counterparty sits there
  - Position-aware capacity distribution (long → shrink buy side, grow sell side)

No PEPPER logic.
"""
import json
from datamodel import Order, TradingState

FV = 10000
PRODUCT = "ASH_COATED_OSMIUM"
LIMIT = 80

# Make layer allocation (sum must equal LIMIT = 80)
LAYERS = [
    {'offset': 1, 'size': 10},  # inside
    {'offset': 4, 'size': 20},  # mid
    {'offset': 7, 'size': 50},  # wall (penny-jump falls here in wide spread)
]


class Trader:
    def __init__(self):
        self.position_limits = {PRODUCT: LIMIT}

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}

        for product in state.order_depths:
            if product == PRODUCT:
                od = state.order_depths[product]
                pos = state.position.get(product, 0)
                result[product] = self.trade(product, od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(trader_data)

    def trade(self, product, order_depth, position):
        orders = []
        buy_vol = 0
        sell_vol = 0

        has_bids = bool(order_depth.buy_orders)
        has_asks = bool(order_depth.sell_orders)

        # --- 1. TAKE every sub-FV ask ---
        if has_asks:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price >= FV:
                    break
                ask_qty = abs(order_depth.sell_orders[ask_price])
                can_buy = LIMIT - position - buy_vol
                if can_buy <= 0:
                    break
                qty = min(ask_qty, can_buy)
                orders.append(Order(product, ask_price, qty))
                buy_vol += qty

        # --- 2. TAKE every super-FV bid ---
        if has_bids:
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price <= FV:
                    break
                bid_qty = order_depth.buy_orders[bid_price]
                can_sell = LIMIT + position - sell_vol
                if can_sell <= 0:
                    break
                qty = min(bid_qty, can_sell)
                orders.append(Order(product, bid_price, -qty))
                sell_vol += qty

        # --- 3. FLATTEN at FV when the other side is sitting there ---
        if position > 0 and order_depth.buy_orders.get(FV, 0) > 0:
            qty = min(order_depth.buy_orders[FV], LIMIT + position - sell_vol, position)
            if qty > 0:
                orders.append(Order(product, FV, -qty))
                sell_vol += qty
        elif position < 0 and order_depth.sell_orders.get(FV, 0) != 0:
            qty = min(abs(order_depth.sell_orders[FV]), LIMIT - position - buy_vol, -position)
            if qty > 0:
                orders.append(Order(product, FV, qty))
                buy_vol += qty

        # --- 4. LAYERED MAKE — 3 depths per side ---
        # determine wall price from book if available
        best_bid = max(order_depth.buy_orders.keys()) if has_bids else FV - 7
        best_ask = min(order_depth.sell_orders.keys()) if has_asks else FV + 7

        rem_buy_budget = LIMIT - position - buy_vol
        rem_sell_budget = LIMIT + position - sell_vol

        for layer in LAYERS:
            if rem_buy_budget <= 0 and rem_sell_budget <= 0:
                break
            # bid-side layer price
            if layer['offset'] == 7:
                # wall layer: use penny-jump so we stay 1 tick inside whatever's there
                bid_price = min(FV - 1, best_bid + 1)
                ask_price = max(FV + 1, best_ask - 1)
            else:
                bid_price = FV - layer['offset']
                ask_price = FV + layer['offset']

            size = layer['size']
            qty_buy = min(size, rem_buy_budget)
            if qty_buy > 0:
                orders.append(Order(product, bid_price, qty_buy))
                rem_buy_budget -= qty_buy
            qty_sell = min(size, rem_sell_budget)
            if qty_sell > 0:
                orders.append(Order(product, ask_price, -qty_sell))
                rem_sell_budget -= qty_sell

        return orders
