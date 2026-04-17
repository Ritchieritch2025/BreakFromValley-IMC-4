"""
Trader18_osmium — OSMIUM only, fully dynamic (no hardcoded layers).

Principles:
  1. FV is the ONLY anchor — 10000 is a market constant measured from 3 days of data.
  2. Every other price comes from the live book each tick.
  3. Make at the tightest non-crossing price (penny-jump), size scaled by edge.
  4. Skew bid/ask prices by inventory dynamically.
  5. Take anything that offers edge vs FV.
  6. Flatten at FV opportunistically.

No fixed offset layers. No fixed sizes per layer. Everything adapts.
"""
import json
from datamodel import Order, TradingState

FV = 10000
PRODUCT = "ASH_COATED_OSMIUM"
LIMIT = 80


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

        # ---------- 1. TAKE everything priced against us (vs FV) ----------
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

        # ---------- 2. FLATTEN at FV when available ----------
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

        # ---------- 3. DYNAMIC MAKE — one adaptive quote per side ----------
        # Price: penny-jump from best, capped by FV±1 (never cross)
        # Size:  full remaining capacity (we always want max presence)
        # Skew:  dynamic, scales with inventory fraction
        if has_bids and has_asks:
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())

            # Dynamic skew: proportional to how full our inventory is
            # +pos → shift both prices DOWN (less eager to buy, more eager to sell)
            inv_fraction = position / LIMIT  # ∈ [-1, 1]
            skew = round(inv_fraction * 3)   # ∈ [-3, 3]

            bid_price = min(best_bid + 1, FV - 1) - skew
            ask_price = max(best_ask - 1, FV + 1) - skew
            # hard cap: never cross FV
            bid_price = min(bid_price, FV - 1)
            ask_price = max(ask_price, FV + 1)

            rem_buy = LIMIT - position - buy_vol
            if rem_buy > 0:
                orders.append(Order(product, bid_price, rem_buy))
            rem_sell = LIMIT + position - sell_vol
            if rem_sell > 0:
                orders.append(Order(product, ask_price, -rem_sell))

        # ---------- 4. ONE-SIDED BOOK — harvest the wide side ----------
        # When only one side of the book exists, quote both sides around FV with size proportional to remaining budget.
        elif has_asks and not has_bids:
            best_ask = min(order_depth.sell_orders.keys())
            # someone wiped all bids → huge opportunity to buy low
            bid_price = FV - 1
            ask_price = max(best_ask - 1, FV + 1)
            rem_buy = LIMIT - position - buy_vol
            rem_sell = LIMIT + position - sell_vol
            if rem_buy > 0:
                orders.append(Order(product, bid_price, rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, ask_price, -rem_sell))
        elif has_bids and not has_asks:
            best_bid = max(order_depth.buy_orders.keys())
            bid_price = min(best_bid + 1, FV - 1)
            ask_price = FV + 1
            rem_buy = LIMIT - position - buy_vol
            rem_sell = LIMIT + position - sell_vol
            if rem_buy > 0:
                orders.append(Order(product, bid_price, rem_buy))
            if rem_sell > 0:
                orders.append(Order(product, ask_price, -rem_sell))

        return orders
